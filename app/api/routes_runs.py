"""
API endpoints for submitting new test runs.

This router exposes endpoints to:
- Create a run (persist metadata in DB + enqueue Celery task)
- Query run status/metadata
- List and download artifacts from the run's artifact directory
"""

import os
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.tasks import execute_run
from app.db.session import get_db
from app.db.crud import create_run as create_run_db, get_run
from app.db.models import RunStatus
from app.reporting.pdf_report import generate_run_report_pdf
from app.api.auth import get_current_user
from app.db.models import User, Run
from app.core.auth_state_store import copy_auth_state_to_dir
from app.core.scenario_inject import inject_storage_state_path_into_scenario_file


router = APIRouter()


class RunCreated(BaseModel):
    """Response model returned when a run is created."""

    run_id: str
    status: str


class RunOut(BaseModel):
    id: str
    status: str
    scenario_path: str
    artifact_dir: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    exit_code: int | None
    error_message: str | None
    is_deleted: bool | None = None
    deleted_at: str | None = None
    deleted_artifact_dir: str | None = None


class MyRunOut(BaseModel):
    id: str
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    exit_code: int | None
    is_deleted: bool


class ArtifactInfo(BaseModel):
    name: str
    size: int
    mtime_epoch: int


@router.post("", response_model=RunCreated)
async def create_run(
    scenario: UploadFile = File(...),
    auth_state_id: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Submit a new scenario for execution.

    The uploaded file is stored on disk in a unique run directory under
    ``settings.ARTIFACT_ROOT``. A Celery task is queued to execute the
    scenario and produce artifacts. The caller receives a run identifier
    immediately and can use it to query status or download artifacts
    later on.

    ## 단일 Run 생성(파일 업로드)

    - **권한**: (현재 MVP) 인증 없음
    - **요청**: multipart `scenario` 파일(.yaml/.yml/.json)
    - **처리**:
      - `ARTIFACT_ROOT/{run_id}/` 생성
      - 업로드 파일을 해당 디렉터리에 저장
      - runs 테이블에 QUEUED로 저장
      - Celery `execute_run(run_id)` 큐잉
    - **응답**: `{run_id, status}`
    - **에러**:
      - 400: 빈 파일

    :param scenario: Multipart file upload containing a YAML/JSON scenario
    :return: Identifier of the created run and its initial status
    """
    run_id = str(uuid.uuid4())
    # Each run has its own directory for storing the uploaded scenario and test artifacts.
    run_dir = os.path.join(settings.ARTIFACT_ROOT, run_id)
    os.makedirs(run_dir, exist_ok=True)

    filename = scenario.filename or "scenario.yaml"
    scenario_path = os.path.join(run_dir, filename)
    content = await scenario.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty scenario file")

    with open(scenario_path, "wb") as f:
        f.write(content)

    # Optional: attach stored Playwright storageState into run directory and inject into scenario.
    if auth_state_id:
        try:
            copy_auth_state_to_dir(
                owner_user_id=user.id,
                auth_state_id=auth_state_id,
                dest_dir=run_dir,
                dest_filename="storage_state.json",
            )
            inject_storage_state_path_into_scenario_file(
                scenario_path=scenario_path,
                storage_state_rel_path="./storage_state.json",
            )
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="auth state not found")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"auth state inject failed: {e}")

    create_run_db(db, run_id=run_id, scenario_path=scenario_path, artifact_dir=run_dir, owner_user_id=user.id)

    execute_run.delay(run_id)

    return RunCreated(run_id=run_id, status=RunStatus.QUEUED.value)


@router.get("/me", response_model=list[MyRunOut])
def list_my_runs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        db.query(Run)
        .filter(Run.owner_user_id == user.id)
        .order_by(Run.created_at.desc())
        .limit(200)
        .all()
    )
    return [
        MyRunOut(
            id=r.id,
            status=r.status,
            created_at=r.created_at.isoformat(),
            started_at=r.started_at.isoformat() if r.started_at else None,
            finished_at=r.finished_at.isoformat() if r.finished_at else None,
            exit_code=r.exit_code,
            is_deleted=bool(getattr(r, "is_deleted", False)),
        )
        for r in rows
    ]


@router.get("/{run_id}", response_model=RunOut)
def get_run_api(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    ## Run 상태/메타 조회

    - **권한**: (현재 MVP) 인증 없음
    - **처리**: runs 테이블에서 조회해 상태/시간/exit_code 등을 반환
    - **에러**: 404(run not found)
    """
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    if run.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="run not found")
    if getattr(run, "is_deleted", False):
        raise HTTPException(status_code=410, detail="run deleted")
    return RunOut(
        id=run.id,
        status=run.status,
        scenario_path=run.scenario_path,
        artifact_dir=run.artifact_dir,
        created_at=run.created_at.isoformat(),
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        exit_code=run.exit_code,
        error_message=run.error_message,
        is_deleted=getattr(run, "is_deleted", False),
        deleted_at=run.deleted_at.isoformat() if getattr(run, "deleted_at", None) else None,
        deleted_artifact_dir=getattr(run, "deleted_artifact_dir", None),
    )


