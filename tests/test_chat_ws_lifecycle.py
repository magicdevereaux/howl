"""WebSocket lifecycle and out-of-band events: drops, caps, receipts, revocation.

These cover the chat-socket defects in GAPS round two that are about the
*connection* and the events carried over it rather than the message rows:

  * #46 — a send timeout unregistered a socket without closing it, so the client
    kept a connection that looked healthy and received nothing ever again.
  * #49 — read receipts were written to the database and broadcast nowhere, so
    the sender's ✓ never became ✓✓ until their client happened to refetch.
  * #59 — nothing capped how many sockets one user could open to one match,
    which multiplied the per-connection typing budget by the socket count.
  * #60 — nothing could evict a live socket, so unmatching or blocking left the
    other party's socket open on a conversation that no longer exists.

Everything here drives the real handler through TestClient's WebSocket support;
`_ws_db` points the handler's own `SessionLocal()` at the test session, the same
trick test_chat.py uses.
"""

import asyncio
import threading

import pytest
import starlette.websockets
from starlette.websockets import WebSocketDisconnect

from app.api.chat import _TYPING_LIMIT, ConnectionManager, manager
from app.models.match import Match
from app.models.message import Message
from app.models.user import AvatarStatus, User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(db, *, email: str, **kwargs) -> User:
    kwargs.setdefault("animal", "wolf")
    user = User(
        email=email,
        password_hash=hash_password("testpass1"),
        avatar_status=AvatarStatus.ready,
        **kwargs,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_match(db, a: User, b: User) -> Match:
    m = Match(user1_id=min(a.id, b.id), user2_id=max(a.id, b.id))
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _cookie(user: User) -> dict[str, str]:
    return {"Cookie": f"access_token={create_access_token(user.id)}"}


def _ws_url(match_id: int) -> str:
    return f"/api/matches/{match_id}/ws"


_RECEIVE_TIMEOUT_S = 5.0


def _recv(ws, timeout: float | None = None) -> tuple[str, object]:
    """Read one thing from *ws* with a deadline.

    Returns ``("frame", payload)``, ``("close", code)`` or ``("timeout", None)``.

    TestClient's `receive_json` has no timeout, and the failure these tests
    guard against is exactly "the server says nothing, ever" — a bare
    `receive_json()` would therefore hang the entire suite with no output
    instead of failing one test. The reader runs on a daemon thread so that a
    timed-out read cannot hold the process open either.
    """
    out: dict[str, object] = {}

    def _read() -> None:
        try:
            out["frame"] = ws.receive_json()
        except WebSocketDisconnect as exc:
            out["close"] = exc.code
        except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
            out["error"] = exc

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()
    reader.join(_RECEIVE_TIMEOUT_S if timeout is None else timeout)
    if "error" in out:
        raise out["error"]  # type: ignore[misc]
    if "close" in out:
        return "close", out["close"]
    if "frame" in out:
        return "frame", out["frame"]
    return "timeout", None


@pytest.fixture()
def _ws_db(db, monkeypatch):
    """Wire the WebSocket handler's SessionLocal() to the test SQLite session."""
    monkeypatch.setattr("app.api.chat.SessionLocal", lambda: db)


@pytest.fixture(autouse=True)
def _clean_manager():
    """The ConnectionManager is a module-level singleton; don't leak sockets."""
    yield
    manager._conns.clear()
    manager._typing_budgets.clear()


# ---------------------------------------------------------------------------
# #46 — a socket the server gives up writing to must be told
# ---------------------------------------------------------------------------


def test_send_timeout_closes_the_socket(client, db, test_user, auth_headers, _ws_db, monkeypatch):
    """A timed-out send must produce a close frame, not a silent black hole.

    Before the fix the socket was popped from the registry and left open at the
    transport layer: the client's onclose never fired, its reconnect never ran,
    and it received neither local nor cross-replica deliveries from then on.
    """
    other = _make_user(db, email="ws_timeout@howl.app")
    m = _make_match(db, test_user, other)

    async def _never_returns(self, data):  # noqa: ANN001 - patched method
        await asyncio.sleep(3600)

    # Only the *server* side is a starlette WebSocket; TestClient's end is a
    # WebSocketTestSession, so this makes the server's write hang and nothing else.
    monkeypatch.setattr(starlette.websockets.WebSocket, "send_json", _never_returns)
    monkeypatch.setattr("app.api.chat._SEND_TIMEOUT_S", 0.05)

    with client.websocket_connect(_ws_url(m.id), headers=_cookie(test_user)) as ws:
        client.post(
            f"/api/matches/{m.id}/messages",
            headers=auth_headers,
            json={"content": "you will never see this"},
        )
        got = _recv(ws)

    assert got == ("close", 1011), (
        "the socket was dropped from the registry but never told about it"
    )


def test_send_timeout_unsubscribes_the_match(client, db, test_user, auth_headers, _ws_db, monkeypatch):
    """Pruning must go through disconnect(), which owns pub/sub bookkeeping.

    Popping the socket straight out of `_conns` left `_conns[match_id]` present
    but empty, so the next `connect()` computed `first_for_match = False` and
    skipped `subscribe()` — the "match_id present ⇒ subscribed" invariant then
    had two owners that could disagree.
    """
    other = _make_user(db, email="ws_timeout_sub@howl.app")
    m = _make_match(db, test_user, other)

    async def _never_returns(self, data):  # noqa: ANN001 - patched method
        await asyncio.sleep(3600)

    monkeypatch.setattr(starlette.websockets.WebSocket, "send_json", _never_returns)
    monkeypatch.setattr("app.api.chat._SEND_TIMEOUT_S", 0.05)

    with client.websocket_connect(_ws_url(m.id), headers=_cookie(test_user)) as ws:
        client.post(
            f"/api/matches/{m.id}/messages",
            headers=auth_headers,
            json={"content": "drop me"},
        )
        _recv(ws)
        assert m.id not in manager._conns, "empty-but-present match left in the registry"


# ---------------------------------------------------------------------------
# #49 — read receipts must reach the sender
# ---------------------------------------------------------------------------


class _RecordingSocket:
    """Minimal stand-in for a starlette WebSocket in manager-level unit tests."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.close_code: int | None = None

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self, code: int = 1000) -> None:
        self.close_code = code


def test_reading_a_chat_broadcasts_a_receipt_to_the_sender(client, db, test_user, auth_headers, _ws_db):
    """`get_messages` wrote read_at, committed, and broadcast nothing.

    Both clients already render sent-vs-read; they were waiting on data the
    server never sent. `MessageOut.read_at` exists and `_msg_event` even carries
    it — only the event was missing.
    """
    other = _make_user(db, email="ws_receipt@howl.app")
    m = _make_match(db, test_user, other)
    # Read ids out before the first commit inside a request expires these
    # instances; `_ws_db` hands the handler the test session and it closes it.
    match_id, other_id, reader_cookie = m.id, other.id, _cookie(other)

    with client.websocket_connect(_ws_url(match_id), headers=_cookie(test_user)) as sender_ws:
        sent = client.post(
            f"/api/matches/{match_id}/messages", headers=auth_headers, json={"content": "seen?"}
        ).json()
        assert _recv(sender_ws)[0] == "frame"  # the sender's own new_message echo

        client.get(f"/api/matches/{match_id}/messages", headers=reader_cookie)
        kind, event = _recv(sender_ws)

    assert kind == "frame", "the reader marked messages read and told nobody"
    assert isinstance(event, dict)
    assert isinstance(event.get("read_at"), str) and event["read_at"]
    assert event == {
        "type": "messages_read",
        "match_id": match_id,
        "reader_id": other_id,
        "last_read_message_id": sent["id"],
        "read_at": event["read_at"],
    }


def test_receipt_is_not_broadcast_when_nothing_was_unread(client, db, test_user, auth_headers, _ws_db):
    """Clients poll this endpoint; a receipt per poll would be pure noise."""
    other = _make_user(db, email="ws_receipt_noop@howl.app")
    m = _make_match(db, test_user, other)
    match_id, reader_cookie, sender_cookie = m.id, _cookie(other), _cookie(test_user)
    client.post(f"/api/matches/{match_id}/messages", headers=auth_headers, json={"content": "hi"})
    # First read consumes the only unread message.
    client.get(f"/api/matches/{match_id}/messages", headers=reader_cookie)

    with client.websocket_connect(_ws_url(match_id), headers=sender_cookie) as sender_ws:
        client.get(f"/api/matches/{match_id}/messages", headers=reader_cookie)
        assert _recv(sender_ws) == ("timeout", None)


def test_receipt_high_water_mark_covers_the_whole_conversation(client, db, test_user, auth_headers, _ws_db):
    """The receipt must agree with #48: reading clears everything, not a page."""
    other = _make_user(db, email="ws_receipt_hw@howl.app")
    m = _make_match(db, test_user, other)
    match_id, sender_id = m.id, test_user.id
    reader_cookie, sender_cookie = _cookie(other), _cookie(test_user)
    ids = []
    for i in range(60):
        msg = Message(match_id=match_id, sender_id=sender_id, content=str(i))
        db.add(msg)
        db.commit()
        db.refresh(msg)
        ids.append(msg.id)
    newest = max(ids)

    with client.websocket_connect(_ws_url(match_id), headers=sender_cookie) as sender_ws:
        client.get(f"/api/matches/{match_id}/messages", headers=reader_cookie)
        kind, event = _recv(sender_ws)

    assert kind == "frame"
    assert isinstance(event, dict)
    assert event["last_read_message_id"] == newest, (
        "the receipt stopped at the page boundary while the DB marked everything"
    )


async def test_read_receipt_from_another_replica_reaches_local_sockets():
    """The cross-replica leg: `kind: "read"` must route to local delivery.

    Without this branch in `_on_remote_event`, a receipt would work only when
    reader and sender happened to land on the same web replica.
    """
    mgr = ConnectionManager()
    ws = _RecordingSocket()
    mgr._conns[42] = {ws: (7, "Wolf")}  # type: ignore[dict-item]
    event = {
        "type": "messages_read",
        "match_id": 42,
        "reader_id": 9,
        "last_read_message_id": 300,
        "read_at": "2026-08-09T00:00:00+00:00",
    }

    await mgr._on_remote_event(42, {"kind": "read", "event": event})

    assert ws.sent == [event], "a receipt published by another replica was dropped"


async def test_receipt_is_delivered_verbatim_without_is_mine():
    """`_deliver_message` injects an is_mine into event["message"]; a receipt has
    no message body and must not grow a synthetic one."""
    mgr = ConnectionManager()
    ws = _RecordingSocket()
    mgr._conns[43] = {ws: (7, "Wolf")}  # type: ignore[dict-item]

    await mgr.broadcast_read_receipt(43, 9, 12, "2026-08-09T00:00:00+00:00")

    assert "message" not in ws.sent[0]


# ---------------------------------------------------------------------------
# #59 — cap sockets per (user, match); budget typing per user
# ---------------------------------------------------------------------------


def test_third_socket_for_one_user_evicts_the_oldest(client, db, test_user, _ws_db):
    """Two tabs are legitimate; fifty are a way to multiply the typing budget."""
    other = _make_user(db, email="ws_cap@howl.app")
    m = _make_match(db, test_user, other)
    match_id, cookie = m.id, _cookie(test_user)

    with client.websocket_connect(_ws_url(match_id), headers=cookie) as first:
        with client.websocket_connect(_ws_url(match_id), headers=cookie):
            assert len(manager._conns[match_id]) == 2, "two sockets is under the cap"

            with client.websocket_connect(_ws_url(match_id), headers=cookie):
                assert _recv(first) == ("close", 4004)
                assert len(manager._conns[match_id]) == 2


def test_socket_cap_is_per_user_not_per_match(client, db, test_user, _ws_db):
    """The other party's sockets must not count against yours."""
    other = _make_user(db, email="ws_cap_other@howl.app")
    m = _make_match(db, test_user, other)
    match_id, mine, theirs = m.id, _cookie(test_user), _cookie(other)

    with client.websocket_connect(_ws_url(match_id), headers=mine):
        with client.websocket_connect(_ws_url(match_id), headers=mine):
            with client.websocket_connect(_ws_url(match_id), headers=theirs):
                with client.websocket_connect(_ws_url(match_id), headers=theirs):
                    assert len(manager._conns[match_id]) == 4


def test_typing_budget_is_keyed_on_the_user_not_the_socket():
    """#26's limit is per user. Fifty sockets must not buy fifty allowances."""
    mgr = ConnectionManager()
    allowed = sum(1 for _ in range(8) if mgr.allow_typing(3, 7))
    assert allowed == 5
    # A different user in the same match has their own budget.
    assert mgr.allow_typing(3, 8) is True


def test_two_sockets_share_one_typing_budget(client, db, test_user, _ws_db):
    """The budget used to be a local in the WS handler, so it was per socket:
    six frames split across two sockets were three and three, both under the
    limit of five, and all six fanned out."""
    other = _make_user(db, email="ws_typing@howl.app")
    m = _make_match(db, test_user, other)
    match_id, mine, theirs = m.id, _cookie(test_user), _cookie(other)

    with client.websocket_connect(_ws_url(match_id), headers=theirs) as watcher:
        with client.websocket_connect(_ws_url(match_id), headers=mine) as a:
            with client.websocket_connect(_ws_url(match_id), headers=mine) as b:
                for sock in (a, b, a, b, a, b):
                    sock.send_json({"type": "typing"})

                delivered = 0
                while True:
                    kind, event = _recv(watcher, timeout=1.0)
                    if kind != "frame":
                        break
                    assert isinstance(event, dict) and event["type"] == "typing"
                    delivered += 1
                    if delivered > _TYPING_LIMIT:
                        break

    assert delivered == _TYPING_LIMIT, "a second socket bought a second budget"


def test_typing_budget_survives_one_socket_of_a_pair_closing(client, db, test_user, _ws_db):
    """Closing one of two tabs must not hand the user a fresh window."""
    other = _make_user(db, email="ws_typing_reset@howl.app")
    m = _make_match(db, test_user, other)
    match_id, uid, cookie = m.id, test_user.id, _cookie(test_user)

    with client.websocket_connect(_ws_url(match_id), headers=cookie):
        with client.websocket_connect(_ws_url(match_id), headers=cookie):
            assert (match_id, uid) in manager._typing_budgets
        assert (match_id, uid) in manager._typing_budgets, "one tab closing reset the window"
    # Last socket gone: the state dies with the user's presence, so nothing leaks.
    assert (match_id, uid) not in manager._typing_budgets
