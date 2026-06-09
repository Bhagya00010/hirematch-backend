from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.ratelimit import (
    register_rate_limiter,
    login_rate_limiter,
    refresh_rate_limiter,
    forgot_password_rate_limiter,
    reset_password_rate_limiter,
    read_rate_limiter,
    write_rate_limiter,
    heavy_rate_limiter,
)
from app.api.deps import get_current_user
#from app.api.ratelimit import RateLimiter
from app.core.security import get_password_hash, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    APIResponse,
    AuthData,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    UpdateMeRequest,
    UserOut,
)
from app.services import auth_service, email_service

router = APIRouter()


def _extract_refresh_token(
    body_token: str | None,
    authorization: str | None,
) -> str | None:
    if body_token:
        return body_token
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1]
    return None


@router.post("/register", response_model=APIResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db),  _: None = Depends(register_rate_limiter),) -> APIResponse:
    try:
        user = auth_service.create_user(
            db,
            full_name=payload.full_name,
            email=str(payload.email),
            password=payload.password,
            role=payload.role,
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already exists",
        ) from exc

    access_token, refresh_token = auth_service.create_token_pair(db, user)
    data = AuthData(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserOut.model_validate(user),
    )
    return APIResponse(data=data.model_dump(mode="json"), message="Registration successful")


@router.post("/login", response_model=APIResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db),_: None = Depends(login_rate_limiter),) -> APIResponse:
    user = auth_service.authenticate_user(
        db,
        email=str(payload.email),
        password=payload.password,
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    access_token, refresh_token = auth_service.create_token_pair(db, user)
    data = AuthData(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserOut.model_validate(user),
    )
    return APIResponse(data=data.model_dump(mode="json"), message="Login successful")


@router.post("/refresh", response_model=APIResponse)
def refresh_access_token(
    payload: RefreshRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
    _: None = Depends(refresh_rate_limiter),
) -> APIResponse:
    refresh_token = _extract_refresh_token(
        payload.refresh_token, authorization)
    if refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is required",
        )

    rotated = auth_service.rotate_refresh_token(db, refresh_token)
    if rotated is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    new_refresh_token, user = rotated
    data = AuthData(
        access_token=auth_service.create_access_token(str(user.id)),
        refresh_token=new_refresh_token,
        user=UserOut.model_validate(user),
    )
    return APIResponse(data=data.model_dump(mode="json"), message="Token refreshed")


@router.post("/logout", response_model=APIResponse)
def logout(
    payload: LogoutRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    __: None = Depends(refresh_rate_limiter),
) -> APIResponse:
    refresh_token = _extract_refresh_token(
        payload.refresh_token, authorization)
    if refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refresh token is required",
        )

    auth_service.revoke_refresh_token(db, refresh_token)
    return APIResponse(data=None, message="Logout successful")


@router.post("/forgot-password", response_model=APIResponse)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db),_: None = Depends(forgot_password_rate_limiter),) -> APIResponse:
    user = auth_service.get_user_by_email(db, str(payload.email))
    if user is not None and user.is_active:

        reset_token = auth_service.create_password_reset_token(db, user)
        email_service.send_password_reset_email(user.email, reset_token)

    return APIResponse(
        data=None,
        message="If the email exists, password reset instructions have been generated",
    )


@router.post("/reset-password", response_model=APIResponse)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db),_: None = Depends(reset_password_rate_limiter),) -> APIResponse:
    is_reset = auth_service.reset_password(
        db,
        token=payload.token,
        new_password=payload.new_password,
    )
    if not is_reset:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    return APIResponse(data=None, message="Password reset successful")


@router.get("/me", response_model=APIResponse)
def get_me(current_user: User = Depends(get_current_user), _: None = Depends(read_rate_limiter),) -> APIResponse:
    return APIResponse(data=UserOut.model_validate(current_user).model_dump(mode="json"))


@router.patch("/me", response_model=APIResponse)
def update_me(
    payload: UpdateMeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(write_rate_limiter),
) -> APIResponse:
    if payload.full_name is not None:
        current_user.full_name = payload.full_name.strip()

    if payload.is_active is not None:
        current_user.is_active = payload.is_active

    if payload.new_password is not None:
        if payload.old_password is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Old password is required to change password",
            )
        if not verify_password(payload.old_password, current_user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Old password is incorrect",
            )
        current_user.password_hash = get_password_hash(payload.new_password)

    db.commit()
    db.refresh(current_user)
    return APIResponse(
        data=UserOut.model_validate(current_user).model_dump(mode="json"),
        message="Profile updated",
    )
