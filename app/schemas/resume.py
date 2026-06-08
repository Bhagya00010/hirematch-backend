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


class ProcessingLogItem(BaseModel):
    resume_file: ResumeFileResponse
    candidate: CandidateResponse | None = None


class ResumeProcessResponse(BaseModel):
    success: bool = True
    total: int
    completed: int
    failed: int
    pending: int
    logs: list[ProcessingLogItem]


class MatchResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_posting_id: UUID
    candidate_id: UUID
    overall_score: float
    score_experience: float | None = None
    score_sector: float | None = None
    score_tech_stack: float | None = None
    score_education: float | None = None
    score_other_skills: float | None = None
    matched_keywords: list[str] | None = None
    unmatched_keywords: list[str] | None = None
    bm25_score: float | None = None
    semantic_score: float | None = None
    rank_position: int | None = None
    ai_summary: str | None = None
    created_at: datetime
    candidate: CandidateResponse | None = None


class ResumeDeleteResponse(BaseModel):
    success: bool = True
    message: str = Field(default="Resume deleted successfully")
