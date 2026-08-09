"""Tests for auth rate limiting: per-endpoint buckets, and client-IP derivation."""

import pytest

from app.models.user import AvatarStatus, User
from app.security import hash_password

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def registered_user(db):
    user = User(
        email="ratelimit@howl.app",
        password_hash=hash_password("goodpassword"),
        avatar_status=AvatarStatus.pending,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(autouse=True)
def _allow_by_default(monkeypatch):
    """Default: rate limiter is a no-op so non-rate-limit tests are unaffected."""
    monkeypatch.setattr("app.services.rate_limit.check_rate_limit", lambda key, limit, window: (False, 0))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client, email="ratelimit@howl.app", password="goodpassword"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# ---------------------------------------------------------------------------
# Normal login still works when under the limit
# ---------------------------------------------------------------------------

def test_login_succeeds_under_limit(client, registered_user):
    res = _login(client)
    assert res.status_code == 200
    assert "user" in res.json()


# ---------------------------------------------------------------------------
# IP rate limit
# ---------------------------------------------------------------------------

def test_ip_rate_limit_returns_429(client, registered_user, monkeypatch):
    """When the IP counter trips, login returns 429 regardless of credentials."""
    calls = []

    def fake_check(key, limit, window):
        calls.append(key)
        # Trip on the first call (IP check)
        if "ip" in key:
            return True, 840   # 14 minutes remaining
        return False, 0

    monkeypatch.setattr("app.services.rate_limit.check_rate_limit", fake_check)

    res = _login(client)
    assert res.status_code == 429
    assert "IP" in res.json()["detail"]
    assert "840" in res.json()["detail"]
    assert res.headers["Retry-After"] == "840"


def test_ip_rate_limit_checked_before_email(client, registered_user, monkeypatch):
    """IP limit is enforced first; if it trips, the email counter is never checked."""
    email_checked = []

    def fake_check(key, limit, window):
        if "email" in key:
            email_checked.append(key)
        return ("ip" in key, 1)

    monkeypatch.setattr("app.services.rate_limit.check_rate_limit", fake_check)

    res = _login(client)
    assert res.status_code == 429
    assert email_checked == []   # email key was never evaluated


# ---------------------------------------------------------------------------
# Email rate limit
# ---------------------------------------------------------------------------

def test_email_rate_limit_returns_429(client, registered_user, monkeypatch):
    """When the email counter trips, login returns 429 with an account-specific message."""
    def fake_check(key, limit, window):
        if "email" in key:
            return True, 300   # 5 minutes remaining
        return False, 0

    monkeypatch.setattr("app.services.rate_limit.check_rate_limit", fake_check)

    res = _login(client)
    assert res.status_code == 429
    assert "account" in res.json()["detail"].lower()
    assert "300" in res.json()["detail"]
    assert res.headers["Retry-After"] == "300"


def test_email_limit_is_case_insensitive(client, registered_user, monkeypatch):
    """Email addresses are normalised to lowercase before being used as keys."""
    seen_keys = []

    def fake_check(key, limit, window):
        seen_keys.append(key)
        return False, 0

    monkeypatch.setattr("app.services.rate_limit.check_rate_limit", fake_check)

    _login(client, email="RateLimit@Howl.App")

    email_keys = [k for k in seen_keys if "email" in k]
    assert all("ratelimit@howl.app" in k for k in email_keys)
    assert not any("RateLimit" in k for k in email_keys)


# ---------------------------------------------------------------------------
# Retry-After header is present on both limit types
# ---------------------------------------------------------------------------

def test_retry_after_header_on_ip_limit(client, registered_user, monkeypatch):
    monkeypatch.setattr(
        "app.services.rate_limit.check_rate_limit",
        lambda key, limit, window: (True, 500) if "ip" in key else (False, 0),
    )
    res = _login(client)
    assert res.status_code == 429
    assert "Retry-After" in res.headers
    assert res.headers["Retry-After"] == "500"


def test_retry_after_header_on_email_limit(client, registered_user, monkeypatch):
    monkeypatch.setattr(
        "app.services.rate_limit.check_rate_limit",
        lambda key, limit, window: (True, 200) if "email" in key else (False, 0),
    )
    res = _login(client)
    assert res.status_code == 429
    assert "Retry-After" in res.headers
    assert res.headers["Retry-After"] == "200"


# ---------------------------------------------------------------------------
# Redis failure is fail-open (does not block login)
# ---------------------------------------------------------------------------

def test_redis_failure_allows_login(client, registered_user, monkeypatch):
    """If check_rate_limit returns (False, 0) due to a Redis error, login proceeds."""
    # _allow_by_default autouse fixture already does this, but be explicit:
    monkeypatch.setattr("app.services.rate_limit.check_rate_limit", lambda *_: (False, 0))
    res = _login(client)
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# check_rate_limit unit tests (pure logic, no Redis required)
# ---------------------------------------------------------------------------

def test_check_rate_limit_returns_false_when_redis_unavailable(monkeypatch):
    """If Redis client cannot be created, check_rate_limit returns (False, 0)."""
    import app.services.rate_limit as rl_module

    monkeypatch.setattr(rl_module, "_client", None)
    monkeypatch.setattr(rl_module, "_get_client", lambda: None)

    limited, retry_after = rl_module.check_rate_limit("test:key", 5, 900)
    assert limited is False
    assert retry_after == 0


def test_login_rate_limit_keys_lowercases_email():
    from app.services.rate_limit import rate_limit_keys
    ip_key, email_key = rate_limit_keys("login", "1.2.3.4", "User@Example.COM")
    assert "user@example.com" in email_key
    assert "1.2.3.4" in ip_key
    assert "User@Example.COM" not in email_key


def test_rate_limit_keys_are_namespaced_per_action():
    """Filling the login bucket must not lock the same user out of password reset."""
    from app.services.rate_limit import rate_limit_keys

    login_ip, login_email = rate_limit_keys("login", "1.2.3.4", "user@example.com")
    reset_ip, reset_email = rate_limit_keys("forgot_password", "1.2.3.4", "user@example.com")
    assert login_ip != reset_ip
    assert login_email != reset_email


def test_rate_limit_keys_omit_email_key_when_no_email():
    from app.services.rate_limit import rate_limit_keys

    ip_key, email_key = rate_limit_keys("verify_email", "1.2.3.4")
    assert ip_key
    assert email_key is None


# ---------------------------------------------------------------------------
# trusted_proxy_count is now a real, declared setting (GAPS #66)
#
# Before this, app/services/rate_limit.py read
# `getattr(settings, "trusted_proxy_count", 1)` — a field app/config.py never
# declared. Setting TRUSTED_PROXY_COUNT in the environment therefore reached
# `Settings()` and was silently dropped: pydantic-settings' default `extra`
# behaviour (inherited from pydantic, "ignore") means an unrecognised
# env/.env key does not raise at import, it just never becomes an attribute
# on the instance — so the getattr fallback of 1 always won regardless of
# what an operator set. That is the finding GAPS #66 asked to be verified.
# ---------------------------------------------------------------------------

def test_trusted_proxy_count_defaults_to_one():
    from app.config import Settings

    assert Settings().trusted_proxy_count == 1


def test_trusted_proxy_count_is_actually_settable_via_env(monkeypatch):
    """This is the regression test: before the field was declared, this
    would still read back as 1 no matter what the environment said."""
    from app.config import Settings

    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "3")
    assert Settings().trusted_proxy_count == 3


def test_undeclared_env_key_is_silently_ignored_not_rejected(monkeypatch):
    """Documents the actual pydantic-settings behaviour this gap relied on:
    an unrecognised environment key does not fail Settings() construction.
    This is what made the old getattr-fallback bug silent instead of loud."""
    from app.config import Settings

    monkeypatch.setenv("SOME_ENTIRELY_UNKNOWN_SETTING_XYZ", "whatever")
    # Must not raise.
    Settings()


def test_rate_limit_module_reads_trusted_proxy_count_from_settings():
    """Guards against reintroducing the getattr-fallback pattern: the
    module-level constant must come from the real settings field."""
    import app.services.rate_limit as rl_module
    from app.config import settings

    assert rl_module.TRUSTED_PROXY_HOPS == settings.trusted_proxy_count
