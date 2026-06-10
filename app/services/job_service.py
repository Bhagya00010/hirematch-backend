import logging
from typing import List, Optional, Dict, Any
from uuid import UUID
import enum

from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.job import Job, JobEmbedding, JobStatus
from app.schemas.job import JobCreate, JobUpdate
from app.services.workflow import (
    job_workflow, JobWorkflowState, validate_answer_relevance
)

logger = logging.getLogger(__name__)





def get_job(db: Session, job_id: UUID) -> Optional[Job]:
    """Retrieve a job by its UUID."""
    return db.query(Job).filter(Job.job_id == job_id).first()


def get_jobs(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    status: Optional[JobStatus] = None,
    search: Optional[str] = None
) -> List[Job]:
    """
    List jobs with optional filtering by status and a basic keyword search
    covering job title, job code, and department.
    """
    query = db.query(Job)
    
    if status:
        query = query.filter(Job.status == status)
        
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            or_(
                Job.job_title.ilike(search_filter),
                Job.job_code.ilike(search_filter),
                Job.department.ilike(search_filter)
            )
        )
        
    return query.order_by(Job.created_at.desc()).offset(skip).limit(limit).all()


def delete_job(db: Session, job_id: UUID) -> bool:
    """Delete a job. Cascade delete handles related job_embeddings."""
    job = get_job(db, job_id)
    if not job:
        return False
    db.delete(job)
    db.commit()
    return True


def update_job(db: Session, job: Job, job_in: JobUpdate) -> Job:
    """
    Update a job's fields. Sets ai_embedding_status to False since
    business data has changed.
    """
    update_data = job_in.model_dump(exclude_unset=True)
    
    for field in update_data:
        if hasattr(job, field):
            setattr(job, field, update_data[field])
            
    job.ai_embedding_status = False
    
    db.commit()
    db.refresh(job)
    return job

def run_job_creation_workflow(db: Session, job_in: JobCreate, creator_id: UUID) -> Dict[str, Any]:
    """
    Execute the simplified LangGraph pipeline to validate input, store the job,
    generate AI summary, and create/store embeddings in the database.
    
    Returns either:
    - {"success": True, "job": job} if workflow completes successfully
    - {"success": True, "needs_clarification": True, "questions": [...]} if questions are needed
    - {"success": False, "errors": [...]} if workflow fails
    """
    initial_state: JobWorkflowState = {
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
        "questions": None
    }
    
    try:
        final_state = job_workflow.invoke(initial_state)
        
        logger.info(f"FINAL STATE: {final_state}")
        
        if final_state.get("errors"):
            logger.error(f"LangGraph job workflow failed: {final_state['errors']}")
            return {"success": False, "errors": final_state["errors"]}
        
        if final_state.get("needs_clarification"):
            return {
                "success": True,
                "needs_clarification": True,
                "questions": final_state.get("questions", []),
                "job_id": final_state.get("job_id")
            }
            
        job_id = final_state.get("job_id")
        job = get_job(db, job_id)
        return {"success": True, "job": job}
        
    except Exception as e:
        logger.exception("Unexpected error in LangGraph job creation workflow")
        return {"success": False, "errors": [str(e)]}


def generate_job_ai_summary(db: Session, job_id: UUID) -> Dict[str, Any]:
    """
    On-demand triggering of AI summarization using simplified workflow.
    """
    job = get_job(db, job_id)
    if not job:
        return {"success": False, "errors": ["Job not found"]}

    input_data = {
        "job_title": job.job_title,
        "job_description": job.job_description,
    }

    state: JobWorkflowState = {
        "job_id": job_id,
        "company_id": job.company_id,
        "created_by": job.created_by,
        "input_data": input_data,
        "db": db,
        "errors": [],
        "validation_result": None,
        "ai_summary_data": None,
        "vectordb_id": None,
        "needs_clarification": None,
        "questions": None
    }

    try:
        # Run the simplified workflow
        final_state = job_workflow.invoke(state)
        
        if final_state.get("errors"):
            return {"success": False, "errors": final_state["errors"]}

        db.refresh(job)
        return {"success": True, "job": job}

    except Exception as e:
        logger.exception("Failed generating on-demand AI summary")
        return {"success": False, "errors": [str(e)]}


