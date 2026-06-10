from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from app.api.v1.api import api_router
from app.core.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
)

app.include_router(
    api_router,
    prefix=settings.API_V1_STR,
)

@app.get("/")
def health():
    return {
        "status": "running",
        "service": settings.APP_NAME,
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
