import logging
from uuid import UUID

from celery.exceptions import MaxRetriesExceededError

from app.celery.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.resume import ResumeFile, ResumeProcessingStatus

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.tasks.resume_tasks.process_single_resume_task",
    max_retries=3,
    default_retry_delay=10,
    acks_late=True,
)
def process_single_resume_task(self, resume_file_id: str) -> dict:
    """
    Celery task: process one resume file end-to-end.
    - Extract text
    - Validate
    - Parse candidate details via LLM
    - Generate and store embedding

    Args:
        resume_file_id: UUID string of the ResumeFile record.

    Returns:
        dict with status and resume_file_id.
    """
    from app.services.resume_service import process_single_resume

    db = SessionLocal()
    try:
        resume_file = (
            db.query(ResumeFile)
            .filter(ResumeFile.id == UUID(resume_file_id))
            .first()
        )

        if not resume_file:
            logger.warning("ResumeFile not found: %s", resume_file_id)
            return {"status": "not_found", "resume_file_id": resume_file_id}

        # Skip if already completed
        if resume_file.processing_status == ResumeProcessingStatus.COMPLETED:
            logger.info("Resume already completed, skipping: %s",
                        resume_file_id)
            return {"status": "already_completed", "resume_file_id": resume_file_id}

        logger.info("Starting resume processing for: %s", resume_file_id)
        process_single_resume(db, resume_file)
        logger.info("Resume processing completed for: %s", resume_file_id)

        return {"status": "completed", "resume_file_id": resume_file_id}

    except Exception as exc:
        logger.exception(
            "Resume processing task failed for %s: %s", resume_file_id, exc)
        will_retry = (
            self.request.retries < self.max_retries
            and not isinstance(exc, (FileNotFoundError, ValueError))
        )
        try:
            resume_file = (
                db.query(ResumeFile)
                .filter(ResumeFile.id == UUID(resume_file_id))
                .first()
            )
            if resume_file:
                if will_retry:
                    resume_file.processing_status = ResumeProcessingStatus.PENDING
                    resume_file.rejection_reason = f"Retrying after task error: {str(exc)[:360]}"
                else:
                    resume_file.processing_status = ResumeProcessingStatus.FAILED
                    resume_file.rejection_reason = f"Task error: {str(exc)[:400]}"
                db.commit()
        except Exception:
            db.rollback()

        if not will_retry:
            logger.error("Max retries exceeded for resume: %s", resume_file_id)
            return {"status": "failed", "resume_file_id": resume_file_id, "error": str(exc)}

        try:
            raise self.retry(exc=exc, countdown=10 *
                             (self.request.retries + 1))
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded for resume: %s", resume_file_id)
            return {"status": "failed", "resume_file_id": resume_file_id, "error": str(exc)}
    finally:
        db.close()


@celery_app.task(
    bind=True,
    name="app.tasks.resume_tasks.process_resumes_for_job_task",
    max_retries=2,
    default_retry_delay=5,
    acks_late=True,
)
def process_resumes_for_job_task(self, job_id: str) -> dict:
    """
    Celery task: dispatch individual resume processing tasks for all
    PENDING or FAILED resumes belonging to a job.

    This is a lightweight fan-out task — it queries the DB and enqueues
    one process_single_resume_task per resume. The heavy LLM work happens
    in those child tasks.

    Args:
        job_id: UUID string of the Job record.

    Returns:
        dict with total dispatched count.
    """
    from pathlib import Path

    db = SessionLocal()
    try:
        resume_files = (
            db.query(ResumeFile)
            .filter(
                ResumeFile.job_posting_id == UUID(job_id),
                ResumeFile.processing_status.in_(
                    [ResumeProcessingStatus.PENDING, ResumeProcessingStatus.FAILED]
                ),
            )
            .order_by(ResumeFile.created_at.asc())
            .all()
        )

        dispatched = 0
        for resume_file in resume_files:
            # Skip FAILED records whose file is already gone from disk
            if (
                resume_file.processing_status == ResumeProcessingStatus.FAILED
                and not Path(resume_file.storage_path).exists()
            ):
                logger.warning(
                    "Skipping missing file for resume: %s", resume_file.id
                )
                continue

            process_single_resume_task.apply_async(
                args=[str(resume_file.id)],
                queue="resume_processing",
            )
            dispatched += 1

        logger.info("Dispatched %d resume tasks for job: %s",
                    dispatched, job_id)
        return {"status": "dispatched", "job_id": job_id, "dispatched": dispatched}

    except Exception as exc:
        logger.exception(
            "Failed to dispatch resume tasks for job %s: %s", job_id, exc)
        try:
            raise self.retry(exc=exc, countdown=5)
        except MaxRetriesExceededError:
            return {"status": "failed", "job_id": job_id, "error": str(exc)}
    finally:
        db.close()
