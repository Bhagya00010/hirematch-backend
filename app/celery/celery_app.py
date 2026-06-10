from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "hirematch",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Task behavior
    # Acknowledge only after task completes (safe re-queue on crash)
    task_acks_late=True,
    task_reject_on_worker_lost=True,   # Re-queue if worker dies mid-task
    # One task per worker at a time (important for LLM/CPU heavy tasks)
    worker_prefetch_multiplier=1,

    # Result backend (using DB so no Redis needed for results)
    result_expires=3600,               # Results expire after 1 hour

    # Retry defaults
    task_max_retries=3,
    task_default_retry_delay=5,        # seconds
)
