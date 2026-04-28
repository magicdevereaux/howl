"""
DALL-E 3 avatar image generation.

Designed to never crash the caller — every failure path returns None so the
task can mark the avatar ready with emoji fallback instead.
"""

import logging
import uuid
from pathlib import Path

import httpx

from app.config import settings

try:
    from openai import OpenAI
except ImportError:  # openai package not installed (e.g., minimal test env)
    OpenAI = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

AVATAR_DIR = Path("static/avatars")
AVATAR_URL_PREFIX = "/avatars"


def generate_avatar_image(image_prompt: str, animal_name: str) -> str | None:
    """
    Generate an avatar with DALL-E 3 and save it to disk.

    Returns a server-relative URL like ``/avatars/<uuid>.png``,
    or ``None`` if the API key is absent or any step fails.
    The caller is responsible for prepending the base URL when sending
    the value to the frontend.
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

        AVATAR_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4()}.png"
        (AVATAR_DIR / filename).write_bytes(img_bytes)

        url = f"{AVATAR_URL_PREFIX}/{filename}"
        logger.info("image_generation: saved avatar for %r → %s", animal_name, url)
        return url

    except Exception as exc:
        logger.warning("image_generation: failed for %r: %s", animal_name, exc)
        return None
