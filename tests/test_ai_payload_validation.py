"""GAPS-ROUND-2 #38 — Claude's output is shape-validated before it is persisted.

Two halves, and both matter:

* **Prevention** — `app/tasks/avatar.py` validates the parsed reply against
  `_ClaudeAvatarPayload` before writing, so a wrong shape marks the avatar
  `failed` (recoverable via regenerate) instead of poisoning the row.
* **Containment** — `app/schemas/ai_fields.py` coerces on read, for rows written
  before prevention existed.

The bug this pins was not "one profile renders oddly". `personality_traits` is a
JSON column, so a bad shape stored cleanly, and pydantic v2 refuses `dict` ->
`str` on the way back out even in lax mode. So one poisoned row 500'd its owner's
login on both clients (`AuthOut` embeds `UserOut`) *and* `GET /api/users/discover`
for **every other user**, because discover has no LIMIT and serialises the whole
ready population at once. The owner could not log in to reach the Regenerate
button, so there was no repair path either.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.models.user import AvatarStatus, User
from app.schemas.ai_fields import _coerce_optional_str, _coerce_str_list
from app.schemas.avatar import AvatarStatusOut
from app.schemas.swipe import DiscoverUserOut
from app.schemas.user import PublicProfileOut, UserOut
from app.security import hash_password
from app.tasks.avatar import _ClaudeAvatarPayload, generate_avatar

# ---------------------------------------------------------------------------
# The shapes an LLM actually produces when it drifts off contract
# ---------------------------------------------------------------------------

#: `[{"trait": ...}]` is the headline one -- exactly what a model returns when it
#: decides a "list of traits" deserves structure. The rest are the near-misses
#: pydantic also refuses to coerce.
BAD_TRAIT_SHAPES = [
    pytest.param([{"trait": "curious", "why": "asks questions"}], id="list-of-objects"),
    pytest.param("curious, clever, adaptable", id="comma-string"),
    pytest.param([1, 2, 3], id="list-of-ints"),
    pytest.param({"traits": ["curious"]}, id="dict-wrapper"),
    pytest.param([["curious"], ["clever"]], id="nested-lists"),
]


def _ready_user(db, email: str, traits) -> User:
    user = User(
        email=email,
        password_hash=hash_password("testpass1"),
        name=email.split("@")[0],
        age=30,
        avatar_status=AvatarStatus.ready,
        animal="wolf",  # required by ck_users_ready_avatar_has_animal (GAPS #23)
        personality_traits=traits,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _claude_response(payload: dict) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload)
    response = MagicMock()
    response.content = [block]
    return response


def _mock_user() -> MagicMock:
    user = MagicMock(spec=User)
    user.id = 1
    user.bio = "A curious fox who loves to explore dense forests."
    user.avatar_status = AvatarStatus.pending
    return user


# ---------------------------------------------------------------------------
# Prevention: the task refuses to persist a bad shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("traits", BAD_TRAIT_SHAPES)
def test_bad_trait_shape_marks_failed_and_never_persists(traits):
    """The whole point: a wrong shape must not reach the database.

    `failed` is the right landing state -- it is what a blank `animal` already
    produced, and `POST /api/avatar/regenerate` recovers from it.
    """
    user = _mock_user()
    db = MagicMock()
    db.get.return_value = user

    payload = {"animal": "fox", "personality_traits": traits, "avatar_description": "A fox."}

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.task_lock.acquire", return_value=True),
        patch("app.tasks.avatar.task_lock.release"),
        patch("app.tasks.avatar.anthropic.Anthropic") as anthropic_cls,
        patch("app.tasks.avatar.generate_avatar_image") as gen_image,
    ):
        anthropic_cls.return_value.messages.create.return_value = _claude_response(payload)
        generate_avatar.apply(args=[user.id])

    assert user.avatar_status == AvatarStatus.failed
    # Never reached the paid image call, and never wrote the bad value.
    gen_image.assert_not_called()
    assert user.personality_traits is not traits


def test_a_bad_description_shape_is_also_refused():
    """`avatar_description` has the same exposure, one field over."""
    user = _mock_user()
    db = MagicMock()
    db.get.return_value = user

    payload = {
        "animal": "fox",
        "personality_traits": ["clever"],
        "avatar_description": {"text": "A fox."},
    }

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.task_lock.acquire", return_value=True),
        patch("app.tasks.avatar.task_lock.release"),
        patch("app.tasks.avatar.anthropic.Anthropic") as anthropic_cls,
        patch("app.tasks.avatar.generate_avatar_image") as gen_image,
    ):
        anthropic_cls.return_value.messages.create.return_value = _claude_response(payload)
        generate_avatar.apply(args=[user.id])

    assert user.avatar_status == AvatarStatus.failed
    gen_image.assert_not_called()


def test_a_valid_payload_still_goes_ready():
    """Guard against the fix being a blanket refusal."""
    user = _mock_user()
    db = MagicMock()
    db.get.return_value = user

    payload = {
        "animal": "  Fox  ",  # normalisation still applies
        "personality_traits": ["clever", "curious"],
        "avatar_description": "A rust-furred fox.",
    }

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.task_lock.acquire", return_value=True),
        patch("app.tasks.avatar.task_lock.release"),
        patch("app.tasks.avatar.anthropic.Anthropic") as anthropic_cls,
        patch("app.tasks.avatar.generate_avatar_image", return_value="/avatars/x.png"),
    ):
        anthropic_cls.return_value.messages.create.return_value = _claude_response(payload)
        generate_avatar.apply(args=[user.id])

    assert user.avatar_status == AvatarStatus.ready
    assert user.animal == "fox"
    assert user.personality_traits == ["clever", "curious"]


# ---------------------------------------------------------------------------
# The payload contract itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("traits", BAD_TRAIT_SHAPES)
def test_payload_model_rejects_every_bad_trait_shape(traits):
    with pytest.raises(ValidationError):
        _ClaudeAvatarPayload.model_validate(
            {"animal": "fox", "personality_traits": traits}
        )


def test_validation_error_is_a_valueerror():
    """Load-bearing: this is *why* the existing
    `except (json.JSONDecodeError, KeyError, ValueError)` handler catches a bad
    shape and marks the avatar failed. If pydantic ever stopped subclassing
    ValueError, the task would fall through to the broad handler instead."""
    assert issubclass(ValidationError, ValueError)


@pytest.mark.parametrize("animal", ["", "   ", "\n\t"])
def test_blank_animal_is_still_rejected(animal):
    """Pre-existing behaviour that must survive the refactor -- and the DB CHECK
    from GAPS #23 (ready => animal IS NOT NULL) depends on it."""
    with pytest.raises(ValidationError):
        _ClaudeAvatarPayload.model_validate({"animal": animal})


