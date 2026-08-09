"""Auth consolidation and rate-limit hardening (GAPS #18, #25, #26).

Three things are covered here, all of which were untested before:

1. **The web/mobile drift bugs.** `app/api/auth.py` and `app/api/mobile_auth.py`
   were near-duplicates that had drifted apart, and CLAUDE.md flagged them as a
   standing hazard. They now delegate to `app/services/auth_service.py`. These
   tests pin the two concrete bugs that drift caused, so they cannot come back.

2. **X-Forwarded-For spoofing.** The IP bucket trusted the *first* XFF entry,
   which is the one an attacker gets to choose, so the limiter was trivially
   defeated by sending a fresh fake IP each request.

3. **The new limiter buckets and the resend-verification endpoint**, neither of
   which existed before.

Note the autouse `_open_login_rate_limit` fixture in conftest holds the limiter
open for the whole suite; tests here that exercise the limiter re-patch it in
their own body, which wins because it runs after the fixture.
"""

from datetime import UTC, datetime, timedelta

import pytest
from starlette.datastructures import Headers
from starlette.requests import Request

from app.models.user import AvatarStatus, User
from app.security import create_access_token, hash_password
from app.services import auth_service, rate_limit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_request(*, peer: str = "10.0.0.9", xff: str | None = None) -> Request:
    """A minimal ASGI scope — enough for client_ip()."""
    headers = {} if xff is None else {"x-forwarded-for": xff}
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/login",
        "headers": Headers(headers).raw,
        "client": (peer, 51234),
    }
    return Request(scope)


def _make_user(db, *, email: str, verified: bool = True, **kwargs) -> User:
    kwargs.setdefault("animal", "wolf")
    user = User(
        email=email,
        password_hash=hash_password("testpass1"),
        avatar_status=AvatarStatus.ready,
        is_email_verified=verified,
        **kwargs,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# #18 — the two drift bugs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/api/auth/login", "/api/mobile/auth/login"])
def test_refresh_token_ttl_comes_from_settings_not_a_hardcoded_30_days(
    client, db, monkeypatch, path
):
    """mobile_auth.py hardcoded timedelta(days=30) while web read the setting.

    Changing refresh_token_expire_days silently had no effect on mobile, which is
    the auth surface the shipped app actually uses. Driven through both login
    routes and asserted against the *stored* expiry, so the shared service is the
    only place the window can come from.
    """
    from app.config import settings
    from app.models.refresh_token import RefreshToken

    # A window that is nothing like the old hardcoded 30 days.
    monkeypatch.setattr(settings, "refresh_token_expire_days", 3)

    _make_user(db, email="ttl@howl.app")
    res = client.post(path, json={"email": "ttl@howl.app", "password": "testpass1"})
    assert res.status_code == 200, res.text

    record = db.query(RefreshToken).order_by(RefreshToken.id.desc()).first()
    assert record is not None, f"{path} issued no refresh token"

    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    days_out = (expires - datetime.now(UTC)).total_seconds() / 86400

    assert 2.9 < days_out < 3.1, (
        f"{path} issued a {days_out:.1f}-day refresh token instead of honouring "
        "settings.refresh_token_expire_days=3"
    )


def test_verification_and_password_reset_ttls_are_distinct():
    """mobile_auth.py used the 1-hour *password-reset* constant for verification.

    Mobile verification links therefore expired 24x sooner than web ones.
    """
    assert auth_service.VERIFICATION_TOKEN_EXPIRY_HOURS == 24
    assert auth_service.PASSWORD_RESET_TOKEN_EXPIRY_HOURS == 1
    assert (
        auth_service.VERIFICATION_TOKEN_EXPIRY_HOURS
        != auth_service.PASSWORD_RESET_TOKEN_EXPIRY_HOURS
    ), "verification is reusing the password-reset TTL again"


@pytest.mark.parametrize(
    ("web_path", "mobile_path"),
    [
        ("/api/auth/register", "/api/mobile/auth/register"),
        ("/api/auth/login", "/api/mobile/auth/login"),
        ("/api/auth/verify-email", "/api/mobile/auth/verify-email"),
        ("/api/auth/resend-verification", "/api/mobile/auth/resend-verification"),
    ],
)
def test_both_routers_expose_the_same_auth_surface(web_path, mobile_path):
    """Neither router may quietly grow or lose an endpoint the other has."""
    from app.main import app

    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert web_path in paths
    assert mobile_path in paths


# ---------------------------------------------------------------------------
# #26 — X-Forwarded-For spoofing
# ---------------------------------------------------------------------------

def test_client_ip_ignores_a_spoofed_leading_xff_entry(monkeypatch):
    """The first XFF entry is attacker-chosen and must never be the bucket key.

    With one trusted proxy, only the last entry was written by our own
    infrastructure; everything left of it came from the client.
    """
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 1)

    req = _fake_request(peer="172.16.0.1", xff="1.2.3.4, 203.0.113.7")
    assert rate_limit.client_ip(req) == "203.0.113.7"


