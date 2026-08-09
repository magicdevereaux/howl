import asyncio
import json
import logging
import time
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)

# Query kept for before_id pagination param
from jose import JWTError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.dependencies import (
    WS_EMAIL_VERIFICATION_REQUIRED,
    email_verification_error,
    get_current_user,
    require_verified_email,
)
from app.models.match import Match
from app.models.message import Message
from app.models.swipe import Swipe
from app.models.user import User
from app.schemas.chat import MessageIn, MessageOut, MessagePageOut, UnreadCountOut
from app.security import decode_access_token
from app.services.pubsub import ChatPubSub
from app.services.rate_limit import check_rate_limit
from app.services.task_queue import enqueue
from app.tasks.notify import notify_new_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/matches", tags=["chat"])

_RATE_LIMIT_MAX = 10       # messages per window, per sender per match
_RATE_LIMIT_WINDOW_S = 60  # seconds
_PAGE_SIZE = 50            # messages returned per request

# Inbound WS "typing" events, budgeted per connection. See _TypingBudget.
_TYPING_LIMIT = 5
_TYPING_WINDOW_S = 2.0

# A single slow socket must not stall delivery for everyone else on this
# replica, because remote events are all delivered by the one pub/sub reader
# task. Past this, treat the socket as dead and drop it.
_SEND_TIMEOUT_S = 5.0

# Close code sent to a socket the server gives up writing to. 1011
# ("internal error") is a normal close as far as the browser is concerned, so
# both clients' existing onclose/onerror reconnect paths fire on it.
_WS_CLOSE_DROPPED = 1011


def _message_rate_limit_key(user_id: int, match_id: int) -> str:
    """Redis key for the send limit. Scoped per (sender, match), as the
    previous DB COUNT implementation was."""
    return f"rl:msg:{user_id}:{match_id}"


class _TypingBudget:
    """Fixed-window counter for inbound `typing` frames on one WebSocket.

    Deliberately in-process and per-connection rather than Redis-backed: a
    WebSocket is pinned to the process that accepted it, so a local counter is
    *exact* for that connection and needs no coordination. It also avoids
    paying a Redis round-trip per keystroke — which, on an endpoint whose whole
    problem is that it can be spammed, would make the limiter the amplifier.
    The state dies with the socket, so nothing leaks.
    """

    __slots__ = ("_window_start", "_count")

    def __init__(self) -> None:
        self._window_start = 0.0
        self._count = 0

    def allow(self) -> bool:
        now = time.monotonic()
        if now - self._window_start >= _TYPING_WINDOW_S:
            self._window_start = now
            self._count = 0
        self._count += 1
        return self._count <= _TYPING_LIMIT


