import json
import logging
from datetime import datetime, timezone

import anthropic

from app.celery_app import celery_app
from app.config import settings
from app.db import SessionLocal
from app.models.user import AvatarStatus, User

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an expert at personality analysis and creative avatar design.
Analyze the bio and determine the user's spirit animal and core traits.

Return ONLY a valid JSON object — no markdown fences, no prose, just the object:
{
    "animal": "<single lowercase word: wolf | otter | fox | bear | owl | rabbit | lion | hawk | dolphin | cat | deer | crow | etc.>",
    "personality_traits": ["<trait>", "<trait>", "<trait>"],
    "avatar_description": "<1-2 sentences describing a vivid human-animal hybrid avatar suitable for image generation>"
}"""


def _mark_failed(db: object, user: User | None) -> None:
    """Set avatar_status to failed and commit. Safe to call with user=None."""
    if user is None:
        return
    try:
        user.avatar_status = AvatarStatus.failed
        user.updated_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        db.rollback()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def generate_avatar(self, user_id: int) -> None:
    """
    Analyse a user's bio with Claude and write back their spirit animal.

    Flow:
      1. Fetch user — bail if missing or has no bio.
      2. Call Claude (claude-sonnet-4-20250514) with the bio.
      3. Parse JSON → update user.animal + avatar_status = 'ready'.
      4. On Claude API errors: retry up to 3×, then mark failed.
      5. On parse / validation errors: mark failed immediately (no point retrying).
    """
    db = SessionLocal()
    user: User | None = None
    try:
        user = db.get(User, user_id)
        if user is None:
            logger.error("generate_avatar: user %d not found", user_id)
            return

        if not user.bio:
            logger.warning("generate_avatar: user %d has no bio — skipping", user_id)
            return

        # ── Claude call ──────────────────────────────────────────────────────
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Bio: {user.bio}"}],
        )

        raw_text = next(
            (block.text for block in response.content if block.type == "text"),
            None,
        )
        if not raw_text:
            raise ValueError("Claude returned no text content")

        logger.info(f"Claude raw response: {raw_text!r}")
        
        # ── Strip markdown fences ───────────────────────────────────────
        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            raw_text = "\n".join(lines[1:-1]).strip()
            logger.info(f"Stripped markdown fences")

        # ── Parse & validate ─────────────────────────────────────────────────
        data: dict = json.loads(raw_text)

        animal: str = data["animal"].strip().lower()
        if not animal:
            raise ValueError("Claude returned an empty animal field")

        personality_traits: list[str] = data.get("personality_traits", [])
        avatar_description: str = data.get("avatar_description", "")

        logger.info(
            "generate_avatar: user=%d animal=%r traits=%r description=%r",
            user_id,
            animal,
            personality_traits,
            avatar_description,
        )

        # ── Persist ──────────────────────────────────────────────────────────
        user.animal = animal
        user.avatar_status = AvatarStatus.ready
        user.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("generate_avatar: user %d → complete (animal=%r)", user_id, animal)

    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        # Bad response from Claude — don't retry, just fail
        logger.error("generate_avatar: parse error for user %d: %s", user_id, exc)
        db.rollback()
        _mark_failed(db, user)

    except anthropic.APIError as exc:
        logger.error("generate_avatar: Claude API error for user %d: %s", user_id, exc)
        db.rollback()
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            _mark_failed(db, user)

    except Exception as exc:
        logger.exception("generate_avatar: unexpected error for user %d: %s", user_id, exc)
        db.rollback()
        _mark_failed(db, user)

    finally:
        db.close()