def test_client_ip_cannot_be_moved_by_prepending_junk(monkeypatch):
    """A client sending a different fake IP per request must still share a bucket."""
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 1)

    seen = {
        rate_limit.client_ip(_fake_request(xff=f"10.9.9.{n}, 203.0.113.7"))
        for n in range(1, 20)
    }
    assert seen == {"203.0.113.7"}, "spoofed entries changed the rate-limit key"


def test_client_ip_reads_the_nth_entry_from_the_right(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 2)
    req = _fake_request(xff="1.2.3.4, 198.51.100.5, 203.0.113.7")
    assert rate_limit.client_ip(req) == "198.51.100.5"


def test_client_ip_falls_back_to_the_socket_peer(monkeypatch):
    """A header shorter than the trusted chain cannot have come from our proxies."""
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 2)

    assert rate_limit.client_ip(_fake_request(peer="192.0.2.50")) == "192.0.2.50"
    assert (
        rate_limit.client_ip(_fake_request(peer="192.0.2.50", xff="203.0.113.7"))
        == "192.0.2.50"
    )


def test_client_ip_ignores_the_header_entirely_with_no_proxies(monkeypatch):
    """Deployed without a proxy, XFF is pure attacker input and must be dropped."""
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 0)
    req = _fake_request(peer="192.0.2.50", xff="1.2.3.4")
    assert rate_limit.client_ip(req) == "192.0.2.50"


def test_client_ip_handles_a_missing_client(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 1)
    scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "client": None}
    assert rate_limit.client_ip(Request(scope)) == "unknown"


# ---------------------------------------------------------------------------
# #26 — the previously unthrottled endpoints
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/auth/register", {"email": "rl_reg@howl.app", "password": "testpass1"}),
        ("/api/auth/forgot-password", {"email": "rl_forgot@howl.app"}),
        ("/api/auth/reset-password", {"token": "nope", "new_password": "testpass1"}),
        ("/api/auth/verify-email", {"token": "nope"}),
        ("/api/auth/resend-verification", {"email": "rl_resend@howl.app"}),
    ],
)
def test_previously_unthrottled_endpoint_now_rate_limits(client, monkeypatch, path, payload):
    """Registration, reset, verify and resend were all unbounded before."""
    monkeypatch.setattr(
        "app.services.rate_limit.check_rate_limit",
        lambda *a, **kw: (True, 42),
    )
    res = client.post(path, json=payload)
    assert res.status_code == 429, f"{path} is still unthrottled"
    assert res.headers.get("Retry-After") == "42"


def test_rate_limit_buckets_are_namespaced_per_action():
    """One action filling its bucket must not lock a user out of the others."""
    actions = ["login", "register", "forgot_password", "reset_password",
               "verify_email", "resend_verification"]
    ip_keys = {rate_limit.rate_limit_keys(a, "1.1.1.1")[0] for a in actions}
    assert len(ip_keys) == len(actions), f"bucket keys collide: {sorted(ip_keys)}"


def test_rate_limiting_still_fails_open_on_redis_errors(client, db, monkeypatch):
    """A load-bearing convention: a Redis outage must not lock everyone out.

    See CLAUDE.md — rate_limit.py swallows Redis errors by design.
    """
    from redis import RedisError

    _make_user(db, email="failopen@howl.app")

    class Boom:
        def incr(self, *a, **kw):
            raise RedisError("redis is down")

    monkeypatch.setattr("app.services.rate_limit._get_client", lambda: Boom())
    limited, retry_after = rate_limit.check_rate_limit("rl:login:ip:1.1.1.1", 5, 60)
    assert limited is False
    assert retry_after == 0

    res = client.post(
        "/api/auth/login",
        json={"email": "failopen@howl.app", "password": "testpass1"},
    )
    assert res.status_code == 200, "a Redis outage blocked a valid login"


# ---------------------------------------------------------------------------
# #25 — resend verification, and the dependency that is deliberately unwired
# ---------------------------------------------------------------------------

def test_resend_verification_issues_a_fresh_token(client, db):
    user = _make_user(db, email="resend@howl.app", verified=False)
    user.email_verification_token = "stale-token"
    user.email_verification_token_expires_at = datetime.now(UTC) - timedelta(hours=5)
    db.commit()

    res = client.post("/api/auth/resend-verification", json={"email": "resend@howl.app"})
    assert res.status_code == 200

    db.refresh(user)
    assert user.email_verification_token not in (None, "stale-token")
    expires = user.email_verification_token_expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    # A 24-hour window, not the 1-hour password-reset one.
    assert expires > datetime.now(UTC) + timedelta(hours=23)


def test_resend_verification_does_not_reveal_whether_an_account_exists(client, db):
    """Same body for a real unverified user, a verified one, and a stranger."""
    _make_user(db, email="known_unverified@howl.app", verified=False)
    _make_user(db, email="known_verified@howl.app", verified=True)

    bodies = [
        client.post("/api/auth/resend-verification", json={"email": e}).json()
        for e in (
            "known_unverified@howl.app",
            "known_verified@howl.app",
            "total_stranger@howl.app",
        )
    ]
    assert len({str(b) for b in bodies}) == 1, f"responses differ and leak state: {bodies}"


