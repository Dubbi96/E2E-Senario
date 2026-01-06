from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.teams import require_role
from app.db.models import ExternalSuiteRequestLog, TeamRole, User, WebhookDeliveryLog
from app.db.session import get_db


router = APIRouter(prefix="/teams", tags=["Team Integrations"])


class ExternalRequestOut(BaseModel):
    id: str
    suite_run_id: str
    api_key_id: str
    idempotency_key: str | None
    webhook_url: str | None
    remote_addr: str | None
    user_agent: str | None
    context: dict | None
    created_at: str


class WebhookDeliveryOut(BaseModel):
    id: str
    suite_run_id: str
    attempt: int
    url: str
    status_code: int | None
    error_message: str | None
    delivered_at: str | None
    created_at: str


@router.get(
    "/{team_id}/integrations/external-requests",
    response_model=list[ExternalRequestOut],
    summary="외부 실행 요청 로그(OWNER만)",
)
def list_external_requests(team_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(db, team_id=team_id, user_id=user.id, allow={TeamRole.OWNER.value})
    rows = (
        db.query(ExternalSuiteRequestLog)
        .filter(ExternalSuiteRequestLog.team_id == team_id)
        .order_by(ExternalSuiteRequestLog.created_at.desc())
        .limit(200)
        .all()
    )
    out: list[ExternalRequestOut] = []
    for r in rows:
        ctx = None
        if r.request_context_json:
            try:
                ctx = json.loads(r.request_context_json)
            except Exception:
                ctx = None
        out.append(
            ExternalRequestOut(
                id=r.id,
                suite_run_id=r.suite_run_id,
                api_key_id=r.api_key_id,
                idempotency_key=r.idempotency_key,
                webhook_url=r.webhook_url,
                remote_addr=r.remote_addr,
                user_agent=r.user_agent,
                context=ctx,
                created_at=r.created_at.isoformat(),
            )
        )
    return out


@router.get(
    "/{team_id}/integrations/webhook-deliveries",
    response_model=list[WebhookDeliveryOut],
    summary="웹훅 delivery 로그(OWNER만)",
)
def list_webhook_deliveries(team_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(db, team_id=team_id, user_id=user.id, allow={TeamRole.OWNER.value})
    rows = (
        db.query(WebhookDeliveryLog)
        .filter(WebhookDeliveryLog.team_id == team_id)
        .order_by(WebhookDeliveryLog.created_at.desc())
        .limit(200)
        .all()
    )
    return [
        WebhookDeliveryOut(
            id=r.id,
            suite_run_id=r.suite_run_id,
            attempt=int(r.attempt),
            url=r.url,
            status_code=r.status_code,
            error_message=r.error_message,
            delivered_at=r.delivered_at.isoformat() if r.delivered_at else None,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


