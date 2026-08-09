import base64
import random
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

# Maps looking_for values to the corresponding gender stored on User rows.
_LOOKING_FOR_TO_GENDER = {
    "men": "man",
    "women": "woman",
    "non-binary": "non-binary",
}

from app.db import get_db
from app.dependencies import get_current_user
from app.models.block import Block
from app.models.match import Match
from app.models.message import Message
from app.models.swipe import Swipe
from app.models.user import AvatarStatus, User
from app.schemas.swipe import DiscoverUserOut, LastMessageOut, MatchedProfileOut, MatchOut

router = APIRouter(prefix="/api/users", tags=["users"])

# GAPS #58: discover had no LIMIT at all -- every eligible user, on every call,
# forever growing with the user table. 30/page keeps a normal deck snappy;
# capped at 50 so a client can't ask its way back into the old behaviour.
_DISCOVER_DEFAULT_LIMIT = 30
_DISCOVER_MAX_LIMIT = 50


def _encode_discover_cursor(created_at: datetime, user_id: int) -> str:
    """Opaque cursor: base64 of `<created_at.isoformat()>|<id>`.

    Not a page number or offset -- see the docstring on `discover_users` for
    why offset pagination breaks here specifically.
    """
    raw = f"{created_at.isoformat()}|{user_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_discover_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        created_at_str, id_str = raw.rsplit("|", 1)
        return datetime.fromisoformat(created_at_str), int(id_str)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor.") from exc


