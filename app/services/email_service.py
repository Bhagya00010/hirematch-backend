import logging
import smtplib
from email.message import EmailMessage
from urllib.parse import urlencode

from app.core.config import settings

logger = logging.getLogger(__name__)


def is_email_configured() -> bool:
    return all(
        [
            settings.SMTP_HOST,
            settings.SMTP_USERNAME,
            settings.SMTP_PASSWORD,
            settings.SMTP_FROM_EMAIL,
        ]
    )


def build_password_reset_url(reset_token: str) -> str:
    separator = "&" if "?" in settings.PASSWORD_RESET_URL else "?"
    return f"{settings.PASSWORD_RESET_URL}{separator}{urlencode({'token': reset_token})}"


def send_password_reset_email(to_email: str, reset_token: str) -> bool:
    if not is_email_configured():
        logger.warning(
            "Password reset email not sent because SMTP settings are missing")
        return False

    reset_url = build_password_reset_url(reset_token)
    message = EmailMessage()
    message["Subject"] = "Reset your HireMatch AI password"
    message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    message["To"] = to_email
    message.set_content(
        "\n".join(
            [
                "Hello,",
                "",
                "We received a request to reset your HireMatch AI password.",
                f"Open this link to reset your password: {reset_url}",
                "",
                f"This link expires in {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes.",
                "If you did not request this, you can ignore this email.",
                "",
                "HireMatch AI",
            ]
        )
    )

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls()
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        logger.exception("Password reset email failed to send")
        return False

    return True
