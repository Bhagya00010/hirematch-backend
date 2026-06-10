from authlib.integrations.starlette_client import OAuth

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db

from app.services import auth_service

router = APIRouter()

oauth = OAuth()

oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile"
    },
)


@router.get("/google/login")
async def google_login(request: Request):

    return await oauth.google.authorize_redirect(
        request,
        settings.GOOGLE_REDIRECT_URI
    )


@router.get("/google/callback")
async def google_callback(
    request: Request,
    db: Session = Depends(get_db),
):

    token = await oauth.google.authorize_access_token(
        request
    )

    user_info = token["userinfo"]

    email = user_info["email"]

    google_id = user_info["sub"]

    full_name = user_info.get(
        "name",
        email.split("@")[0]
    )

    avatar_url = user_info.get("picture")

    user = auth_service.get_user_by_google_id(
        db,
        google_id,
    )

    if not user:

        user = auth_service.get_user_by_email(
            db,
            email,
        )

        if user:

            user.google_id = google_id
            user.auth_provider = "google"

            db.commit()
            db.refresh(user)

        else:

            user = auth_service.create_google_user(
                db,
                email=email,
                full_name=full_name,
                google_id=google_id,
                avatar_url=avatar_url,
            )

    access_token, refresh_token = (
        auth_service.create_token_pair(
            db,
            user,
        )
    )

    return RedirectResponse(
        url=
        f"{settings.FRONTEND_URL}/auth/google/callback"
        f"?access_token={access_token}"
        f"&refresh_token={refresh_token}"
    )