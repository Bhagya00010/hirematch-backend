# app/models/ats_config.py

import uuid

from datetime import datetime

from sqlalchemy import (
    String,
    Integer,
    Numeric,
    DateTime,
    ForeignKey,
    func,
)

from sqlalchemy.dialects.postgresql import UUID

from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ATSConfig(Base):
    __tablename__ = "ats_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        unique=True,
    )

    config_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="default",
    )

    # =====================================================
    # ATS WEIGHTS
    # =====================================================

    weight_must_have: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.600,
    )

    weight_semantic: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.150,
    )

    weight_project_impact: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.100,
    )

    weight_domain: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.100,
    )

    weight_education: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.050,
    )

    # =====================================================
    # ATS WEIGHTS WITH EXPERIENCE
    # =====================================================

    weight_exp_must_have: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.600,
    )

    weight_exp_semantic: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.100,
    )

    weight_exp_project_impact: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.100,
    )

    weight_exp_experience: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.100,
    )

    weight_exp_domain: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.050,
    )

    weight_exp_education: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.050,
    )

    # =====================================================
    # FINAL BLEND
    # =====================================================

    llm_weight: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.200,
    )

    # =====================================================
    # MANDATORY GATE
    # =====================================================

    mandatory_gate_threshold: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.400,
    )

    gate_penalty_multiplier: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.200,
    )

    soft_penalty_threshold: Mapped[float] = mapped_column(
        Numeric(5, 3),
        nullable=False,
        default=30.000,
    )

    soft_penalty_multiplier: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.700,
    )

    # =====================================================
    # CONFIDENCE THRESHOLDS
    # =====================================================

    confidence_min: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.750,
    )

    confidence_exact: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=1.000,
    )

    confidence_boundary: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.950,
    )

    confidence_fuzzy: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.850,
    )

    confidence_ontology: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.780,
    )

    confidence_arch_family: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.720,
    )

    # =====================================================
    # RETRIEVAL SETTINGS
    # =====================================================

    retrieval_top_n: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
    )

    vector_weight: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.700,
    )

    bm25_weight: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.300,
    )

    vector_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=200,
    )

    bm25_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=200,
    )

    llm_rerank_top_n: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=20,
    )

    # =====================================================
    # SKILL TIER WEIGHTS
    # =====================================================

    tier_weight_mandatory: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=1.000,
    )

    tier_weight_preferred: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.600,
    )

    tier_weight_bonus: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.300,
    )

    # =====================================================
    # PROJECT WEIGHTS
    # =====================================================

    project_weight_complexity: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.300,
    )

    project_weight_scale: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.250,
    )

    project_weight_ownership: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.250,
    )

    project_weight_impact: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.200,
    )

    # =====================================================
    # ARCHITECTURE SETTINGS
    # =====================================================

    arch_family_min_skills: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=2,
    )

    # =====================================================
    # AUDIT
    # =====================================================

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