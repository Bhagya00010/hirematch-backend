import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.db.base import Base


class ResumeValidationStatus(str, enum.Enum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"


class ResumeProcessingStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ResumeFile(Base):
    __tablename__ = "resume_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_posting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    file_hash_md5: Mapped[str | None] = mapped_column(String(32), index=True)
    validation_status: Mapped[ResumeValidationStatus] = mapped_column(
        Enum(
            ResumeValidationStatus,
            name="resume_validation_status",
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        nullable=False,
        default=ResumeValidationStatus.PENDING,
        index=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500))
    processing_status: Mapped[ResumeProcessingStatus] = mapped_column(
        Enum(
            ResumeProcessingStatus,
            name="resume_processing_status",
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        nullable=False,
        default=ResumeProcessingStatus.PENDING,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job = relationship("Job")
    candidate = relationship("Candidate", back_populates="resume_file", cascade="all, delete-orphan", uselist=False)


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resume_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resume_files.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    full_name: Mapped[str | None] = mapped_column(String(200), index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(30))
    total_experience_years: Mapped[float | None] = mapped_column(Numeric(4, 1))
    education_degree: Mapped[str | None] = mapped_column(String(150))
    education_field: Mapped[str | None] = mapped_column(String(150))
    skills: Mapped[list[str] | None] = mapped_column(ARRAY(Text), default=list)
    tech_stack: Mapped[list[str] | None] = mapped_column(ARRAY(Text), default=list)
    sector_experience: Mapped[list[str] | None] = mapped_column(ARRAY(Text), default=list)
    raw_text: Mapped[str | None] = mapped_column(Text)
    embedding_id: Mapped[str | None] = mapped_column(String(200))
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    resume_file = relationship("ResumeFile", back_populates="candidate")
    embedding_relation = relationship(
        "CandidateEmbedding",
        back_populates="candidate",
        cascade="all, delete-orphan",
        uselist=False,
    )
    match_results = relationship("MatchResult", back_populates="candidate", cascade="all, delete-orphan")


class CandidateEmbedding(Base):
    __tablename__ = "candidate_embeddings"

    embedding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    embedding = mapped_column(Vector, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    candidate = relationship("Candidate", back_populates="embedding_relation")


class MatchResult(Base):
    __tablename__ = "match_results"
    __table_args__ = (
        UniqueConstraint("job_posting_id", "candidate_id", name="uq_match_results_job_candidate"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_posting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    overall_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, index=True)
    score_experience: Mapped[float | None] = mapped_column(Numeric(5, 2))
    score_sector: Mapped[float | None] = mapped_column(Numeric(5, 2))
    score_tech_stack: Mapped[float | None] = mapped_column(Numeric(5, 2))
    score_skill: Mapped[float | None] = mapped_column(Numeric(5, 2))
    score_education: Mapped[float | None] = mapped_column(Numeric(5, 2))
    score_other_skills: Mapped[float | None] = mapped_column(Numeric(5, 2))
    matched_keywords: Mapped[list[str] | None] = mapped_column(ARRAY(Text), default=list)
    unmatched_keywords: Mapped[list[str] | None] = mapped_column(ARRAY(Text), default=list)
    matched_skills: Mapped[list[str] | None] = mapped_column(ARRAY(Text), default=list)
    missing_skills: Mapped[list[str] | None] = mapped_column(ARRAY(Text), default=list)
    matched_tech_stack: Mapped[list[str] | None] = mapped_column(ARRAY(Text), default=list)
    missing_tech_stack: Mapped[list[str] | None] = mapped_column(ARRAY(Text), default=list)
    bm25_score: Mapped[float | None] = mapped_column(Numeric(8, 4))
    semantic_score: Mapped[float | None] = mapped_column(Numeric(8, 4))
    rank_position: Mapped[int | None] = mapped_column(Integer, index=True)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    candidate = relationship("Candidate", back_populates="match_results")
    job = relationship("Job")
