"""
Email delivery.

Until now every function in this module was a `print()`. That is fine in dev —
you copy the link out of the terminal — but in production it meant password
reset and email verification tokens were written to the Railway log stream and
nothing was ever delivered to a user. With email verification now enforced
after a 72-hour grace window (GAPS #25), "no provider" is not a cosmetic gap:
an account whose grace period lapses is locked out with no way to receive the
link that would unlock it.

Three backends, chosen by `settings.email_backend`:

* ``console`` — the old behaviour, kept verbatim. Prints the link with a banner.
  This is the default when nothing is configured, so a fresh clone still works
  and the developer experience does not change.
* ``resend`` — HTTPS POST to the Resend API. Chosen because it needs no new
  dependency: `httpx` is already vendored for the avatar image download.
* ``smtp`` — stdlib `smtplib`, for anyone with an existing relay (SES, Postmark,
  Mailgun all speak SMTP).

``auto`` (the default) picks ``resend`` if an API key is set, else ``smtp`` if a
host is set, else ``console``. So configuring a provider is purely additive: set
the env vars and delivery starts; unset them and you are back to printing.

Two deliberate decisions worth defending
----------------------------------------

**Delivery is synchronous and bounded, not queued.** These functions are called
from request handlers in `app/services/auth_service.py`. Routing them through
Celery would take them off the request path, but it would also make delivery
depend on a worker being up — and a worker that is not running is *the*
documented production failure of this deployment (CLAUDE.md gotcha #5; the
Celery services are not started by `startup.sh`). A password-reset email that
silently never sends because nobody drained the queue is worse than one that
costs the request a few hundred milliseconds. `settings.email_timeout_seconds`
bounds the blocking so a hanging provider cannot park a threadpool worker the
way an unbounded call did in GAPS-ROUND-2 #43.

**A send failure never raises.** Same posture as every other outbound
dependency here (rate limiting, pub/sub, task locks, task enqueue): the caller's
transaction is already committed, and failing the request would neither un-send
the email nor help the user. Failures log at `error`, so Sentry — wired in
`app/main.py` — carries them. Callers that need to know can check the bool.
"""

import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)

_RESEND_ENDPOINT = "https://api.resend.com/emails"


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def _resolve_backend() -> str:
    """Return the backend to use: ``console``, ``resend`` or ``smtp``.

    Resolved per call rather than cached at import so that tests (and an
    operator flipping an env var) get the current value.
    """
    configured = (settings.email_backend or "auto").strip().lower()
    if configured != "auto":
        return configured

    if settings.resend_api_key:
        return "resend"
    if settings.smtp_host:
        return "smtp"
    return "console"


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def _deliver_console(to_email: str, subject: str, text_body: str) -> bool:
    """Print the message. The historical dev-mode behaviour, unchanged."""
    separator = "=" * 60
    print(f"\n{separator}")
    print(f"  {subject.upper()} (console mode — no email sent)")
    print(f"  To: {to_email}")
    for line in text_body.strip().splitlines():
        print(f"  {line}")
    print(f"{separator}\n")
    return True


def _deliver_resend(to_email: str, subject: str, text_body: str, html_body: str) -> bool:
    # Imported lazily, matching how boto3/openai are handled in
    # app/services/image_generation.py — the module must import cleanly in an
    # environment that never sends mail.
    import httpx

    try:
        response = httpx.post(
            _RESEND_ENDPOINT,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.email_from,
                "to": [to_email],
                "subject": subject,
                "text": text_body,
                "html": html_body,
            },
            timeout=settings.email_timeout_seconds,
        )
    except Exception:
        logger.exception("email: Resend request failed for %s", to_email)
        return False

    if response.status_code >= 400:
        # Body, not just status: Resend puts the actionable part ("domain is not
        # verified", "invalid to address") in the JSON, and an operator reading
        # a bare 403 in Sentry has nothing to act on.
        logger.error(
            "email: Resend rejected message to %s — %s %s",
            to_email, response.status_code, response.text[:500],
        )
        return False

    logger.info("email: delivered %r to %s via Resend", subject, to_email)
    return True


def _deliver_smtp(to_email: str, subject: str, text_body: str, html_body: str) -> bool:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.email_from
    message["To"] = to_email
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    try:
        smtp_class = smtplib.SMTP_SSL if settings.smtp_use_ssl else smtplib.SMTP
        with smtp_class(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.email_timeout_seconds,
        ) as server:
            if settings.smtp_use_tls and not settings.smtp_use_ssl:
                server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password or "")
            server.send_message(message)
    except Exception:
        logger.exception("email: SMTP delivery failed for %s", to_email)
        return False

    logger.info("email: delivered %r to %s via SMTP", subject, to_email)
    return True


def _deliver(to_email: str, subject: str, text_body: str, html_body: str) -> bool:
    """Dispatch to the resolved backend. Never raises."""
    backend = _resolve_backend()

    if backend == "resend":
        return _deliver_resend(to_email, subject, text_body, html_body)
    if backend == "smtp":
        return _deliver_smtp(to_email, subject, text_body, html_body)
    if backend != "console":
        # A typo in EMAIL_BACKEND must not silently drop mail on the floor.
        logger.error("email: unknown backend %r — falling back to console", backend)

    return _deliver_console(to_email, subject, text_body)


