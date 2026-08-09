"""Tolerant read types for the two columns Claude writes free-form.

GAPS-ROUND-2 #38. `app/tasks/avatar.py` now validates Claude's reply against a
shape contract *before* persisting it, so no new row can hold a wrong shape.
These types exist for rows written before that validation landed, and as a
standing backstop.

Why they are needed at all: `users.personality_traits` and
`users.avatar_description` are `JSON` columns, so any JSON value stored cleanly
while five response schemas declare them `list[str] | None` and `str | None`.
Pydantic v2 rejects every near-miss on the way back out — it does not coerce
`dict` -> `str` or `int` -> `str`, in lax mode either. So a single row whose
traits Claude returned as objects (``[{"trait": "curious"}]`` — a shape LLMs
routinely produce) raised a 500 on:

  * that user's login, on both clients, because `AuthOut` embeds `UserOut`, and
  * `GET /api/users/discover` for **every other user**, because discover has no
    `LIMIT` and serialises the whole ready population in one response.

The second one is what made a single bad row an outage rather than one broken
profile. And it was unrecoverable: the owner could not log in to reach the
"Regenerate" button that clears the field.

Coercion is deliberately lossy in one direction only — drop what cannot be a
string, never invent content. A profile that renders with fewer traits is a
cosmetic problem; a profile that 500s the whole discover queue is not. Dropping
also restores the repair path, since the user can now log in and regenerate.
"""

from typing import Annotated, Any

from pydantic import BeforeValidator


def _coerce_str_list(value: Any) -> Any:
    """Make `value` safe for `list[str] | None`, or hand it back untouched.

    Anything already valid passes through unchanged, so the happy path costs one
    isinstance check and this can never alter a well-formed row.
    """
    if value is None:
        return None
    # A bare string where a list was expected: the single most likely near-miss
    # after objects, and the intent is unambiguous.
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return value
        # Keep the strings, drop the rest. Pulling a value out of a dict item
        # would mean guessing which key held the trait, and a wrong guess shows
        # users invented text -- worse than showing fewer traits.
        return [item for item in value if isinstance(item, str)]
    # A dict, number or bool here is not salvageable as a trait list.
    return None


def _coerce_optional_str(value: Any) -> Any:
    """Make `value` safe for `str | None`, or hand it back untouched.

    Non-strings become None rather than `str(value)`: rendering a serialised dict
    into a user-facing profile description is worse than rendering nothing.
    """
    if value is None or isinstance(value, str):
        return value
    return None


#: `list[str] | None`, tolerant of pre-#38 rows.
TraitList = Annotated[list[str] | None, BeforeValidator(_coerce_str_list)]

#: `str | None`, tolerant of pre-#38 rows.
DescriptionText = Annotated[str | None, BeforeValidator(_coerce_optional_str)]
