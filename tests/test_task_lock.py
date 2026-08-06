"""Tests for the Celery task lock and the duplicate-work guards on generate_avatar.

Celery runs with task_acks_late, so a worker killed mid-task has its message
redelivered and the task runs again — paying a second time for the Claude and
DALL-E calls. These cover both guards.
"""

from unittest.mock import MagicMock, patch

from redis import RedisError

from app.models.user import AvatarStatus, User
from app.services import task_lock
from app.tasks.avatar import generate_avatar

# ---------------------------------------------------------------------------
# task_lock primitives
# ---------------------------------------------------------------------------

def test_acquire_returns_true_when_key_is_free():
    client = MagicMock()
    client.set.return_value = True
    with patch("app.services.task_lock._get_client", return_value=client):
        assert task_lock.acquire("k") is True
    # SET NX EX — atomic, no check-then-set race
    assert client.set.call_args.kwargs["nx"] is True
    assert client.set.call_args.kwargs["ex"] == task_lock.DEFAULT_TTL_SECONDS


def test_acquire_returns_false_when_key_is_held():
    client = MagicMock()
    client.set.return_value = None  # redis-py returns None when NX fails
    with patch("app.services.task_lock._get_client", return_value=client):
        assert task_lock.acquire("k") is False


def test_acquire_fails_open_when_redis_errors():
    """A Redis outage must not stop avatars generating."""
    client = MagicMock()
    client.set.side_effect = RedisError("connection refused")
    with patch("app.services.task_lock._get_client", return_value=client):
        assert task_lock.acquire("k") is True


def test_acquire_fails_open_when_no_client():
    with patch("app.services.task_lock._get_client", return_value=None):
        assert task_lock.acquire("k") is True


def test_release_never_raises():
    client = MagicMock()
    client.delete.side_effect = RedisError("gone")
    with patch("app.services.task_lock._get_client", return_value=client):
        task_lock.release("k")  # must not raise


def test_release_is_a_noop_without_a_client():
    with patch("app.services.task_lock._get_client", return_value=None):
        task_lock.release("k")


# ---------------------------------------------------------------------------
# generate_avatar duplicate-work guards
# ---------------------------------------------------------------------------

def _user(**kw):
    user = MagicMock(spec=User)
    user.id = 1
    user.bio = "A curious fox who loves dense forests."
    user.avatar_status = kw.get("avatar_status", AvatarStatus.pending)
    user.avatar_url = kw.get("avatar_url", None)
    return user


def test_skips_when_avatar_already_ready():
    """Redelivery after a successful run must not pay for a second image."""
    db = MagicMock()
    db.get.return_value = _user(avatar_status=AvatarStatus.ready, avatar_url="/avatars/x.png")

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClient,
        patch("app.tasks.avatar.generate_avatar_image") as mock_img,
    ):
        generate_avatar.apply(args=[1])

    MockClient.assert_not_called()
    mock_img.assert_not_called()
    db.commit.assert_not_called()


def test_ready_without_url_still_generates():
    """A ready row with no image is the emoji-fallback case — regenerating is valid."""
    db = MagicMock()
    db.get.return_value = _user(avatar_status=AvatarStatus.ready, avatar_url=None)

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClient,
        patch("app.tasks.avatar.generate_avatar_image", return_value=None),
    ):
        MockClient.return_value.messages.create.return_value = _claude_ok()
        generate_avatar.apply(args=[1])

    MockClient.assert_called()


def test_skips_when_lock_is_held(monkeypatch):
    """A concurrent duplicate must not run the paid calls."""
    db = MagicMock()
    db.get.return_value = _user()
    monkeypatch.setattr("app.services.task_lock.acquire", lambda *a, **kw: False)

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClient,
        patch("app.tasks.avatar.generate_avatar_image") as mock_img,
    ):
        generate_avatar.apply(args=[1])

    MockClient.assert_not_called()
    mock_img.assert_not_called()


def test_lock_is_released_after_a_successful_run(monkeypatch):
    db = MagicMock()
    db.get.return_value = _user()
    released = []
    monkeypatch.setattr("app.services.task_lock.acquire", lambda *a, **kw: True)
    monkeypatch.setattr("app.services.task_lock.release", lambda key: released.append(key))

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClient,
        patch("app.tasks.avatar.generate_avatar_image", return_value=None),
    ):
        MockClient.return_value.messages.create.return_value = _claude_ok()
        generate_avatar.apply(args=[1])

    assert released == ["avatar:generate:1"]


def test_lock_is_released_even_when_generation_fails(monkeypatch):
    """A held lock after a crash would block the user for the whole TTL."""
    db = MagicMock()
    db.get.return_value = _user()
    released = []
    monkeypatch.setattr("app.services.task_lock.acquire", lambda *a, **kw: True)
    monkeypatch.setattr("app.services.task_lock.release", lambda key: released.append(key))

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClient,
    ):
        MockClient.return_value.messages.create.return_value = _claude_text("not json")
        generate_avatar.apply(args=[1])

    assert released == ["avatar:generate:1"]


def test_lock_not_released_when_it_was_never_acquired(monkeypatch):
    """Releasing a lock we don't hold would free someone else's."""
    db = MagicMock()
    db.get.return_value = _user()
    released = []
    monkeypatch.setattr("app.services.task_lock.acquire", lambda *a, **kw: False)
    monkeypatch.setattr("app.services.task_lock.release", lambda key: released.append(key))

    with patch("app.tasks.avatar.SessionLocal", return_value=db):
        generate_avatar.apply(args=[1])

    assert released == []


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _claude_text(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def _claude_ok():
    return _claude_text(
        '{"animal": "fox", "personality_traits": ["clever"], '
        '"avatar_description": "d", "image_prompt": "p"}'
    )