@router.get("/{run_id}/artifacts", response_model=list[ArtifactInfo])
def list_artifacts(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    ## Run 아티팩트 목록

    - **권한**: (현재 MVP) 인증 없음
    - **처리**: run.artifact_dir 디렉터리를 스캔해서 파일 목록 반환(DB에는 파일을 저장하지 않음)
    """
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    if run.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="run not found")
    if getattr(run, "is_deleted", False):
        raise HTTPException(status_code=410, detail="run deleted")

    run_dir = Path(run.artifact_dir)
    if not run_dir.exists():
        return []

    items: list[ArtifactInfo] = []
    for p in run_dir.iterdir():
        if p.is_file():
            st = p.stat()
            items.append(ArtifactInfo(name=p.name, size=st.st_size, mtime_epoch=int(st.st_mtime)))
    items.sort(key=lambda x: x.mtime_epoch)
    return items


@router.get("/{run_id}/artifacts/{name}")
def download_artifact(run_id: str, name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    ## Run 아티팩트 다운로드

    - **권한**: (현재 MVP) 인증 없음
    - **보안**: path traversal 방지(artifact_dir 밖으로 나가는 경로는 400)
    - **에러**: 404(파일 없음)
    """
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    if run.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="run not found")
    if getattr(run, "is_deleted", False):
        raise HTTPException(status_code=410, detail="run deleted")

    run_dir = Path(run.artifact_dir).resolve()
    target = (run_dir / name).resolve()

    # Path Traversal 방지: target이 run_dir 밖이면 거부
    if run_dir not in target.parents and run_dir != target:
        raise HTTPException(status_code=400, detail="invalid artifact path")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")

    return FileResponse(path=str(target), filename=target.name)


@router.get("/{run_id}/report.pdf")
def download_report_pdf(
    run_id: str,
    refresh: bool = False,
    debug: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    ## Run PDF 리포트 다운로드

    - **권한**: (현재 MVP) 인증 없음
    - **동작**:
      - 기본: `{artifact_dir}/report.pdf`가 없으면 생성 후 다운로드
      - `refresh=true`: 항상 재생성
      - `debug=true`: 내부 로그 부록까지 포함

    - 생성 결과는 `{artifact_dir}/report.pdf` 로 저장됩니다.
    - `refresh=true`면 기존 PDF가 있어도 재생성합니다.
    """
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    if run.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="run not found")
    if getattr(run, "is_deleted", False):
        raise HTTPException(status_code=410, detail="run deleted")

    run_dir = Path(run.artifact_dir)
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="artifact dir not found")

    pdf_path = run_dir / "report.pdf"
    if refresh or not pdf_path.exists():
        generate_run_report_pdf(
            run_id=run.id,
            status=run.status,
            scenario_path=run.scenario_path,
            artifact_dir=run.artifact_dir,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            exit_code=run.exit_code,
            error_message=run.error_message,
            debug=debug,
            output_path=str(pdf_path),
        )

    return FileResponse(path=str(pdf_path), filename="report.pdf")


@router.delete(
    "/{run_id}",
    summary="내 단일 Run 삭제(soft delete) + artifact pending_delete 이관",
    description="""
    단일 Run을 soft delete 처리합니다.

    - **권한**: 로그인 필요 + owner_user_id == me.id
    - **제약**: RUNNING/QUEUED 상태에서는 삭제 불가(409)
    - **처리**:
      - `ARTIFACT_ROOT/_pending_delete/{run_id}_{ts}/`로 디렉터리 이동(가능한 경우)
      - DB에 is_deleted/deleted_at/deleted_artifact_dir 갱신
    """,
)
def delete_my_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = get_run(db, run_id)
    if not run or run.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="run not found")

    if getattr(run, "is_deleted", False):
        return {"deleted": True, "id": run_id, "already_deleted": True}

    if run.status in (RunStatus.QUEUED.value, RunStatus.RUNNING.value):
        raise HTTPException(status_code=409, detail="cannot delete while running/queued")

    old_dir = Path(run.artifact_dir)
    pending_root = Path(settings.ARTIFACT_ROOT) / "_pending_delete"
    pending_root.mkdir(parents=True, exist_ok=True)
    new_dir = pending_root / f"{run.id}_{int(time.time())}"

    moved = False
    try:
        if old_dir.exists():
            old_dir.rename(new_dir)
            moved = True
    except Exception:
        moved = False

    # Update paths if moved
    if moved:
        try:
            old_dir_str = str(old_dir)
            if run.scenario_path.startswith(old_dir_str):
                rel = Path(run.scenario_path).relative_to(old_dir)
                run.scenario_path = str(new_dir / rel)
        except Exception:
            pass
        run.artifact_dir = str(new_dir)
        run.deleted_artifact_dir = str(new_dir)

    run.is_deleted = True
    run.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"deleted": True, "id": run_id, "moved": moved, "pending_dir": run.deleted_artifact_dir}
