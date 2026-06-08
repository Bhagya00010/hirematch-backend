from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.dashboard import DashboardResponse
from app.services.dashboard_service import get_dashboard_data

router = APIRouter()


@router.get("", response_model=DashboardResponse)
def dashboard(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_dashboard_data(
        db=db,
        skip=skip,
        limit=limit,
    )