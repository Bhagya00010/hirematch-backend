from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth,
    settings,
    jobs,
    dashboard,
    resumes,
    google_auth
)
from app.api.v1.endpoints import ats

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(
    settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(
    dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(resumes.router, prefix="/jobs", tags=["resumes"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(
    google_auth.router,
    prefix="/auth",
    tags=["auth"]
)
api_router.include_router(
    ats.router,
    prefix="/ats",
    tags=["ats"],
)