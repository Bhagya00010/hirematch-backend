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

    # LLM and Embedding Providers configuration
    LLM_PROVIDER: str | None = None
    EMBEDDING_PROVIDER: str | None = None

    # Ollama config
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_API_KEY: str | None = None
    OLLAMA_LLM_MODEL: str | None = None
    OLLAMA_EMBEDDING_MODEL: str | None = None
    OLLAMA_MODEL: str | None = None
    AI_EMBEDDING_MODEL: str | None = None

    # Gemini config
    GEMINI_API_KEY: str | None = None
    GEMINI_LLM_MODEL: str = "gemini-1.5-flash"

    # OpenAI config
    OPENAI_API_KEY: str | None = None
    OPENAI_LLM_MODEL: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"

    # Hugging Face config
    HUGGINGFACE_EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
