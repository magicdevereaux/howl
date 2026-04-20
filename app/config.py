from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database - MUST come from env var
    database_url: str

    # Redis - MUST come from env var
    redis_url: str

    # Security - MUST come from env var
    secret_key: str
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Anthropic - MUST come from env var
    anthropic_api_key: str

    # App - Safe defaults for production
    environment: str = "production"
    debug: bool = False

    # CORS — comma-separated list of allowed origins
    allowed_origins: str = ""


settings = Settings()