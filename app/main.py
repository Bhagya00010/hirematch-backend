from fastapi import FastAPI

from app.api.v1.api import api_router
from app.core.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0"
)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
def health():
    return {
        "status": "running",
        "service": settings.APP_NAME
    }


@app.get(f"{settings.API_V1_STR}/health")
def api_health():
    return {
        "success": True,
        "data": {
            "status": "running",
            "service": settings.APP_NAME,
        },
        "message": "System health check passed",
    }
