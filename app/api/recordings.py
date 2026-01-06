from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.config import settings
from app.db.models import Scenario, User
from app.db.session import get_db
from app.runner.scenario_compiler import compile_scenario


router = APIRouter(prefix="/recordings", tags=["recordings"])


class RecordingEvent(BaseModel):
    kind: Literal["action", "assert"] = Field(..., description="이벤트 종류(action/assert)")
    type: str = Field(..., description="이벤트 타입(click/input/navigate/assert_text/assert_visible/assert_url 등)")
    selector: str | None = None
    url: str | None = None
    text: str | None = None
    value: str | None = None
    # Optional meta from advanced recorder (ignored by older clients)
    id: str | None = None
    ts: int | None = None
    delay: int | None = Field(None, description="(ms) 다음 스텝까지 기다릴 시간")
    frame: dict[str, Any] | None = Field(
        None, description="(선택) 프레임 메타 {href,name,isTop} - iframe 이벤트 실행에 사용"
    )


class RecordingToScenarioIn(BaseModel):
    name: str = Field(..., description="생성될 개인 시나리오 이름")
    base_url: str | None = Field(None, description="(선택) base_url")
    events: list[RecordingEvent] = Field(..., description="브라우저에서 기록한 이벤트 리스트")


class ScenarioOut(BaseModel):
    id: str
    name: str
    owner_user_id: str | None
    owner_team_id: str | None
    created_at: str
    updated_at: str


@router.options(
    "/to-scenario",
    summary="(CORS) recorder 업로드 preflight",
    include_in_schema=False,
)
def recordings_to_scenario_preflight() -> Response:
    # CORSMiddleware가 헤더를 처리하지만, 일부 환경에서 OPTIONS가 400/405로 떨어지는 경우를 방지합니다.
    return Response(status_code=200)


def _ensure_dirs() -> None:
    Path(settings.SCENARIO_ROOT).mkdir(parents=True, exist_ok=True)


def _events_to_steps(events: list[RecordingEvent]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for ev in events:
        t = ev.type
        delay_ms = int(ev.delay or 0)
        frame = ev.frame
        if t == "navigate" and ev.url:
            s: dict[str, Any] = {"type": "go", "url": ev.url}
            if delay_ms:
                s["delay_ms"] = delay_ms
            if frame:
                s["frame"] = frame
            steps.append(s)
        elif t == "click" and ev.selector:
            s = {"type": "click", "selector": ev.selector}
            if delay_ms:
                s["delay_ms"] = delay_ms
            if frame:
                s["frame"] = frame
            steps.append(s)
        elif t == "click_popup" and ev.selector:
            # Click that is expected to open a popup/new page (target=_blank, window.open)
            s = {"type": "click_popup", "selector": ev.selector}
            if ev.url:
                s["popup_url"] = ev.url
            if delay_ms:
                s["delay_ms"] = delay_ms
            if frame:
                s["frame"] = frame
            steps.append(s)
        elif t == "popup_open" and ev.url:
            # Some sites open popup programmatically (window.open). Open a new page and goto url.
            s = {"type": "popup_go", "url": ev.url}
            if delay_ms:
                s["delay_ms"] = delay_ms
            if frame:
                s["frame"] = frame
            steps.append(s)
        elif t == "popup_close":
            steps.append({"type": "close_page"})
        elif t in ("input", "fill") and ev.selector is not None:
            # Recorder can emit many input events (per keystroke). Compress by keeping only
            # the latest value for the same selector until the next non-fill action.
            if steps and steps[-1].get("type") == "fill" and steps[-1].get("selector") == ev.selector:
                steps[-1]["value"] = ev.value or ""
                if delay_ms:
                    steps[-1]["delay_ms"] = delay_ms
            else:
                s = {"type": "fill", "selector": ev.selector, "value": ev.value or ""}
                if delay_ms:
                    s["delay_ms"] = delay_ms
                if frame:
                    s["frame"] = frame
                steps.append(s)
        elif t == "assert_text" and ev.selector and ev.text is not None:
            s = {"type": "expect_text", "selector": ev.selector, "text": ev.text}
            if delay_ms:
                s["delay_ms"] = delay_ms
            if frame:
                s["frame"] = frame
            steps.append(s)
        elif t == "assert_visible" and ev.selector:
            s = {"type": "expect_visible", "selector": ev.selector}
            if delay_ms:
                s["delay_ms"] = delay_ms
            if frame:
                s["frame"] = frame
            steps.append(s)
        elif t == "assert_url" and ev.url:
            s = {"type": "expect_url", "url": ev.url}
            if delay_ms:
                s["delay_ms"] = delay_ms
            if frame:
                s["frame"] = frame
            steps.append(s)
        else:
            # unknown/insufficient event -> skip (MVP)
            continue
    return steps


def _infer_base_url(events: list[RecordingEvent]) -> str | None:
    for ev in events:
        if ev.type == "navigate" and ev.url:
            try:
                from urllib.parse import urlparse

                u = urlparse(ev.url)
                if u.scheme and u.netloc:
                    return f"{u.scheme}://{u.netloc}"
            except Exception:
                continue
    return None


@router.post(
    "/to-scenario",
    response_model=ScenarioOut,
    summary="브라우저 녹화 이벤트를 개인 시나리오(JSON)로 변환/저장",
    description="""
    크롬 확장(Recorder)에서 수집한 이벤트 목록을 현재 서비스의 시나리오 포맷(steps)으로 변환합니다.

    - **권한**: 로그인 필요(Bearer JWT)
    - **검증(step) MVP**: expect_text / expect_visible / expect_url
    - **저장 위치**: SCENARIO_ROOT/{user_id}/{scenario_id}.json
    """,
)
def recording_to_scenario(body: RecordingToScenarioIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    if not body.events:
        raise HTTPException(status_code=400, detail="events is empty")

    _ensure_dirs()
    sid = str(uuid.uuid4())
    path = os.path.join(settings.SCENARIO_ROOT, user.id, f"{sid}.json")
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    base_url = body.base_url or _infer_base_url(body.events) or ""
    
    # Step 1: Raw events를 steps로 변환
    raw_scenario: dict[str, Any] = {
        "base_url": base_url,
        "steps": _events_to_steps(body.events),
        "_meta": {"source": "chrome_extension_recorder_v1"},
    }
    
    # Step 2: Scenario Compiler로 Executable Scenario로 변환
    # - Selector 후보군 생성
    # - Wait 자동 삽입
    # - 텍스트 기반 locator 추가
    scenario_obj = compile_scenario(raw_scenario)

    Path(path).write_text(json.dumps(scenario_obj, ensure_ascii=False, indent=2), encoding="utf-8")

    sc = Scenario(id=sid, name=body.name.strip(), owner_user_id=user.id, owner_team_id=None, scenario_path=path)
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


