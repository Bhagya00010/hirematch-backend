from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid import UUID

from fastapi import HTTPException
from app.models.settings import Settings
from app.services.auth_service import get_user_by_id



def get_settings(
    db: Session,
    user_id,
) -> Settings | None:
    stmt = select(Settings).where(
        Settings.user_id == user_id
    )

    return db.scalar(stmt)


def create_default_settings(
    db: Session,
    user_id,
) -> Settings:
    settings = Settings(
        user_id=user_id
    )

    db.add(settings)
    db.commit()
    db.refresh(settings)

    return settings


def get_or_create_settings(
    db: Session,
    user_id,
) -> Settings:
    settings = get_settings(
        db,
        user_id,
    )

    if settings is None:
        if get_user_by_id(db, user_id) is None:
            raise HTTPException(
                status_code=404,
                detail="User not found",
            )
        settings = create_default_settings(
            db,
            user_id,
        )

    return settings


def update_settings(
    db: Session,
    settings: Settings,
    payload,
) -> Settings:
    update_data = payload.model_dump(
        exclude_unset=True
    )

    for field, value in update_data.items():
        setattr(settings, field, value)

    db.commit()
    db.refresh(settings)

    return settings


def get_file_types(
    db: Session,
    user_id,
) -> list[str]:
    settings = get_or_create_settings(
        db,
        user_id,
    )

    return settings.allowed_file_types


def update_file_types(
    db: Session,
    user_id,
    allowed_file_types: list[str],
) -> Settings:
    settings = get_or_create_settings(
        db,
        user_id,
    )

    settings.allowed_file_types = allowed_file_types

    db.commit()
    db.refresh(settings)

    return settings


