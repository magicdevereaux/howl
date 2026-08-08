"""
Redis pub/sub fan-out for real-time chat across web replicas.

Why this exists
---------------
A WebSocket lives in the process that accepted it. With more than one web
replica (Railway replicas, multiple Gunicorn workers) a message sent by a user
whose request landed on replica A must still reach the recipient's socket on
replica B. This module is the transport that carries chat events between
replicas; `app.api.chat.ConnectionManager` owns the local sockets and uses it.

Shape
-----
One channel per match: ``howl:chat:match:<match_id>``. A replica subscribes to
a match channel when its *first* local socket for that match connects, and
unsubscribes when the last one disconnects, so a replica only pays for the
conversations it is actually serving.

Every envelope carries the publisher's ``origin`` — a uuid4 generated once per
process. The reader drops envelopes stamped with its own origin because the
publishing replica already delivered to its own sockets synchronously, before
publishing. Without that filter every local socket would receive each event
twice (the classic publish-then-receive-your-own-message bug).

There is exactly one reader task per process. It owns the pub/sub connection
and is supervised: any error tears the connection down, sleeps with capped
exponential backoff, reopens it, and re-subscribes to the whole desired
channel set. Every loop iteration also reconciles the live subscription set
against the desired set, so a subscribe that was issued while Redis was down
is repaired within one read timeout rather than silently going deaf. A
``health_check_interval`` on the connection makes redis-py PING the socket
periodically, which converts a half-open TCP connection into a raised error
the supervisor can act on.

Failure policy: FAIL OPEN
-------------------------
If Redis is unreachable, `publish` logs and returns False and `subscribe`
records the channel without raising. Delivery degrades to **local-only** —
which is exactly the behaviour of the single-replica manager this replaces, so
a Redis outage costs cross-replica fan-out, not chat itself. This deliberately
matches the precedent in `app/services/rate_limit.py`, which also fails open
on Redis errors by design.

Delivery guarantee: none, and that is intentional
-------------------------------------------------
Redis pub/sub is fire-and-forget. An event published while a replica is
momentarily disconnected is dropped, with no replay. That is acceptable
because a message row is committed to Postgres *before* it is broadcast (see
the send path in `app/api/chat.py`): the socket is the optimistic layer and
``GET /api/matches/{id}/messages`` is the source of truth. A dropped socket
event costs latency until the client refetches, never the message itself.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable

from redis import RedisError
from redis import asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

_MATCH_PREFIX = "howl:chat:match:"
_IDLE_PREFIX = "howl:chat:idle:"

_READ_TIMEOUT_S = 1.0        # how long one blocking read parks before looping
_BACKOFF_MIN_S = 0.5
_BACKOFF_MAX_S = 10.0
_HEALTH_CHECK_INTERVAL_S = 30

# (match_id, payload) -> awaitable. Payload is whatever the publisher passed.
EventHandler = Callable[[int, dict], Awaitable[None]]


def channel_for(match_id: int) -> str:
    return f"{_MATCH_PREFIX}{match_id}"


def match_id_from_channel(channel: str) -> int | None:
    if not channel.startswith(_MATCH_PREFIX):
        return None
    try:
        return int(channel[len(_MATCH_PREFIX):])
    except ValueError:
        return None


class ChatPubSub:
    """Cross-replica transport for chat events. See the module docstring.

    Lazily started: nothing connects to Redis until the first `subscribe` or
    `publish` call, so a process that never serves a chat socket never opens a
    pub/sub connection. There is no application startup hook to hang this off.
    """

    def __init__(
        self,
        handler: EventHandler | None = None,
        redis_url: str | None = None,
    ) -> None:
        self.origin_id = uuid.uuid4().hex
        self._handler = handler
        self._redis_url = redis_url or settings.redis_url

        # The desired channel set is the source of truth; the reader reconciles
        # the live connection against it. The idle channel is always subscribed
        # so the connection stays in subscriber mode (and therefore readable)
        # even when no match channel is wanted.
        self._idle_channel = f"{_IDLE_PREFIX}{self.origin_id}"
        self._desired: set[str] = set()

        self._reader_client: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._publisher: aioredis.Redis | None = None
        self._reader: asyncio.Task[None] | None = None
        self._send_lock = asyncio.Lock()
        self._closing = False
        self._connected = False

        # The loop every cached object above belongs to.  A redis-py asyncio
        # client, an asyncio.Task and an asyncio.Lock are all bound to the loop
        # that created them and are unusable from another one.
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── event-loop affinity ──────────────────────────────────────────────────

    def _reset_if_loop_changed(self) -> None:
        """Drop cached connections that belong to a different event loop.

        This manager is a process-wide singleton, so under a normal deployment
        it sees exactly one loop for its whole life and this is a no-op.  It
        matters when a process runs several loops in sequence — most visibly the
        test suite, where each test may get a fresh loop and a client cached on
        a closed one raises "Event loop is closed" on first use.

        Nothing is awaited here on purpose: the previous loop is already gone,
        so its sockets cannot be closed gracefully and there is no coroutine to
        await them in.  The references are dropped and the OS reclaims the fds.
        """
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            return  # called outside a loop — nothing to reconcile

        if self._loop is running:
            return

        if self._loop is not None:
            logger.debug("chat pubsub: event loop changed; rebuilding redis clients")
            if self._reader is not None and not self._reader.done():
                self._reader.cancel()

        self._loop = running
        self._reader_client = None
        self._pubsub = None
        self._publisher = None
        self._reader = None
        self._send_lock = asyncio.Lock()
        self._connected = False

    # ── wiring ───────────────────────────────────────────────────────────────

    def set_handler(self, handler: EventHandler) -> None:
        self._handler = handler

    @property
    def connected(self) -> bool:
        """True when the reader currently holds a live pub/sub connection."""
        return self._connected

    # ── subscription management ──────────────────────────────────────────────

    async def subscribe(self, match_id: int) -> None:
        """Start receiving events for *match_id* on this replica.

        Best-effort: if Redis is down the channel is still recorded and the
        reader subscribes to it on reconnect.
        """
        self._reset_if_loop_changed()
        channel = channel_for(match_id)
        if channel in self._desired:
            return
        self._desired.add(channel)
        self._ensure_reader()
        await self._send(lambda ps: ps.subscribe(channel), f"subscribe {channel}")

    async def unsubscribe(self, match_id: int) -> None:
        """Stop receiving events for *match_id* on this replica."""
        self._reset_if_loop_changed()
        channel = channel_for(match_id)
        if channel not in self._desired:
            return
        self._desired.discard(channel)
        await self._send(lambda ps: ps.unsubscribe(channel), f"unsubscribe {channel}")

    async def _send(self, command: Callable[..., Awaitable], what: str) -> None:
        """Issue a pub/sub command, swallowing failures for the reader to repair."""
        pubsub = self._pubsub
        if pubsub is None:
            return  # not connected yet — the reader subscribes from _desired
        try:
            # Serialise writes so two coroutines can't interleave commands on
            # the one connection. The reader's blocking read is not held under
            # this lock: sends and reads are independent directions.
            async with self._send_lock:
                await command(pubsub)
        except (RedisError, OSError) as exc:
            logger.warning("chat pubsub: %s failed (%s); reader will reconcile", what, exc)

    # ── publishing ───────────────────────────────────────────────────────────

    async def publish(self, match_id: int, payload: dict) -> bool:
        """Fan *payload* out to the other replicas serving *match_id*.

        Returns True if Redis accepted the publish. Never raises: on failure
        the caller keeps whatever it already delivered locally (fail open).
        """
        self._reset_if_loop_changed()
        client = self._get_publisher()
        if client is None:
            return False
        envelope = json.dumps({"origin": self.origin_id, "payload": payload})
        try:
            await client.publish(channel_for(match_id), envelope)
            return True
        except (RedisError, OSError) as exc:
            logger.warning(
                "chat pubsub: publish for match %d failed (%s); local delivery only",
                match_id, exc,
            )
            return False

    def _get_publisher(self) -> aioredis.Redis | None:
        """Publishing uses its own client so a reader reconnect can't disturb it."""
        if self._publisher is None and not self._closing:
            try:
                self._publisher = aioredis.from_url(
                    self._redis_url,
                    decode_responses=True,
                    health_check_interval=_HEALTH_CHECK_INTERVAL_S,
                )
            except Exception as exc:  # bad URL, missing driver — never fatal
                logger.error("chat pubsub: could not create publisher client: %s", exc)
        return self._publisher

    # ── reader ───────────────────────────────────────────────────────────────

    def _ensure_reader(self) -> None:
        if self._closing:
            return
        if self._reader is None or self._reader.done():
            self._reader = asyncio.create_task(self._reader_loop())

    async def _reader_loop(self) -> None:
        """Supervise one pub/sub connection for the lifetime of the process."""
        backoff = _BACKOFF_MIN_S
        try:
            while not self._closing:
                try:
                    pubsub = await self._open()
                    backoff = _BACKOFF_MIN_S
                    while not self._closing:
                        await self._reconcile()
                        message = await pubsub.get_message(timeout=_READ_TIMEOUT_S)
                        if message is None:
                            continue
                        await self._dispatch(message)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._connected = False
                    logger.warning(
                        "chat pubsub: reader connection lost (%s); retrying in %.1fs",
                        exc, backoff,
                    )
                    await self._close_reader_connection()
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _BACKOFF_MAX_S)
        finally:
            self._connected = False
            await self._close_reader_connection()

    async def _open(self) -> "aioredis.client.PubSub":
        await self._close_reader_connection()
        self._reader_client = aioredis.from_url(
            self._redis_url,
            decode_responses=True,
            health_check_interval=_HEALTH_CHECK_INTERVAL_S,
        )
        pubsub = self._reader_client.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(*sorted(self._desired | {self._idle_channel}))
        self._pubsub = pubsub
        self._connected = True
        logger.info(
            "chat pubsub: reader connected (origin=%s, channels=%d)",
            self.origin_id, len(self._desired),
        )
        return pubsub

    async def _reconcile(self) -> None:
        """Repair drift between the live subscription set and the desired set.

        Runs every loop iteration. This is what stops the replica going quietly
        deaf after a `subscribe` that failed while Redis was unavailable.
        """
        pubsub = self._pubsub
        if pubsub is None:
            return
        wanted = self._desired | {self._idle_channel}
        live = set(pubsub.channels)
        missing = wanted - live
        extra = live - wanted
        if missing:
            async with self._send_lock:
                await pubsub.subscribe(*sorted(missing))
        if extra:
            async with self._send_lock:
                await pubsub.unsubscribe(*sorted(extra))

    async def _dispatch(self, message: dict) -> None:
        """Decode one pub/sub message and hand it to the handler."""
        channel = message.get("channel")
        match_id = match_id_from_channel(channel) if isinstance(channel, str) else None
        if match_id is None:
            return  # idle channel or an unrecognised name
        try:
            envelope = json.loads(message.get("data") or "{}")
        except (TypeError, ValueError):
            logger.warning("chat pubsub: dropping malformed envelope on %s", channel)
            return
        if not isinstance(envelope, dict):
            return
        if envelope.get("origin") == self.origin_id:
            return  # our own publish — already delivered locally
        payload = envelope.get("payload")
        if not isinstance(payload, dict) or self._handler is None:
            return
        try:
            await self._handler(match_id, payload)
        except Exception:
            # A bad handler must not kill the reader; that would look like a
            # working deployment that has silently stopped delivering.
            logger.exception("chat pubsub: handler failed for match %d", match_id)

    # ── teardown ─────────────────────────────────────────────────────────────

    async def _close_reader_connection(self) -> None:
        pubsub, self._pubsub = self._pubsub, None
        client, self._reader_client = self._reader_client, None
        for closeable in (pubsub, client):
            if closeable is None:
                continue
            try:
                await closeable.aclose()
            except Exception:  # already broken — nothing useful to do
                pass

    async def aclose(self) -> None:
        """Stop the reader and release every Redis connection."""
        self._closing = True
        reader, self._reader = self._reader, None
        if reader is not None and not reader.done():
            reader.cancel()
            try:
                await reader
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("chat pubsub: reader raised during shutdown", exc_info=True)
        await self._close_reader_connection()
        publisher, self._publisher = self._publisher, None
        if publisher is not None:
            try:
                await publisher.aclose()
            except Exception:
                pass
        self._desired.clear()
