from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.resume import ResumeProcessingStatus, ResumeValidationStatus


class ResumeFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_posting_id: UUID
    original_filename: str
    storage_path: str
    file_size_bytes: int | None = None
    file_hash_md5: str | None = None
    validation_status: ResumeValidationStatus
    rejection_reason: str | None = None
    processing_status: ResumeProcessingStatus
    created_at: datetime


class ResumeUploadResponse(BaseModel):
    success: bool = True
    total_uploaded: int
    resumes: list[ResumeFileResponse]


class Project(BaseModel):
    name: str | None = None
    description: str | None = None
    technologies: list[str] | None = None


class CandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    resume_file_id: UUID
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    total_experience_years: float | None = None
    education_degree: str | None = None
    education_field: str | None = None
    skills: list[str] | None = None
    tech_stack: list[str] | None = None
    sector_experience: list[str] | None = None
    raw_text: str | None = None
    embedding_id: str | None = None
    is_duplicate: bool
    created_at: datetime
    projects: list[Project] | None = None


class ProcessingLogItem(BaseModel):
    resume_file: ResumeFileResponse
    candidate: CandidateResponse | None = None


class ResumeProcessResponse(BaseModel):
    success: bool = True
    total: int
    completed: int
    failed: int
    pending: int
    processing: int = 0
    logs: list[ProcessingLogItem]


class ScoreBreakdown(BaseModel):
    semantic_score: float | None = None
    bm25_score: float | None = None
    keyword_score: float | None = None
    skill_score: float | None = None
    tech_stack_score: float | None = None
    experience_score: float | None = None
    education_score: float | None = None
    sector_score: float | None = None
    other_skills_score: float | None = None


class MatchResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_posting_id: UUID
    candidate_id: UUID
    overall_score: float
    rank_position: int | None = None
    created_at: datetime
    
    # Candidate details
    candidate: CandidateResponse | None = None
    
    # AI summary
    ai_summary: str | None = None
    
    # Matched/missing skills
    matched_skills: list[str] | None = None
    missing_skills: list[str] | None = None
    matched_tech_stack: list[str] | None = None
    missing_tech_stack: list[str] | None = None
    matched_keywords: list[str] | None = None
    unmatched_keywords: list[str] | None = None
    
    # Score breakdown
    score_breakdown: ScoreBreakdown | None = None


class ResumeDeleteResponse(BaseModel):
    success: bool = True
    message: str = Field(default="Resume deleted successfully")
