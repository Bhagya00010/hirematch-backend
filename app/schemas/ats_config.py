from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ATSConfigBase(BaseModel):

    # ATS Weights
    weight_must_have: Decimal = Field(default=0.600)
    weight_semantic: Decimal = Field(default=0.150)
    weight_project_impact: Decimal = Field(default=0.100)
    weight_domain: Decimal = Field(default=0.100)
    weight_education: Decimal = Field(default=0.050)

    # Experience Weights
    weight_exp_must_have: Decimal = Field(default=0.600)
    weight_exp_semantic: Decimal = Field(default=0.100)
    weight_exp_project_impact: Decimal = Field(default=0.100)
    weight_exp_experience: Decimal = Field(default=0.100)
    weight_exp_domain: Decimal = Field(default=0.050)
    weight_exp_education: Decimal = Field(default=0.050)

    # Final Blend
    llm_weight: Decimal = Field(default=0.200)

    # Mandatory Gate
    mandatory_gate_threshold: Decimal = Field(default=0.400)
    gate_penalty_multiplier: Decimal = Field(default=0.200)
    soft_penalty_threshold: Decimal = Field(default=30.000)
    soft_penalty_multiplier: Decimal = Field(default=0.700)

    # Confidence
    confidence_min: Decimal = Field(default=0.750)
    confidence_exact: Decimal = Field(default=1.000)
    confidence_boundary: Decimal = Field(default=0.950)
    confidence_fuzzy: Decimal = Field(default=0.850)
    confidence_ontology: Decimal = Field(default=0.780)
    confidence_arch_family: Decimal = Field(default=0.720)

    # Retrieval
    retrieval_top_n: int = 100
    vector_weight: Decimal = Field(default=0.700)
    bm25_weight: Decimal = Field(default=0.300)
    vector_limit: int = 200
    bm25_limit: int = 200
    llm_rerank_top_n: int = 20

    # Tier
    tier_weight_mandatory: Decimal = Field(default=1.000)
    tier_weight_preferred: Decimal = Field(default=0.600)
    tier_weight_bonus: Decimal = Field(default=0.300)

    # Project
    project_weight_complexity: Decimal = Field(default=0.300)
    project_weight_scale: Decimal = Field(default=0.250)
    project_weight_ownership: Decimal = Field(default=0.250)
    project_weight_impact: Decimal = Field(default=0.200)

    # Architecture
    arch_family_min_skills: int = 2

    @model_validator(mode="after")
    def validate_totals(self):

        ats_total = (
            self.weight_must_have +
            self.weight_semantic +
            self.weight_project_impact +
            self.weight_domain +
            self.weight_education
        )

        if round(float(ats_total), 3) != 1.000:
            raise ValueError(
                "ATS Weights must total 1.000"
            )

        exp_total = (
            self.weight_exp_must_have +
            self.weight_exp_semantic +
            self.weight_exp_project_impact +
            self.weight_exp_experience +
            self.weight_exp_domain +
            self.weight_exp_education
        )

        if round(float(exp_total), 3) != 1.000:
            raise ValueError(
                "Experience ATS Weights must total 1.000"
            )

        retrieval_total = (
            self.vector_weight +
            self.bm25_weight
        )

        if round(float(retrieval_total), 3) != 1.000:
            raise ValueError(
                "vector_weight + bm25_weight must equal 1.000"
            )

        project_total = (
            self.project_weight_complexity +
            self.project_weight_scale +
            self.project_weight_ownership +
            self.project_weight_impact
        )

        if round(float(project_total), 3) != 1.000:
            raise ValueError(
                "Project Weights must total 1.000"
            )

        return self


class ATSConfigUpdate(ATSConfigBase):
    pass


class ATSConfigResponse(ATSConfigBase):

    id: UUID
    company_id: UUID
    config_name: str

    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True
    }