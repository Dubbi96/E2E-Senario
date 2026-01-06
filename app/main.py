"""
FastAPI application entrypoint.

This module defines the FastAPI app and mounts the routes used to
submit new test runs. The actual business logic lives in other
modules under the app package (for example, ``app/api/routes_runs.py``).
"""

import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes_runs import router as runs_router
from app.api.auth import router as auth_router
from app.api.scenarios import router as scenarios_router
from app.api.teams import router as teams_router
from app.api.suite_runs import router as suite_runs_router
from app.api.drafts import router as drafts_router
from app.api.recordings import router as recordings_router
from app.api.public import router as public_router
from app.api.team_api_keys import router as team_api_keys_router
from app.api.integration_logs import router as integration_logs_router
from app.api.auth_states import router as auth_states_router
from app.core.config import settings
from app.db.session import Base, engine
from app.db.schema_ensure import ensure_schema
from sqlalchemy.exc import OperationalError

# Create FastAPI app instance and include the runs router.
app = FastAPI(title="E2E Service")
origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    # Recorder extension(content/background)의 Origin은 chrome-extension://... 또는 경우에 따라 null로 들어올 수 있습니다.
    # 또한 본 서비스는 쿠키 기반 인증을 사용하지 않고 Bearer(JWT) 헤더를 사용하므로 credentials는 필요 없습니다.
    # -> allow_credentials=False + allow_origins=["*"]로 preflight/업로드를 가장 안정적으로 처리합니다.
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(runs_router, prefix="/runs", tags=["runs"])
app.include_router(auth_router)
app.include_router(auth_states_router)
app.include_router(scenarios_router)
app.include_router(teams_router)
app.include_router(suite_runs_router)
app.include_router(drafts_router)
app.include_router(recordings_router)
app.include_router(public_router)
app.include_router(team_api_keys_router)
app.include_router(integration_logs_router)


@app.on_event("startup")
def on_startup() -> None:
    # Ensure models are registered before creating tables.
    # (import side-effect registers `Run` on `Base.metadata`).
    from app.db import models  # noqa: F401

    # Docker compose 환경에서 DB가 아직 ready가 아닐 수 있어, 간단히 재시도합니다.
    last_exc: Exception | None = None
    for _ in range(10):
        try:
            Base.metadata.create_all(bind=engine)
            # Additive schema updates for existing DBs (no Alembic in MVP)
            ensure_schema(engine)
            return
        except OperationalError as e:
            last_exc = e
            time.sleep(1)
    if last_exc:
        raise last_exc