def test_mobile_resend_verification_works_too(client, db):
    """mobile_auth had no resend path at all, so a mobile user was simply stuck."""
    _make_user(db, email="mobile_resend@howl.app", verified=False)
    res = client.post(
        "/api/mobile/auth/resend-verification",
        json={"email": "mobile_resend@howl.app"},
    )
    assert res.status_code == 200


def test_require_verified_email_rejects_an_unverified_account_past_grace(db):
    """Enforcement is graduated, so the account has to be past its grace window.

    A freshly created unverified account is deliberately *allowed* -- see
    test_email_enforcement.py, which owns the full matrix.
    """
    from fastapi import HTTPException

    from app.dependencies import require_verified_email

    unverified = _make_user(
        db,
        email="unverified_dep@howl.app",
        verified=False,
        created_at=datetime.now(UTC) - timedelta(days=100),
    )
    with pytest.raises(HTTPException) as exc:
        require_verified_email(current_user=unverified)
    # 403 not 401: the caller authenticated fine, re-authenticating won't help.
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "email_verification_required"


def test_require_verified_email_allows_an_unverified_account_inside_grace(db):
    """The grace window is what makes enabling enforcement survivable."""
    from app.dependencies import require_verified_email

    fresh = _make_user(
        db,
        email="unverified_fresh@howl.app",
        verified=False,
        created_at=datetime.now(UTC),
    )
    assert require_verified_email(current_user=fresh) is fresh


def test_require_verified_email_allows_a_verified_account(db):
    from app.dependencies import require_verified_email

    verified = _make_user(db, email="verified_dep@howl.app", verified=True)
    assert require_verified_email(current_user=verified) is verified


def test_require_verified_email_is_wired_to_the_outbound_routes():
    """Enforcement is on (GAPS #25). This is the inverse of the test it replaces.

    The predecessor asserted the dependency was attached to *no* route, because
    the rollout was still a product decision. It has been made: enforcement is
    graduated behind a grace window derived from `created_at`, with a config kill
    switch, and only the outbound actions are gated.

    Kept here as a tripwire so an auth refactor that silently drops the gate
    fails in the auth suite too, not only in test_email_enforcement.py. That
    file owns the behavioural coverage, including the exact 403 contract.
    """
    from app.dependencies import require_verified_email
    from app.main import app

    wired = set()
    for route in app.routes:
        for dep in getattr(getattr(route, "dependant", None), "dependencies", []):
            if getattr(dep, "call", None) is require_verified_email:
                for method in sorted(getattr(route, "methods", set()) or {"WS"}):
                    wired.add(f"{method} {route.path}")

    assert wired == {
        "POST /api/swipes",
        "DELETE /api/swipes/last",
        "POST /api/matches/{match_id}/messages",
        "POST /api/avatar/regenerate",
    }, f"the gated route set changed: {sorted(wired)}"


# ---------------------------------------------------------------------------
# #6 regression — password reset still revokes sessions after the refactor
# ---------------------------------------------------------------------------

def test_password_reset_still_revokes_refresh_tokens(client, db):
    """Closed in b2efe68; the auth refactor moved this code, so re-pin it."""
    from app.models.password_reset_token import PasswordResetToken
    from app.models.refresh_token import RefreshToken

    user = _make_user(db, email="revoke@howl.app")
    db.add(RefreshToken(
        user_id=user.id,
        token="live-session-token",
        expires_at=datetime.now(UTC) + timedelta(days=10),
    ))
    # Reset tokens live in their own table, not on the user row.
    db.add(PasswordResetToken(
        user_id=user.id,
        token="reset-me",
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    ))
    db.commit()

    res = client.post(
        "/api/auth/reset-password",
        json={"token": "reset-me", "new_password": "brandnewpass9"},
    )
    assert res.status_code == 200

    # Revocation flips a flag rather than deleting rows, so the audit trail of
    # which sessions existed survives. What must not survive is a *usable* one.
    live = (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user.id, RefreshToken.revoked == False)  # noqa: E712
        .count()
    )
    assert live == 0, "a user resetting a compromised password stays compromised"

    # And the reset token itself is single-use.
    replay = client.post(
        "/api/auth/reset-password",
        json={"token": "reset-me", "new_password": "anotherpass9"},
    )
    assert replay.status_code == 400, "the reset token was replayable"


def test_access_token_still_resolves_from_cookie_and_bearer(client, db):
    """The deliberate cookie-or-bearer unification must survive the refactor.

    CLAUDE.md calls this out as correct and intentional.
    """
    user = _make_user(db, email="both_auth@howl.app")
    token = create_access_token(user.id)

    by_cookie = client.get("/api/profile/me", headers={"Cookie": f"access_token={token}"})
    by_bearer = client.get("/api/profile/me", headers={"Authorization": f"Bearer {token}"})

    assert by_cookie.status_code == 200
    assert by_bearer.status_code == 200
    assert by_cookie.json()["email"] == by_bearer.json()["email"] == "both_auth@howl.app"
