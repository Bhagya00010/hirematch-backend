from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    id: UUID
    user_id: UUID

    default_weight_experience: float
    default_weight_sector: float
    default_weight_tech_stack: float
    default_weight_education: float
    default_weight_other_skills: float

    max_upload_files: int
    allowed_file_types: list[str]

    updated_at: datetime

    class Config:
        from_attributes = True


class SettingsUpdate(BaseModel):
    default_weight_experience: float | None = Field(default=None, ge=0, le=100)
    default_weight_sector: float | None = Field(default=None, ge=0, le=100)
    default_weight_tech_stack: float | None = Field(default=None, ge=0, le=100)
    default_weight_education: float | None = Field(default=None, ge=0, le=100)
    default_weight_other_skills: float | None = Field(default=None, ge=0, le=100)

    max_upload_files: int | None = Field(default=None, ge=1)


class FileTypesResponse(BaseModel):
    allowed_file_types: list[str]


class FileTypesUpdate(BaseModel):
    allowed_file_types: list[str]




