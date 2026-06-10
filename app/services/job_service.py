import logging
from typing import List, Optional, Dict, Any
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.job import Job, JobEmbedding, JobStatus
from app.schemas.job import JobCreate, JobUpdate
from app.services.workflow import (
    job_workflow, JobWorkflowState, validate_answer_relevance
)
from app.celery.tasks import create_job_embedding_task

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_state(job: Job, db: Session) -> JobWorkflowState:
    """Build a minimal workflow state from an existing Job row."""
    return {
        "job_id": job.job_id,
        "company_id": job.company_id,
        "created_by": job.created_by,
        "input_data": {
            "job_title": job.job_title,
            "job_description": job.job_description,
        },
        "db": db,
        "errors": [],
        "validation_result": None,
        "ai_summary_data": None,
        "vectordb_id": None,
        "needs_clarification": None,
        "questions": None,
    }


def _invoke_workflow(state: JobWorkflowState) -> Dict[str, Any]:
    """Run the workflow and return a normalised result dict."""
    try:
        final = job_workflow.invoke(state)
        logger.info(f"Workflow final state: {final}")

        if final.get("errors"):
            return {"success": False, "errors": final["errors"]}

        if final.get("needs_clarification"):
            return {
                "success": True,
                "needs_clarification": True,
                "questions": final.get("questions", []),
                "job_id": final.get("job_id"),
            }

        return {"success": True, "_final": final}
    except Exception as e:
        logger.exception("Unexpected workflow error")
        return {"success": False, "errors": [str(e)]}


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def get_job(db: Session, job_id: UUID) -> Optional[Job]:
    return db.query(Job).filter(Job.job_id == job_id).first()


def get_jobs(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    status: Optional[JobStatus] = None,
    search: Optional[str] = None,
) -> List[Job]:
    query = db.query(Job)
    if status:
        query = query.filter(Job.status == status)
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                Job.job_title.ilike(like),
                Job.job_code.ilike(like),
                Job.department.ilike(like),
            )
        )
    return query.order_by(Job.created_at.desc()).offset(skip).limit(limit).all()


def delete_job(db: Session, job_id: UUID) -> bool:
    job = get_job(db, job_id)
    if not job:
        return False
    db.delete(job)
    db.commit()
    return True


def update_job(db: Session, job: Job, job_in: JobUpdate) -> Job:
    for field, value in job_in.model_dump(exclude_unset=True).items():
        if hasattr(job, field):
            setattr(job, field, value)
    job.ai_embedding_status = False
    db.commit()
    db.refresh(job)
    return job


# ---------------------------------------------------------------------------
# Workflow-backed operations
# ---------------------------------------------------------------------------

def run_job_creation_workflow(
    db: Session, job_in: JobCreate, creator_id: UUID
) -> Dict[str, Any]:
    """
    Validate input → store job → generate AI summary → create embedding.

    Returns:
      {"success": True, "job": Job}
      {"success": True, "needs_clarification": True, "questions": [...], "job_id": UUID}
      {"success": False, "errors": [...]}
    """
    state: JobWorkflowState = {
        "job_id": None,
        "company_id": job_in.company_id,
        "created_by": creator_id,
        "input_data": job_in.model_dump(mode="json"),
        "db": db,
        "errors": [],
        "validation_result": None,
        "ai_summary_data": None,
        "vectordb_id": None,
        "needs_clarification": None,
        "questions": None,
    }

    result = _invoke_workflow(state)
    if not result["success"] or result.get("needs_clarification"):
        return result

    job = get_job(db, result["_final"].get("job_id"))
    
    # Trigger embedding creation asynchronously via Celery
    try:
        create_job_embedding_task.delay(str(job.job_id))
        logger.info(f"Embedding task queued for job: {job.job_id}")
    except Exception as e:
        logger.error(f"Failed to queue embedding task: {e}")
        # Don't fail the job creation if Celery task fails
    
    return {"success": True, "job": job}


