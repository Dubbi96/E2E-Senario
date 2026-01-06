from __future__ import annotations

import base64
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings


@dataclass
class AuthStateMeta:
    id: str
    owner_user_id: str
    name: str
    provider: str  # e.g. "google"
    created_at: str
    updated_at: str
    size_bytes: int


def _user_dir(user_id: str) -> str:
    return os.path.join(settings.AUTH_STATE_ROOT, user_id)


def _paths(user_id: str, auth_state_id: str) -> tuple[str, str]:
    base = os.path.join(_user_dir(user_id), auth_state_id)
    return base + ".json", base + ".meta.json"


def ensure_dirs(user_id: str) -> None:
    Path(_user_dir(user_id)).mkdir(parents=True, exist_ok=True)


def validate_storage_state_dict(d: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Minimal validation for Playwright storageState.
    Expected shape:
      { "cookies": [...], "origins": [ { "origin": "...", "localStorage": [...] } ] }
    """
    errors: list[str] = []
    if not isinstance(d, dict):
        return False, ["storageState must be an object"]
    if "cookies" not in d or not isinstance(d.get("cookies"), list):
        errors.append("missing or invalid 'cookies' (must be array)")
    if "origins" not in d or not isinstance(d.get("origins"), list):
        errors.append("missing or invalid 'origins' (must be array)")
    # optional deeper checks
    origins = d.get("origins") if isinstance(d.get("origins"), list) else []
    for i, o in enumerate(origins[:20]):
        if not isinstance(o, dict):
            errors.append(f"origins[{i}] must be object")
            continue
        if "origin" not in o:
            errors.append(f"origins[{i}] missing 'origin'")
        if "localStorage" in o and not isinstance(o.get("localStorage"), list):
            errors.append(f"origins[{i}].localStorage must be array")
    return (len(errors) == 0), errors


def save_auth_state(*, owner_user_id: str, name: str, provider: str, raw_json_bytes: bytes) -> AuthStateMeta:
    ensure_dirs(owner_user_id)
    auth_state_id = str(uuid.uuid4())
    data_path, meta_path = _paths(owner_user_id, auth_state_id)

    # validate JSON
    try:
        d = json.loads(raw_json_bytes.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"storageState JSON 파싱 실패: {e}")

    ok, errors = validate_storage_state_dict(d)
    if not ok:
        raise ValueError("storageState 형식 오류:\n" + "\n".join(f"- {e}" for e in errors))

    now = datetime.now(timezone.utc).isoformat()
    Path(data_path).write_bytes(raw_json_bytes)
    meta = AuthStateMeta(
        id=auth_state_id,
        owner_user_id=owner_user_id,
        name=name.strip() or f"{provider}-auth",
        provider=provider.strip() or "unknown",
        created_at=now,
        updated_at=now,
        size_bytes=len(raw_json_bytes),
    )
    Path(meta_path).write_text(json.dumps(meta.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def list_auth_states(owner_user_id: str) -> list[AuthStateMeta]:
    ensure_dirs(owner_user_id)
    rows: list[AuthStateMeta] = []
    for p in sorted(Path(_user_dir(owner_user_id)).glob("*.meta.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("owner_user_id") != owner_user_id:
                continue
            rows.append(AuthStateMeta(**d))
        except Exception:
            continue
    return rows


def get_auth_state_paths(owner_user_id: str, auth_state_id: str) -> tuple[str, str]:
    data_path, meta_path = _paths(owner_user_id, auth_state_id)
    if not os.path.exists(data_path) or not os.path.exists(meta_path):
        raise FileNotFoundError("auth state not found")
    # verify ownership from meta file
    meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    if meta.get("owner_user_id") != owner_user_id:
        raise FileNotFoundError("auth state not found")
    return data_path, meta_path


def delete_auth_state(owner_user_id: str, auth_state_id: str) -> None:
    data_path, meta_path = get_auth_state_paths(owner_user_id, auth_state_id)
    try:
        os.remove(data_path)
    except Exception:
        pass
    try:
        os.remove(meta_path)
    except Exception:
        pass


def storage_state_b64(owner_user_id: str, auth_state_id: str) -> str:
    data_path, _ = get_auth_state_paths(owner_user_id, auth_state_id)
    return base64.b64encode(Path(data_path).read_bytes()).decode("utf-8")


def copy_auth_state_to_dir(*, owner_user_id: str, auth_state_id: str, dest_dir: str, dest_filename: str) -> str:
    """
    Copy stored auth state JSON into dest_dir and return absolute dest path.
    """
    src_path, _ = get_auth_state_paths(owner_user_id, auth_state_id)
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    dst = os.path.join(dest_dir, dest_filename)
    shutil.copyfile(src_path, dst)
    return dst


