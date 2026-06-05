import uuid
from datetime import datetime

from sqlalchemy import Integer, Numeric, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    default_weight_experience: Mapped[float] = mapped_column(
        Numeric(5, 2),
        default=30.00,
    )

    default_weight_sector: Mapped[float] = mapped_column(
        Numeric(5, 2),
        default=25.00,
    )

    default_weight_tech_stack: Mapped[float] = mapped_column(
        Numeric(5, 2),
        default=25.00,
    )

    default_weight_education: Mapped[float] = mapped_column(
        Numeric(5, 2),
        default=10.00,
    )

    default_weight_other_skills: Mapped[float] = mapped_column(
        Numeric(5, 2),
        default=10.00,
    )

    max_upload_files: Mapped[int] = mapped_column(
        Integer,
        default=500,
    )

    allowed_file_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        default=["doc", "docx"],
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )