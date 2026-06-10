from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_secure_token,
    get_password_hash,
    hash_token,
    verify_password,
)
from app.models.token import PasswordResetToken, RefreshToken
from app.models.user import User, UserRole


def get_user_by_email(db: Session, email: str) -> User | None:
    normalized_email = email.strip().lower()

    stmt = select(User).where(User.email == normalized_email)

    user = db.scalar(stmt)

    return user


def get_user_by_id(db: Session, user_id: UUID) -> User | None:
    stmt = select(User).where(User.id == user_id)
    return db.scalar(stmt)


def create_user(
    db: Session,
    *,
    full_name: str,
    email: str,
    password: str,
    role: UserRole,
) -> User:
    user = User(
        email=email.lower(),
        full_name=full_name.strip(),
        password_hash=get_password_hash(password),
        role=role,
        auth_provider="local",
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user

def get_user_by_google_id(
    db: Session,
    google_id: str,
) -> User | None:
    stmt = select(User).where(
        User.google_id == google_id
    )
    return db.scalar(stmt)

def create_google_user(
    db: Session,
    *,
    email: str,
    full_name: str,
    google_id: str,
    avatar_url: str | None = None,
) -> User:

    user = User(
        email=email.lower(),
        full_name=full_name.strip(),
        google_id=google_id,
        avatar_url=avatar_url,
        auth_provider="google",
        role=UserRole.HR_ADMIN,
        is_active=True,
    )

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, *, email: str, password: str) -> User | None:

    user = get_user_by_email(db, email)

    if user is None:
        return None

    if not user.is_active:
        return None

    # Prevent Google accounts from password login
    if user.auth_provider == "google":
        return None

    if (user.password_hash is None
        or not verify_password(
            password,
            user.password_hash,
        )
    ):
        return None
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user


def create_refresh_token(db: Session, user: User) -> str:
    refresh_token = create_secure_token()
    token_row = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(refresh_token),
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(token_row)
    db.commit()
    return refresh_token


def create_token_pair(db: Session, user: User) -> tuple[str, str]:
    return create_access_token(str(user.id)), create_refresh_token(db, user)


def get_active_refresh_token(db: Session, refresh_token: str) -> RefreshToken | None:
    stmt = select(RefreshToken).where(
        RefreshToken.token_hash == hash_token(refresh_token))
    token_row = db.scalar(stmt)
    now = datetime.now(timezone.utc)

    if token_row is None:
        return None
    if token_row.revoked_at is not None or token_row.expires_at <= now:
        return None

    return token_row


def rotate_refresh_token(db: Session, refresh_token: str) -> tuple[str, User] | None:
    token_row = get_active_refresh_token(db, refresh_token)
    if token_row is None:
        return None

    user = get_user_by_id(db, token_row.user_id)
    if user is None or not user.is_active:
        return None

    token_row.revoked_at = datetime.now(timezone.utc)
    new_refresh_token = create_refresh_token(db, user)
    db.commit()
    return new_refresh_token, user


def revoke_refresh_token(db: Session, refresh_token: str) -> bool:
    token_row = get_active_refresh_token(db, refresh_token)
    if token_row is None:
        return False

    token_row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return True


def create_password_reset_token(db: Session, user: User) -> str:
    reset_token = create_secure_token()
    token_row = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_token(reset_token),
        expires_at=datetime.now(timezone.utc)
        + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
    )
    db.add(token_row)
    db.commit()
    return reset_token


def reset_password(db: Session, *, token: str, new_password: str) -> bool:
    stmt = select(PasswordResetToken).where(
        PasswordResetToken.token_hash == hash_token(token))
    token_row = db.scalar(stmt)
    now = datetime.now(timezone.utc)

    if token_row is None or token_row.used_at is not None or token_row.expires_at <= now:
        return False

    user = get_user_by_id(db, token_row.user_id)
    if user is None or not user.is_active:
        return False

    user.password_hash = get_password_hash(new_password)
    token_row.used_at = now
    db.commit()
    return True
