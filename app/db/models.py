"""
SQLAlchemy models for persisting run metadata.

This MVP stores run state in a single ``runs`` table and uses the filesystem as
the source of truth for artifacts (scanned at request time).
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.session import Base


# ----------------------------
# Existing single-run table (kept for backward compatibility)
# ----------------------------

class RunStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID string
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    owner_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    scenario_path: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_dir: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # soft delete (artifact dir is moved to pending-delete directory)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    deleted_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_artifact_dir: Mapped[str | None] = mapped_column(Text, nullable=True)


# ----------------------------
# Auth + ownership model
# ----------------------------

class TeamRole(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    memberships: Mapped[list["TeamMember"]] = relationship(back_populates="user")
    scenarios: Mapped[list["Scenario"]] = relationship(back_populates="owner_user")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    members: Mapped[list["TeamMember"]] = relationship(back_populates="team")
    scenarios: Mapped[list["Scenario"]] = relationship(back_populates="owner_team")
    api_keys: Mapped[list["TeamApiKey"]] = relationship(back_populates="team")


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=TeamRole.MEMBER.value)
    joined_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    team: Mapped["Team"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships")


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # ownership: personal OR team
    owner_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_team_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    # file path (yaml/json) stored in filesystem
    scenario_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    source_scenario_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("scenarios.id", ondelete="SET NULL"), nullable=True)

    owner_user: Mapped["User | None"] = relationship(back_populates="scenarios", foreign_keys=[owner_user_id])
    owner_team: Mapped["Team | None"] = relationship(back_populates="scenarios", foreign_keys=[owner_team_id])


# ----------------------------
# Suite execution model (user-defined combinations)
# ----------------------------

class SuiteStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class SuiteRun(Base):
    __tablename__ = "suite_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    requested_by_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # target scope
    team_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=SuiteStatus.QUEUED.value, index=True)

    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    artifact_dir: Mapped[str] = mapped_column(Text, nullable=False)
    summary_pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_combinations_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- External trigger (CI/CD) ---
    trigger_api_key_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("team_api_keys.id", ondelete="SET NULL"), nullable=True, index=True)
    external_idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    external_context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    webhook_last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    webhook_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_delivered_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    deleted_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_artifact_dir: Mapped[str | None] = mapped_column(Text, nullable=True)

    cases: Mapped[list["SuiteCase"]] = relationship(back_populates="suite_run", cascade="all, delete-orphan")

    trigger_api_key: Mapped["TeamApiKey | None"] = relationship()


class CombinationDraft(Base):
    """
    사용자가 '제출할 조합 목록'을 저장해두는 Draft.
    - 개인 단위로만 관리(owner_user_id)
    - 필요 시 삭제
    """

    __tablename__ = "combination_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    team_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    combinations_json: Mapped[str] = mapped_column(Text, nullable=False)  # json string
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SuiteCase(Base):
    __tablename__ = "suite_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    suite_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("suite_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    case_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=SuiteStatus.QUEUED.value, index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_dir: Mapped[str] = mapped_column(Text, nullable=False)
    combined_scenario_path: Mapped[str] = mapped_column(Text, nullable=False)

    suite_run: Mapped["SuiteRun"] = relationship(back_populates="cases")
    scenario_links: Mapped[list["SuiteCaseScenario"]] = relationship(
        back_populates="suite_case", cascade="all, delete-orphan"
    )


class SuiteCaseScenario(Base):
    __tablename__ = "suite_case_scenarios"
    __table_args__ = (UniqueConstraint("suite_case_id", "order_index", name="uq_case_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    suite_case_id: Mapped[str] = mapped_column(String(36), ForeignKey("suite_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    suite_case: Mapped["SuiteCase"] = relationship(back_populates="scenario_links")
    scenario: Mapped["Scenario"] = relationship()


# ----------------------------
# Team API keys (for CI/CD public API)
# ----------------------------

class TeamApiKey(Base):
    __tablename__ = "team_api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Token format: dubbi_sk_<prefix>_<secret>
    prefix: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # sha256 hex

    created_by_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    revoked_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    team: Mapped["Team"] = relationship(back_populates="api_keys")


# ----------------------------
# Integration logs (external trigger + webhook delivery)
# ----------------------------


class ExternalSuiteRequestLog(Base):
    __tablename__ = "external_suite_request_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    api_key_id: Mapped[str] = mapped_column(String(36), ForeignKey("team_api_keys.id", ondelete="CASCADE"), nullable=False, index=True)
    suite_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("suite_runs.id", ondelete="CASCADE"), nullable=False, index=True)

    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    request_context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    remote_addr: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class WebhookDeliveryLog(Base):
    __tablename__ = "webhook_delivery_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    team_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    suite_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("suite_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