def generate_job_ai_summary(db: Session, job_id: UUID) -> Dict[str, Any]:
    """On-demand AI summarisation for an existing job."""
    job = get_job(db, job_id)
    if not job:
        return {"success": False, "errors": ["Job not found"]}

    result = _invoke_workflow(_base_state(job, db))
    if not result["success"]:
        return result

    db.refresh(job)
    
    # Trigger embedding creation asynchronously via Celery
    try:
        create_job_embedding_task.delay(str(job.job_id))
        logger.info(f"Embedding task queued for job: {job.job_id}")
    except Exception as e:
        logger.error(f"Failed to queue embedding task: {e}")
    
    return {"success": True, "job": job}


def generate_job_embedding(db: Session, job_id: UUID) -> Dict[str, Any]:
    """On-demand embedding generation for an existing job (triggers Celery task)."""
    job = get_job(db, job_id)
    if not job:
        return {"success": False, "errors": ["Job not found"]}

    # Trigger embedding creation asynchronously via Celery
    try:
        create_job_embedding_task.delay(str(job.job_id))
        logger.info(f"Embedding task queued for job: {job.job_id}")
        return {"success": True, "message": "Embedding task queued"}
    except Exception as e:
        logger.error(f"Failed to queue embedding task: {e}")
        return {"success": False, "errors": [str(e)]}


def submit_job_answers(
    db: Session, job_id: UUID, answers: Dict[str, Dict[str, str]], user_id: UUID
) -> Dict[str, Any]:
    """
    Accept clarification answers, apply them to the job, then re-run
    AI summary + embedding (validation is SKIPPED — already done once).

    answers format: {question_id: {"answer": str, "field_name": str}}
    """
    job = get_job(db, job_id)
    if not job:
        return {"success": False, "errors": ["Job not found"]}

    # --- Validate answers and apply to job ---
    for question_id, answer_data in answers.items():
        field_name = answer_data.get("field_name")
        answer = answer_data.get("answer")
        if not field_name or not answer:
            continue

        # Only validate critical fields
        if field_name in ("responsibilities", "required_skills"):
            is_valid, error_msg = validate_answer_relevance(field_name, answer)
            if not is_valid:
                return {
                    "success": True,
                    "needs_clarification": True,
                    "questions": [{
                        "id": f"q_{field_name}",
                        "question": (
                            f"Your answer for {field_name} was not valid: {error_msg}. "
                            f"Please provide proper {field_name}."
                        ),
                        "field_name": field_name,
                    }],
                    "job_id": job_id,
                }

        # Apply answer to job field
        if field_name == "job_description":
            job.job_description = answer
        elif hasattr(job, field_name):
            numeric_fields = {
                "experience_min", "experience_max", "vacancies", "notice_period_max",
                "salary_min", "salary_max",
            }
            list_fields = {"required_skills", "certifications"}
            bool_fields = {"relocation_support", "visa_sponsorship"}

            if field_name in numeric_fields:
                try:
                    val = int(answer) if field_name not in ("salary_min", "salary_max") else float(answer)
                    setattr(job, field_name, val)
                except ValueError:
                    logger.warning(f"Invalid numeric value for {field_name}: {answer}")
            elif field_name in list_fields:
                setattr(job, field_name, [s.strip() for s in answer.split(",")])
            elif field_name in bool_fields:
                setattr(job, field_name, answer.lower() in ("true", "yes", "1"))
            else:
                setattr(job, field_name, answer)

    db.commit()
    db.refresh(job)

    # --- Re-run workflow (validation disabled via state — validation_result already set) ---
    state = _base_state(job, db)
    # Pre-fill validation_result so the workflow skips re-validation
    state["validation_result"] = {"valid": True, "skipped": True}

    try:
        result = _invoke_workflow(state)
        if result.get("errors"):
            logger.warning(f"Re-processing workflow errors (non-fatal): {result['errors']}")
        db.refresh(job)
    except Exception as e:
        logger.exception("Failed to re-process job after answer submission (non-fatal)")

    # Trigger embedding creation asynchronously via Celery
    try:
        create_job_embedding_task.delay(str(job.job_id))
        logger.info(f"Embedding task queued for job: {job.job_id}")
    except Exception as e:
        logger.error(f"Failed to queue embedding task: {e}")

    return {"success": True, "job": job}