from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Optional

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.job import JobStatus
from app.schemas.job import (
    JobCreate, JobUpdate, JobResponse,
    JobEmbeddingResponse, JobAISummaryResponse,
    JobQuestionsResponse, AnswerSubmission, JobWithQuestionsResponse
)
from app.services import job_service

router = APIRouter()


@router.post("", response_model=JobWithQuestionsResponse, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new job and trigger the full AI metadata extraction and
    embedding generation workflow using LangGraph.
    
    If insufficient data is detected, returns questions for clarification.
    Otherwise, returns the created job with AI-generated metadata.
    """
    result = job_service.run_job_creation_workflow(db, payload, current_user.id)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job creation workflow failed: {', '.join(result.get('errors', []))}"
        )
    
    # If clarification is needed, return questions
    if result.get("needs_clarification"):
        return JobWithQuestionsResponse(
            job=None,
            questions=JobQuestionsResponse(
                job_id=result["job_id"],
                needs_clarification=True,
                questions=result["questions"],
                message="Some information is missing or unclear. Please answer the following questions to complete the job posting."
            ),
            requires_answers=True
        )
    
    # Otherwise return the job
    return JobWithQuestionsResponse(
        job=result["job"],
        questions=None,
        requires_answers=False
    )


@router.get("", response_model=List[JobResponse])
def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1),
    status: Optional[JobStatus] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List jobs with optional status filter and keyword search."""
    return job_service.get_jobs(db, skip=skip, limit=limit, status=status, search=search)


@router.get("/{id}", response_model=JobResponse)
def get_job(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve details of a single job by its ID."""
    job = job_service.get_job(db, id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    return job


@router.put("/{id}", response_model=JobResponse)
def update_job(
    id: UUID,
    payload: JobUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update job fields."""
    job = job_service.get_job(db, id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    return job_service.update_job(db, job, payload)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
def delete_job(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a job and its associated vector embeddings."""
    success = job_service.delete_job(db, id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    return {"success": True, "message": "Job deleted successfully"}


@router.post("/{id}/generate-ai-summary", response_model=JobAISummaryResponse)
def generate_ai_summary(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger on-demand AI summary and metadata extraction for a job."""
    result = job_service.generate_job_ai_summary(db, id)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"AI summary generation failed: {', '.join(result.get('errors', []))}"
        )
    return result["job"]


@router.post("/{id}/generate-embedding", response_model=JobEmbeddingResponse)
def generate_embedding(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger on-demand vector embedding generation and pgvector storage for a job."""
    result = job_service.generate_job_embedding(db, id)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Embedding generation failed: {', '.join(result.get('errors', []))}"
        )
    return result["embedding"]


@router.post("/{id}/submit-answers", response_model=JobWithQuestionsResponse)
def submit_answers(
    id: UUID,
    answers: AnswerSubmission,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Submit answers to clarifying questions and re-verify the job data.
    Updates the job with the provided answers and re-runs the AI workflow.
    """
    result = job_service.submit_job_answers(db, id, answers.answers, current_user.id)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Answer submission failed: {', '.join(result.get('errors', []))}"
        )
    
    # If clarification is still needed, return questions
    if result.get("needs_clarification"):
        return JobWithQuestionsResponse(
            job=None,
            questions=JobQuestionsResponse(
                job_id=result["job_id"],
                needs_clarification=True,
                questions=result["questions"],
                message="More information needed. Please answer the following questions."
            ),
            requires_answers=True
        )
    
    # Otherwise return the job
    return JobWithQuestionsResponse(
        job=result["job"],
        questions=None,
        requires_answers=False
    )
