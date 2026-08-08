"""Cross-replica chat fan-out (GAPS #17).

`ConnectionManager` was an in-process dict, so a second web replica silently
dropped delivery for users whose socket lived in the other process. These tests
drive **two independent `ChatPubSub` instances** — standing in for two replicas —
against one in-memory broker, and assert the properties that make the fan-out
trustworthy rather than merely present:

  * an event published by replica A reaches a handler on replica B
  * replica A does *not* receive its own publish back (the publish-then-
    receive-your-own-message double-delivery bug)
  * a replica only receives events for matches it subscribed to
  * Redis being unreachable degrades to local-only delivery instead of raising
  * a dropped connection reconnects and re-subscribes without going deaf
  * a handler that raises does not kill the reader

The broker below implements only the slice of the redis-py asyncio API that
`ChatPubSub` actually uses: `publish`, `pubsub()`, `subscribe`, `unsubscribe`,
`channels`, `get_message(timeout=...)` and `aclose`.
"""

import asyncio
import json

import pytest

from app.services.pubsub import ChatPubSub, channel_for, match_id_from_channel

#: real_pubsub opts this module out of the conftest fixture that neuters
#: ChatPubSub for every other test — here the fan-out *is* the thing under test.
pytestmark = [pytest.mark.anyio, pytest.mark.real_pubsub]


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------------------
# In-memory stand-in for Redis pub/sub
# ---------------------------------------------------------------------------

class Broker:
    """Shared message bus. One instance is 'the Redis server'."""

    def __init__(self) -> None:
        self.subscribers: list[FakePubSub] = []
        self.published: list[tuple[str, str]] = []
        self.fail = False          # when True every operation raises
        self.connect_count = 0

    def publish(self, channel: str, data: str) -> int:
        self.published.append((channel, data))
        delivered = 0
        for ps in list(self.subscribers):
            if channel in ps.channels:
                ps.inbox.put_nowait({"channel": channel, "data": data})
                delivered += 1
        return delivered

    def drop_all_connections(self) -> None:
        """Simulate the Redis server dropping every live pub/sub connection."""
        for ps in list(self.subscribers):
            ps.broken = True


class FakePubSub:
    def __init__(self, broker: Broker) -> None:
        self.broker = broker
        self.channels: dict[str, None] = {}
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.broken = False
        broker.subscribers.append(self)

    def _check(self) -> None:
        if self.broken or self.broker.fail:
            raise ConnectionError("fake redis: connection lost")

    async def subscribe(self, *channels: str) -> None:
        self._check()
        for c in channels:
            self.channels[c] = None

    async def unsubscribe(self, *channels: str) -> None:
        self._check()
        for c in channels:
            self.channels.pop(c, None)

    async def get_message(self, timeout: float = 0.0):
        self._check()
        try:
            return await asyncio.wait_for(self.inbox.get(), timeout=timeout)
        except TimeoutError:
            return None

    async def aclose(self) -> None:
        if self in self.broker.subscribers:
            self.broker.subscribers.remove(self)


class FakeRedis:
    def __init__(self, broker: Broker) -> None:
        self.broker = broker
        broker.connect_count += 1

    def pubsub(self, ignore_subscribe_messages: bool = False) -> FakePubSub:
        return FakePubSub(self.broker)

    async def publish(self, channel: str, data: str) -> int:
        if self.broker.fail:
            raise ConnectionError("fake redis: unreachable")
        return self.broker.publish(channel, data)

    async def aclose(self) -> None:
        return None


@pytest.fixture
def broker(monkeypatch) -> Broker:
    b = Broker()
    monkeypatch.setattr(
        "app.services.pubsub.aioredis.from_url",
        lambda *a, **kw: FakeRedis(b),
    )
    return b


class Replica:
    """A ChatPubSub plus a record of what its handler received."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.received: list[tuple[int, dict]] = []
        self.raise_on_handle = False
        self.pubsub = ChatPubSub(handler=self._handle, redis_url="redis://fake/0")

    async def _handle(self, match_id: int, payload: dict) -> None:
        if self.raise_on_handle:
            raise RuntimeError("handler exploded")
        self.received.append((match_id, payload))


async def _settle(predicate, timeout: float = 2.0) -> bool:
    """Poll until *predicate* holds. Beats a fixed sleep on a busy CI box."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


