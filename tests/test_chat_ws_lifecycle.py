"""WebSocket lifecycle: dropped sockets, per-user connection caps, revocation.

These cover the three chat-socket defects in GAPS round two that are about the
*connection* rather than the message:

  * #46 — a send timeout unregistered a socket without closing it, so the client
    kept a connection that looked healthy and received nothing ever again.
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

from app.api.chat import manager
from app.models.match import Match
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


def _recv(ws) -> tuple[str, object]:
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
    reader.join(_RECEIVE_TIMEOUT_S)
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
