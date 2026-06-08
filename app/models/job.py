import enum
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Numeric, Boolean, Text, DateTime, ForeignKey, Enum, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.db.base import Base


class JobStatus(str, enum.Enum):
    DRAFT = "Draft"
    ACTIVE = "Active"
    CLOSED = "Closed"


class Job(Base):
    __tablename__ = "jobs"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_title: Mapped[str] = mapped_column(String(255), nullable=False)
    job_code: Mapped[str] = mapped_column(String(100), nullable=False)
    department: Mapped[str] = mapped_column(String(150), nullable=False)

    experience_min: Mapped[int] = mapped_column(Integer, nullable=True)
    experience_max: Mapped[int] = mapped_column(Integer, nullable=True)
    vacancies: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    job_description: Mapped[str] = mapped_column(Text, nullable=False)
    responsibilities: Mapped[str] = mapped_column(Text, nullable=False)
    required_skills: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    education_requirements: Mapped[str] = mapped_column(Text, nullable=False)
    certifications: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    status: Mapped[JobStatus] = mapped_column(
        Enum(
            JobStatus,
            name="job_status",
            values_callable=lambda statuses: [s.value for s in statuses],
        ),
        nullable=False,
        default=JobStatus.DRAFT,
    )

    industry: Mapped[str | None] = mapped_column(String(150), nullable=True)
    team_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_required_skills: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True, default=list)
    ai_job_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ai_seniority_level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ai_keywords: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True, default=list)
    ai_must_have_keywords: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True, default=list)
    ai_nice_to_have_keywords: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True, default=list)
    ai_tools: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True, default=list)
    ai_technologies: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True, default=list)
    ai_soft_skills: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True, default=list)
    ai_domain_experience: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True, default=list)
    ai_embedding_status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    creator = relationship("User", foreign_keys=[created_by])
    embedding_relation = relationship(
        "JobEmbedding",
        back_populates="job",
        cascade="all, delete-orphan",
        uselist=False,
    )


class JobEmbedding(Base):
    __tablename__ = "job_embeddings"

    embedding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    embedding = mapped_column(Vector, nullable=False) 

    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    job = relationship("Job", back_populates="embedding_relation")
