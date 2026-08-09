import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import sentry_sdk
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from redis import Redis, RedisError
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sqlalchemy import text

from app.api.auth import router as auth_router
from app.api.avatar import router as avatar_router
from app.api.blocks import router as blocks_router
from app.api.chat import router as chat_router
from app.api.mobile_auth import router as mobile_auth_router
from app.api.profile import router as profile_router
from app.api.push_tokens import router as push_tokens_router
from app.api.reports import router as reports_router
from app.api.swipes import router as swipes_router
from app.api.users import router as users_router
from app.config import settings
from app.db import engine

logger = logging.getLogger(__name__)

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            CeleryIntegration(),
            SqlalchemyIntegration(),
        ],
        traces_sample_rate=0.2,
        environment=settings.environment,
    )

app = FastAPI(
    title="Howl",
    description="AI-powered dating app with animal-human hybrid avatars",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

_cors_origins: list[str] = [
    o.strip() for o in settings.allowed_origins.split(",") if o.strip()
]
if settings.debug:
    _cors_origins.extend(["http://localhost:3000", "http://127.0.0.1:3000"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_router)
app.include_router(mobile_auth_router)
app.include_router(profile_router)
app.include_router(avatar_router)
app.include_router(users_router)
app.include_router(swipes_router)
app.include_router(chat_router)
app.include_router(blocks_router)
app.include_router(reports_router)
app.include_router(push_tokens_router)


_avatar_dir = Path("static/avatars")
_avatar_dir.mkdir(parents=True, exist_ok=True)
app.mount("/avatars", StaticFiles(directory=str(_avatar_dir)), name="avatars")


_HEALTH_TIMEOUT_SECONDS = 1.0


def _check_database(timeout: float = _HEALTH_TIMEOUT_SECONDS) -> bool:
    """``SELECT 1`` against Postgres with a short timeout.

    A bounded thread — rather than a driver-level statement timeout — is what
    lets this stay correct across both the production Postgres engine and the
    SQLite engine the test suite runs against, without depending on a specific
    DBAPI's timeout knobs.
    """

    def _probe() -> bool:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_probe).result(timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - any failure means "unreachable"
        logger.warning("health: database check failed: %s", exc)
        return False


def _check_redis(timeout: float = _HEALTH_TIMEOUT_SECONDS) -> bool:
    """``PING`` Redis with a short timeout. A fresh client avoids sharing
    connection state with the rate limiter's client."""
    try:
        client = Redis.from_url(
            settings.redis_url,
            socket_timeout=timeout,
            socket_connect_timeout=timeout,
        )
        return bool(client.ping())
    except (RedisError, OSError) as exc:
        logger.warning("health: redis check failed: %s", exc)
        return False


def _r2_configured() -> bool:
    """Whether R2 env vars are present — cheap, no network call.

    This is deliberately *configured*, not *reachable*: a HeadBucket call
    would tell us more (see GAPS #62) but needs boto3, which is lazily
    imported in app/services/image_generation.py and not even installed in
    this environment (CLAUDE.md). Doing that probe on every health check
    would add a network round trip and a hard dependency this endpoint
    doesn't otherwise need, so it's left to #62 rather than folded in here.
    """
    return bool(
        settings.r2_endpoint_url
        and settings.r2_access_key_id
        and settings.r2_secret_access_key
        and settings.r2_bucket_name
    )


@app.get("/health", tags=["system"])
def health_check(response: Response) -> dict[str, object]:
    """Deploy healthcheck / liveness signal used by Railway.

    Actually touches Postgres and Redis (both with a ~1s timeout) so a
    replica that cannot reach either is reported unhealthy and returns 503
    instead of a routing-worthy 200. See ``/health/live`` for a dependency-free
    liveness path.
    """
    db_ok = _check_database()
    redis_ok = _check_redis()
    overall_ok = db_ok and redis_ok

    if not overall_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if overall_ok else "unhealthy",
        "environment": settings.environment,
        "checks": {
            "database": "ok" if db_ok else "unreachable",
            "redis": "ok" if redis_ok else "unreachable",
            "r2": "configured" if _r2_configured() else "unconfigured",
        },
    }


@app.get("/health/live", tags=["system"])
async def liveness_check() -> dict[str, str]:
    """Always-200 liveness path.

    Deliberately does not touch Postgres or Redis: this is what Railway
    should point at if it needs a signal that must not restart the container
    on a transient dependency blip. ``/health`` is the readiness/deploy gate;
    this is "is the process alive at all".
    """
    return {"status": "ok"}