# ---------------------------------------------------------------------------
# Templates
#
# Deliberately plain: inline styles only, no external assets, no tracking, and
# a text/plain alternative that carries the whole message. A link-only HTML mail
# with no text part is the fastest way onto a spam list for a new domain.
# ---------------------------------------------------------------------------

def _wrap_html(heading: str, body_html: str) -> str:
    return (
        '<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;'
        'max-width:480px;margin:0 auto;padding:24px;color:#1a1a1a">'
        f'<h1 style="font-size:22px;margin:0 0 16px">{heading}</h1>'
        f"{body_html}"
        '<p style="font-size:12px;color:#777;margin-top:32px">'
        "Howl — your spirit animal is waiting.</p>"
        "</div>"
    )


def _button(url: str, label: str) -> str:
    return (
        f'<p style="margin:24px 0"><a href="{url}" '
        'style="background:#6B3FA0;color:#fff;padding:12px 20px;border-radius:8px;'
        f'text-decoration:none;display:inline-block">{label}</a></p>'
        f'<p style="font-size:13px;color:#555">Or paste this into your browser:<br>{url}</p>'
    )


# ---------------------------------------------------------------------------
# Public API — signatures unchanged, so every existing caller and test patch
# point keeps working.
# ---------------------------------------------------------------------------

def send_password_reset_email(to_email: str, reset_token: str) -> bool:
    """Send a password-reset link. Returns whether delivery succeeded."""
    # `{frontend_url}?token=…` rather than `/reset-password?token=…`: the web
    # client captures the token from the query string at whatever path it lands
    # on, before routing, and strips it from the URL afterwards. The shape is a
    # contract with `frontend/src/App.jsx` — do not "tidy" it without changing
    # both sides.
    reset_link = f"{settings.frontend_url}?token={reset_token}"

    text = (
        "Someone asked to reset your Howl password.\n\n"
        f"Reset it here: {reset_link}\n\n"
        "If that wasn't you, ignore this email — nothing has changed."
    )
    html = _wrap_html(
        "Reset your password",
        "<p>Someone asked to reset your Howl password.</p>"
        + _button(reset_link, "Reset password")
        + '<p style="font-size:13px;color:#555">'
        "If that wasn't you, ignore this email — nothing has changed.</p>",
    )

    delivered = _deliver(to_email, "Reset your Howl password", text, html)
    logger.info("password_reset: link issued for %s (delivered=%s)", to_email, delivered)
    return delivered


def send_verification_email(to_email: str, token: str) -> bool:
    """Send an email-verification link. Returns whether delivery succeeded."""
    verify_link = f"{settings.frontend_url}?verify={token}"

    text = (
        "Welcome to Howl! Confirm your email address to keep your account active.\n\n"
        f"Verify here: {verify_link}\n\n"
        f"You have {settings.email_verification_grace_period_hours} hours of full "
        "access before verification is required."
    )
    html = _wrap_html(
        "Confirm your email",
        "<p>Welcome to Howl! Confirm your email address to keep your account active.</p>"
        + _button(verify_link, "Verify email")
        + '<p style="font-size:13px;color:#555">You have '
        f"{settings.email_verification_grace_period_hours} hours of full access "
        "before verification is required.</p>",
    )

    delivered = _deliver(to_email, "Confirm your Howl email", text, html)
    logger.info("email_verification: link issued for %s (delivered=%s)", to_email, delivered)
    return delivered


def send_email_changed_notice(old_email: str, new_email: str) -> bool:
    """Warn the *previous* address that the account moved.

    Sent to the address that is losing the account, not the one gaining it. If
    an attacker who has both a session and the password changes the address,
    this notice is the only signal the real owner ever gets — so it is worth
    sending even though the change itself was authenticated.
    """
    text = (
        "The email address on your Howl account was changed to "
        f"{new_email}.\n\n"
        "If you did not do this, reset your password immediately at "
        f"{settings.frontend_url} — whoever made the change knew your password."
    )
    html = _wrap_html(
        "Your email address was changed",
        "<p>The email address on your Howl account was changed to "
        f"<strong>{new_email}</strong>.</p>"
        '<p style="font-size:13px;color:#555">If you did not do this, reset your '
        "password immediately — whoever made the change knew your password.</p>"
        + _button(settings.frontend_url, "Go to Howl"),
    )

    return _deliver(old_email, "Your Howl email address was changed", text, html)


def send_message_notification(
    to_email: str,
    sender_name: str | None,
    sender_animal: str | None,
) -> bool:
    """Tell a user a match has messaged them.

    Message content is deliberately excluded for privacy — only the sender's
    name and spirit animal.
    """
    display_name = sender_name or "Someone"
    display_animal = sender_animal.capitalize() if sender_animal else "Unknown"

    text = (
        f"{display_name} ({display_animal}) sent you a message on Howl.\n\n"
        f"Open Howl to read it: {settings.frontend_url}"
    )
    html = _wrap_html(
        "You have a new message",
        f"<p><strong>{display_name}</strong> "
        f'<span style="color:#6B3FA0">({display_animal})</span> '
        "sent you a message on Howl.</p>"
        + _button(settings.frontend_url, "Open Howl"),
    )

    delivered = _deliver(to_email, f"{display_name} sent you a message", text, html)
    logger.info(
        "message_notification: issued to %s from %s (delivered=%s)",
        to_email, display_name, delivered,
    )
    return delivered
