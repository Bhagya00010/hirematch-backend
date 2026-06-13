from fastapi import APIRouter
from fastapi import Depends

from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db

from app.models.user import User

from app.schemas.ats_config import (
    ATSConfigResponse,
    ATSConfigUpdate,
)

from app.services import ats_config_service

router = APIRouter()


@router.get(
    "",
    response_model=ATSConfigResponse,
)
def get_ats_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    config = ats_config_service.get_or_create_config(
        db=db,
        company_id=current_user.id,
    )

    return config


@router.patch(
    "",
    response_model=ATSConfigResponse,
)
def update_ats_config(
    payload: ATSConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    config = ats_config_service.get_or_create_config(
        db=db,
        company_id=current_user.id,
    )

    return ats_config_service.update_config(
        db=db,
        config=config,
        payload=payload,
    )


@router.post(
    "/reset",
    response_model=ATSConfigResponse,
)
def reset_ats_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    return ats_config_service.reset_config(
        db=db,
        company_id=current_user.id,
    )