# ---------------------------------------------------------------------------
# The core property: delivery crosses replicas
# ---------------------------------------------------------------------------

async def test_event_published_on_one_replica_reaches_the_other(broker):
    a, b = Replica("a"), Replica("b")
    try:
        await a.pubsub.subscribe(7)
        await b.pubsub.subscribe(7)
        assert await _settle(lambda: b.pubsub.connected)

        await a.pubsub.publish(7, {"kind": "message", "event": {"content": "hi"}})

        assert await _settle(lambda: b.received), "the other replica never got the event"
        match_id, payload = b.received[0]
        assert match_id == 7
        assert payload["event"]["content"] == "hi"
    finally:
        await a.pubsub.aclose()
        await b.pubsub.aclose()


async def test_publisher_does_not_receive_its_own_event(broker):
    """The publishing replica already delivered locally; a copy back is a dupe."""
    a, b = Replica("a"), Replica("b")
    try:
        await a.pubsub.subscribe(7)
        await b.pubsub.subscribe(7)
        assert await _settle(lambda: a.pubsub.connected and b.pubsub.connected)

        await a.pubsub.publish(7, {"kind": "message", "event": {"content": "mine"}})
        assert await _settle(lambda: b.received)

        # Give the reader ample opportunity to hand it back before asserting.
        await asyncio.sleep(0.1)
        assert a.received == [], "replica echoed its own publish back to itself"
    finally:
        await a.pubsub.aclose()
        await b.pubsub.aclose()


async def test_replica_ignores_matches_it_did_not_subscribe_to(broker):
    a, b = Replica("a"), Replica("b")
    try:
        await a.pubsub.subscribe(1)
        await b.pubsub.subscribe(2)          # different conversation
        assert await _settle(lambda: b.pubsub.connected)

        await a.pubsub.publish(1, {"kind": "message", "event": {}})
        await asyncio.sleep(0.15)

        assert b.received == [], "a replica received an unsubscribed match's traffic"
    finally:
        await a.pubsub.aclose()
        await b.pubsub.aclose()


async def test_unsubscribe_stops_delivery(broker):
    a, b = Replica("a"), Replica("b")
    try:
        await a.pubsub.subscribe(3)
        await b.pubsub.subscribe(3)
        assert await _settle(lambda: b.pubsub.connected)

        await a.pubsub.publish(3, {"kind": "message", "event": {"n": 1}})
        assert await _settle(lambda: len(b.received) == 1)

        await b.pubsub.unsubscribe(3)
        await asyncio.sleep(0.05)
        await a.pubsub.publish(3, {"kind": "message", "event": {"n": 2}})
        await asyncio.sleep(0.15)

        assert len(b.received) == 1, "events kept arriving after unsubscribe"
    finally:
        await a.pubsub.aclose()
        await b.pubsub.aclose()


# ---------------------------------------------------------------------------
# Failure behaviour: fail open to local-only delivery
# ---------------------------------------------------------------------------

async def test_publish_with_redis_down_returns_false_and_does_not_raise(broker):
    """Fail open. Chat keeps working single-replica; only fan-out is lost."""
    a = Replica("a")
    broker.fail = True
    try:
        assert await a.pubsub.publish(9, {"kind": "message", "event": {}}) is False
    finally:
        broker.fail = False
        await a.pubsub.aclose()


async def test_subscribe_with_redis_down_does_not_raise(broker):
    """A socket must still connect when Redis is unavailable."""
    a = Replica("a")
    broker.fail = True
    try:
        await a.pubsub.subscribe(9)          # must not raise
        assert a.pubsub.connected is False
    finally:
        broker.fail = False
        await a.pubsub.aclose()