# ---------------------------------------------------------------------------
# WebSocket connection manager
#
# Tracks open WebSocket connections per match, storing user_id alongside each
# connection so is_mine can be computed per recipient without an extra DB call.
#
# The local registry is still an in-process dict — a socket can only be written
# to by the process holding it — but it is no longer the whole story. Outbound
# events are delivered to local sockets *and* published to a Redis channel for
# the match, and every replica serving that match subscribes to it. That makes
# delivery correct across replicas. See app/services/pubsub.py for the
# transport, its fail-open-to-local-delivery policy, and why double delivery
# to the publishing replica cannot happen (origin stamping).
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self, pubsub: ChatPubSub | None = None) -> None:
        # match_id → {WebSocket: (user_id, display_name)}
        self._conns: dict[int, dict[WebSocket, tuple[int, str | None]]] = {}
        # Strong references to in-flight close tasks. asyncio only holds a weak
        # reference to a running task, so without this the GC is free to cancel
        # a close mid-handshake and we are back to a socket that never learns.
        self._close_tasks: set[asyncio.Task] = set()
        self._pubsub = pubsub if pubsub is not None else ChatPubSub()
        self._pubsub.set_handler(self._on_remote_event)

    @property
    def pubsub(self) -> ChatPubSub:
        return self._pubsub

    async def connect(self, match_id: int, user_id: int, display_name: str | None, ws: WebSocket) -> None:
        await ws.accept()
        first_for_match = match_id not in self._conns
        self._conns.setdefault(match_id, {})[ws] = (user_id, display_name)
        if first_for_match:
            # Only subscribe once per match, on the first local socket.
            await self._pubsub.subscribe(match_id)
        logger.debug("ws: user %d connected to match %d", user_id, match_id)

    async def disconnect(self, match_id: int, ws: WebSocket) -> None:
        conns = self._conns.get(match_id, {})
        entry = conns.pop(ws, None)
        if not conns:
            self._conns.pop(match_id, None)
            # No local socket cares about this match any more.
            await self._pubsub.unsubscribe(match_id)
        if entry is not None:
            logger.debug("ws: user %d disconnected from match %d", entry[0], match_id)

    # ── dropping a socket the server has given up on ────────────────────────

    def _close_soon(self, ws: WebSocket, code: int) -> None:
        """Close *ws* out of band, without blocking the caller.

        Deliberately not awaited: the reason we are closing is usually that the
        socket is unresponsive, so awaiting the close handshake would reintroduce
        exactly the stall that dropping it was meant to avoid. The close is
        bounded by the same timeout and every failure is swallowed — a socket we
        have already written off cannot fail any harder.
        """
        async def _close() -> None:
            try:
                await asyncio.wait_for(ws.close(code=code), timeout=_SEND_TIMEOUT_S)
            except Exception:
                pass  # already gone, or gone unresponsive — nothing left to do

        task = asyncio.create_task(_close())
        self._close_tasks.add(task)
        task.add_done_callback(self._close_tasks.discard)

    async def _drop(self, match_id: int, ws: WebSocket) -> None:
        """Evict a socket we could not write to, and tell the client.

        Unregistering alone leaves the TCP connection open, so the client's
        onclose/onerror never fires, its reconnect logic never runs, and it sits
        in a chat that looks connected while receiving nothing for the rest of
        the session. Closing turns a silent black hole into the reconnect the
        client already knows how to do.

        Pruning goes through disconnect() rather than mutating _conns directly so
        that pub/sub subscribe/unsubscribe bookkeeping stays owned by one
        function. Otherwise _conns[match_id] can be left as an empty-but-present
        dict, and connect()'s `match_id not in self._conns` test then skips the
        subscribe for the next socket.
        """
        self._close_soon(ws, _WS_CLOSE_DROPPED)
        await self.disconnect(match_id, ws)

    # ── outbound: local delivery + cross-replica publish ────────────────────

    async def broadcast(self, match_id: int, event: dict) -> None:
        """Push event to every connection for a match, on any replica.

        event must have a "message" dict containing at least "sender_id".
        is_mine is computed per recipient so each client receives the correct
        value without the server needing to send separate payloads.

        Local sockets are served first and synchronously, so delivery on this
        replica does not depend on Redis at all.
        """
        await self._deliver_message(match_id, event)
        await self._pubsub.publish(match_id, {"kind": "message", "event": event})

    async def broadcast_typing(self, match_id: int, sender_user_id: int) -> None:
        """Notify everyone else in the match that sender_user_id is typing."""
        conns = self._conns.get(match_id) or {}
        sender_name = next(
            (name for _ws, (uid, name) in conns.items() if uid == sender_user_id),
            None,
        )
        display = sender_name or "Someone"
        await self._deliver_typing(match_id, sender_user_id, display)
        # The name has to travel with the event: on another replica the typer
        # has no local connection to look it up from.
        await self._pubsub.publish(
            match_id,
            {"kind": "typing", "sender_id": sender_user_id, "user_name": display},
        )

    # ── inbound: events published by another replica ─────────────────────────

    async def _on_remote_event(self, match_id: int, payload: dict) -> None:
        """Handle an event another replica published. Never called for our own
        publishes — ChatPubSub filters those out by origin id."""
        kind = payload.get("kind")
        if kind == "message":
            event = payload.get("event")
            if isinstance(event, dict):
                await self._deliver_message(match_id, event)
        elif kind == "typing":
            sender_id = payload.get("sender_id")
            if isinstance(sender_id, int):
                await self._deliver_typing(
                    match_id, sender_id, payload.get("user_name") or "Someone"
                )

    # ── local socket writes ──────────────────────────────────────────────────

    async def _deliver_message(self, match_id: int, event: dict) -> None:
        conns = self._conns.get(match_id)
        if not conns:
            return
        msg = event.get("message", {})
        sender_id = msg.get("sender_id")
        dead: list[WebSocket] = []
        for ws, (uid, _name) in list(conns.items()):
            payload = {**event, "message": {**msg, "is_mine": uid == sender_id}}
            if not await self._send(ws, payload):
                dead.append(ws)
        for ws in dead:
            await self._drop(match_id, ws)

    async def _deliver_typing(self, match_id: int, sender_user_id: int, display: str) -> None:
        conns = self._conns.get(match_id)
        if not conns:
            return
        dead: list[WebSocket] = []
        for ws, (uid, _name) in list(conns.items()):
            if uid == sender_user_id:
                continue  # don't echo back to the typer
            if not await self._send(ws, {"type": "typing", "user_name": display}):
                dead.append(ws)
        for ws in dead:
            await self._drop(match_id, ws)

    async def _send(self, ws: WebSocket, payload: dict) -> bool:
        """Write one frame. Returns False if the socket should be dropped."""
        try:
            await asyncio.wait_for(ws.send_json(payload), timeout=_SEND_TIMEOUT_S)
            return True
        except TimeoutError:
            logger.warning("ws: send timed out after %.0fs; dropping socket", _SEND_TIMEOUT_S)
            return False
        except Exception:
            return False


