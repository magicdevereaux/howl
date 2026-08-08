"""Repo-level invariants that nothing else would catch (GAPS #28, #32).

These are not tests of application behaviour — they are tests of the repo's own
consistency. Both guard a duplication that was chosen deliberately, and both
exist because the duplication had already silently drifted once.
"""

import ast
import re
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _parse_requirement(line: str) -> str | None:
    """Normalise one requirement line, or None if it isn't one."""
    line = line.split("#", 1)[0].strip()
    if not line or line.startswith("-"):
        return None
    return line


def _requirement_name(spec: str) -> str:
    """`sentry-sdk[fastapi,celery]>=2.0.0` -> `sentry-sdk`."""
    return re.split(r"[<>=!~\[]", spec, maxsplit=1)[0].strip().lower()


# ---------------------------------------------------------------------------
# #28 — the two dependency manifests must not drift
# ---------------------------------------------------------------------------

def test_dependency_manifests_agree():
    """pyproject's `dependencies` must equal requirements.txt, exactly.

    pyproject previously omitted openai, boto3, sentry-sdk, httpx and pydantic's
    email extra — every one of them imported by the app — so `pip install -e .`
    yielded an app that could not start. requirements.txt is the source of truth
    (CLAUDE.md tells contributors to install from it); this test is what stops
    the copy in pyproject.toml from rotting again.
    """
    reqs = {
        r for r in (
            _parse_requirement(line)
            for line in (REPO_ROOT / "requirements.txt").read_text().splitlines()
        ) if r
    }
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        declared = set(tomllib.load(fh)["project"]["dependencies"])

    missing_from_pyproject = reqs - declared
    extra_in_pyproject = declared - reqs

    assert not missing_from_pyproject, (
        f"in requirements.txt but not pyproject.toml: {sorted(missing_from_pyproject)}"
    )
    assert not extra_in_pyproject, (
        f"in pyproject.toml but not requirements.txt: {sorted(extra_in_pyproject)}"
    )


@pytest.mark.parametrize(
    ("module", "distribution"),
    [
        ("anthropic", "anthropic"),
        ("openai", "openai"),          # DALL-E 3, app/services/image_generation.py
        ("boto3", "boto3"),            # R2 upload, lazily imported
        ("httpx", "httpx"),            # Expo push
        ("sentry_sdk", "sentry-sdk"),
        ("jose", "python-jose"),
        ("redis", "redis"),
        ("celery", "celery"),
    ],
)
def test_imported_third_party_module_is_declared(module, distribution):
    """Every third-party module the app imports must be a declared dependency.

    Several of these are imported *lazily inside functions* behind `None`
    guards (openai and boto3 especially), so a missing declaration does not
    break startup or the test suite — it breaks the avatar pipeline in
    production, which is the one path CLAUDE.md calls the critical path.
    That is exactly why this is asserted rather than assumed.
    """
    reqs = {
        _requirement_name(r) for r in (
            _parse_requirement(line)
            for line in (REPO_ROOT / "requirements.txt").read_text().splitlines()
        ) if r
    }
    assert distribution.lower() in reqs, f"{module} is imported but {distribution} is not declared"


def test_app_imports_nothing_undeclared():
    """Catch a new third-party import that nobody added to requirements.txt.

    Parsed with `ast` rather than a regex, because a regex over source lines
    also matches English prose inside docstrings ("...from the database...").
    """
    declared = {
        _requirement_name(r) for r in (
            _parse_requirement(line)
            for line in (REPO_ROOT / "requirements.txt").read_text().splitlines()
        ) if r
    }
    # Import name -> distribution that provides it, where the two differ.
    module_to_dist = {
        "jose": "python-jose",
        "sentry_sdk": "sentry-sdk",
        "pydantic_settings": "pydantic-settings",
        "dotenv": "python-dotenv",
        "psycopg2": "psycopg2-binary",
        # botocore is boto3's own hard runtime dependency, so it is always
        # present wherever boto3 is. app/services/image_generation.py imports
        # its exception types directly. Declaring botocore separately would mean
        # pinning another package's internal dependency, so it maps to boto3.
        "botocore": "boto3",
    }

    found: set[str] = set()
    for path in (REPO_ROOT / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                # level > 0 is a relative import, i.e. first-party.
                if node.level == 0 and node.module:
                    found.add(node.module.split(".")[0])

    undeclared = {
        module for module in found
        if module != "app"
        and module not in sys.stdlib_module_names
        and module_to_dist.get(module, module).lower() not in declared
    }

    assert not undeclared, f"imported but not declared in requirements.txt: {sorted(undeclared)}"


# ---------------------------------------------------------------------------
# #32 — the two client constants files must stay byte-identical
# ---------------------------------------------------------------------------

_SHARED_COPIES = (
    Path("frontend/src/shared/constants.js"),
    Path("mobile/src/shared/constants.ts"),
)


def test_shared_client_constants_are_byte_identical():
    """The two copies are duplicated on purpose; they must never diverge.

    A single `packages/shared` would remove the duplication, but Metro does not
    resolve out-of-tree workspace packages without extra config, so the file is
    written to be simultaneously valid JS and valid strict TS and kept in two
    places. That is only safe if the identity is enforced mechanically — the
    animal->emoji maps had *already* drifted (GAPS #32: the web copy had
    `rabbit` and was missing tiger/salmon/coyote/hummingbird/raven/lynx/
    elephant), which is the bug this prevents recurring.
    """
    web, mobile = (REPO_ROOT / p for p in _SHARED_COPIES)
    assert web.exists() and mobile.exists()
    assert web.read_bytes() == mobile.read_bytes(), (
        f"{_SHARED_COPIES[0]} and {_SHARED_COPIES[1]} have diverged. "
        "Any edit must be applied to both copies."
    )


def test_shared_constants_do_not_encode_server_enforced_quotas():
    """The backend is the authority for anything it enforces.

    `DAILY_SWIPE_LIMIT = 20` used to be hardcoded client-side while
    `_DAILY_SWIPE_LIMIT` in app/api/swipes.py was the real rule, so the two could
    disagree and the UI would lie. Quotas must reach the client over the API.
    """
    text = (REPO_ROOT / _SHARED_COPIES[0]).read_text(encoding="utf-8")
    code = "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith("//")
    )
    for banned in ("DAILY_SWIPE_LIMIT", "REGENERATION", "MONTHLY_LIMIT"):
        assert banned not in code, (
            f"{banned} is a server-enforced quota and must not be a client constant"
        )
