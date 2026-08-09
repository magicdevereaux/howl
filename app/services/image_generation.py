"""
Avatar image generation and storage.

Generation: DALL-E 3 (requires OPENAI_API_KEY).
Storage priority:
  1. Cloudflare R2 (requires R2_* env vars) — persists across Railway redeploys.
  2. Local filesystem fallback (static/avatars/) — ephemeral on Railway.

Returns a full public URL (R2) or a server-relative path (/avatars/…) so the
frontend avatarUrl() helper can handle both without changes.

All paths are fail-open: any exception returns None so the caller can mark
the avatar ready with an emoji placeholder instead of crashing. Falling back
is not the same as failing quietly, though — see `_report_r2_failure`.
"""

import logging
import uuid
from pathlib import Path

import httpx
import sentry_sdk

from app.config import settings

logger = logging.getLogger(__name__)

# ── Optional dependencies (fail-open if missing) ──────────────────────────────

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore[assignment,misc]

try:
    import boto3
    _BOTO3_AVAILABLE = True
except ImportError:
    boto3 = None  # type: ignore[assignment]
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


def _r2_is_configured() -> bool:
    """True when this deployment is *supposed* to be storing avatars in R2.

    Distinct from "_get_r2_client() returned something": a deployment with all
    four R2_* vars set but a client that could not be built, or credentials the
    bucket rejects, is configured *and* broken. That is the whole distinction
    #62 was missing.
    """
    return bool(
        _BOTO3_AVAILABLE
        and settings.r2_endpoint_url
        and settings.r2_access_key_id
        and settings.r2_secret_access_key
        and settings.r2_bucket_name
    )


def _report_r2_failure(message: str, exc: BaseException | None = None) -> None:
    """Escalate an R2 failure on a deployment that is configured to use R2.

    GAPS-ROUND-2 #62. `_upload_to_r2` used to return None both when R2 was not
    configured and when a configured upload failed, with one `logger.warning`
    to tell them apart. Either way the bytes went to `static/avatars/` and the
    row committed `ready`, so a wrong `R2_SECRET_ACCESS_KEY`, a deleted bucket
    or an R2 outage produced avatars that looked completely healthy — 200s from
    the StaticFiles mount, images rendering, users happy — until the next
    Railway redeploy wiped the ephemeral disk and every avatar generated since
    the misconfiguration 404'd at once. There was no signal at any observable
    layer: no metric, no Sentry event (a `warning` is not an exception), and
    nothing in /health.

    Why alert and keep the local copy rather than failing the task:

    * The DALL-E image is already paid for and already works. Failing the task
      would mark the row `failed`, show the user a broken avatar, and offer a
      "Try Again" that buys a *second* image — which, while the credentials are
      still wrong, fails identically. That converts an operator problem into a
      user-visible outage that also doubles image spend, and it does so at the
      moment the operator has not yet been told anything is wrong.
    * The consequence of storing locally is bounded by how fast the operator
      fixes the config, which is exactly what this alert exists to enable.
    * "Flag the row for a repair job" needs no column. When R2 *is* configured,
      an `avatar_url` that is a local `/avatars/…` path is by definition a row
      that failed to upload, so the repair query already exists:
      `WHERE avatar_url LIKE '/avatars/%'`. Adding a boolean would duplicate a
      fact the URL already carries — and would need a migration.
    """
    logger.error("image_generation: %s", message, exc_info=exc)
    with sentry_sdk.new_scope() as scope:
        scope.set_level("error")
        scope.set_tag("subsystem", "avatar_storage")
        scope.set_context(
            "r2",
            {
                "bucket": settings.r2_bucket_name,
                "endpoint_url": settings.r2_endpoint_url,
                "consequence": (
                    "avatar stored on ephemeral local disk; it will 404 after "
                    "the next redeploy"
                ),
            },
        )
        if exc is not None:
            sentry_sdk.capture_exception(exc)
        else:
            sentry_sdk.capture_message(message, level="error")


def _r2_public_base() -> str:
    """Return the public URL base for R2 objects."""
    if settings.r2_public_url:
        return settings.r2_public_url.rstrip("/")
    # Default: endpoint + bucket (works for public R2 buckets)
    return f"{settings.r2_endpoint_url.rstrip('/')}/{settings.r2_bucket_name}"


# ── Storage helpers ────────────────────────────────────────────────────────────

def _upload_to_r2(img_bytes: bytes, filename: str) -> str | None:
    """Upload image bytes to R2. Returns the public URL, or None if not stored there.

    None still means "fall back to local disk", but it is no longer silent when
    it shouldn't be: on a deployment with the R2_* vars set, every route to None
    is an error and is escalated by `_report_r2_failure`. On a deployment
    without them, local storage is the intended behaviour and nothing is
    reported.
    """
    client = _get_r2_client()
    if client is None:
        if _r2_is_configured():
            # All four vars are set, so this is a client that could not be
            # constructed — malformed credentials, most likely. `_get_r2_client`
            # memoises, so it logs once per process and would otherwise go quiet
            # for every subsequent avatar.
            _report_r2_failure(
                "R2 is configured but no client could be built; avatars are "
                "falling back to ephemeral local storage"
            )
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
    except Exception as exc:
        # `except (BotoCoreError, BotoClientError, Exception)` was the same
        # thing written three times — and when boto3 is missing the first two
        # *are* `Exception` (see the import guard above).
        _report_r2_failure(
            f"R2 upload failed for {filename}; the avatar is on ephemeral local "
            f"disk and will 404 after the next redeploy",
            exc,
        )
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

        # Try R2 first; fall back to local filesystem. Spelled out rather than
        # `_upload_to_r2(...) or _save_locally(...)` because the fallback is not
        # unconditionally benign: on a deployment configured for R2 it means the
        # avatar is on a disk the next redeploy wipes. `_upload_to_r2` raises the
        # alarm for that case (#62); this call site stays fail-open so the user
        # still gets the image they paid for.
        url = _upload_to_r2(img_bytes, filename)
        if url is None:
            url = _save_locally(img_bytes, filename)
        logger.info("image_generation: avatar stored for %r → %s", animal_name, url)
        return url

    except Exception as exc:
        logger.warning("image_generation: generation failed for %r: %s", animal_name, exc)
        return None