@router.get("/discover", response_model=list[DiscoverUserOut])
def discover_users(
    response: Response,
    cursor: str | None = Query(
        default=None,
        description="Opaque cursor from a previous response's X-Next-Cursor header. Omit for the first page.",
    ),
    limit: int = Query(default=_DISCOVER_DEFAULT_LIMIT, ge=1, le=_DISCOVER_MAX_LIMIT),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[User]:
    """Return ready users the current user hasn't swiped on or blocked (either direction).

    Preference filtering is opt-in: a filter is only applied when the current
    user has set the corresponding preference.  Users who have not filled in
    their own age or gender are always included so incomplete profiles are not
    unfairly hidden.

    GAPS #58: this used to return every eligible user in one response with a
    fixed `created_at DESC` order -- unbounded (it was what turned the #38 P0
    from one broken profile into a global outage) and identical for every
    user, so the newest bots dominated everyone's first impressions.

    Pagination contract (backwards compatible; see below for why):
      - Query params: `limit` (int, default 30, min 1, max 50) and `cursor`
        (opaque string, omit for page 1).
      - Response body is unchanged: a bare JSON array of `DiscoverUserOut`,
        capped at `limit` items, shuffled within the page.
      - Pagination metadata rides in response headers, not the body:
        `X-Has-More` ("true"/"false") and, when true, `X-Next-Cursor` (pass it
        back as `cursor` to fetch the next page).

    Why headers instead of `{"items": [...], "next_cursor": ...}`: an already
    -installed client (a mobile build in the wild that can't be force-upgraded,
    or a web client not yet rebuilt) that calls this with no params and expects
    a bare array must keep working. It gets today's fix for free even without
    reading `cursor` at all: each swipe removes that user from the underlying
    query, so a client that always calls with no cursor keeps seeing the next
    batch of up to `limit` unswiped users as it swipes through the current
    batch -- "pagination advances naturally," per the brief, no cursor logic
    required. Clients that read `X-Next-Cursor` can prefetch ahead of that.

    Why a cursor and not an offset: swiping removes rows from the filtered
    set the query pages over. An offset counts *positions*, so swiping on
    anything already fetched shifts every later position up by one and skips
    whoever would have been next. A cursor names a specific (`created_at`,
    `id`) boundary instead of a position, so it is unaffected by rows dropping
    out of the pool ahead of it.
    """
    swiped = (
        db.query(Swipe.target_user_id)
        .filter(Swipe.user_id == current_user.id)
        .scalar_subquery()
    )
    blocked_by_me = (
        db.query(Block.blocked_id)
        .filter(Block.blocker_id == current_user.id)
        .scalar_subquery()
    )
    blocking_me = (
        db.query(Block.blocker_id)
        .filter(Block.blocked_id == current_user.id)
        .scalar_subquery()
    )
    q = (
        db.query(User)
        .filter(
            User.id != current_user.id,
            User.avatar_status == AvatarStatus.ready,
            User.id.notin_(swiped),
            User.id.notin_(blocked_by_me),
            User.id.notin_(blocking_me),
        )
    )

    # Age range preference — include profiles that haven't set their age
    if current_user.age_preference_min is not None:
        q = q.filter(
            or_(User.age.is_(None), User.age >= current_user.age_preference_min)
        )
    if current_user.age_preference_max is not None:
        q = q.filter(
            or_(User.age.is_(None), User.age <= current_user.age_preference_max)
        )

    # Gender/looking_for — include profiles that haven't set their gender
    if current_user.looking_for and current_user.looking_for != "everyone":
        target_gender = _LOOKING_FOR_TO_GENDER.get(current_user.looking_for)
        if target_gender:
            q = q.filter(
                or_(User.gender.is_(None), User.gender == target_gender)
            )

    if cursor is not None:
        cursor_created_at, cursor_id = _decode_discover_cursor(cursor)
        q = q.filter(
            or_(
                User.created_at < cursor_created_at,
                and_(User.created_at == cursor_created_at, User.id < cursor_id),
            )
        )

    # Tie-break on id: bulk-seeded rows (scripts/seed_demo_users.py) can share
    # a created_at down to the second, and without a deterministic secondary
    # key the cursor boundary above could skip or repeat rows across pages.
    rows = q.order_by(User.created_at.desc(), User.id.desc()).limit(limit + 1).all()

    has_more = len(rows) > limit
    page = rows[:limit]

    response.headers["X-Has-More"] = "true" if has_more else "false"
    if has_more:
        last = page[-1]
        response.headers["X-Next-Cursor"] = _encode_discover_cursor(last.created_at, last.id)

    # Randomised within the page (not globally): the query order above must
    # stay deterministic for cursor correctness, so the shuffle happens after
    # the cursor is computed from it, purely for display order.
    random.shuffle(page)
    return page


@router.get("/matches", response_model=list[MatchOut])
def list_matches(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MatchOut]:
    """Return all matches with unread count and last message in a single query.

    Replaces the previous N+1 loop (3 queries per match) with:
      - one CASE-based JOIN to resolve the other user without a subloop
      - one ROW_NUMBER window-function subquery to get the newest message per match
      - one correlated scalar subquery for the per-match unread count
    Total: one database round-trip regardless of match count.
    """
    uid = current_user.id

    # Resolve "the other participant" as a SQL expression so the JOIN is computed
    # in the database rather than fetched row-by-row in Python.
    other_id_col = case(
        (Match.user1_id == uid, Match.user2_id),
        else_=Match.user1_id,
    )

    # Rank every message within its match newest-first.
    # Selecting rn == 1 from this subquery gives the last message per match
    # without a separate query per match.
    ranked_msgs = (
        db.query(
            Message.match_id.label("match_id"),
            Message.sender_id.label("sender_id"),
            Message.content.label("content"),
            Message.created_at.label("created_at"),
            func.row_number()
            .over(
                partition_by=Message.match_id,
                order_by=Message.created_at.desc(),
            )
            .label("rn"),
        )
        .subquery("ranked_msgs")
    )

    # Correlated scalar subquery for unread count.
    # COUNT(*) always returns an integer (0 when no rows match), so this is
    # never NULL regardless of whether there are any messages in the match.
    unread_sq = (
        select(func.count())
        .where(
            Message.match_id == Match.id,
            Message.sender_id != uid,
            Message.read_at.is_(None),
        )
        .correlate(Match)
        .scalar_subquery()
    )

    rows = (
        db.query(
            Match,
            User,
            unread_sq.label("unread_count"),
            ranked_msgs.c.sender_id.label("last_sender_id"),
            ranked_msgs.c.content.label("last_content"),
            ranked_msgs.c.created_at.label("last_created_at"),
        )
        .join(User, User.id == other_id_col)
        .outerjoin(
            ranked_msgs,
            (ranked_msgs.c.match_id == Match.id) & (ranked_msgs.c.rn == 1),
        )
        .filter(or_(Match.user1_id == uid, Match.user2_id == uid))
        .order_by(Match.matched_at.desc())
        .all()
    )

    return [
        MatchOut(
            id=match.id,
            matched_at=match.matched_at,
            other_user=MatchedProfileOut.model_validate(other),
            unread_count=unread_count or 0,
            last_message=(
                LastMessageOut(
                    sender_id=last_sender_id,
                    content=last_content,
                    created_at=last_created_at,
                )
                if last_content is not None else None
            ),
        )
        for match, other, unread_count, last_sender_id, last_content, last_created_at in rows
    ]
