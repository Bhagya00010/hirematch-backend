import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings


def _password_bytes(password: str) -> bytes:
    return hashlib.sha256(password.encode("utf-8")).digest()


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(_password_bytes(plain_password), password_hash.encode("utf-8"))


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt()).decode("utf-8")


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    expires_at = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict[str, Any] = {
        "sub": subject,
        "type": "access",
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str, expected_type: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None

    if payload.get("type") != expected_type:
        return None

    return payload


def create_secure_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
