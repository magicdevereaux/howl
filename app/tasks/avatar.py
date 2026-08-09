import json
import logging
from datetime import UTC, datetime

import anthropic
from pydantic import BaseModel, Field, field_validator

from app.celery_app import celery_app
from app.config import settings
from app.db import SessionLocal
from app.models.user import AvatarStatus, User
from app.services import task_lock
from app.services.image_generation import generate_avatar_image

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an expert at personality analysis and creative avatar design.
Analyze the bio and determine the user's spirit animal and core traits.

Return ONLY a valid JSON object — no markdown fences, no prose, just the object:
{
    "animal": "<single lowercase word: wolf | otter | fox | bear | owl | rabbit | lion | hawk | dolphin | cat | deer | crow | etc.>",
    "personality_traits": ["<trait>", "<trait>", "<trait>"],
    "avatar_description": "<1-2 sentences describing a vivid human-animal hybrid avatar suitable for image generation>",
    "image_prompt": "<DALL-E 3 prompt under 350 characters: mystical animal spirit art, specific colors, fantasy aesthetic>"
}"""


class _ClaudeAvatarPayload(BaseModel):
    """Shape contract for Claude's JSON reply, enforced before anything persists.

    GAPS-ROUND-2 #38. Nothing used to validate this. The annotations at the parse
    site were decoration, `personality_traits` and `avatar_description` are JSON
    columns so any shape stored cleanly, and five response schemas then declare
    them `list[str] | None` / `str | None`. One plausible-but-wrong reply — traits
    as objects rather than strings — permanently 500'd the affected user's login
    on both clients *and* `GET /api/users/discover` for every other user, since
    discover has no LIMIT and serialises the whole ready population at once.

    Enforcing it here is the real fix: a bad shape must never reach the database.
    `ValidationError` subclasses `ValueError`, so it lands in the existing
    `(json.JSONDecodeError, KeyError, ValueError)` handler below and marks the
    avatar `failed` — a state the app already recovers from via
    `POST /api/avatar/regenerate`. `app/schemas/ai_fields.py` handles rows written
    before this existed.

    Pydantic v2 does the work here: in lax mode it still refuses `dict` -> `str`
    and `int` -> `str`, so every near-miss shape is rejected rather than coerced
    into something that looks fine until it is read back.
    """

    animal: str
    personality_traits: list[str] = Field(default_factory=list)
    avatar_description: str = ""
    # Optional so the caller's animal-specific fallback still applies when Claude
    # omits it; an empty string would defeat that.
    image_prompt: str | None = None

    @field_validator("animal")
    @classmethod
    def _animal_must_be_meaningful(cls, value: str) -> str:
        # Mirrors the old `data["animal"].strip().lower()` plus its empty check.
        # Normalising here means the DB CHECK from #23
        # (ready => animal IS NOT NULL) can never see a whitespace-only animal.
        normalised = value.strip().lower()
        if not normalised:
            raise ValueError("Claude returned an empty animal field")
        return normalised


def _refund_regen_slot(user: User) -> None:
    """Give back the monthly regeneration slot this attempt consumed.

    GAPS-ROUND-2 #40. Both paths that can queue a generation --
    ``POST /api/avatar/regenerate`` and a bio edit on ``PATCH /api/profile/me``
    -- charge ``avatar_regenerations_this_month`` at *enqueue* time, and
    ``_MONTHLY_REGEN_LIMIT`` is 1. Without a refund, a generation that
    permanently fails leaves a free user 429'd for thirty days over an avatar
    they never received, and the 429 copy tells them to upgrade to premium.
    The users most likely to hit that are new ones whose first impression of
    the product's differentiating feature is a broken image and a paywall.

    Floored at 0 rather than asserted, because the counter is also reset by the
    30-day window: a failure that lands after the window rolled over must not
    push it negative and hand out a free extra slot next month.
    """
    charged = user.avatar_regenerations_this_month or 0
    user.avatar_regenerations_this_month = max(0, charged - 1)


def _mark_failed(db: object, user: User | None) -> None:
    """Mark the avatar failed, refund the regeneration slot, and commit.

    Safe to call with user=None. This is the single choke point for every
    *permanent* failure -- parse/validation errors, generic exceptions, and
    Claude retry exhaustion -- which is why the refund belongs here and not at
    the individual call sites: one of them would eventually be forgotten.

    The refund is written in the same transaction as the status, so the user is
    never observable as "failed but still charged".
    """
    if user is None:
        return
    try:
        user.avatar_status = AvatarStatus.failed
        _refund_regen_slot(user)
        user.updated_at = datetime.now(UTC)
        db.commit()
    except Exception:
        db.rollback()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def generate_avatar(self, user_id: int) -> None:
    """
    Analyse a user's bio with Claude and write back their spirit animal.

    Flow:
      1. Fetch user — bail if missing or has no bio.
      2. Call Claude (claude-haiku-4-5-20251001) with the bio.
      3. Parse JSON → update user.animal + avatar_status = 'ready'.
      4. On Claude API errors: retry up to 3×, then mark failed.
      5. On parse / validation errors: mark failed immediately (no point retrying).

    Duplicate-work protection: this task calls two paid APIs, and Celery runs
    with task_acks_late, so a worker killed after the DALL-E call but before the
    commit gets the message redelivered and pays for a second image. Two guards
    apply — an already-ready check for redelivery after a successful run, and a
    Redis single-flight lock for concurrent or in-flight duplicates. The lock
    fails open, so a Redis outage degrades to the old behaviour rather than
    blocking avatar generation entirely.
    """
    db = SessionLocal()
    user: User | None = None
    lock_key = f"avatar:generate:{user_id}"
    lock_held = False
    try:
        user = db.get(User, user_id)
        if user is None:
            logger.error("generate_avatar: user %d not found", user_id)
            return

        if not user.bio:
            logger.warning("generate_avatar: user %d has no bio — skipping", user_id)
            return

        # Redelivery after a run that already succeeded. Regeneration resets
        # status to pending before queueing, so this never blocks a real regen.
        if user.avatar_status == AvatarStatus.ready and user.avatar_url:
            logger.info(
                "generate_avatar: user %d already has a ready avatar — skipping", user_id
            )
            return

        lock_held = task_lock.acquire(lock_key)
        if not lock_held:
            logger.info(
                "generate_avatar: user %d already being generated elsewhere — skipping", user_id
            )
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
            logger.info("Stripped markdown fences")

        # ── Parse & validate ─────────────────────────────────────────────────
        # Shape-validated before anything is persisted -- see _ClaudeAvatarPayload
        # and GAPS-ROUND-2 #38. A wrong shape raises ValidationError (a ValueError)
        # and routes to _mark_failed rather than poisoning the row.
        data: dict = json.loads(raw_text)
        payload = _ClaudeAvatarPayload.model_validate(data)

        animal: str = payload.animal
        personality_traits: list[str] = payload.personality_traits
        avatar_description: str = payload.avatar_description
        image_prompt: str = payload.image_prompt or (
            f"A mystical {animal} spirit animal, ethereal digital art, "
            "fantasy style, vibrant colors"
        )

        logger.info(
            "generate_avatar: user=%d animal=%r traits=%r",
            user_id, animal, personality_traits,
        )

        # ── Generate avatar image (best-effort — never blocks ready status) ──
        avatar_url = generate_avatar_image(image_prompt, animal)

        # ── Persist ──────────────────────────────────────────────────────────
        # One commit, deliberately. ck_users_ready_avatar_has_animal enforces
        # "avatar_status='ready' implies animal IS NOT NULL", and a CHECK is
        # evaluated per *statement*, not per transaction — so inserting a
        # db.commit() or db.flush() between the status flip and the animal write
        # (in either order) turns this into an IntegrityError. If you need to
        # persist something mid-task, do it before this block, not inside it.
        #
        # `animal` is guaranteed non-empty here: the parse above raises
        # ValueError on a blank animal, which routes to _mark_failed instead.
        user.animal = animal
        user.personality_traits = personality_traits
        user.avatar_description = avatar_description
        user.avatar_url = avatar_url
        user.avatar_status = AvatarStatus.ready
        user.updated_at = datetime.now(UTC)
        db.commit()
        logger.info(
            "generate_avatar: user %d → complete (animal=%r, image=%s)",
            user_id, animal, "yes" if avatar_url else "no (emoji fallback)",
        )

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
        if lock_held:
            task_lock.release(lock_key)
        db.close()