manager = ConnectionManager()


def _msg_event(event_type: str, msg: Message) -> dict:
    """Serialise a Message row into a broadcastable event dict (no is_mine)."""
    return {
        "type": event_type,
        "message": {
            "id": msg.id,
            "sender_id": msg.sender_id,
            "content": None if msg.deleted_at else msg.content,
            "created_at": msg.created_at.isoformat(),
            "read_at": msg.read_at.isoformat() if msg.read_at else None,
            "deleted_at": msg.deleted_at.isoformat() if msg.deleted_at else None,
        },
    }


def _mark_conversation_read(
    match_id: int, reader_id: int, now: datetime, db: Session
) -> int | None:
    """Mark every unread incoming message in *match_id* as read at *now*.

    Returns the id of the newest row it marked (the read high-water mark), or
    None if there was nothing unread.

    One UPDATE for the whole conversation rather than a Python loop over a page:
    cheaper than the per-row version it replaces, and it makes "opened the chat"
    mean "read the conversation", which is what the badge already claims.
    """
    unread = [
        Message.match_id == match_id,
        Message.sender_id != reader_id,
        Message.read_at.is_(None),
    ]
    # Taken *before* the UPDATE, while the rows are still identifiable as unread.
    high_water = db.query(func.max(Message.id)).filter(*unread).scalar()
    if high_water is None:
        return None
    db.query(Message).filter(*unread).update(
        {Message.read_at: now}, synchronize_session=False
    )
    db.commit()
    return int(high_water)


def _require_match_member(match_id: int, user_id: int, db: Session) -> Match:
    """Return the Match or raise 404/403."""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found.")
    if user_id not in (match.user1_id, match.user2_id):
        raise HTTPException(status_code=403, detail="Not part of this match.")
    return match


def _to_out(msg: Message, current_user_id: int) -> MessageOut:
    return MessageOut(
        id=msg.id,
        sender_id=msg.sender_id,
        # Hide content for soft-deleted messages so neither party sees the original text
        content=None if msg.deleted_at else msg.content,
        created_at=msg.created_at,
        read_at=msg.read_at,
        deleted_at=msg.deleted_at,
        is_mine=(msg.sender_id == current_user_id),
    )


