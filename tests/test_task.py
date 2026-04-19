"""
Unit tests for the generate_avatar Celery task.

All external I/O (Anthropic API, database) is mocked so these tests
run without Docker, Postgres, Redis, or a real API key.

The task is invoked via ``generate_avatar.apply(args=[user_id])`` which
runs it synchronously (Celery eager mode) in the current process.
"""

import json
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest

from app.models.user import AvatarStatus, User
from app.tasks.avatar import _mark_failed, generate_avatar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _claude_response(payload: dict) -> MagicMock:
    """Build a mock Anthropic response whose text content is `payload` as JSON."""
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload)
    response = MagicMock()
    response.content = [block]
    return response


def _mock_user(bio: str | None = "A curious fox who loves to explore dense forests.") -> MagicMock:
    user = MagicMock(spec=User)
    user.id = 1
    user.bio = bio
    return user


def _mock_db(user: MagicMock) -> MagicMock:
    db = MagicMock()
    db.get.return_value = user
    return db


VALID_PAYLOAD = {
    "animal": "fox",
    "personality_traits": ["clever", "curious", "adaptable"],
    "avatar_description": "A rust-furred fox-human hybrid with sharp green eyes.",
}

# A fake httpx.Request used when constructing anthropic error types
_FAKE_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_successful_generation():
    user = _mock_user()
    db = _mock_db(user)

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClient,
    ):
        MockClient.return_value.messages.create.return_value = _claude_response(VALID_PAYLOAD)
        generate_avatar.apply(args=[1])

    assert user.animal == "fox"
    assert user.personality_traits == ["clever", "curious", "adaptable"]
    assert "fox-human hybrid" in user.avatar_description
    assert user.avatar_status == AvatarStatus.ready
    db.commit.assert_called()
    db.close.assert_called()


def test_markdown_fence_stripped():
    """Claude sometimes wraps JSON in ```json fences; verify they are removed."""
    user = _mock_user()
    db = _mock_db(user)

    block = MagicMock()
    block.type = "text"
    block.text = "```json\n" + json.dumps(VALID_PAYLOAD) + "\n```"
    fenced_response = MagicMock()
    fenced_response.content = [block]

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClient,
    ):
        MockClient.return_value.messages.create.return_value = fenced_response
        generate_avatar.apply(args=[1])

    assert user.animal == "fox"
    assert user.avatar_status == AvatarStatus.ready


def test_animal_stored_lowercase():
    """Animal name is lowercased even if Claude returns mixed case."""
    user = _mock_user()
    db = _mock_db(user)

    payload = {**VALID_PAYLOAD, "animal": "  WOLF  "}

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClient,
    ):
        MockClient.return_value.messages.create.return_value = _claude_response(payload)
        generate_avatar.apply(args=[1])

    assert user.animal == "wolf"


# ---------------------------------------------------------------------------
# Early-exit cases
# ---------------------------------------------------------------------------

def test_user_not_found():
    db = MagicMock()
    db.get.return_value = None

    with patch("app.tasks.avatar.SessionLocal", return_value=db):
        generate_avatar.apply(args=[999])

    db.commit.assert_not_called()
    db.close.assert_called()


def test_user_has_no_bio():
    user = _mock_user(bio=None)
    db = _mock_db(user)

    with patch("app.tasks.avatar.SessionLocal", return_value=db):
        generate_avatar.apply(args=[1])

    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Parse / validation failures → immediate fail (no retry)
# ---------------------------------------------------------------------------

def test_invalid_json_marks_failed():
    user = _mock_user()
    db = _mock_db(user)

    block = MagicMock()
    block.type = "text"
    block.text = "this is not json at all"
    bad_response = MagicMock()
    bad_response.content = [block]

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClient,
    ):
        MockClient.return_value.messages.create.return_value = bad_response
        generate_avatar.apply(args=[1])

    assert user.avatar_status == AvatarStatus.failed


def test_missing_animal_key_marks_failed():
    user = _mock_user()
    db = _mock_db(user)

    payload = {"personality_traits": ["bold"], "avatar_description": "No animal key here"}

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClient,
    ):
        MockClient.return_value.messages.create.return_value = _claude_response(payload)
        generate_avatar.apply(args=[1])

    assert user.avatar_status == AvatarStatus.failed


def test_empty_animal_marks_failed():
    user = _mock_user()
    db = _mock_db(user)

    payload = {**VALID_PAYLOAD, "animal": "   "}  # blank after strip

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClient,
    ):
        MockClient.return_value.messages.create.return_value = _claude_response(payload)
        generate_avatar.apply(args=[1])

    assert user.avatar_status == AvatarStatus.failed


def test_no_text_content_marks_failed():
    """Claude response with no text block should mark the user as failed."""
    user = _mock_user()
    db = _mock_db(user)

    non_text_block = MagicMock()
    non_text_block.type = "tool_use"
    empty_response = MagicMock()
    empty_response.content = [non_text_block]

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClient,
    ):
        MockClient.return_value.messages.create.return_value = empty_response
        generate_avatar.apply(args=[1])

    assert user.avatar_status == AvatarStatus.failed


# ---------------------------------------------------------------------------
# API error → retry → eventually marks failed
# ---------------------------------------------------------------------------

def test_api_error_retries_correct_number_of_times():
    """Persistent Claude API errors trigger exactly max_retries retries.

    Note: in Celery's eager mode (apply()), after retries are exhausted the
    original exception propagates rather than MaxRetriesExceededError being
    catchable.  We therefore verify the *retry count* (max_retries=3 means
    4 total attempts) rather than the final avatar_status.
    """
    user = _mock_user()
    db = _mock_db(user)

    api_err = anthropic.APIConnectionError(request=_FAKE_REQUEST)
    call_count = []

    def _raise(*args, **kwargs):
        call_count.append(1)
        raise api_err

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClient,
        patch("app.tasks.avatar._mark_failed"),  # prevent side-effects
    ):
        MockClient.return_value.messages.create.side_effect = _raise
        generate_avatar.apply(args=[1])

    # 1 original attempt + 3 retries (max_retries=3)
    assert len(call_count) == 4


# ---------------------------------------------------------------------------
# _mark_failed helper
# ---------------------------------------------------------------------------

def test_mark_failed_with_none_user():
    """_mark_failed must be safe to call with user=None (e.g. DB lookup failed)."""
    db = MagicMock()
    _mark_failed(db, None)
    db.commit.assert_not_called()


def test_mark_failed_sets_status():
    user = MagicMock(spec=User)
    db = MagicMock()
    _mark_failed(db, user)
    assert user.avatar_status == AvatarStatus.failed
    db.commit.assert_called_once()


def test_mark_failed_rolls_back_on_commit_error():
    """If the commit itself fails, _mark_failed swallows the error gracefully."""
    user = MagicMock(spec=User)
    db = MagicMock()
    db.commit.side_effect = Exception("DB is gone")
    _mark_failed(db, user)  # should not raise
    db.rollback.assert_called_once()
