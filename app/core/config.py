from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "HireMatch AI"

    API_V1_STR: str = "/api/v1"

    SQLALCHEMY_ECHO: bool = False

    DATABASE_URL: str

    SECRET_KEY: str

    ALGORITHM: str

    ACCESS_TOKEN_EXPIRE_MINUTES: int

    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30

    PASSWORD_RESET_URL: str = "http://localhost:3000/reset-password"

    SMTP_HOST: str | None = None

    SMTP_PORT: int = 587

    SMTP_USERNAME: str | None = None

    SMTP_PASSWORD: str | None = None

    SMTP_FROM_EMAIL: str | None = None

    SMTP_FROM_NAME: str = "HireMatch AI"

    SMTP_USE_TLS: bool = True

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
