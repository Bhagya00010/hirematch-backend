import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.resume import (
    CandidateResponse,
    MatchResultResponse,
    MatchResultModalResponse,
    ResumeDeleteResponse,
    ResumeFileResponse,
    ResumeProcessResponse,
    ResumeUploadResponse,
)
from app.services import resume_service

router = APIRouter()


@router.post("/{job_id}/resumes", response_model=ResumeUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_resumes(
    job_id: UUID,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Upload resumes — processing starts automatically in background."""
    if not files:
        raise HTTPException(
            status_code=400, detail="Please upload at least one resume file")
    if not resume_service.get_job_or_none(db, job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    resumes = await resume_service.save_resume_files(db, job_id, files)
    return ResumeUploadResponse(total_uploaded=len(resumes), resumes=resumes)


@router.get("/{job_id}/resumes", response_model=list[ResumeFileResponse])
def list_resumes(
    job_id: UUID,
    db: Session = Depends(get_db),
):
    """Retrieve all uploaded resume files for a job."""
    if not resume_service.get_job_or_none(db, job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return resume_service.get_resume_files(db, job_id)


@router.get("/{job_id}/resumes/stream")
async def stream_resume_processing(
    job_id: UUID,
    interval_seconds: float = Query(2.0, ge=0.5, le=10.0),
    db: Session = Depends(get_db),
):
    """Server-Sent Events stream for resume processing status updates."""
    if not resume_service.get_job_or_none(db, job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    async def event_generator():
        while True:
            summary = resume_service.get_processing_summary(db, job_id)
            payload = {
                "total": summary["total"],
                "completed": summary["completed"],
                "failed": summary["failed"],
                "pending": summary["pending"],
                "processing": summary["processing"],
                "logs": [
                    {
                        "resume_file_id": str(item["resume_file"].id),
                        "filename": item["resume_file"].original_filename,
                        "validation_status": item["resume_file"].validation_status.value,
                        "processing_status": item["resume_file"].processing_status.value,
                        "rejection_reason": item["resume_file"].rejection_reason,
                    }
                    for item in summary["logs"]
                ],
            }
            yield f"data: {json.dumps(payload)}\n\n"
            if summary["pending"] == 0 and summary["processing"] == 0:
                break
            await asyncio.sleep(interval_seconds)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/file")
async def get_resume_file(
    path: str = Query(..., description="Storage path of the resume file"),
    db: Session = Depends(get_db),
):
    """Fetch resume file content from storage path."""
    import os
    from app.core.config import settings
    
    # Security check: ensure path is within allowed directory
    if not path or ".." in path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file path"
        )
    
    full_path = os.path.join(settings.RESUME_UPLOAD_DIR, path)
    
    if not os.path.exists(full_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    if not os.path.isfile(full_path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path is not a file"
        )
    
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return {"content": content}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reading file: {str(e)}"
        )


@router.delete("/{job_id}/resumes/{resume_file_id}", response_model=ResumeDeleteResponse)
def delete_resume(
    job_id: UUID,
    resume_file_id: UUID,
    db: Session = Depends(get_db),
):
    """Delete a specific uploaded resume file and extracted candidate data."""
    deleted = resume_service.delete_resume_file(db, job_id, resume_file_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume file not found")
    return ResumeDeleteResponse()


@router.get("/{job_id}/resumes/processing-log", response_model=ResumeProcessResponse)
def processing_log(
    job_id: UUID,
    db: Session = Depends(get_db),
):
    """View processing results for each resume, including failed files and extracted candidates."""
    if not resume_service.get_job_or_none(db, job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return resume_service.get_processing_summary(db, job_id)


@router.get("/{job_id}/candidates", response_model=list[CandidateResponse])
def list_candidates(
    job_id: UUID,
    db: Session = Depends(get_db),
):
    """List extracted candidates for a job."""
    if not resume_service.get_job_or_none(db, job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return resume_service.get_candidates_for_job(db, job_id)


@router.post("/{job_id}/match", response_model=list[MatchResultResponse])
def run_match(
    job_id: UUID,
    db: Session = Depends(get_db),
):
    """Run a first-pass candidate matching score for processed resumes."""
    if not resume_service.get_job_or_none(db, job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return resume_service.run_matching(db, job_id)


@router.get("/{job_id}/match/results")
def match_results(
    job_id: UUID,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List ranked match results for a job with detailed score breakdown."""
    if not resume_service.get_job_or_none(db, job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )

    return resume_service.get_match_results(
        db,
        job_id,
        limit=limit
    )