def generate_job_embedding(db: Session, job_id: UUID) -> Dict[str, Any]:
    """
    On-demand generation of job pgvector embeddings using simplified workflow.
    """
    job = get_job(db, job_id)
    if not job:
        return {"success": False, "errors": ["Job not found"]}

    input_data = {
        "job_title": job.job_title,
        "job_description": job.job_description,
    }

    state: JobWorkflowState = {
        "job_id": job_id,
        "company_id": job.company_id,
        "created_by": job.created_by,
        "input_data": input_data,
        "db": db,
        "errors": [],
        "validation_result": None,
        "ai_summary_data": None,
        "vectordb_id": None,
        "needs_clarification": None,
        "questions": None
    }

    try:
        # Run the simplified workflow
        final_state = job_workflow.invoke(state)
        
        if final_state.get("errors"):
            return {"success": False, "errors": final_state["errors"]}

        db.refresh(job)
        embedding_record = db.query(JobEmbedding).filter(JobEmbedding.job_id == job_id).first()
        return {"success": True, "embedding": embedding_record}

    except Exception as e:
        logger.exception("Failed generating on-demand job embedding")
        return {"success": False, "errors": [str(e)]}


def submit_job_answers(db: Session, job_id: UUID, answers: Dict[str, Dict[str, str]], user_id: UUID) -> Dict[str, Any]:
    """
    Submit answers to clarifying questions and update the existing job.
    Uses simplified workflow for re-processing after answers.
    
    Args:
        answers: Dictionary mapping question IDs to {answer: str, field_name: str}
    """
    job = get_job(db, job_id)
    if not job:
        return {"success": False, "errors": ["Job not found"]}

    for question_id, answer_data in answers.items():
        field_name = answer_data.get("field_name")
        answer = answer_data.get("answer")
        
        if not field_name or not answer:
            continue
        
        # Validate answer relevance for critical fields
        if field_name in ["responsibilities", "required_skills"]:
            is_valid, error_msg = validate_answer_relevance(field_name, answer)
            if not is_valid:
                logger.warning(f"Invalid answer for {field_name}: {error_msg}")
                # Return the question again instead of error
                return {
                    "success": True,
                    "needs_clarification": True,
                    "questions": [{
                        "id": f"q_{field_name}",
                        "question": f"Your previous answer for {field_name} was not valid: {error_msg}. Please provide proper {field_name}.",
                        "field_name": field_name
                    }],
                    "job_id": job_id
                }
        
        # Update job description if that's the field being updated
        if field_name == "job_description":
            job.job_description = answer
        elif hasattr(job, field_name):
            if field_name in ["experience_min", "experience_max", "salary_min", "salary_max", "vacancies", "notice_period_max"]:
                try:
                    setattr(job, field_name, int(answer) if "experience" in field_name or "vacancies" in field_name or "notice" in field_name else float(answer))
                except ValueError:
                    logger.warning(f"Invalid numeric value for {field_name}: {answer}")
            elif field_name in ["required_skills", "certifications"]:
                setattr(job, field_name, [s.strip() for s in answer.split(",")])
            elif field_name in ["relocation_support", "visa_sponsorship"]:
                setattr(job, field_name, answer.lower() in ["true", "yes", "1"])
            else:
                setattr(job, field_name, answer)
    
    db.commit()
    db.refresh(job)
    
    # Re-run simplified workflow to regenerate AI summary and embedding
    input_data = {
        "job_title": job.job_title,
        "job_description": job.job_description,
    }
    
    state: JobWorkflowState = {
        "job_id": job_id,
        "company_id": job.company_id,
        "created_by": job.created_by,
        "input_data": input_data,
        "db": db,
        "errors": [],
        "validation_result": None,
        "ai_summary_data": None,
        "vectordb_id": None,
        "needs_clarification": None,
        "questions": None
    }
    
    try:
        # Run the simplified workflow
        final_state = job_workflow.invoke(state)
        
        if final_state.get("errors"):
            logger.warning(f"Re-processing workflow had errors: {final_state['errors']}")
            # Don't fail the entire operation, just log it
        
        db.refresh(job)
        logger.info("Job updated and re-processed successfully")
        
    except Exception as e:
        logger.exception("Failed to re-process job after answer submission")
        # Don't fail the entire operation if workflow fails, just log it
    
    return {"success": True, "job": job}
