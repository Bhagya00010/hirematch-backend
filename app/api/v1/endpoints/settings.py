from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from uuid import UUID
from app.models.user import User

from app.schemas.settings import (
    SettingsResponse,
    SettingsUpdate,
    FileTypesResponse,
    FileTypesUpdate,
    
)

from app.services import settings_service

router = APIRouter()


@router.get(
    "",
    response_model=SettingsResponse,
)
def get_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = settings_service.get_or_create_settings(
        db,
        current_user.id,
    )

    return settings


@router.patch(
    "",
    response_model=SettingsResponse,
)
def update_settings(
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = settings_service.get_or_create_settings(
        db,
        current_user.id,
    )

    return settings_service.update_settings(
        db,
        settings,
        payload,
    )


@router.get(
    "/file-types",
    response_model=FileTypesResponse,
)
def get_file_types(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_types = settings_service.get_file_types(
        db,
        current_user.id,
    )

    return FileTypesResponse(
        allowed_file_types=file_types
    )


@router.patch(
    "/file-types",
    response_model=FileTypesResponse,
)
def update_file_types(
    payload: FileTypesUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = settings_service.update_file_types(
        db,
        current_user.id,
        payload.allowed_file_types,
    )

    return FileTypesResponse(
        allowed_file_types=settings.allowed_file_types
    )

@router.get(
    "/{user_id}",
    response_model=SettingsResponse,
)
def get_settings_by_user_id(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access another user's settings",
        )

    settings = settings_service.get_or_create_settings(
        db,
        user_id,
    )

    return settings

@router.patch(
    "/{user_id}",
    response_model=SettingsResponse,
)
def update_settings_by_user_id(
    user_id: UUID,
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot update another user's settings",
        )

    settings = settings_service.get_or_create_settings(
        db,
        user_id,
    )

    return settings_service.update_settings(
        db,
        settings,
        payload,
    ) 