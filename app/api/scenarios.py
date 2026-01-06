from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.config import settings
from app.db.models import Scenario, TeamMember, TeamRole, User
from app.db.session import get_db
from app.runner.scenario_validator import validate_scenario, get_scenario_schema_example


router = APIRouter(prefix="/scenarios", tags=["scenarios"])


class ScenarioOut(BaseModel):
    id: str
    name: str
    owner_user_id: str | None
    owner_team_id: str | None
    created_at: str
    updated_at: str


class PublishIn(BaseModel):
    team_id: str
    name: str | None = None


class ScenarioContentOut(BaseModel):
    id: str
    name: str
    content: dict


class ScenarioContentIn(BaseModel):
    content: dict


class ScenarioValidationOut(BaseModel):
    valid: bool
    errors: list[str]
    example: dict | None = None


def _ensure_dirs() -> None:
    Path(settings.SCENARIO_ROOT).mkdir(parents=True, exist_ok=True)


def _require_team_role(db: Session, *, team_id: str, user_id: str, allow: set[str]) -> TeamMember:
    m = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
        .first()
    )
    if not m or m.role not in allow:
        raise HTTPException(status_code=403, detail="insufficient team role")
    return m


@router.post("", response_model=ScenarioOut)
async def upload_my_scenario(
    name: str,
    scenario: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    ## 내 시나리오 업로드

    - **권한**: 로그인 필요(Bearer JWT)
    - **요청**:
      - Query: `name` (시나리오 이름)
      - Multipart: `scenario` 파일(.yaml/.yml/.json)
    - **처리**:
      - 파일을 `SCENARIO_ROOT/{user_id}/{scenario_id}.(yaml|json)`에 저장
      - DB에 Scenario row 생성(owner_user_id=user)
    - **응답**: Scenario 메타데이터
    - **에러**:
      - 400: 빈 파일
      - 401: 인증 실패
    """
    _ensure_dirs()
    sid = str(uuid.uuid4())
    filename = scenario.filename or "scenario.yaml"
    ext = os.path.splitext(filename)[1].lower() or ".yaml"
    path = os.path.join(settings.SCENARIO_ROOT, user.id, f"{sid}{ext}")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    content = await scenario.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty scenario file")
    
    # 파일 내용 파싱 및 검증
    try:
        if ext == ".json":
            scenario_dict = json.loads(content.decode("utf-8"))
        else:
            import yaml
            scenario_dict = yaml.safe_load(content.decode("utf-8"))
        
        # 검증 수행
        is_valid, errors = validate_scenario(scenario_dict)
        if not is_valid:
            error_msg = "시나리오 검증 실패:\n" + "\n".join(f"- {e}" for e in errors)
            raise HTTPException(status_code=400, detail=error_msg)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 파싱 오류: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"시나리오 파싱 오류: {str(e)}")
    
    with open(path, "wb") as f:
        f.write(content)
    sc = Scenario(id=sid, name=name, owner_user_id=user.id, owner_team_id=None, scenario_path=path)
    db.add(sc)
    db.commit()
    db.refresh(sc)
    return ScenarioOut(
        id=sc.id,
        name=sc.name,
        owner_user_id=sc.owner_user_id,
        owner_team_id=sc.owner_team_id,
        created_at=sc.created_at.isoformat(),
        updated_at=sc.updated_at.isoformat(),
    )


@router.get("/me", response_model=list[ScenarioOut])
def list_my_scenarios(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    ## 내 시나리오 목록

    - **권한**: 로그인 필요
    - **처리**: `owner_user_id == me.id`인 시나리오만 반환
    """
    rows = db.query(Scenario).filter(Scenario.owner_user_id == user.id).order_by(Scenario.created_at.desc()).all()
    return [
        ScenarioOut(
            id=s.id,
            name=s.name,
            owner_user_id=s.owner_user_id,
            owner_team_id=s.owner_team_id,
            created_at=s.created_at.isoformat(),
            updated_at=s.updated_at.isoformat(),
        )
        for s in rows
    ]


@router.post("/{scenario_id}/publish", response_model=ScenarioOut)
def publish_to_team(
    scenario_id: str,
    body: PublishIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    ## 내 시나리오를 팀 시나리오로 발행(publish)

    - **권한**: 로그인 필요 + 대상 팀의 멤버(OWNER/ADMIN/MEMBER)
    - **처리**:
      - 개인 시나리오(owner_user_id=me)만 발행 가능
      - 원본 파일을 `SCENARIO_ROOT/teams/{team_id}/{new_id}.ext`로 복사
      - 새 Scenario를 `owner_team_id=team_id`로 생성(원본 추적: source_scenario_id)
    - **응답**: 생성된 팀 시나리오 메타
    - **에러**:
      - 403: 팀 멤버가 아님 / 접근 불가
      - 404: 시나리오 없음
    """
    # 모든 유저는 팀 시나리오 생성 가능 -> MEMBER도 publish 가능
    _require_team_role(db, team_id=body.team_id, user_id=user.id, allow={TeamRole.OWNER.value, TeamRole.ADMIN.value, TeamRole.MEMBER.value})

    src = db.get(Scenario, scenario_id)
    if not src or src.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="scenario not found")

    sid = str(uuid.uuid4())
    src_path = Path(src.scenario_path)
    ext = src_path.suffix or ".yaml"
    _ensure_dirs()
    dest_path = os.path.join(settings.SCENARIO_ROOT, "teams", body.team_id, f"{sid}{ext}")
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    Path(dest_path).write_bytes(src_path.read_bytes())

    sc = Scenario(
        id=sid,
        name=body.name or src.name,
        owner_user_id=None,
        owner_team_id=body.team_id,
        scenario_path=dest_path,
        source_scenario_id=src.id,
    )
    db.add(sc)
    db.commit()
    db.refresh(sc)
    return ScenarioOut(
        id=sc.id,
        name=sc.name,
        owner_user_id=sc.owner_user_id,
        owner_team_id=sc.owner_team_id,
        created_at=sc.created_at.isoformat(),
        updated_at=sc.updated_at.isoformat(),
    )


@router.delete(
    "/{scenario_id}",
    summary="내 개인 시나리오 삭제(파일+DB)",
    description="""
    개인 시나리오를 삭제합니다.

    - **권한**: 로그인 필요 + owner_user_id == me.id
    - **처리**:
      - 시나리오 파일 삭제(best-effort)
      - DB Scenario row 삭제
    """,
)
def delete_my_scenario(scenario_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sc = db.get(Scenario, scenario_id)
    if not sc or sc.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="scenario not found")
    try:
        p = Path(sc.scenario_path)
        if p.exists() and p.is_file():
            p.unlink()
    except Exception:
        # best-effort
        pass
    db.delete(sc)
    db.commit()
    return {"deleted": True, "id": scenario_id}


@router.get(
    "/{scenario_id}/content",
    response_model=ScenarioContentOut,
    summary="내 개인 시나리오 내용(JSON) 조회",
    description="""
    시나리오 파일(JSON)을 읽어 그대로 반환합니다.

    - **권한**: 로그인 필요 + owner_user_id == me.id
    - **주의**: MVP는 JSON 기반 편집을 우선 지원합니다.
    """,
)
def get_my_scenario_content(scenario_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sc = db.get(Scenario, scenario_id)
    if not sc or sc.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="scenario not found")
    p = Path(sc.scenario_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="scenario file not found")
    if p.suffix.lower() != ".json":
        raise HTTPException(status_code=400, detail="only .json scenario is supported for content API (MVP)")
    try:
        content = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="failed to parse scenario json")
    return ScenarioContentOut(id=sc.id, name=sc.name, content=content)


@router.post(
    "/validate",
    response_model=ScenarioValidationOut,
    summary="시나리오 검증",
    description="""
    시나리오가 runner에서 안정적으로 실행될 수 있는지 검증합니다.

    - **권한**: 로그인 필요
    - **응답**: 검증 결과와 에러 목록, 예시 스키마
    """,
)
def validate_scenario_api(
    body: ScenarioContentIn,
    user: User = Depends(get_current_user),
):
    is_valid, errors = validate_scenario(body.content)
    example = get_scenario_schema_example() if not is_valid else None
    return ScenarioValidationOut(valid=is_valid, errors=errors, example=example)


@router.put(
    "/{scenario_id}/content",
    response_model=ScenarioContentOut,
    summary="내 개인 시나리오 내용(JSON) 수정/저장",
    description="""
    UI 에디터에서 수정한 시나리오 JSON을 파일에 덮어씁니다.

    - **권한**: 로그인 필요 + owner_user_id == me.id
    - **주의**: MVP는 JSON 기반 편집을 우선 지원합니다.
    - **검증**: 저장 전 자동으로 시나리오 검증을 수행합니다.
    """,
)
def update_my_scenario_content(
    scenario_id: str,
    body: ScenarioContentIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sc = db.get(Scenario, scenario_id)
    if not sc or sc.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="scenario not found")
    
    # 저장 전 검증
    is_valid, errors = validate_scenario(body.content)
    if not is_valid:
        error_msg = "시나리오 검증 실패:\n" + "\n".join(f"- {e}" for e in errors)
        raise HTTPException(status_code=400, detail=error_msg)
    
    p = Path(sc.scenario_path)
    if p.suffix.lower() != ".json":
        raise HTTPException(status_code=400, detail="only .json scenario is supported for content API (MVP)")
    p.write_text(json.dumps(body.content, ensure_ascii=False, indent=2), encoding="utf-8")
    db.commit()  # updated_at onupdate
    db.refresh(sc)
    return ScenarioContentOut(id=sc.id, name=sc.name, content=body.content)


