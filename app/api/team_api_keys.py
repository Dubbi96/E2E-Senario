from __future__ import annotations

import secrets
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.teams import require_role
from app.db.models import TeamApiKey, TeamRole, User
from app.db.session import get_db


router = APIRouter(prefix="/teams", tags=["Team Integrations"])


def _hash_secret(secret: str) -> str:
    return sha256(secret.encode("utf-8")).hexdigest()


def _make_token(prefix: str, secret: str) -> str:
    return f"dubbi_sk_{prefix}_{secret}"


class ApiKeyOut(BaseModel):
    id: str
    name: str
    prefix: str
    created_at: str
    revoked_at: str | None


class ApiKeyCreated(ApiKeyOut):
    api_key: str = Field(..., description="생성 직후 1회만 노출되는 실제 토큰(복사해두세요)")


class ApiKeyCreateIn(BaseModel):
    name: str = Field(..., description="키 이름(예: github-actions-prod)")


@router.get("/{team_id}/api-keys", response_model=list[ApiKeyOut], summary="팀 API Key 목록(OWNER만)")
def list_team_api_keys(team_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(db, team_id=team_id, user_id=user.id, allow={TeamRole.OWNER.value})
    rows = db.query(TeamApiKey).filter(TeamApiKey.team_id == team_id).order_by(TeamApiKey.created_at.desc()).all()
    return [
        ApiKeyOut(
            id=r.id,
            name=r.name,
            prefix=r.prefix,
            created_at=r.created_at.isoformat(),
            revoked_at=r.revoked_at.isoformat() if r.revoked_at else None,
        )
        for r in rows
    ]


@router.post("/{team_id}/api-keys", response_model=ApiKeyCreated, summary="팀 API Key 발급(OWNER만)")
def create_team_api_key(team_id: str, body: ApiKeyCreateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_role(db, team_id=team_id, user_id=user.id, allow={TeamRole.OWNER.value})
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if len(name) > 200:
        raise HTTPException(status_code=400, detail="name too long")

    prefix = secrets.token_hex(8)  # 16 chars
    secret = secrets.token_urlsafe(24)
    token = _make_token(prefix, secret)

    row = TeamApiKey(
        team_id=team_id,
        name=name,
        prefix=prefix,
        secret_hash=_hash_secret(secret),
        created_by_user_id=user.id,
        revoked_at=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return ApiKeyCreated(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        created_at=row.created_at.isoformat(),
        revoked_at=None,
        api_key=token,
    )


@router.delete("/{team_id}/api-keys/{api_key_id}", summary="팀 API Key 폐기(OWNER만)")
def revoke_team_api_key(team_id: str, api_key_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    require_role(db, team_id=team_id, user_id=user.id, allow={TeamRole.OWNER.value})
    row = db.get(TeamApiKey, api_key_id)
    if not row or row.team_id != team_id:
        raise HTTPException(status_code=404, detail="api key not found")
    if row.revoked_at:
        return {"revoked": True, "id": api_key_id, "already": True}
    row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"revoked": True, "id": api_key_id}


