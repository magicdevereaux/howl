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
    refresh_token_expire_days: int = 30

    # Anthropic - MUST come from env var
    anthropic_api_key: str

    # OpenAI (DALL-E image generation) — optional; omitting disables image gen
    openai_api_key: str | None = None

    # Cloudflare R2 — optional; omitting falls back to local filesystem storage
    r2_endpoint_url: str | None = None      # https://<accountid>.r2.cloudflarestorage.com
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket_name: str | None = None
    r2_public_url: str | None = None        # public base URL (e.g. https://pub-xxx.r2.dev)

    # App - Safe defaults for production
    environment: str = "production"
    debug: bool = False

    # CORS — comma-separated list of allowed origins
    allowed_origins: str = ""

    # Frontend base URL used in password-reset email links
    frontend_url: str = "http://localhost:3000"

    # Sentry — optional; omitting disables error/performance monitoring
    sentry_dsn: str | None = None


settings = Settings()