"""
Centralised configuration using Pydantic settings.

This module defines a ``Settings`` class which encapsulates
configuration for the service. Environment variables can override
defaults defined here by creating a ``.env`` file at the project
root or by exporting variables before starting the application.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration loaded from environment variables.

    ``DATABASE_URL``: SQLAlchemy database URL for storing run metadata.
    ``REDIS_URL``: URL for the Redis broker/backend used by Celery.
    ``ARTIFACT_ROOT``: Directory where run artifacts are persisted.
    ``BASE_URL_ALLOWLIST``: Optional comma-separated allowlist of hosts
    that scenarios are permitted to access. Provides a rudimentary
    security control to prevent SSRF attacks when processing untrusted
    URLs.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@db:5432/e2e"
    REDIS_URL: str = "redis://redis:6379/0"

    ARTIFACT_ROOT: str = "./artifacts"
    BASE_URL_ALLOWLIST: str = ""  # optional allowlist of base URLs (comma separated)

    # Auth
    JWT_SECRET_KEY: str = "CHANGE_ME"  # override in env for production
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # Scenario storage root (separate from artifacts; default under ARTIFACT_ROOT for docker volume)
    SCENARIO_ROOT: str = "./scenario_store"

    # Playwright storageState store (for login/session injection; e.g., Google test account)
    # Stored per-user on filesystem to keep MVP simple.
    AUTH_STATE_ROOT: str = "./auth_state_store"

    # Dev CORS (comma-separated)
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Public base URL for webhook payload links (CI/CD convenience)
    PUBLIC_BASE_URL: str = "http://localhost:8000"


settings = Settings()