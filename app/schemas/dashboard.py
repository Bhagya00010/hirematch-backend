from datetime import datetime
from pydantic import BaseModel
from typing import List


class DashboardStats(BaseModel):
    total_jobs: int
    active_jobs: int
    closed_jobs: int
    draft_jobs: int
    parsed_jobs: int
    unparsed_jobs: int


class RoleVolume(BaseModel):
    job_title: str
    count: int


class ResumeParsingStat(BaseModel):
    job_title: str
    parsed_count: int
    unparsed_count: int


class RecentJob(BaseModel):
    job_id: str
    job_title: str
    department: str
    status: str
    created_at: datetime


class DashboardResponse(BaseModel):
    stats: DashboardStats
    top_roles: List[RoleVolume]
    resume_parsing_stats: List[ResumeParsingStat]
    recent_jobs: List[RecentJob]