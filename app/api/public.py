from __future__ import annotations

import json
import os
import secrets
import uuid
import base64
from datetime import datetime, timezone
from hashlib import sha256
from hmac import compare_digest
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import ExternalSuiteRequestLog, Scenario, SuiteCase, SuiteCaseScenario, SuiteRun, SuiteStatus, TeamApiKey
from app.db.session import get_db
from app.tasks_suite import execute_suite_case, finalize_suite_run
from app.core.auth_state_store import validate_storage_state_dict


router = APIRouter(prefix="/public/v1", tags=["Public API"])


def _hash_secret(secret: str) -> str:
    return sha256(secret.encode("utf-8")).hexdigest()


def _parse_api_key(raw: str) -> tuple[str, str]:
    """
    Token format: dubbi_sk_<prefix>_<secret>
    """
    raw = (raw or "").strip()
    if not raw.startswith("dubbi_sk_"):
        raise ValueError("invalid key format")
    parts = raw.split("_", 3)
    # ["dubbi", "sk", "<prefix>", "<secret>"]
    if len(parts) != 4:
        raise ValueError("invalid key format")
    prefix = parts[2]
    secret = parts[3]
    if not prefix or not secret:
        raise ValueError("invalid key format")
    return prefix, secret


def get_team_api_key(
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    db: Session = Depends(get_db),
) -> TeamApiKey:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-Api-Key is required")
    try:
        prefix, secret = _parse_api_key(x_api_key)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid api key") from None

    key = db.query(TeamApiKey).filter(TeamApiKey.prefix == prefix).first()
    if not key or key.revoked_at is not None:
        raise HTTPException(status_code=401, detail="invalid api key")

    if not compare_digest(key.secret_hash, _hash_secret(secret)):
        raise HTTPException(status_code=401, detail="invalid api key")
    return key


class PublicSuiteCreateIn(BaseModel):
    team_id: str = Field(..., description="대상 팀 ID (API Key의 팀과 반드시 일치)")
    combinations: list[list[str]] = Field(..., description="실행할 조합(시나리오 ID 리스트들의 리스트)")
    context: dict[str, Any] | None = Field(None, description="CI/CD 메타데이터(git_sha, build_id 등)")
    webhook_url: str | None = Field(None, description="(선택) 완료 시 콜백 받을 URL")
    webhook_secret: str | None = Field(None, description="(선택) webhook 서명 secret(HMAC)")
    storage_state_b64: str | None = Field(
        None,
        description="(선택) Playwright storageState JSON을 base64로 인코딩한 값. 로그인 우회 세션 주입용.",
    )
    storage_state_filename: str | None = Field(
        None,
        description="(선택) 저장될 storage_state 파일명(기본: storage_state.json)",
    )


class PublicSuiteCreated(BaseModel):
    suite_run_id: str
    status: str
    status_url: str
    report_url: str
    idempotency_key: str | None


class PublicSuiteOut(BaseModel):
    suite_run_id: str
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    case_count: int
    passed_cases: int
    failed_cases: int
    report_url: str
    context: dict[str, Any] | None
    webhook_url: str | None
    webhook_attempts: int
    webhook_last_status_code: int | None
    webhook_last_error: str | None
    webhook_delivered_at: str | None


def _public_status_url(suite_id: str) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/public/v1/suite-runs/{suite_id}"


def _public_report_url(suite_id: str) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/public/v1/suite-runs/{suite_id}/report.pdf"