@router.websocket("/{match_id}/ws")
async def chat_websocket(
    match_id: int,
    ws: WebSocket,
) -> None:
    """
    Persistent WebSocket connection for real-time chat delivery.

    The client authenticates by passing the JWT as a query parameter:
        ws://host/api/matches/{id}/ws?token=<JWT>

    After authentication the server keeps the connection open and pushes
    events of the form:
        {"type": "new_message",    "message": {...MessageOut fields...}}
        {"type": "message_deleted","message": {...MessageOut fields...}}

    is_mine is computed per-recipient server-side so each client receives
    the correct value without any client-side state lookup.
    """
    # ── Authenticate via httpOnly cookie (web) or ?token= query param (mobile) ─
    token = ws.cookies.get("access_token") or ws.query_params.get("token")
    if not token:
        await ws.accept()
        await ws.close(code=4001)
        return
    db = SessionLocal()
    try:
        user_id = decode_access_token(token)
        user = db.get(User, user_id)
        if not user:
            raise JWTError("user not found")
    except JWTError:
        await ws.accept()
        await ws.close(code=4001)
        return
    finally:
        db.close()

    # ── Authorise ─────────────────────────────────────────────────────────────
    db = SessionLocal()
    try:
        match = db.get(Match, match_id)
        if not match or user_id not in (match.user1_id, match.user2_id):
            await ws.accept()
            await ws.close(code=4003)
            return
    finally:
        db.close()

    # ── Enforce email verification (GAPS #25) ────────────────────────────────
    # Rejected at connect rather than per-frame: the socket exists to carry live
    # chat, and the REST send path is gated too, so admitting a connection that
    # may not send would only defer the same refusal. Read access to the
    # conversation is unaffected -- history is a plain REST GET, deliberately
    # ungated, so the user can still see what they are about to lose.
    #
    # Deliberately after the match-authorisation check above, so probing a match
    # you are not part of still yields 4003 regardless of verification state.
    #
    # `user` is detached here (its session is closed) but its columns were
    # already loaded, so reading them is safe -- the same reason `user.name`
    # below works.
    verification_error = email_verification_error(user)
    if verification_error is not None:
        await ws.accept()
        # Send the structured payload before closing, so the client can branch on
        # the same `code` the REST routes return rather than having to map a bare
        # close code. Best-effort: if the peer is already gone, still close.
        try:
            await ws.send_json({"type": "error", "error": verification_error})
        except Exception:
            pass
        await ws.close(code=WS_EMAIL_VERIFICATION_REQUIRED)
        logger.info(
            "ws: refused unverified user %d on match %d (grace expired)", user_id, match_id
        )
        return

    # ── Register and handle incoming events ──────────────────────────────────
    await manager.connect(match_id, user_id, user.name, ws)
    typing_budget = _TypingBudget()
    try:
        while True:
            try:
                raw = await ws.receive_text()
            except WebSocketDisconnect:
                break
            try:
                data = json.loads(raw)
                if data.get("type") == "typing":
                    # Rate limited: an unbounded typing stream now fans out to
                    # every replica serving the match, so spam amplifies.
                    # Excess frames are dropped silently rather than closing the
                    # socket — the event is cosmetic and the client cannot tell.
                    if typing_budget.allow():
                        await manager.broadcast_typing(match_id, user_id)
                    else:
                        logger.debug(
                            "ws: dropping typing flood from user %d on match %d",
                            user_id, match_id,
                        )
            except Exception:
                pass  # malformed input — keep the connection alive
    finally:
        await manager.disconnect(match_id, ws)


