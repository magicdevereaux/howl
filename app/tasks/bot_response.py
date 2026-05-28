"""
Periodic bot response task.

Runs every 15 minutes via Celery Beat.  Finds every bot user who has an
unanswered message from a real user, respects per-archetype timing windows,
generates responses in batches of 10 using a single Claude Haiku call each,
and saves the resulting messages.  Also handles desperate-archetype follow-ups
when the bot's own message has gone unanswered for 2 hours.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

import anthropic
from sqlalchemy import or_

from app.celery_app import celery_app
from app.config import settings
from app.db import SessionLocal
from app.models.match import Match
from app.models.message import Message
from app.models.user import User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Archetype configuration
# ---------------------------------------------------------------------------

#: Minimum elapsed time (minutes) before a bot with this archetype will reply.
ARCHETYPE_MIN_DELAY: dict[str, int] = {
    "responsive":   5,
    "slow_burn":    120,
    "flirty":       10,
    "intellectual": 30,
    "ghost":        1,
    "desperate":    0,
}

#: Ghost bots go silent after this many messages in a conversation.
GHOST_MSG_LIMIT = 4

#: Desperate bots send a follow-up when their last message has been ignored
#: for this many seconds.
DESPERATE_FOLLOWUP_SECONDS = 7200  # 2 hours

_BATCH_SIZE = 10

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tz(dt: datetime) -> datetime:
    """Ensure the datetime is timezone-aware (handles SQLite naive datetimes)."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _recent_history(db, match_id: int, bot_id: int, limit: int = 5) -> list[dict]:
    """Return the last *limit* messages as labelled dicts for the prompt."""
    msgs = (
        db.query(Message)
        .filter(Message.match_id == match_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {"role": "you" if m.sender_id == bot_id else "them", "text": m.content or ""}
        for m in reversed(msgs)
    ]


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


# ---------------------------------------------------------------------------
# Claude batch call
# ---------------------------------------------------------------------------

def _generate_batch(batch: list[dict]) -> list[dict]:
    """
    Single Claude Haiku call for up to _BATCH_SIZE pending responses.

    Returns a list of ``{match_id, bot_id, message}`` dicts.
    Falls back to an empty list on any error (responses are best-effort).
    """
    items: list[str] = []
    for i, item in enumerate(batch):
        traits = ", ".join((item["traits"] or [])[:3]) or "curious"
        history_str = " | ".join(
            f"{h['role']}: {h['text'][:80]}" for h in item["history"][-3:]
        )
        if item["response_type"] == "followup":
            desc = (
                f"[{i}] {item['name']} ({item['animal']}, {item['archetype']}): "
                f"their last message went unanswered for 2 hours — send a follow-up. "
                f"History: {history_str}"
            )
        else:
            desc = (
                f"[{i}] {item['name']} ({item['animal']}, {item['archetype']}, "
                f"traits: {traits}): received \"{item['message_received']}\". "
                f"History: {history_str}"
            )
        items.append(desc)

    prompt = f"""Generate realistic dating-app replies for these characters. Match each archetype's voice:
- responsive: friendly, engaged, normal texting
- slow_burn: thoughtful, concise, unhurried
- flirty: playful, warm, one emoji max
- intellectual: asks a real question, references an idea
- ghost: terse, noncommittal (≤1 sentence — they're losing interest)
- desperate: overly eager, emotionally forward, slightly too much

{chr(10).join(items)}

Return ONLY a JSON array, no markdown:
[{{"index": 0, "message": "..."}}, ...]

Rules: 1–3 sentences. No opener like "Hey!". Sound human and distinct per character."""

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:-1]).strip()
        parsed = json.loads(raw)
        return [
            {
                "match_id": batch[r["index"]]["match_id"],
                "bot_id":   batch[r["index"]]["bot_id"],
                "message":  r["message"],
            }
            for r in parsed
            if isinstance(r.get("index"), int) and r["index"] < len(batch)
        ]
    except Exception as exc:
        logger.warning("bot_response: Claude batch call failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(name="app.tasks.bot_response.process_bot_responses")
def process_bot_responses() -> None:
    """
    Periodic task (every 15 minutes).

    Scans all bot users for conversations requiring a reply, respects
    archetype-specific delay windows, builds batches of up to 10, makes a
    single Claude call per batch, and saves the resulting messages.
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        pending: list[dict] = []

        bots = db.query(User).filter(User.is_bot == True).all()  # noqa: E712

        for bot in bots:
            archetype = bot.archetype or "responsive"
            min_delay_sec = ARCHETYPE_MIN_DELAY.get(archetype, 5) * 60

            matches = (
                db.query(Match)
                .filter(or_(Match.user1_id == bot.id, Match.user2_id == bot.id))
                .all()
            )

            for match in matches:
                real_id = match.user2_id if match.user1_id == bot.id else match.user1_id

                # Skip bot-to-bot matches (shouldn't happen, but be defensive)
                real_user = db.get(User, real_id)
                if real_user is None or real_user.is_bot:
                    continue

                last_msg = (
                    db.query(Message)
                    .filter(Message.match_id == match.id)
                    .order_by(Message.created_at.desc())
                    .first()
                )
                if last_msg is None:
                    continue

                # Ghost silencing: count how many messages the bot has sent
                if archetype == "ghost":
                    bot_sent = (
                        db.query(Message)
                        .filter(Message.match_id == match.id, Message.sender_id == bot.id)
                        .count()
                    )
                    if bot_sent >= GHOST_MSG_LIMIT:
                        continue

                last_dt = _tz(last_msg.created_at)
                elapsed = (now - last_dt).total_seconds()

                if last_msg.sender_id == real_id:
                    # Real user sent the last message — bot should reply if delay has passed
                    if elapsed >= min_delay_sec:
                        pending.append({
                            "match_id":       match.id,
                            "bot_id":         bot.id,
                            "name":           bot.name or "Someone",
                            "animal":         bot.animal or "wolf",
                            "traits":         bot.personality_traits,
                            "archetype":      archetype,
                            "response_type":  "reply",
                            "message_received": last_msg.content or "",
                            "history":        _recent_history(db, match.id, bot.id),
                        })

                elif last_msg.sender_id == bot.id and archetype == "desperate":
                    # Desperate bot: follow up if ignored for 2 hours
                    if elapsed >= DESPERATE_FOLLOWUP_SECONDS:
                        pending.append({
                            "match_id":       match.id,
                            "bot_id":         bot.id,
                            "name":           bot.name or "Someone",
                            "animal":         bot.animal or "wolf",
                            "traits":         bot.personality_traits,
                            "archetype":      "desperate",
                            "response_type":  "followup",
                            "message_received": None,
                            "history":        _recent_history(db, match.id, bot.id),
                        })

        logger.info("bot_response: %d pending responses across %d bots", len(pending), len(bots))

        saved = 0
        for batch in _chunks(pending, _BATCH_SIZE):
            results = _generate_batch(batch)
            for r in results:
                try:
                    msg = Message(
                        match_id=r["match_id"],
                        sender_id=r["bot_id"],
                        content=r["message"],
                    )
                    db.add(msg)
                    db.commit()
                    saved += 1
                except Exception as exc:
                    db.rollback()
                    logger.warning("bot_response: failed to save message: %s", exc)

        logger.info("bot_response: saved %d/%d responses", saved, len(pending))

    except Exception as exc:
        logger.exception("bot_response: task failed: %s", exc)
    finally:
        db.close()
