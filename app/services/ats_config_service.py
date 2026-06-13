from uuid import UUID

from sqlalchemy.orm import Session

from app.models.ats_config import ATSConfig
from app.schemas.ats_config import ATSConfigUpdate


def get_config(
    db: Session,
    company_id: UUID,
) -> ATSConfig | None:

    return (
        db.query(ATSConfig)
        .filter(
            ATSConfig.company_id == company_id
        )
        .first()
    )


def create_default_config(
    db: Session,
    company_id: UUID,
) -> ATSConfig:

    config = ATSConfig(
        company_id=company_id,
        config_name="default",
    )

    db.add(config)
    db.commit()
    db.refresh(config)

    return config


def get_or_create_config(
    db: Session,
    company_id: UUID,
) -> ATSConfig:

    config = get_config(
        db,
        company_id,
    )

    if config:
        return config

    return create_default_config(
        db,
        company_id,
    )


def update_config(
    db: Session,
    config: ATSConfig,
    payload: ATSConfigUpdate,
) -> ATSConfig:

    update_data = payload.model_dump(
        exclude_unset=True
    )

    for field, value in update_data.items():
        setattr(
            config,
            field,
            value,
        )

    db.commit()
    db.refresh(config)

    return config


def reset_config(
    db: Session,
    company_id: UUID,
) -> ATSConfig:

    config = get_or_create_config(
        db,
        company_id,
    )

    db.delete(config)
    db.commit()

    return create_default_config(
        db,
        company_id,
    )