@router.delete("/{match_id}", status_code=204)
def unmatch(
    match_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Remove a match and its conversation without blocking either user.

    Deletes the match (messages cascade), then removes both swipe records so
    both parties can rediscover each other organically.
    """
    match = _require_match_member(match_id, current_user.id, db)
    other_id = match.user2_id if match.user1_id == current_user.id else match.user1_id

    db.delete(match)  # messages cascade via FK

    # Remove both swipes so each user reappears in the other's discover queue
    db.query(Swipe).filter(
        ((Swipe.user_id == current_user.id) & (Swipe.target_user_id == other_id)) |
        ((Swipe.user_id == other_id) & (Swipe.target_user_id == current_user.id))
    ).delete(synchronize_session=False)

    db.commit()
    logger.info("chat: user %d unmatched match %d", current_user.id, match_id)


@router.delete("/{match_id}/messages/{message_id}", response_model=MessageOut, status_code=200)
def delete_message(
    match_id: int,
    message_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageOut:
    """Soft-delete a sent message. Only the original sender may delete it."""
    _require_match_member(match_id, current_user.id, db)

    msg = db.query(Message).filter(
        Message.id == message_id,
        Message.match_id == match_id,
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found.")
    if msg.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot delete a message you did not send.")
    if msg.deleted_at:
        return _to_out(msg, current_user.id)  # idempotent

    msg.deleted_at = datetime.now(UTC)
    db.commit()
    db.refresh(msg)
    logger.info("chat: user %d soft-deleted message %d", current_user.id, message_id)
    background_tasks.add_task(manager.broadcast, match_id, _msg_event("message_deleted", msg))
    return _to_out(msg, current_user.id)


@router.get("/{match_id}/messages", response_model=MessagePageOut)
def get_messages(
    match_id: int,
    before_id: int | None = Query(default=None, description="Cursor: return messages with id < before_id"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessagePageOut:
    """
    Fetch paginated conversation history and mark incoming messages as read.

    Returns the _PAGE_SIZE most recent messages by default.  Pass
    ``before_id`` to page backward (load older messages).  The response
    includes ``has_more`` so the client knows whether a previous page exists.
    """
    _require_match_member(match_id, current_user.id, db)

    # Opening the chat marks the *conversation* read, not just the page that
    # happens to fit in one response. Both unread counters — `unread_count` here
    # and the correlated subquery in `list_matches` — count every unread row in
    # the match with no limit, while this endpoint is the only thing that ever
    # writes `read_at`. Marking one 50-row page therefore left a match with 60
    # unread stuck at a badge of 10 forever: the user has read everything the UI
    # will show them and there is no way left to clear it. Reachable in ordinary
    # use — the `desperate` seed archetype chases after two hours of silence and
    # there are fifty of them.
    #
    # Paging backward (`before_id`) is a different act: it loads history the user
    # is scrolling into, so it still marks only what it returns.
    #
    # Ordered before the page fetch so the returned rows carry the new `read_at`
    # without a second round trip.
    now = datetime.now(UTC)
    if before_id is None:
        _mark_conversation_read(match_id, current_user.id, now, db)

    q = db.query(Message).filter(Message.match_id == match_id)
    if before_id is not None:
        q = q.filter(Message.id < before_id)

    # Fetch newest-first so LIMIT gives us the _PAGE_SIZE most recent rows;
    # then reverse to restore chronological (ascending) display order.
    raw = q.order_by(Message.id.desc()).limit(_PAGE_SIZE + 1).all()
    has_more = len(raw) > _PAGE_SIZE
    if has_more:
        raw = raw[:_PAGE_SIZE]
    messages = list(reversed(raw))

    if before_id is not None:
        marked = False
        for msg in messages:
            if msg.sender_id != current_user.id and msg.read_at is None:
                msg.read_at = now
                marked = True
        if marked:
            db.commit()

    return MessagePageOut(
        messages=[_to_out(msg, current_user.id) for msg in messages],
        has_more=has_more,
    )


@router.post("/{match_id}/messages", response_model=MessageOut, status_code=201)
def send_message(
    match_id: int,
    body: MessageIn,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_verified_email),
    db: Session = Depends(get_db),
) -> MessageOut:
    """Send a message to a match. Rate-limited to 10 per 60 seconds.

    Gated on email verification (GAPS #25): sending is outbound and reaches a
    real person. Reading history via `GET /{match_id}/messages` stays open.
    """
    match = _require_match_member(match_id, current_user.id, db)

    # Counted in Redis rather than with a DB COUNT over the messages table, so
    # the limit costs one INCR instead of an index scan that grows with the
    # conversation. Fails open on Redis errors, like the login limiter.
    limited, retry_after = check_rate_limit(
        _message_rate_limit_key(current_user.id, match_id),
        _RATE_LIMIT_MAX,
        _RATE_LIMIT_WINDOW_S,
    )
    if limited:
        raise HTTPException(
            status_code=429,
            detail="Sending too fast. Please wait a moment.",
            headers={"Retry-After": str(retry_after)},
        )

    msg = Message(
        match_id=match_id,
        sender_id=current_user.id,
        content=body.content,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    logger.info("chat: user=%d sent message to match=%d", current_user.id, match_id)

    # Push to open WebSocket connections (real-time delivery)
    background_tasks.add_task(manager.broadcast, match_id, _msg_event("new_message", msg))

    # Email notification for offline recipients (Celery task handles all skip logic)
    recipient_id = match.user2_id if match.user1_id == current_user.id else match.user1_id
    enqueue(notify_new_message, match_id, recipient_id, current_user.id)

    return _to_out(msg, current_user.id)


@router.get("/{match_id}/unread-count", response_model=UnreadCountOut)
def unread_count(
    match_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UnreadCountOut:
    """Count unread messages sent by the other user."""
    _require_match_member(match_id, current_user.id, db)

    count = (
        db.query(Message)
        .filter(
            Message.match_id == match_id,
            Message.sender_id != current_user.id,
            Message.read_at.is_(None),
        )
        .count()
    )
    return UnreadCountOut(count=count)
