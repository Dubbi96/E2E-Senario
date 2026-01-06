"""
Run CRUD helpers.

MVP 목표:
- Run 메타/상태/시간은 DB가 source of truth
- Artifact는 파일시스템이 source of truth (DB에 별도 저장하지 않음)
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import Run, RunStatus


def create_run(
    db: Session,
    run_id: str,
    scenario_path: str,
    artifact_dir: str,
    owner_user_id: str | None = None,
) -> Run:
    run = Run(
        id=run_id,
        status=RunStatus.QUEUED.value,
        scenario_path=scenario_path,
        artifact_dir=artifact_dir,
        owner_user_id=owner_user_id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_run(db: Session, run_id: str) -> Run | None:
    return db.get(Run, run_id)


def mark_running(db: Session, run_id: str) -> None:
    run = db.get(Run, run_id)
    if not run:
        return
    run.status = RunStatus.RUNNING.value
    run.started_at = datetime.now(timezone.utc)
    db.commit()


def mark_finished(
    db: Session,
    run_id: str,
    passed: bool,
    exit_code: int | None,
    error_message: str | None = None,
) -> None:
    run = db.get(Run, run_id)
    if not run:
        return
    run.status = RunStatus.PASSED.value if passed else RunStatus.FAILED.value
    run.exit_code = exit_code
    run.error_message = error_message
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
