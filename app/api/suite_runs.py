from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.teams import require_role
from app.core.config import settings
from app.db.models import (
    Scenario,
    SuiteCase,
    SuiteCaseScenario,
    SuiteRun,
    SuiteStatus,
    TeamRole,
    User,
)
from app.db.session import get_db
from app.reporting.suite_pdf_report import generate_suite_report_pdf
from app.tasks_suite import execute_suite_case, finalize_suite_run
from app.core.auth_state_store import copy_auth_state_to_dir


router = APIRouter(prefix="/suite-runs", tags=["suite-runs"])


class SuiteCreateIn(BaseModel):
    # optional: run under a team (requires ADMIN/OWNER to execute)
    team_id: str | None = None
    # user-defined combinations: list of ordered scenario_id lists
    combinations: list[list[str]]
    # optional: auth state (Playwright storageState) to inject for headless login bypass
    auth_state_id: str | None = None


class SuiteCreated(BaseModel):
    suite_run_id: str
    status: str
    case_ids: list[str]


class SuiteRunOut(BaseModel):
    id: str
    status: str
    team_id: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    case_count: int
    passed_cases: int
    failed_cases: int


def _require_suite_access(db: Session, *, suite: SuiteRun, user: User) -> None:
    """
    조회 권한:
    - 개인 스코프(team_id 없음): 요청자만
    - 팀 스코프(team_id 있음): 해당 팀 멤버(OWNER/ADMIN/MEMBER)면 조회 가능
    """
    if suite.team_id:
        require_role(
            db,
            team_id=suite.team_id,
            user_id=user.id,
            allow={TeamRole.OWNER.value, TeamRole.ADMIN.value, TeamRole.MEMBER.value},
        )
        return
    if suite.requested_by_user_id != user.id:
        raise HTTPException(status_code=404, detail="suite run not found")


@router.get("/me")
def list_my_suite_runs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    ## 내 Suite Run 실행 이력

    - **권한**: 로그인 필요
    - **처리**: requested_by_user_id == me.id 인 suite_runs 목록 반환
    """
    rows = (
        db.query(SuiteRun)
        .filter(SuiteRun.requested_by_user_id == user.id, SuiteRun.is_deleted == False)  # noqa: E712
        .order_by(SuiteRun.created_at.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": r.id,
            "status": r.status,
            "team_id": r.team_id,
            "created_at": r.created_at.isoformat(),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in rows
    ]


@router.post("", response_model=SuiteCreated)
def create_suite_run(
    body: SuiteCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    ## Suite Run 생성(사용자 정의 조합 실행)

    **핵심 개념**
    - 사용자가 조합(combinations)을 직접 정의합니다.
      - 예: `[[1,2,3], [1,4,5], [2,4,5]]`
    - 각 조합은 1개의 **SuiteCase**가 되고, 케이스는 독립적으로 실행됩니다.
    - 최종 SuiteRun 결과는 **모든 케이스가 PASSED일 때만 PASSED**입니다.

    **순차 실행(A안)**
    - 케이스 내부에서는 선택된 시나리오들의 step을 **하나로 이어붙인 combined.json**을 생성하고,
      pytest는 그 combined.json을 단 1회 실행합니다.
      → 즉, 동일 브라우저 세션에서 step이 이어서 수행됩니다.

    **권한**
    - 개인 스코프(team_id 없음): 로그인만 하면 가능
    - 팀 스코프(team_id 지정): 해당 팀의 ADMIN/OWNER만 실행 가능

    **에러**
    - 400: combinations 비어있음/조합이 비어있음
    - 403: 팀 권한 부족/시나리오 접근 불가/스코프 불일치
    - 404: 시나리오 없음
    """
    if not body.combinations:
        raise HTTPException(status_code=400, detail="combinations is empty")

    # Execution permission: team run requires ADMIN/OWNER; personal run always allowed
    if body.team_id:
        require_role(db, team_id=body.team_id, user_id=user.id, allow={TeamRole.OWNER.value, TeamRole.ADMIN.value})

    suite_id = str(uuid.uuid4())
    suite_dir = os.path.join(settings.ARTIFACT_ROOT, "suite", suite_id)
    Path(suite_dir).mkdir(parents=True, exist_ok=True)

    suite = SuiteRun(
        id=suite_id,
        requested_by_user_id=user.id,
        team_id=body.team_id,
        status=SuiteStatus.QUEUED.value,
        artifact_dir=suite_dir,
        submitted_combinations_json=json.dumps(body.combinations, ensure_ascii=False),
    )
    db.add(suite)
    db.commit()
    db.refresh(suite)

    case_ids: list[str] = []
    for idx, combo in enumerate(body.combinations, start=1):
        if not combo:
            raise HTTPException(status_code=400, detail=f"empty combination at index {idx}")

        # Validate scenario visibility
        scenarios: list[Scenario] = []
        for sid in combo:
            sc = db.get(Scenario, sid)
            if not sc:
                raise HTTPException(status_code=404, detail=f"scenario not found: {sid}")
            # personal visibility
            if sc.owner_user_id == user.id:
                scenarios.append(sc)
                continue
            # team visibility: must match suite team or any of user's teams
            if sc.owner_team_id:
                # if suite is team-scoped, require same team
                if body.team_id and sc.owner_team_id != body.team_id:
                    raise HTTPException(status_code=403, detail=f"scenario not in target team: {sid}")
                # require membership
                require_role(db, team_id=sc.owner_team_id, user_id=user.id, allow={TeamRole.OWNER.value, TeamRole.ADMIN.value, TeamRole.MEMBER.value})
                scenarios.append(sc)
                continue
            raise HTTPException(status_code=403, detail=f"no access to scenario: {sid}")

        case_id = str(uuid.uuid4())
        case_dir = os.path.join(suite_dir, f"case_{idx:03d}_{case_id}")
        Path(case_dir).mkdir(parents=True, exist_ok=True)

        combined_path = os.path.join(case_dir, "combined.json")
        # Combine steps (A안): same browser session = one scenario file with concatenated steps
        combined = {"base_url": scenarios[0].scenario_path, "steps": []}  # base_url will be overwritten below
        combined_base_url = None
        steps: list[dict] = []
        for sc in scenarios:
            # load scenario dict from file (json/yaml)
            from app.runner.scenario import load_scenario

            s = load_scenario(sc.scenario_path)
            combined_base_url = combined_base_url or s.base_url
            steps.extend(list(s.steps))
        combined = {"base_url": combined_base_url or "https://example.com", "steps": steps}

        # Optional: inject storageState for headless login bypass (Google test account recommended).
        if body.auth_state_id:
            try:
                copy_auth_state_to_dir(
                    owner_user_id=user.id,
                    auth_state_id=body.auth_state_id,
                    dest_dir=case_dir,
                    dest_filename="storage_state.json",
                )
                combined["requires_auth"] = True
                combined["storage_state_path"] = "./storage_state.json"
            except FileNotFoundError:
                raise HTTPException(status_code=404, detail="auth state not found")
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
            link = SuiteCaseScenario(suite_case_id=case.id, scenario_id=sc.id, order_index=order_i)
            db.add(link)

        case_ids.append(case_id)

    db.commit()

    # Queue execution: 순차 실행 (안정화를 위해 병렬 실행 비활성화)
    # 각 케이스를 순차적으로 실행한 후 finalize
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

    return SuiteCreated(suite_run_id=suite_id, status=suite.status, case_ids=case_ids)


