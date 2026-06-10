from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "hirematch",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.resume_tasks",
    ],
)

# autodiscover is more reliable than include= on Windows
celery_app.autodiscover_tasks([
    "app.tasks",
])

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
    task_max_retries=3,
    task_default_retry_delay=5,
    task_default_queue="resume_processing",
    task_routes={
        "app.tasks.resume_tasks.process_single_resume_task": {"queue": "resume_processing"},
        "app.tasks.resume_tasks.process_resumes_for_job_task": {"queue": "resume_processing"},
    },
)
