from fastapi import APIRouter

from app.api.v1.endpoints import auth, settings, jobs

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])