@router.post("/suite-runs", response_model=PublicSuiteCreated, summary="(CI/CD) Suite Run 실행 요청(비동기)")
def public_create_suite_run(
    request: Request,
    body: PublicSuiteCreateIn,
    api_key: TeamApiKey = Depends(get_team_api_key),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    if body.team_id != api_key.team_id:
        raise HTTPException(status_code=403, detail="team_id does not match api key scope")
    if not body.combinations:
        raise HTTPException(status_code=400, detail="combinations is empty")
    for combo in body.combinations:
        if not combo:
            raise HTTPException(status_code=400, detail="empty combination is not allowed")

    # Idempotency: same (api_key, idempotency_key) returns existing suite_run
    if idempotency_key:
        existing = (
            db.query(SuiteRun)
            .filter(SuiteRun.trigger_api_key_id == api_key.id, SuiteRun.external_idempotency_key == idempotency_key)
            .first()
        )
        if existing:
            # Log idempotent hit (best-effort)
            try:
                db.add(
                    ExternalSuiteRequestLog(
                        team_id=api_key.team_id,
                        api_key_id=api_key.id,
                        suite_run_id=existing.id,
                        idempotency_key=idempotency_key,
                        request_context_json=json.dumps(body.context, ensure_ascii=False) if body.context else None,
                        webhook_url=body.webhook_url,
                        remote_addr=request.client.host if request.client else None,
                        user_agent=request.headers.get("user-agent"),
                    )
                )
                db.commit()
            except Exception:
                db.rollback()
            return PublicSuiteCreated(
                suite_run_id=existing.id,
                status=existing.status,
                status_url=_public_status_url(existing.id),
                report_url=_public_report_url(existing.id),
                idempotency_key=idempotency_key,
            )

    suite_id = str(uuid.uuid4())
    suite_dir = os.path.join(settings.ARTIFACT_ROOT, "suite", suite_id)
    Path(suite_dir).mkdir(parents=True, exist_ok=True)

    # Optional: decode and validate provided storageState (for headless login bypass).
    storage_state_bytes: bytes | None = None
    storage_state_rel = None
    if body.storage_state_b64:
        try:
            storage_state_bytes = base64.b64decode(body.storage_state_b64.encode("utf-8"))
            obj = json.loads(storage_state_bytes.decode("utf-8"))
            ok, errors = validate_storage_state_dict(obj if isinstance(obj, dict) else {})
            if not ok:
                raise HTTPException(status_code=400, detail="invalid storage_state_b64:\n" + "\n".join(f"- {e}" for e in errors))
            fname = (body.storage_state_filename or "storage_state.json").strip() or "storage_state.json"
            # keep it simple: avoid path traversal
            fname = os.path.basename(fname)
            Path(suite_dir, fname).write_bytes(storage_state_bytes)
            storage_state_rel = f"./{fname}"
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"invalid storage_state_b64: {e}")

    suite = SuiteRun(
        id=suite_id,
        requested_by_user_id=api_key.created_by_user_id,
        team_id=body.team_id,
        status=SuiteStatus.QUEUED.value,
        artifact_dir=suite_dir,
        submitted_combinations_json=json.dumps(body.combinations, ensure_ascii=False),
        trigger_api_key_id=api_key.id,
        external_idempotency_key=idempotency_key,
        external_context_json=json.dumps(body.context, ensure_ascii=False) if body.context else None,
        webhook_url=body.webhook_url,
        webhook_secret=body.webhook_secret,
        webhook_attempts=0,
    )
    db.add(suite)
    db.commit()
    db.refresh(suite)

    # Log external request (best-effort)
    try:
        db.add(
            ExternalSuiteRequestLog(
                team_id=api_key.team_id,
                api_key_id=api_key.id,
                suite_run_id=suite.id,
                idempotency_key=idempotency_key,
                request_context_json=json.dumps(body.context, ensure_ascii=False) if body.context else None,
                webhook_url=body.webhook_url,
                remote_addr=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
        )
        db.commit()
    except Exception:
        db.rollback()

    # Create cases (same as internal create)
    case_ids: list[str] = []
    for idx, combo in enumerate(body.combinations, start=1):
        scenarios: list[Scenario] = []
        for sid in combo:
            sc = db.get(Scenario, sid)
            if not sc:
                raise HTTPException(status_code=404, detail=f"scenario not found: {sid}")
            if sc.owner_team_id != body.team_id:
                raise HTTPException(status_code=403, detail=f"scenario not in target team: {sid}")
            scenarios.append(sc)

        case_id = str(uuid.uuid4())
        case_dir = os.path.join(suite_dir, f"case_{idx:03d}_{case_id}")
        Path(case_dir).mkdir(parents=True, exist_ok=True)

        combined_path = os.path.join(case_dir, "combined.json")
        steps: list[dict[str, Any]] = []
        combined_base_url = None
        for sc in scenarios:
            from app.runner.scenario import load_scenario

            s = load_scenario(sc.scenario_path)
            combined_base_url = combined_base_url or s.base_url
            steps.extend(list(s.steps))
        combined: dict[str, Any] = {"base_url": combined_base_url or "", "steps": steps}
        if storage_state_rel:
            # copy into each case dir for execution isolation
            try:
                fname = storage_state_rel.replace("./", "", 1)
                src = Path(suite_dir) / fname
                dst = Path(case_dir) / fname
                if src.exists() and not dst.exists():
                    dst.write_bytes(src.read_bytes())
            except Exception:
                pass
            combined["requires_auth"] = True
            combined["storage_state_path"] = storage_state_rel
        Path(combined_path).write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")

        case = SuiteCase(
            id=case_id,
            suite_run_id=suite.id,
            case_index=idx,
            status=SuiteStatus.QUEUED.value,
            artifact_dir=case_dir,
            combined_scenario_path=combined_path,
        )
        db.add(case)
        db.flush()

        for order_i, sc in enumerate(scenarios, start=1):
            db.add(SuiteCaseScenario(suite_case_id=case.id, scenario_id=sc.id, order_index=order_i))

        case_ids.append(case_id)

    db.commit()

    # Queue execution: 순차 실행 (안정화를 위해 병렬 실행 비활성화)
    from celery import chain
    
    # 순차 실행 체인 생성
    if case_ids:
        # 첫 번째 케이스부터 시작
        job_chain = execute_suite_case.s(case_ids[0])
        # 나머지 케이스들을 체인으로 연결
        for cid in case_ids[1:]:
            job_chain = job_chain | execute_suite_case.s(cid)
        # 마지막에 finalize 추가 (chain의 마지막 결과를 무시하고 suite_id만 전달)
        job_chain = job_chain | finalize_suite_run.si(suite_id)
        job_chain.apply_async()
    else:
        # 케이스가 없으면 바로 finalize
        finalize_suite_run.delay(suite_id)

    return PublicSuiteCreated(
        suite_run_id=suite.id,
        status=suite.status,
        status_url=_public_status_url(suite.id),
        report_url=_public_report_url(suite.id),
        idempotency_key=idempotency_key,
    )


@router.get("/suite-runs/{suite_run_id}", response_model=PublicSuiteOut, summary="(CI/CD) Suite Run 상태 조회")
def public_get_suite_run(
    suite_run_id: str,
    api_key: TeamApiKey = Depends(get_team_api_key),
    db: Session = Depends(get_db),
):
    suite = db.get(SuiteRun, suite_run_id)
    if not suite or suite.trigger_api_key_id != api_key.id:
        raise HTTPException(status_code=404, detail="suite run not found")

    cases = db.query(SuiteCase).filter(SuiteCase.suite_run_id == suite.id).all()
    passed = sum(1 for c in cases if c.status == SuiteStatus.PASSED.value)
    failed = sum(1 for c in cases if c.status == SuiteStatus.FAILED.value)

    ctx = None
    if suite.external_context_json:
        try:
            ctx = json.loads(suite.external_context_json)
        except Exception:
            ctx = None

    return PublicSuiteOut(
        suite_run_id=suite.id,
        status=suite.status,
        created_at=suite.created_at.isoformat(),
        started_at=suite.started_at.isoformat() if suite.started_at else None,
        finished_at=suite.finished_at.isoformat() if suite.finished_at else None,
        case_count=len(cases),
        passed_cases=passed,
        failed_cases=failed,
        report_url=_public_report_url(suite.id),
        context=ctx,
        webhook_url=suite.webhook_url,
        webhook_attempts=int(getattr(suite, "webhook_attempts", 0) or 0),
        webhook_last_status_code=getattr(suite, "webhook_last_status_code", None),
        webhook_last_error=getattr(suite, "webhook_last_error", None),
        webhook_delivered_at=suite.webhook_delivered_at.isoformat() if getattr(suite, "webhook_delivered_at", None) else None,
    )


@router.get("/suite-runs/{suite_run_id}/report.pdf", summary="(CI/CD) Suite Run 리포트 PDF 다운로드")
def public_download_suite_report(
    suite_run_id: str,
    api_key: TeamApiKey = Depends(get_team_api_key),
    db: Session = Depends(get_db),
):
    suite = db.get(SuiteRun, suite_run_id)
    if not suite or suite.trigger_api_key_id != api_key.id:
        raise HTTPException(status_code=404, detail="suite run not found")
    pdf_path = Path(suite.artifact_dir) / "suite_report.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="report not ready")
    return FileResponse(path=str(pdf_path), filename="suite_report.pdf")


