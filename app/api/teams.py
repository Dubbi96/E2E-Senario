from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.models import Team, TeamMember, TeamRole, User, Scenario
from app.db.session import get_db


router = APIRouter(prefix="/teams", tags=["teams"])


class TeamOut(BaseModel):
    id: str
    name: str


class TeamCreateIn(BaseModel):
    name: str


class TeamMemberOut(BaseModel):
    user_id: str
    role: str


class AddMemberIn(BaseModel):
    user_id: str
    role: str = TeamRole.MEMBER.value


class TeamScenarioUpdateIn(BaseModel):
    name: str | None = None


def require_role(db: Session, *, team_id: str, user_id: str, allow: set[str]) -> TeamMember:
    m = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
        .first()
    )
    if not m or m.role not in allow:
        raise HTTPException(status_code=403, detail="insufficient team role")
    return m


@router.post("", response_model=TeamOut)
def create_team(data: TeamCreateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    ## 팀 생성

    - **권한**: 로그인 필요
    - **처리**:
      - Team 생성
      - 생성자를 TeamMember(OWNER)로 자동 등록
    - **응답**: team id/name
    """
    team = Team(name=data.name)
    db.add(team)
    db.commit()
    db.refresh(team)

    # creator becomes OWNER
    m = TeamMember(team_id=team.id, user_id=user.id, role=TeamRole.OWNER.value)
    db.add(m)
    db.commit()
    return TeamOut(id=team.id, name=team.name)


@router.get("/me", response_model=list[TeamOut])
def list_my_teams(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    ## 내가 속한 팀 목록

    - **권한**: 로그인 필요
    - **처리**: TeamMember 조인으로 `user_id==me`인 팀만 반환
    """
    rows = (
        db.query(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .filter(TeamMember.user_id == user.id)
        .order_by(Team.created_at.desc())
        .all()
    )
    return [TeamOut(id=t.id, name=t.name) for t in rows]


@router.get("/{team_id}/members", response_model=list[TeamMemberOut])
def list_members(team_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    ## 팀 멤버 목록

    - **권한**: 로그인 필요 + 팀 멤버(OWNER/ADMIN/MEMBER)
    """
    require_role(db, team_id=team_id, user_id=user.id, allow={TeamRole.OWNER.value, TeamRole.ADMIN.value, TeamRole.MEMBER.value})
    rows = db.query(TeamMember).filter(TeamMember.team_id == team_id).all()
    return [TeamMemberOut(user_id=r.user_id, role=r.role) for r in rows]


@router.post("/{team_id}/members", response_model=TeamMemberOut)
def add_member(team_id: str, body: AddMemberIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    ## 팀 멤버 추가

    - **권한**: OWNER만
    - **주의**: 실제 서비스에선 초대/수락 플로우를 두는 것을 권장(MVP 단순화)
    """
    # membership 관리(추가)는 OWNER만 (요청에 명시되지 않았지만 안전상 기본값)
    require_role(db, team_id=team_id, user_id=user.id, allow={TeamRole.OWNER.value})
    existing = db.query(TeamMember).filter(TeamMember.team_id == team_id, TeamMember.user_id == body.user_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="member already exists")
    if body.role not in {TeamRole.OWNER.value, TeamRole.ADMIN.value, TeamRole.MEMBER.value}:
        raise HTTPException(status_code=400, detail="invalid role")
    m = TeamMember(team_id=team_id, user_id=body.user_id, role=body.role)
    db.add(m)
    db.commit()
    return TeamMemberOut(user_id=m.user_id, role=m.role)


@router.get("/{team_id}/scenarios", response_model=list[dict])
def list_team_scenarios(team_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    ## 팀 시나리오 목록

    - **권한**: 팀 멤버(OWNER/ADMIN/MEMBER)
    """
    require_role(db, team_id=team_id, user_id=user.id, allow={TeamRole.OWNER.value, TeamRole.ADMIN.value, TeamRole.MEMBER.value})
    rows = db.query(Scenario).filter(Scenario.owner_team_id == team_id).order_by(Scenario.created_at.desc()).all()
    return [{"id": s.id, "name": s.name, "created_at": s.created_at.isoformat()} for s in rows]


@router.get("/{team_id}/suite-runs")
def list_team_suite_runs(team_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    ## 팀 Suite Run 실행 이력

    - **권한**: 팀 멤버(OWNER/ADMIN/MEMBER)
    - **처리**: suite_runs.team_id == team_id 인 실행 이력 반환
    """
    require_role(
        db,
        team_id=team_id,
        user_id=user.id,
        allow={TeamRole.OWNER.value, TeamRole.ADMIN.value, TeamRole.MEMBER.value},
    )
    from app.db.models import SuiteRun

    rows = (
        db.query(SuiteRun)
        .filter(SuiteRun.team_id == team_id, SuiteRun.is_deleted == False)  # noqa: E712
        .order_by(SuiteRun.created_at.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": r.id,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in rows
    ]


@router.patch("/{team_id}/scenarios/{scenario_id}")
def update_team_scenario(
    team_id: str,
    scenario_id: str,
    body: TeamScenarioUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    ## 팀 시나리오 이름 수정

    - **권한**: OWNER만
    """
    # 수정은 OWNER만
    require_role(db, team_id=team_id, user_id=user.id, allow={TeamRole.OWNER.value})
    sc = db.get(Scenario, scenario_id)
    if not sc or sc.owner_team_id != team_id:
        raise HTTPException(status_code=404, detail="scenario not found")
    if body.name:
        sc.name = body.name
    db.commit()
    return {"id": sc.id, "name": sc.name, "updated_at": sc.updated_at.isoformat()}


@router.put("/{team_id}/scenarios/{scenario_id}/file")
async def replace_team_scenario_file(
    team_id: str,
    scenario_id: str,
    scenario: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    ## 팀 시나리오 파일 교체

    - **권한**: OWNER만
    - **요청**: multipart `scenario` 파일(기존 파일 경로에 overwrite)
    """
    # 수정(파일 교체)도 OWNER만
    require_role(db, team_id=team_id, user_id=user.id, allow={TeamRole.OWNER.value})
    sc = db.get(Scenario, scenario_id)
    if not sc or sc.owner_team_id != team_id:
        raise HTTPException(status_code=404, detail="scenario not found")
    content = await scenario.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty scenario file")
    Path(sc.scenario_path).parent.mkdir(parents=True, exist_ok=True)
    with open(sc.scenario_path, "wb") as f:
        f.write(content)
    db.commit()
    return {"id": sc.id, "scenario_path": sc.scenario_path, "updated_at": sc.updated_at.isoformat()}


@router.delete("/{team_id}/scenarios/{scenario_id}")
def delete_team_scenario(
    team_id: str,
    scenario_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    ## 팀 시나리오 삭제

    - **권한**: OWNER만
    - **처리**: DB row 삭제 + 시나리오 파일 best-effort 삭제
    """
    # 삭제는 OWNER만
    require_role(db, team_id=team_id, user_id=user.id, allow={TeamRole.OWNER.value})
    sc = db.get(Scenario, scenario_id)
    if not sc or sc.owner_team_id != team_id:
        raise HTTPException(status_code=404, detail="scenario not found")
    # best-effort file delete
    try:
        if sc.scenario_path and os.path.exists(sc.scenario_path):
            os.remove(sc.scenario_path)
    except Exception:
        pass
    db.delete(sc)
    db.commit()
    return {"deleted": True, "id": scenario_id}


