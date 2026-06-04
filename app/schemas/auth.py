from datetime import datetime
from email.utils import parseaddr
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.user import UserRole


class UserOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.HR_ADMIN

    @field_validator("email")
    @classmethod
    def validate_email(cls, email: str) -> str:
        parsed_name, parsed_email = parseaddr(email.strip())
        if parsed_name or parsed_email != email.strip() or "@" not in parsed_email:
            raise ValueError("invalid email address")
        local_part, _, domain = parsed_email.partition("@")
        if not local_part or "." not in domain:
            raise ValueError("invalid email address")
        return parsed_email.lower()

    @field_validator("role")
    @classmethod
    def validate_registration_role(cls, role: UserRole) -> UserRole:
        if role not in {UserRole.HR_ADMIN, UserRole.OWNER}:
            raise ValueError("registration role must be hr_admin or owner")
        return role


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, email: str) -> str:
        return RegisterRequest.validate_email(email)


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)

    @field_validator("email")
    @classmethod
    def validate_email(cls, email: str) -> str:
        return RegisterRequest.validate_email(email)


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class UpdateMeRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    is_active: bool | None = None
    old_password: str | None = Field(default=None, min_length=1, max_length=128)
    new_password: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password_pair(cls, new_password: str | None, values) -> str | None:
        return new_password


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AuthData(TokenPair):
    user: UserOut


class AccessTokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PasswordResetData(BaseModel):
    reset_token: str


class APIResponse(BaseModel):
    success: bool = True
    data: object | None = None
    message: str = "Operation completed"
