from pathlib import Path

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.api.auth import router as auth_router
from app.api.avatar import router as avatar_router
from app.api.chat import router as chat_router
from app.api.profile import router as profile_router
from app.api.swipes import router as swipes_router
from app.api.users import router as users_router
from app.config import settings

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
app.include_router(profile_router)
app.include_router(avatar_router)
app.include_router(users_router)
app.include_router(swipes_router)
app.include_router(chat_router)


_avatar_dir = Path("static/avatars")
_avatar_dir.mkdir(parents=True, exist_ok=True)
app.mount("/avatars", StaticFiles(directory=str(_avatar_dir)), name="avatars")


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}
