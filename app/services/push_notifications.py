"""
Push notification delivery via the Expo Push Notification service.

Fail-open: any error talking to the Expo push API is logged and swallowed so
a notification failure never breaks the request/task that triggered it.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_REQUEST_TIMEOUT_S = 10


def send_push_notifications(
    tokens: list[str],
    title: str,
    body: str,
    data: dict | None = None,
) -> None:
    """Send the same notification to one or more Expo push tokens."""
    tokens = [t for t in tokens if t]
    if not tokens:
        return

    messages = [
        {
            "to": token,
            "title": title,
            "body": body,
            "data": data or {},
            "sound": "default",
        }
        for token in tokens
    ]

    try:
        resp = httpx.post(
            _EXPO_PUSH_URL,
            json=messages,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=_REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
        logger.info("push_notifications: sent %d notification(s): %r", len(tokens), title)
    except Exception:
        logger.exception("push_notifications: failed to send to %d token(s)", len(tokens))
