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

    # ---------------------------------------------------------------------
    # Email delivery (GAPS #3)
    #
    # `auto` picks resend if an API key is present, else SMTP if a host is,
    # else console (print to stdout — the historical behaviour, and still the
    # right default for a fresh clone). Configuring a provider is additive:
    # set the vars and delivery starts.
    #
    # The timeout matters. These sends happen inline in the request path, so an
    # unbounded provider call would park a Starlette threadpool worker exactly
    # the way an unbounded Celery enqueue did (GAPS-ROUND-2 #43).
    # ---------------------------------------------------------------------
    email_backend: str = "auto"             # auto | console | resend | smtp
    email_from: str = "Howl <noreply@howl.app>"
    email_timeout_seconds: float = 5.0

    resend_api_key: str | None = None

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True               # STARTTLS on a plaintext connection
    smtp_use_ssl: bool = False              # implicit TLS (port 465); wins over the above

    # App - Safe defaults for production
    environment: str = "production"
    debug: bool = False

    # CORS — comma-separated list of allowed origins
    allowed_origins: str = ""

    # Frontend base URL used in password-reset email links
    frontend_url: str = "http://localhost:3000"

    # Sentry — optional; omitting disables error/performance monitoring
    sentry_dsn: str | None = None

    # ---------------------------------------------------------------------
    # Rate limiting / client IP resolution (GAPS #66)
    #
    # Number of trusted reverse proxies in front of the app. `client_ip()` in
    # app/services/rate_limit.py reads the Nth `X-Forwarded-For` entry from
    # the *right* using this value — Railway/Vercel put exactly one proxy in
    # front, hence the default of 1. Get this wrong in the direction of "too
    # low" (e.g. a second proxy such as Cloudflare added in front of Railway,
    # with this left at 1) and the parsed "client" IP becomes a proxy's own
    # egress address, which every user shares — the IP bucket then locks the
    # entire application out of login after 10 attempts in 15 minutes.
    #
    # This field used to not exist: rate_limit.py read it via
    # `getattr(settings, "trusted_proxy_count", 1)`, so setting
    # TRUSTED_PROXY_COUNT in the environment did nothing (verified: with
    # pydantic-settings 2.x and this class's default `extra` behavior,
    # an undeclared env/.env key is silently ignored, not rejected — no
    # exception at import, the value just never reaches the object). It's
    # declared for real now so it's actually settable.
    # ---------------------------------------------------------------------
    trusted_proxy_count: int = 1

    # ---------------------------------------------------------------------
    # Email verification enforcement (GAPS #25)
    #
    # Enforcement is graduated, not a hard gate at registration: an unverified
    # account keeps full access for `email_verification_grace_period_hours`
    # measured from `users.created_at`, and only then loses the *outbound*
    # actions (swiping, sending messages, avatar generation). Reads stay open
    # throughout so a user can see what they are about to lose.
    #
    # `enforce_email_verification` is the operator kill switch. It defaults to
    # True because that is the correct posture and the grace window is what
    # makes it survivable — but GAPS #3 is still open (no email provider is
    # wired, verification links are printed to stdout), so an operator who
    # discovers users cannot actually receive their link needs a way to turn
    # enforcement off without a code change.
    # ---------------------------------------------------------------------
    enforce_email_verification: bool = True
    email_verification_grace_period_hours: int = 72


settings = Settings()