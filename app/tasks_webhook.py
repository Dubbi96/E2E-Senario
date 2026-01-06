from __future__ import annotations

import hmac
import json
import time
import traceback
import urllib.error
import urllib.request
from hashlib import sha256

from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.config import settings
from app.db.models import SuiteRun, SuiteStatus, WebhookDeliveryLog
from app.db.session import SessionLocal


def _sign(secret: str, ts: int, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), msg=f"{ts}.".encode("utf-8") + body, digestmod=sha256)
    return mac.hexdigest()


@celery_app.task(bind=True, name="send_suite_webhook", max_retries=5, default_retry_delay=10)
def send_suite_webhook(self, suite_run_id: str) -> dict:
    db: Session = SessionLocal()
    try:
        suite = db.get(SuiteRun, suite_run_id)
        if not suite:
            return {"suite_run_id": suite_run_id, "skipped": True, "reason": "suite not found"}

        if not suite.webhook_url:
            return {"suite_run_id": suite_run_id, "skipped": True, "reason": "no webhook_url"}

        if suite.status not in (SuiteStatus.PASSED.value, SuiteStatus.FAILED.value):
            return {"suite_run_id": suite_run_id, "skipped": True, "reason": f"not finished ({suite.status})"}

        suite.webhook_attempts = int(getattr(suite, "webhook_attempts", 0) or 0) + 1
        db.commit()

        payload = {
            "event": "suite_run.completed",
            "suite_run_id": suite.id,
            "team_id": suite.team_id,
            "status": suite.status,
            "created_at": suite.created_at.isoformat() if suite.created_at else None,
            "started_at": suite.started_at.isoformat() if suite.started_at else None,
            "finished_at": suite.finished_at.isoformat() if suite.finished_at else None,
            "status_url": f"{settings.PUBLIC_BASE_URL.rstrip('/')}/public/v1/suite-runs/{suite.id}",
            "report_url": f"{settings.PUBLIC_BASE_URL.rstrip('/')}/public/v1/suite-runs/{suite.id}/report.pdf",
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        ts = int(time.time())
        req = urllib.request.Request(
            suite.webhook_url,
            data=body,
            method="POST",
            headers={
                "content-type": "application/json",
                "user-agent": "dubbi-e2e-service/1.0",
                "x-dubbi-event": "suite_run.completed",
                "x-dubbi-timestamp": str(ts),
            },
        )
        if suite.webhook_secret:
            sig = _sign(str(suite.webhook_secret), ts, body)
            req.add_header("x-dubbi-signature", f"t={ts},v1={sig}")

        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                code = int(getattr(resp, "status", 0) or 0)
                ok = 200 <= code < 300
                suite.webhook_last_status_code = code
                suite.webhook_last_error = None if ok else f"http {code}"
                if ok:
                    from datetime import datetime, timezone

                    suite.webhook_delivered_at = datetime.now(timezone.utc)
                db.commit()
                # Log delivery attempt
                try:
                    db.add(
                        WebhookDeliveryLog(
                            team_id=suite.team_id,
                            suite_run_id=suite.id,
                            attempt=int(suite.webhook_attempts),
                            url=str(suite.webhook_url),
                            status_code=code,
                            error_message=None if ok else f"http {code}",
                            delivered_at=suite.webhook_delivered_at,
                        )
                    )
                    db.commit()
                except Exception:
                    db.rollback()
                if not ok:
                    raise RuntimeError(f"webhook non-2xx: {code}")
                return {"suite_run_id": suite.id, "delivered": True, "status_code": code}
        except urllib.error.HTTPError as e:
            suite.webhook_last_status_code = int(getattr(e, "code", 0) or 0)
            suite.webhook_last_error = f"HTTPError: {e}"
            db.commit()
            try:
                db.add(
                    WebhookDeliveryLog(
                        team_id=suite.team_id,
                        suite_run_id=suite.id,
                        attempt=int(suite.webhook_attempts),
                        url=str(suite.webhook_url),
                        status_code=suite.webhook_last_status_code,
                        error_message=str(suite.webhook_last_error),
                        delivered_at=None,
                    )
                )
                db.commit()
            except Exception:
                db.rollback()
            raise
        except Exception as e:
            suite.webhook_last_status_code = None
            suite.webhook_last_error = f"{e}\n{traceback.format_exc()}"
            db.commit()
            try:
                db.add(
                    WebhookDeliveryLog(
                        team_id=suite.team_id,
                        suite_run_id=suite.id,
                        attempt=int(suite.webhook_attempts),
                        url=str(suite.webhook_url),
                        status_code=None,
                        error_message=str(suite.webhook_last_error),
                        delivered_at=None,
                    )
                )
                db.commit()
            except Exception:
                db.rollback()
            raise
    except Exception as e:
        try:
            self.retry(exc=e)
        except Exception:
            return {"suite_run_id": suite_run_id, "delivered": False, "error": str(e)}
        return {"suite_run_id": suite_run_id, "delivered": False, "retrying": True}
    finally:
        db.close()