@router.get("/{suite_run_id}", response_model=SuiteRunOut)
def get_suite_run(suite_run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    ## Suite Run 상태 조회

    - **권한**: 로그인 필요 + 본인이 요청한 suite_run만 조회 가능(MVP)
    - **응답**: suite 상태 + 케이스 집계(passed/failed count)
    """
    suite = db.get(SuiteRun, suite_run_id)
    if not suite:
        raise HTTPException(status_code=404, detail="suite run not found")
    if getattr(suite, "is_deleted", False):
        raise HTTPException(status_code=410, detail="suite run deleted")
    _require_suite_access(db, suite=suite, user=user)
    cases = db.query(SuiteCase).filter(SuiteCase.suite_run_id == suite.id).all()
    passed = sum(1 for c in cases if c.status == SuiteStatus.PASSED.value)
    failed = sum(1 for c in cases if c.status == SuiteStatus.FAILED.value)
    return SuiteRunOut(
        id=suite.id,
        status=suite.status,
        team_id=suite.team_id,
        created_at=suite.created_at.isoformat(),
        started_at=suite.started_at.isoformat() if suite.started_at else None,
        finished_at=suite.finished_at.isoformat() if suite.finished_at else None,
        case_count=len(cases),
        passed_cases=passed,
        failed_cases=failed,
    )


@router.get("/{suite_run_id}/cases")
def list_cases(suite_run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    ## Suite Run 케이스 목록

    - **권한**: 로그인 필요 + 본인이 요청한 suite_run만
    - **응답**: case_index 순으로 케이스의 상태/시간/exit_code
    """
    suite = db.get(SuiteRun, suite_run_id)
    if not suite:
        raise HTTPException(status_code=404, detail="suite run not found")
    if getattr(suite, "is_deleted", False):
        raise HTTPException(status_code=410, detail="suite run deleted")
    _require_suite_access(db, suite=suite, user=user)
    rows = db.query(SuiteCase).filter(SuiteCase.suite_run_id == suite.id).order_by(SuiteCase.case_index.asc()).all()
    return [
        {
            "id": c.id,
            "case_index": c.case_index,
            "status": c.status,
            "started_at": c.started_at.isoformat() if c.started_at else None,
            "finished_at": c.finished_at.isoformat() if c.finished_at else None,
            "exit_code": c.exit_code,
        }
        for c in rows
    ]


@router.get("/{suite_run_id}/report.pdf")
def download_suite_report(suite_run_id: str, refresh: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    ## Suite 합본 리포트(PDF) 다운로드

    - **권한**: 로그인 필요 + 본인이 요청한 suite_run만
    - **동작**:
      - 워커 finalize 시점에 자동으로 `{suite.artifact_dir}/suite_report.pdf`를 생성합니다.
      - `refresh=true`면 API 호출 시 재생성합니다(최신 케이스 아티팩트 기준).
    """
    suite = db.get(SuiteRun, suite_run_id)
    if not suite:
        raise HTTPException(status_code=404, detail="suite run not found")
    if getattr(suite, "is_deleted", False):
        raise HTTPException(status_code=410, detail="suite run deleted")
    _require_suite_access(db, suite=suite, user=user)
    pdf_path = Path(suite.artifact_dir) / "suite_report.pdf"
    # Auto-heal: if an existing suite_report is cover-only (<=2 pages), regenerate.
    if pdf_path.exists() and not refresh:
        try:
            from pypdf import PdfReader

            r = PdfReader(str(pdf_path))
            if len(r.pages) <= 2:
                refresh = True
        except Exception:
            pass

    if refresh or not pdf_path.exists():
        cases = db.query(SuiteCase).filter(SuiteCase.suite_run_id == suite.id).all()
        case_dicts = [
            {
                "case_index": c.case_index,
                "case_id": c.id,
                "status": c.status,
                "started_at": c.started_at,
                "finished_at": c.finished_at,
                "error_message": c.error_message,
                "artifact_dir": c.artifact_dir,
                "combined_scenario_path": c.combined_scenario_path,
            }
            for c in cases
        ]
        generate_suite_report_pdf(
            suite_id=suite.id,
            status=suite.status,
            created_at=suite.created_at,
            started_at=suite.started_at,
            finished_at=suite.finished_at,
            suite_dir=suite.artifact_dir,
            cases=case_dicts,
            output_path=str(pdf_path),
        )
        suite.summary_pdf_path = str(pdf_path)
        db.commit()
    return FileResponse(path=str(pdf_path), filename="suite_report.pdf")


@router.delete(
    "/{suite_run_id}",
    summary="Suite Run 이력 삭제(soft delete) + artifact pending_delete 이관",
    description="""
    Suite Run 이력을 삭제(soft delete) 처리합니다.

    - 개인 스코프(team_id 없음): 요청자만 가능
    - 팀 스코프(team_id 있음): **팀 OWNER만 가능**
    - RUNNING/QUEUED 상태에서는 삭제 불가(409)
    - artifact_dir를 `ARTIFACT_ROOT/_pending_delete/suite_{id}_{ts}/`로 이동(best-effort)
    """,
)
def delete_suite_run(suite_run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    suite = db.get(SuiteRun, suite_run_id)
    if not suite:
        raise HTTPException(status_code=404, detail="suite run not found")

    # permission
    if suite.team_id:
        require_role(db, team_id=suite.team_id, user_id=user.id, allow={TeamRole.OWNER.value})
    else:
        if suite.requested_by_user_id != user.id:
            raise HTTPException(status_code=404, detail="suite run not found")

    if getattr(suite, "is_deleted", False):
        return {"deleted": True, "id": suite_run_id, "already_deleted": True}

    if suite.status in (SuiteStatus.QUEUED.value, SuiteStatus.RUNNING.value):
        raise HTTPException(status_code=409, detail="cannot delete while running/queued")

    old_dir = Path(suite.artifact_dir)
    pending_root = Path(settings.ARTIFACT_ROOT) / "_pending_delete"
    pending_root.mkdir(parents=True, exist_ok=True)
    new_dir = pending_root / f"suite_{suite.id}_{int(time.time())}"

    moved = False
    try:
        if old_dir.exists():
            old_dir.rename(new_dir)
            moved = True
    except Exception:
        moved = False

    if moved:
        suite.artifact_dir = str(new_dir)
        suite.deleted_artifact_dir = str(new_dir)

    suite.is_deleted = True
    suite.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"deleted": True, "id": suite_run_id, "moved": moved, "pending_dir": suite.deleted_artifact_dir}


