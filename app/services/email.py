"""
Email delivery service.

Development mode: reset links are printed to stdout so they can be copied
from the server logs without any email infrastructure.

Production upgrade path: replace the body of send_password_reset_email with
a call to SendGrid, AWS SES, Resend, etc.  The signature stays the same.
"""

import logging

from app.config import settings

logger = logging.getLogger(__name__)


def send_password_reset_email(to_email: str, reset_token: str) -> None:
    """Send a password-reset link to the given address.

    Currently logs the link to stdout (dev / portfolio mode).
    Swap the body for a real SMTP / transactional-email call in production.
    """
    reset_link = f"{settings.frontend_url}?token={reset_token}"

    # ── Dev: print link so it can be copied from logs ───────────────────────
    separator = "=" * 60
    print(f"\n{separator}")
    print(f"  PASSWORD RESET (dev mode — no email sent)")
    print(f"  To:   {to_email}")
    print(f"  Link: {reset_link}")
    print(f"{separator}\n")
    logger.info("password_reset: link generated for %s", to_email)

    # ── Production: see commented-out providers below ──────────────────────────


def send_message_notification(
    to_email: str,
    sender_name: str | None,
    sender_animal: str | None,
) -> None:
    """Notify a user that a match has sent them a new message.

    Message content is intentionally excluded for privacy — only the sender's
    name and spirit animal are included.
    Currently logs to stdout (dev / portfolio mode).
    """
    display_name = sender_name or "Someone"
    display_animal = sender_animal.capitalize() if sender_animal else "Unknown"

    separator = "=" * 60
    print(f"\n{separator}")
    print(f"  NEW MESSAGE NOTIFICATION (dev mode — no email sent)")
    print(f"  To:     {to_email}")
    print(f"  From:   {display_name} (spirit animal: {display_animal})")
    print(f"  Open Howl to read your message.")
    print(f"{separator}\n")
    logger.info("message_notification: sent to %s from %s", to_email, display_name)

    # ── Production: see commented-out providers below ──────────────────────────
    #
    # --- SendGrid ---
    # import sendgrid
    # from sendgrid.helpers.mail import Mail
    # sg = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)
    # msg = Mail(from_email="noreply@howl.app", to_emails=to_email,
    #            subject="Reset your Howl password",
    #            html_content=f'<a href="{reset_link}">Reset password</a>')
    # sg.send(msg)
    #
    # --- AWS SES (boto3) ---
    # import boto3
    # ses = boto3.client("ses", region_name="us-east-1")
    # ses.send_email(Source="noreply@howl.app",
    #                Destination={"ToAddresses": [to_email]},
    #                Message={"Subject": {"Data": "Reset your Howl password"},
    #                         "Body": {"Text": {"Data": f"Reset link: {reset_link}"}}})
