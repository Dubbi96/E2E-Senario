from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.models import CombinationDraft, User
from app.db.session import get_db


router = APIRouter(prefix="/drafts", tags=["drafts"])


class DraftCreateIn(BaseModel):
    name: str
    team_id: str | None = None
    combinations: list[list[str]]


class DraftOut(BaseModel):
    id: str
    name: str
    team_id: str | None
    combinations: list[list[str]]
    created_at: str
    updated_at: str


@router.get("", response_model=list[DraftOut])
def list_drafts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    ## 제출 조합 Draft 목록(개인)

    - **권한**: 로그인 필요
    - **처리**: 내가 저장해둔 draft 목록을 최신순으로 반환
    """
    rows = (
        db.query(CombinationDraft)
        .filter(CombinationDraft.owner_user_id == user.id)
        .order_by(CombinationDraft.updated_at.desc())
        .limit(200)
        .all()
    )
    out: list[DraftOut] = []
    for r in rows:
        out.append(
            DraftOut(
                id=r.id,
                name=r.name,
                team_id=r.team_id,
                combinations=json.loads(r.combinations_json),
                created_at=r.created_at.isoformat(),
                updated_at=r.updated_at.isoformat(),
            )
        )
    return out


@router.post("", response_model=DraftOut)
def create_draft(body: DraftCreateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    ## 제출 조합 Draft 저장(개인)

    - **권한**: 로그인 필요
    - **처리**:
      - 현재 UI의 '제출할 조합 목록'을 그대로 JSON으로 저장
      - 필요 시 삭제 가능
    """
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    if not body.combinations:
        raise HTTPException(status_code=400, detail="combinations is empty")

    d = CombinationDraft(
        owner_user_id=user.id,
        name=body.name.strip(),
        team_id=body.team_id,
        combinations_json=json.dumps(body.combinations, ensure_ascii=False),
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return DraftOut(
        id=d.id,
        name=d.name,
        team_id=d.team_id,
        combinations=json.loads(d.combinations_json),
        created_at=d.created_at.isoformat(),
        updated_at=d.updated_at.isoformat(),
    )


@router.delete("/{draft_id}")
def delete_draft(draft_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    ## 제출 조합 Draft 삭제(개인)
    """
    d = db.get(CombinationDraft, draft_id)
    if not d or d.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="draft not found")
    db.delete(d)
    db.commit()
    return {"deleted": True, "id": draft_id}


