"""GAPS #3 — a real email provider behind the print() statements.

What matters here is not the HTML. It is that (a) an unconfigured deployment
still behaves exactly as before, (b) a configured one actually sends, and (c) a
provider outage cannot take down a request, because these run inline in the
auth routes and the caller's work is already committed.
"""

import smtplib

import pytest

from app.services import email as email_service


@pytest.fixture()
def console_backend(monkeypatch):
    monkeypatch.setattr(email_service.settings, "email_backend", "auto")
    monkeypatch.setattr(email_service.settings, "resend_api_key", None)
    monkeypatch.setattr(email_service.settings, "smtp_host", None)


# ---------------------------------------------------------------------------
# Backend resolution
# ---------------------------------------------------------------------------

def test_unconfigured_deployment_still_prints(console_backend, capsys):
    """The default must not change for a fresh clone."""
    assert email_service._resolve_backend() == "console"
    assert email_service.send_password_reset_email("wolf@howl.app", "tok123") is True

    out = capsys.readouterr().out
    assert "tok123" in out
    assert "console mode" in out


def test_resend_wins_when_an_api_key_is_set(monkeypatch):
    monkeypatch.setattr(email_service.settings, "email_backend", "auto")
    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.example.com")
    assert email_service._resolve_backend() == "resend"


def test_smtp_is_used_when_only_a_host_is_set(monkeypatch):
    monkeypatch.setattr(email_service.settings, "email_backend", "auto")
    monkeypatch.setattr(email_service.settings, "resend_api_key", None)
    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.example.com")
    assert email_service._resolve_backend() == "smtp"


def test_an_explicit_backend_overrides_autodetection(monkeypatch):
    monkeypatch.setattr(email_service.settings, "email_backend", "console")
    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    assert email_service._resolve_backend() == "console"


def test_a_typo_in_the_backend_name_falls_back_to_console(monkeypatch, capsys, caplog):
    """A misconfigured EMAIL_BACKEND must not silently drop mail."""
    monkeypatch.setattr(email_service.settings, "email_backend", "resned")
    assert email_service.send_verification_email("wolf@howl.app", "tok") is True
    assert "unknown backend" in caplog.text
    assert "tok" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Resend
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def _use_resend(monkeypatch):
    monkeypatch.setattr(email_service.settings, "email_backend", "resend")
    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")


def test_resend_send_posts_the_expected_payload(monkeypatch):
    _use_resend(monkeypatch)
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return _FakeResponse(200)

    monkeypatch.setattr("httpx.post", fake_post)

    assert email_service.send_password_reset_email("wolf@howl.app", "tok123") is True
    assert captured["url"] == email_service._RESEND_ENDPOINT
    assert captured["headers"]["Authorization"] == "Bearer re_test"
    assert captured["json"]["to"] == ["wolf@howl.app"]
    assert "tok123" in captured["json"]["text"]
    assert "tok123" in captured["json"]["html"]
    # Both parts are required: a link-only HTML mail with no text/plain
    # alternative is the fastest way onto a spam list for a new domain.
    assert captured["json"]["text"] and captured["json"]["html"]
    assert captured["timeout"] == email_service.settings.email_timeout_seconds


def test_resend_rejection_is_reported_not_raised(monkeypatch, caplog):
    _use_resend(monkeypatch)
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **kw: _FakeResponse(403, '{"message":"domain is not verified"}'),
    )

    assert email_service.send_verification_email("wolf@howl.app", "tok") is False
    # The body, not just the status — a bare 403 in Sentry is unactionable.
    assert "domain is not verified" in caplog.text


def test_a_provider_outage_does_not_raise(monkeypatch, caplog):
    """The request that triggered this has already committed. It must not 500."""
    _use_resend(monkeypatch)

    def explode(*_a, **_kw):
        raise OSError("connection reset by peer")

    monkeypatch.setattr("httpx.post", explode)

    assert email_service.send_password_reset_email("wolf@howl.app", "tok") is False
    assert "Resend request failed" in caplog.text


# ---------------------------------------------------------------------------
# SMTP
# ---------------------------------------------------------------------------

class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.started_tls = False
        self.logged_in_as = None
        self.sent = []
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in_as = user

    def send_message(self, message):
        self.sent.append(message)


def test_smtp_send_starts_tls_logs_in_and_sends_both_parts(monkeypatch):
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(email_service.settings, "email_backend", "smtp")
    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(email_service.settings, "smtp_username", "howl")
    monkeypatch.setattr(email_service.settings, "smtp_password", "secret")
    monkeypatch.setattr(email_service.settings, "smtp_use_tls", True)
    monkeypatch.setattr(email_service.settings, "smtp_use_ssl", False)
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    assert email_service.send_message_notification("wolf@howl.app", "Ada", "otter") is True

    server = _FakeSMTP.instances[0]
    assert server.started_tls is True
    assert server.logged_in_as == "howl"
    message = server.sent[0]
    assert message["To"] == "wolf@howl.app"
    assert "Ada" in message["Subject"]
    assert message.is_multipart()


def test_smtp_failure_is_reported_not_raised(monkeypatch, caplog):
    monkeypatch.setattr(email_service.settings, "email_backend", "smtp")
    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.example.com")

    def explode(*_a, **_kw):
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(smtplib, "SMTP", explode)

    assert email_service.send_verification_email("wolf@howl.app", "tok") is False
    assert "SMTP delivery failed" in caplog.text


# ---------------------------------------------------------------------------
# The link shape is a contract with the web client
# ---------------------------------------------------------------------------

def test_reset_and_verify_links_keep_the_query_shape_the_client_parses(monkeypatch):
    """`frontend/src/App.jsx` reads `?token=` / `?verify=` off the landing URL.

    Changing these to path-based links silently breaks both flows, and neither
    has an end-to-end test that would catch it.
    """
    _use_resend(monkeypatch)
    sent = []
    monkeypatch.setattr(
        "httpx.post",
        lambda url, headers=None, json=None, timeout=None: (
            sent.append(json) or _FakeResponse(200)
        ),
    )
    monkeypatch.setattr(email_service.settings, "frontend_url", "https://howl.app")

    email_service.send_password_reset_email("wolf@howl.app", "abc")
    email_service.send_verification_email("wolf@howl.app", "xyz")

    assert "https://howl.app?token=abc" in sent[0]["text"]
    assert "https://howl.app?verify=xyz" in sent[1]["text"]
