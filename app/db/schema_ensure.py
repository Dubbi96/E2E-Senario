from __future__ import annotations

"""
Lightweight schema auto-migration for MVP.

We don't use Alembic yet. `create_all()` creates tables but does NOT add columns.
This module ensures a small set of additive columns at startup using Postgres'
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (best-effort).
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine


def ensure_schema(engine: Engine) -> None:
    # Only attempt on Postgres (our docker compose default). Best-effort.
    if engine.dialect.name not in ("postgresql", "postgres"):
        return

    stmts = [
        # runs: ownership + soft-delete fields (additive)
        'ALTER TABLE IF EXISTS runs ADD COLUMN IF NOT EXISTS owner_user_id VARCHAR(36)',
        'ALTER TABLE IF EXISTS runs ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE',
        'ALTER TABLE IF EXISTS runs ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ',
        'ALTER TABLE IF EXISTS runs ADD COLUMN IF NOT EXISTS deleted_artifact_dir TEXT',
        # suite_runs: preserve submitted combinations (additive)
        'ALTER TABLE IF EXISTS suite_runs ADD COLUMN IF NOT EXISTS submitted_combinations_json TEXT',
        'ALTER TABLE IF EXISTS suite_runs ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE',
        'ALTER TABLE IF EXISTS suite_runs ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ',
        'ALTER TABLE IF EXISTS suite_runs ADD COLUMN IF NOT EXISTS deleted_artifact_dir TEXT',

        # suite_runs: external trigger + webhook (additive)
        'ALTER TABLE IF EXISTS suite_runs ADD COLUMN IF NOT EXISTS trigger_api_key_id VARCHAR(36)',
        'ALTER TABLE IF EXISTS suite_runs ADD COLUMN IF NOT EXISTS external_idempotency_key VARCHAR(200)',
        'ALTER TABLE IF EXISTS suite_runs ADD COLUMN IF NOT EXISTS external_context_json TEXT',
        'ALTER TABLE IF EXISTS suite_runs ADD COLUMN IF NOT EXISTS webhook_url TEXT',
        'ALTER TABLE IF EXISTS suite_runs ADD COLUMN IF NOT EXISTS webhook_secret TEXT',
        'ALTER TABLE IF EXISTS suite_runs ADD COLUMN IF NOT EXISTS webhook_attempts INTEGER NOT NULL DEFAULT 0',
        'ALTER TABLE IF EXISTS suite_runs ADD COLUMN IF NOT EXISTS webhook_last_status_code INTEGER',
        'ALTER TABLE IF EXISTS suite_runs ADD COLUMN IF NOT EXISTS webhook_last_error TEXT',
        'ALTER TABLE IF EXISTS suite_runs ADD COLUMN IF NOT EXISTS webhook_delivered_at TIMESTAMPTZ',
    ]

    with engine.begin() as conn:
        for sql in stmts:
            try:
                conn.execute(text(sql))
            except Exception:
                # best-effort: don't block startup in MVP
                continue


