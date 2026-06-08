import logging
from typing import List, Optional, Dict, Any
from uuid import UUID
import enum

from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.job import Job, JobEmbedding, JobStatus
from app.schemas.job import JobCreate, JobUpdate
from app.services.workflow import (
    job_workflow, JobWorkflowState,
    generate_ai_summary_node, extract_skills_node, generate_searchable_keywords_node,
    create_embedding_text_node, generate_embedding_node, store_vector_node,
    update_ai_metadata_node
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
    Execute the full LangGraph pipeline to validate input, store the job,
    generate AI summary, extract skills, generate keywords, and create/store
    embeddings in the database.
    
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
        "ai_summary": None,
        "ai_extracted_metadata": None,
        "ai_keywords": None,
        "embedding_text": None,
        "embedding_vector": None,
        "embedding_dimension": None,
        "embedding_model_name": None,
        "needs_clarification": None,
        "questions": None
    }
    
    try:
        final_state = job_workflow.invoke(initial_state)
        
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
    On-demand triggering of AI summarization, skill extraction,
    and keyword generation. Updates metadata directly.
    """
    job = get_job(db, job_id)
    if not job:
        return {"success": False, "errors": ["Job not found"]}

    input_data = {
        "job_title": job.job_title,
        "department": job.department,
        "job_description": job.job_description,
        "responsibilities": job.responsibilities,
        "education_requirements": job.education_requirements,
        "certifications": job.certifications,
        "required_skills": job.required_skills,
        "experience_min": job.experience_min,
        "experience_max": job.experience_max,
    }

    state: JobWorkflowState = {
        "job_id": job_id,
        "company_id": job.company_id,
        "created_by": job.created_by,
        "input_data": input_data,
        "db": db,
        "errors": [],
        "ai_summary": None,
        "ai_extracted_metadata": None,
        "ai_keywords": None,
        "embedding_text": None,
        "embedding_vector": None,
        "embedding_dimension": None,
        "embedding_model_name": None
    }

    try:
        summary_result = generate_ai_summary_node(state)
        if summary_result.get("errors"):
            return {"success": False, "errors": summary_result["errors"]}
        state["ai_summary"] = summary_result.get("ai_summary")

        skills_result = extract_skills_node(state)
        if skills_result.get("errors"):
            return {"success": False, "errors": skills_result["errors"]}
        state["ai_extracted_metadata"] = skills_result.get("ai_extracted_metadata")

        keywords_result = generate_searchable_keywords_node(state)
        if keywords_result.get("errors"):
            return {"success": False, "errors": keywords_result["errors"]}
        state["ai_keywords"] = keywords_result.get("ai_keywords")

        update_result = update_ai_metadata_node(state)
        if update_result.get("errors"):
            return {"success": False, "errors": update_result["errors"]}

        db.refresh(job)
        db.refresh(job)
        return {"success": True, "job": job}

    except Exception as e:
        logger.exception("Failed generating on-demand AI summary")
        return {"success": False, "errors": [str(e)]}


def generate_job_embedding(db: Session, job_id: UUID) -> Dict[str, Any]:
    """
    On-demand generation of job pgvector embeddings. Combines all fields,
    requests vector from Embedding provider, and saves to pgvector.
    """
    job = get_job(db, job_id)
    if not job:
        return {"success": False, "errors": ["Job not found"]}

    input_data = {
        "job_title": job.job_title,
        "department": job.department,
        "job_description": job.job_description,
        "responsibilities": job.responsibilities,
        "education_requirements": job.education_requirements,
        "certifications": job.certifications,
        "required_skills": job.required_skills,
        "experience_min": job.experience_min,
        "experience_max": job.experience_max,
    }

    extracted = {
        "primary_skills": job.ai_required_skills,
        "tools": job.ai_tools,
        "education": job.education_requirements,  # Fallback
        "seniority_level": job.ai_seniority_level,
        "job_category": job.ai_job_category,
    }

    keywords = {
        "keywords": job.ai_keywords,
        "must_have_keywords": job.ai_must_have_keywords,
        "nice_to_have_keywords": job.ai_nice_to_have_keywords,
    }

    state: JobWorkflowState = {
        "job_id": job_id,
        "company_id": job.company_id,
        "created_by": job.created_by,
        "input_data": input_data,
        "db": db,
        "errors": [],
        "ai_summary": job.ai_summary,
        "ai_extracted_metadata": extracted,
        "ai_keywords": keywords,
        "embedding_text": None,
        "embedding_vector": None,
        "embedding_dimension": None,
        "embedding_model_name": None
    }

    try:
        text_result = create_embedding_text_node(state)
        state["embedding_text"] = text_result.get("embedding_text")

        vector_result = generate_embedding_node(state)
        if vector_result.get("errors"):
            return {"success": False, "errors": vector_result["errors"]}
        state["embedding_vector"] = vector_result.get("embedding_vector")
        state["embedding_dimension"] = vector_result.get("embedding_dimension")
        state["embedding_model_name"] = vector_result.get("embedding_model_name")

        store_result = store_vector_node(state)
        if store_result.get("errors"):
            return {"success": False, "errors": store_result["errors"]}

        job.ai_embedding_status = True
        job.ai_embedding_status = True
        db.commit()
        db.refresh(job)

        embedding_record = db.query(JobEmbedding).filter(JobEmbedding.job_id == job_id).first()
        return {"success": True, "embedding": embedding_record}

    except Exception as e:
        logger.exception("Failed generating on-demand job embedding")
        return {"success": False, "errors": [str(e)]}


def submit_job_answers(db: Session, job_id: UUID, answers: Dict[str, Dict[str, str]], user_id: UUID) -> Dict[str, Any]:
    """
    Submit answers to clarifying questions and update the existing job.
    Does NOT create a new job - only updates the existing one.
    
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
        
        if hasattr(job, field_name):
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
    
    from app.core.job_settings import get_fields_to_ask
    from app.services.workflow import is_insufficient_data, generate_clarifying_questions_node
    
    input_data = {
        "job_title": job.job_title,
        "job_description": job.job_description,
        "department": job.department,
        "responsibilities": job.responsibilities,
        "required_skills": job.required_skills,
        "education_requirements": job.education_requirements,
        "experience_min": job.experience_min,
        "experience_max": job.experience_max,
        "vacancies": job.vacancies,
        "certifications": job.certifications,
        "industry": job.industry,
        "team_name": job.team_name,
        "project_name": job.project_name,
        "internal_notes": job.internal_notes,
    }
    
    fields_to_ask = get_fields_to_ask()
    insufficient_fields = []
    for field_config in fields_to_ask:
        field_name = field_config["field_name"]
        description = field_config["description"]
        value = input_data.get(field_name)
        if is_insufficient_data(value):
            insufficient_fields.append((field_name, description, value))
    
    if insufficient_fields:
        state = {
            "input_data": input_data,
            "job_id": str(job_id),
        }
        question_result = generate_clarifying_questions_node(state)
        if question_result.get("needs_clarification"):
            return {
                "success": True,
                "needs_clarification": True,
                "questions": question_result.get("questions", []),
                "job_id": str(job_id)
            }
    
    
    logger.info("All data complete, triggering full AI workflow for embedding generation")
    
    
    complete_input_data = {
        "job_title": job.job_title,
        "job_code": job.job_code,
        "department": job.department,
        "experience_min": job.experience_min,
        "experience_max": job.experience_max,
        "vacancies": job.vacancies,
        "job_description": job.job_description,
        "responsibilities": job.responsibilities,
        "required_skills": job.required_skills,
        "education_requirements": job.education_requirements,
        "certifications": job.certifications,
        "industry": job.industry,
        "team_name": job.team_name,
        "project_name": job.project_name,
        "internal_notes": job.internal_notes,
        "status": job.status.value if hasattr(job.status, 'value') else str(job.status),
    }
    
    from app.services.workflow import (
        generate_ai_summary_node, extract_skills_node, generate_searchable_keywords_node,
        create_embedding_text_node, generate_embedding_node, store_vector_node,
        update_ai_metadata_node, JobWorkflowState
    )
    
    state: JobWorkflowState = {
        "job_id": job_id,
        "company_id": job.company_id,
        "created_by": job.created_by,
        "input_data": complete_input_data,
        "db": db,
        "errors": [],
        "ai_summary": None,
        "ai_extracted_metadata": None,
        "ai_keywords": None,
        "embedding_text": None,
        "embedding_vector": None,
        "embedding_dimension": None,
        "embedding_model_name": None,
        "needs_clarification": None,
        "questions": None
    }
    
    try:
        # Generate AI summary
        summary_result = generate_ai_summary_node(state)
        if summary_result.get("errors"):
            logger.error(f"AI summary generation failed: {summary_result['errors']}")
        else:
            state["ai_summary"] = summary_result.get("ai_summary")
        
        # Extract skills
        skills_result = extract_skills_node(state)
        if skills_result.get("errors"):
            logger.error(f"Skills extraction failed: {skills_result['errors']}")
        else:
            state["ai_extracted_metadata"] = skills_result.get("ai_extracted_metadata")
        
        # Generate keywords
        keywords_result = generate_searchable_keywords_node(state)
        if keywords_result.get("errors"):
            logger.error(f"Keywords generation failed: {keywords_result['errors']}")
        else:
            state["ai_keywords"] = keywords_result.get("ai_keywords")
        
        # Update AI metadata
        update_result = update_ai_metadata_node(state)
        if update_result.get("errors"):
            logger.error(f"AI metadata update failed: {update_result['errors']}")
        
        # Create embedding text
        text_result = create_embedding_text_node(state)
        if text_result.get("errors"):
            logger.error(f"Embedding text creation failed: {text_result['errors']}")
        else:
            state["embedding_text"] = text_result.get("embedding_text")
        
        # Generate embedding
        vector_result = generate_embedding_node(state)
        if vector_result.get("errors"):
            logger.error(f"Embedding generation failed: {vector_result['errors']}")
        else:
            state["embedding_vector"] = vector_result.get("embedding_vector")
            state["embedding_dimension"] = vector_result.get("embedding_dimension")
            state["embedding_model_name"] = vector_result.get("embedding_model_name")
        
        # Store vector
        store_result = store_vector_node(state)
        if store_result.get("errors"):
            logger.error(f"Vector storage failed: {store_result['errors']}")
        
        db.refresh(job)
        logger.info("Full AI workflow completed successfully for job embedding generation")
        
    except Exception as e:
        logger.exception("Failed to run full AI workflow after answer submission")
        # Don't fail the entire operation if AI workflow fails, just log it
    
    return {"success": True, "job": job}