async def test_reader_reconnects_and_resubscribes_after_a_dropped_connection(broker):
    """A quietly-dead pub/sub connection is worse than no fan-out at all."""
    a, b = Replica("a"), Replica("b")
    try:
        await a.pubsub.subscribe(5)
        await b.pubsub.subscribe(5)
        assert await _settle(lambda: b.pubsub.connected)

        await a.pubsub.publish(5, {"kind": "message", "event": {"n": 1}})
        assert await _settle(lambda: len(b.received) == 1)

        # The server drops every connection underneath both replicas.
        broker.drop_all_connections()
        assert await _settle(lambda: not b.pubsub.connected, timeout=3.0)

        # ...and the supervisor brings it back, re-subscribed to match 5.
        assert await _settle(lambda: b.pubsub.connected, timeout=5.0), "reader never recovered"

        await a.pubsub.publish(5, {"kind": "message", "event": {"n": 2}})
        assert await _settle(lambda: len(b.received) == 2, timeout=3.0), (
            "reader reconnected but stopped delivering — it went deaf"
        )
    finally:
        await a.pubsub.aclose()
        await b.pubsub.aclose()


async def test_subscribe_issued_while_down_is_repaired_on_reconnect(broker):
    """The desired-channel set is the source of truth, not the live connection."""
    a, b = Replica("a"), Replica("b")
    try:
        await a.pubsub.subscribe(11)
        broker.fail = True
        await b.pubsub.subscribe(11)         # recorded, but cannot be sent
        await asyncio.sleep(0.1)
        broker.fail = False

        assert await _settle(lambda: b.pubsub.connected, timeout=5.0)
        await asyncio.sleep(0.1)             # let _reconcile run
        await a.pubsub.publish(11, {"kind": "message", "event": {}})

        assert await _settle(lambda: b.received, timeout=3.0), (
            "a subscribe made during an outage was never repaired"
        )
    finally:
        broker.fail = False
        await a.pubsub.aclose()
        await b.pubsub.aclose()


# ---------------------------------------------------------------------------
# Robustness of the reader loop
# ---------------------------------------------------------------------------

async def test_handler_exception_does_not_kill_the_reader(broker):
    """A crashed reader looks like a healthy deployment that delivers nothing."""
    a, b = Replica("a"), Replica("b")
    try:
        await a.pubsub.subscribe(4)
        await b.pubsub.subscribe(4)
        assert await _settle(lambda: b.pubsub.connected)

        b.raise_on_handle = True
        await a.pubsub.publish(4, {"kind": "message", "event": {"n": 1}})
        await asyncio.sleep(0.2)

        b.raise_on_handle = False
        await a.pubsub.publish(4, {"kind": "message", "event": {"n": 2}})

        assert await _settle(lambda: len(b.received) == 1, timeout=3.0), (
            "the reader died on a handler exception"
        )
        assert b.received[0][1]["event"]["n"] == 2
    finally:
        await a.pubsub.aclose()
        await b.pubsub.aclose()


async def test_malformed_envelope_is_dropped_not_fatal(broker):
    a = Replica("a")
    try:
        await a.pubsub.subscribe(6)
        assert await _settle(lambda: a.pubsub.connected)

        broker.publish(channel_for(6), "this is not json")
        broker.publish(channel_for(6), json.dumps(["not", "a", "dict"]))
        await asyncio.sleep(0.15)

        assert a.received == []
        assert a.pubsub.connected, "a malformed message tore down the connection"

        broker.publish(
            channel_for(6),
            json.dumps({"origin": "someone-else", "payload": {"kind": "message"}}),
        )
        assert await _settle(lambda: len(a.received) == 1), "reader stopped after bad input"
    finally:
        await a.pubsub.aclose()


# ---------------------------------------------------------------------------
# Channel naming
# ---------------------------------------------------------------------------

def test_channel_round_trips():
    assert match_id_from_channel(channel_for(42)) == 42


@pytest.mark.parametrize("bad", ["howl:chat:match:abc", "howl:chat:idle:x", "nonsense", ""])
def test_non_match_channels_yield_no_match_id(bad):
    assert match_id_from_channel(bad) is None


async def test_two_replicas_have_distinct_origins(broker):
    a, b = Replica("a"), Replica("b")
    try:
        assert a.pubsub.origin_id != b.pubsub.origin_id
    finally:
        await a.pubsub.aclose()
        await b.pubsub.aclose()
