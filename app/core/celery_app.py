"""
Celery application configuration.

This module exposes a configured Celery application instance which is
used to process long running tasks such as executing end-to-end
scenarios. The Celery broker and backend are configured via
environment variables defined in ``app/core/config.py``.
"""

from celery import Celery
from app.core.config import settings

# Create the Celery application. Both the broker and the result backend
# point at the same Redis instance. In a production deployment you might
# use separate Redis databases or even different backends entirely.
celery_app = Celery(
    "e2e_service",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks", "app.tasks_suite", "app.tasks_webhook"],
)

# Global Celery configuration. These values can be tuned based on your
# infrastructure capacity and desired runtime limits.
celery_app.conf.update(
    task_track_started=True,
    task_time_limit=60 * 30,  # 30 minutes upper bound per task
)

__all__ = ["celery_app"]