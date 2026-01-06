from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.auth_state_store import (
    copy_auth_state_to_dir,
    delete_auth_state,
    list_auth_states,
    save_auth_state,
    storage_state_b64,
    get_auth_state_paths,
)
from app.db.models import User
from app.db.session import get_db


router = APIRouter(prefix="/auth-states", tags=["auth-states"])


class AuthStateOut(BaseModel):
    id: str
    name: str
    provider: str
    created_at: str
    updated_at: str
    size_bytes: int


class AuthStateB64Out(BaseModel):
    auth_state_id: str
    b64: str


@router.get("/me", response_model=list[AuthStateOut])
def list_my_auth_states(user: User = Depends(get_current_user)):
    rows = list_auth_states(user.id)
    return [AuthStateOut(**r.__dict__) for r in rows]


@router.post("", response_model=AuthStateOut)
async def upload_auth_state(
    name: str = Form(""),
    provider: str = Form("google"),
    storage_state: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    content = await storage_state.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty storage_state file")
    try:
        meta = save_auth_state(owner_user_id=user.id, name=name, provider=provider, raw_json_bytes=content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AuthStateOut(**meta.__dict__)


@router.get("/{auth_state_id}/download")
def download_auth_state(auth_state_id: str, user: User = Depends(get_current_user)):
    try:
        data_path, meta_path = get_auth_state_paths(user.id, auth_state_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="auth state not found")
    filename = f"{auth_state_id}.storage_state.json"
    return FileResponse(data_path, filename=filename, media_type="application/json")


@router.post("/{auth_state_id}/b64", response_model=AuthStateB64Out)
def get_auth_state_b64(auth_state_id: str, user: User = Depends(get_current_user)):
    try:
        b64 = storage_state_b64(user.id, auth_state_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="auth state not found")
    return AuthStateB64Out(auth_state_id=auth_state_id, b64=b64)


@router.delete("/{auth_state_id}")
def delete_my_auth_state(auth_state_id: str, user: User = Depends(get_current_user)):
    try:
        delete_auth_state(user.id, auth_state_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="auth state not found")
    return {"ok": True}