def test_missing_optional_fields_get_safe_defaults():
    payload = _ClaudeAvatarPayload.model_validate({"animal": "owl"})
    assert payload.personality_traits == []
    assert payload.avatar_description == ""
    # None, not "", so the caller's animal-specific fallback prompt still applies.
    assert payload.image_prompt is None


# ---------------------------------------------------------------------------
# Containment: rows written before prevention existed must still serialise
# ---------------------------------------------------------------------------

_ROW_SHAPES = [
    pytest.param([{"trait": "curious"}], [], id="objects-dropped"),
    pytest.param(["clever", {"trait": "x"}, "kind"], ["clever", "kind"], id="mixed-keeps-strings"),
    pytest.param("curious", ["curious"], id="bare-string-wrapped"),
    pytest.param("   ", [], id="blank-string-empties"),
    pytest.param({"traits": ["x"]}, None, id="dict-becomes-none"),
    pytest.param([1, 2], [], id="ints-dropped"),
    pytest.param(None, None, id="none-passes-through"),
    pytest.param(["clever", "kind"], ["clever", "kind"], id="valid-untouched"),
]


@pytest.mark.parametrize("stored,expected", _ROW_SHAPES)
def test_trait_coercion_covers_every_shape(stored, expected):
    assert _coerce_str_list(stored) == expected


@pytest.mark.parametrize(
    "stored,expected",
    [
        ("a description", "a description"),
        (None, None),
        # str(value) would render a serialised dict into a user-facing profile.
        ({"text": "hi"}, None),
        (["a", "b"], None),
        (42, None),
    ],
)
def test_description_coercion_never_stringifies_a_non_string(stored, expected):
    assert _coerce_optional_str(stored) == expected


@pytest.mark.parametrize("stored,expected", _ROW_SHAPES)
@pytest.mark.parametrize(
    "schema", [UserOut, PublicProfileOut, DiscoverUserOut, AvatarStatusOut]
)
def test_every_schema_survives_a_poisoned_row(schema, stored, expected, db):
    """All four schemas that declare the field, not just the one that was noticed.

    Validated from a real persisted `User`, which is the actual production path
    (FastAPI serialises the ORM object). Note you cannot test this by building the
    schema with `model_construct` and re-validating it: pydantic's
    `revalidate_instances` defaults to `'never'`, so validating an instance of the
    same class returns it untouched and every validator is skipped -- a test
    written that way passes regardless of whether the coercion exists.
    """
    user = _ready_user(db, f"poison_{schema.__name__}@howl.app", stored)

    result = schema.model_validate(user, from_attributes=True)

    assert result.personality_traits == expected


# ---------------------------------------------------------------------------
# The reproduction: one poisoned row used to take out everyone else's discover
# ---------------------------------------------------------------------------


def test_one_poisoned_profile_no_longer_500s_discover_for_everyone(client, db, auth_headers):
    """The blast radius, pinned. Discover has no LIMIT (GAPS-ROUND-2 #58), so it
    serialises every ready user -- one bad row used to break the endpoint for the
    entire user base, not only for whoever would have seen that profile."""
    _ready_user(db, "poisoned@howl.app", [{"trait": "curious", "why": "asks"}])

    res = client.get("/api/users/discover", headers=auth_headers)

    assert res.status_code == 200
    bodies = {u["email"] if "email" in u else u["name"] for u in res.json()}
    assert bodies  # the healthy population is still served


def test_a_poisoned_user_can_log_in_again_to_reach_regenerate(client, db):
    """AuthOut embeds UserOut, so login 500'd -- which is what made this
    unrecoverable, since Regenerate is behind a login."""
    _ready_user(db, "victim@howl.app", [{"trait": "curious"}])

    res = client.post(
        "/api/auth/login",
        json={"email": "victim@howl.app", "password": "testpass1"},
    )

    assert res.status_code == 200
    assert res.json()["user"]["personality_traits"] == []
