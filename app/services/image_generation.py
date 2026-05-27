"""
Avatar image generation and storage.

Generation: DALL-E 3 (requires OPENAI_API_KEY).
Storage priority:
  1. Cloudflare R2 (requires R2_* env vars) — persists across Railway redeploys.
  2. Local filesystem fallback (static/avatars/) — ephemeral on Railway.

Returns a full public URL (R2) or a server-relative path (/avatars/…) so the
frontend avatarUrl() helper can handle both without changes.

All paths are fail-open: any exception returns None so the caller can mark
the avatar ready with an emoji placeholder instead of crashing.
"""

import logging
import uuid
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ── Optional dependencies (fail-open if missing) ──────────────────────────────

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore[assignment,misc]

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError as BotoClientError
    _BOTO3_AVAILABLE = True
except ImportError:
    boto3 = None  # type: ignore[assignment]
    BotoCoreError = BotoClientError = Exception  # type: ignore[assignment,misc]
    _BOTO3_AVAILABLE = False

# ── Local fallback constants ───────────────────────────────────────────────────

AVATAR_DIR = Path("static/avatars")
AVATAR_URL_PREFIX = "/avatars"

# ── Lazy R2 client ─────────────────────────────────────────────────────────────

_r2_client = None
_r2_init_done = False


def _get_r2_client():
    """Return a boto3 S3 client pointed at R2, or None if not configured."""
    global _r2_client, _r2_init_done
    if _r2_init_done:
        return _r2_client
    _r2_init_done = True

    if not _BOTO3_AVAILABLE:
        logger.debug("image_generation: boto3 not installed — R2 unavailable")
        return None
    if not all([
        settings.r2_endpoint_url,
        settings.r2_access_key_id,
        settings.r2_secret_access_key,
        settings.r2_bucket_name,
    ]):
        logger.debug("image_generation: R2 env vars not set — using local storage")
        return None

    try:
        _r2_client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
        )
        logger.info("image_generation: R2 client initialised (bucket=%s)", settings.r2_bucket_name)
    except Exception as exc:
        logger.error("image_generation: R2 client init failed: %s", exc)
    return _r2_client


def _r2_public_base() -> str:
    """Return the public URL base for R2 objects."""
    if settings.r2_public_url:
        return settings.r2_public_url.rstrip("/")
    # Default: endpoint + bucket (works for public R2 buckets)
    return f"{settings.r2_endpoint_url.rstrip('/')}/{settings.r2_bucket_name}"


# ── Storage helpers ────────────────────────────────────────────────────────────

def _upload_to_r2(img_bytes: bytes, filename: str) -> str | None:
    """Upload image bytes to R2. Returns the public URL or None on failure."""
    client = _get_r2_client()
    if client is None:
        return None
    try:
        client.put_object(
            Bucket=settings.r2_bucket_name,
            Key=filename,
            Body=img_bytes,
            ContentType="image/png",
        )
        url = f"{_r2_public_base()}/{filename}"
        logger.info("image_generation: uploaded to R2 → %s", url)
        return url
    except (BotoCoreError, BotoClientError, Exception) as exc:
        logger.warning("image_generation: R2 upload failed, falling back to local: %s", exc)
        return None


def _save_locally(img_bytes: bytes, filename: str) -> str:
    """Save image bytes to the local filesystem. Returns a server-relative URL."""
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    (AVATAR_DIR / filename).write_bytes(img_bytes)
    url = f"{AVATAR_URL_PREFIX}/{filename}"
    logger.info("image_generation: saved locally → %s", url)
    return url


def delete_avatar(avatar_url: str | None) -> None:
    """
    Best-effort deletion of an avatar from wherever it's stored.

    Full https:// URLs are assumed to be R2; server-relative paths are local.
    Never raises — a failed delete must never block account deletion.
    """
    if not avatar_url:
        return
    try:
        if avatar_url.startswith("http"):
            client = _get_r2_client()
            if client is None:
                return
            # Extract the object key by stripping the public base URL
            base = _r2_public_base()
            key = avatar_url.replace(base + "/", "", 1)
            client.delete_object(Bucket=settings.r2_bucket_name, Key=key)
            logger.info("image_generation: deleted from R2: %s", key)
        else:
            filename = Path(avatar_url).name
            (AVATAR_DIR / filename).unlink(missing_ok=True)
            logger.info("image_generation: deleted locally: %s", filename)
    except Exception as exc:
        logger.warning("image_generation: avatar delete failed (non-blocking): %s", exc)


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_avatar_image(image_prompt: str, animal_name: str) -> str | None:
    """
    Generate an avatar with DALL-E 3 and store it.

    Storage priority: R2 → local filesystem → None (emoji fallback).
    Returns a full HTTPS URL (R2) or a server-relative path (local),
    or None if generation or both storage options fail.
    """
    if not settings.openai_api_key or OpenAI is None:
        logger.debug("image_generation: OPENAI_API_KEY not configured — skipping")
        return None

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.images.generate(
            model="dall-e-3",
            prompt=image_prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        temp_url = response.data[0].url

        with httpx.Client(timeout=30.0) as http:
            img_bytes = http.get(temp_url).raise_for_status().content

        filename = f"{uuid.uuid4()}.png"

        # Try R2 first; fall back to local filesystem
        url = _upload_to_r2(img_bytes, filename) or _save_locally(img_bytes, filename)
        logger.info("image_generation: avatar stored for %r → %s", animal_name, url)
        return url

    except Exception as exc:
        logger.warning("image_generation: generation failed for %r: %s", animal_name, exc)
        return None
