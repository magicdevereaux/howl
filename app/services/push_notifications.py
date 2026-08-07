"""
Push notification delivery via the Expo Push Notification service.

This module never raises for a delivery problem — it *classifies* one and hands
the classification back to the caller as a :class:`PushSendResult`.  The caller
(``app/tasks/notify.py``) decides what to do: prune dead tokens, retry with
backoff, or give up and log.  Programming errors are deliberately *not* caught,
so a bug here still surfaces as a failed task rather than a silent no-op.

Expo's send endpoint reports two very different kinds of failure:

* **Request-level** — a 4xx/5xx HTTP status, a network error, or a top-level
  ``errors`` array.  Nothing was delivered.
* **Ticket-level** — HTTP 200 with a ``data`` array of *push tickets*, one per
  message and in the same order the messages were sent.  Individual tickets can
  carry ``{"status": "error", "details": {"error": "<code>"}}`` while the
  request as a whole succeeded.  This is the case the old implementation missed
  entirely, which is why ``DeviceNotRegistered`` tokens were never pruned.

Only tickets are handled here, not receipts.  A ticket is Expo's own verdict on
the message ("accepted", "this token is dead", "you are sending too fast") and
it is the only signal that identifies a token as unusable at send time.
Receipts (``POST /--/api/v2/push/getReceipts``) carry the downstream FCM/APNs
verdict, are keyed by ticket id, and are only meaningful ~15 minutes later — so
consuming them requires persisting ticket ids and running a second scheduled
task.  That is a separate piece of work; see the note in the module docstring
of ``app/tasks/notify.py``.

Reference: https://docs.expo.dev/push-notifications/sending-notifications/
"""

import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_REQUEST_TIMEOUT_S = 10

# Expo rejects a request carrying more than 100 messages
# (request error ``PUSH_TOO_MANY_NOTIFICATIONS``), so send in chunks.
_MAX_MESSAGES_PER_REQUEST = 100

# --- documented ticket-level error codes -----------------------------------
ERROR_DEVICE_NOT_REGISTERED = "DeviceNotRegistered"
ERROR_MESSAGE_TOO_BIG = "MessageTooBig"
ERROR_MESSAGE_RATE_EXCEEDED = "MessageRateExceeded"
ERROR_INVALID_CREDENTIALS = "InvalidCredentials"
ERROR_MISMATCH_SENDER_ID = "MismatchSenderId"

#: The device can never receive a push on this token again — delete it.
_EXPIRED_TOKEN_ERRORS = frozenset({ERROR_DEVICE_NOT_REGISTERED})

#: "Slow down" — back off and send to the *same* token again later.  Explicitly
#: not a pruning condition: the token is perfectly valid.
_RATE_LIMIT_ERRORS = frozenset({ERROR_MESSAGE_RATE_EXCEEDED})

#: A definite verdict that retrying will not change.  ``MessageTooBig`` is our
#: payload's fault; the credential errors need an operator to rotate keys.
_PERMANENT_TICKET_ERRORS = frozenset(
    {ERROR_MESSAGE_TOO_BIG, ERROR_INVALID_CREDENTIALS, ERROR_MISMATCH_SENDER_ID}
)

#: Request-level error code that means "retry later" rather than "bad request".
_REQUEST_ERROR_TOO_MANY_REQUESTS = "TOO_MANY_REQUESTS"


@dataclass
class PushSendResult:
    """
    Outcome of one :func:`send_push_notifications` call.

    Every token handed in lands in exactly one bucket, so the caller can always
    account for what happened:

    ``accepted``
        Expo took the message (ticket ``status == "ok"``).  Note this means
        *Expo* accepted it, not that the device displayed it.
    ``expired_tokens``
        Ticket reported ``DeviceNotRegistered``.  Delete these rows.
    ``retry_tokens``
        Transient failure — the request never landed, or the ticket said
        ``MessageRateExceeded``, or the ticket was missing/unreadable so the
        outcome is genuinely unknown.  Resend to these after a backoff.
    ``failed_tokens``
        ``(token, error_code)`` pairs that failed permanently.  Retrying is
        pointless and pruning would be wrong, so these are dropped and logged.
    """

    accepted: list[str] = field(default_factory=list)
    expired_tokens: list[str] = field(default_factory=list)
    retry_tokens: list[str] = field(default_factory=list)
    failed_tokens: list[tuple[str, str]] = field(default_factory=list)
    #: Human-readable diagnostics for the request-level problems encountered.
    errors: list[str] = field(default_factory=list)
    #: Server-suggested delay from a ``Retry-After`` header, if one was sent.
    retry_after_s: int | None = None

    @property
    def should_retry(self) -> bool:
        """True when at least one token still needs delivering."""
        return bool(self.retry_tokens)

    def _merge(self, other: "PushSendResult") -> None:
        self.accepted += other.accepted
        self.expired_tokens += other.expired_tokens
        self.retry_tokens += other.retry_tokens
        self.failed_tokens += other.failed_tokens
        self.errors += other.errors
        if other.retry_after_s is not None:
            self.retry_after_s = max(self.retry_after_s or 0, other.retry_after_s)


def _retry_after_seconds(resp: httpx.Response) -> int | None:
    """Parse a numeric ``Retry-After`` header; ignore HTTP-date form."""
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0, int(float(raw.strip())))
    except (TypeError, ValueError):
        return None


def _request_error_codes(payload: object) -> list[str]:
    """Pull ``code`` values out of a top-level ``errors`` array, if present."""
    if not isinstance(payload, dict):
        return []
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return []
    return [e.get("code") or "" for e in errors if isinstance(e, dict)]


def _ticket_error_code(ticket: object) -> str | None:
    """
    Return the ticket's error code, ``None`` if the ticket is a success, or the
    sentinel ``""`` if the ticket cannot be interpreted at all.
    """
    if not isinstance(ticket, dict):
        return ""
    status = ticket.get("status")
    if status == "ok":
        return None
    if status != "error":
        return ""
    details = ticket.get("details")
    code = details.get("error") if isinstance(details, dict) else None
    return code if isinstance(code, str) and code else ""


def _classify_tickets(tokens: list[str], payload: object) -> PushSendResult:
    """Map an HTTP-200 response body onto per-token outcomes."""
    result = PushSendResult()

    tickets = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(tickets, list):
        # 200 but no usable ticket array — we have no idea what happened, so
        # treat the whole batch as unresolved rather than silently dropping it.
        result.retry_tokens += tokens
        result.errors.append("expo returned HTTP 200 with no 'data' ticket array")
        return result

    for index, token in enumerate(tokens):
        if index >= len(tickets):
            result.retry_tokens.append(token)
            result.errors.append(f"expo returned no ticket for message {index}")
            continue

        code = _ticket_error_code(tickets[index])

        if code is None:
            result.accepted.append(token)
        elif code in _EXPIRED_TOKEN_ERRORS:
            result.expired_tokens.append(token)
        elif code in _RATE_LIMIT_ERRORS:
            result.retry_tokens.append(token)
        elif code in _PERMANENT_TICKET_ERRORS:
            result.failed_tokens.append((token, code))
        elif code:
            # An explicit code we do not recognise is still a definite verdict.
            # Retrying it forever is as bad as never retrying, so fail it loudly.
            result.failed_tokens.append((token, code))
            result.errors.append(f"unrecognised expo ticket error {code!r}")
        else:
            # Malformed ticket — outcome unknown, so retry rather than drop.
            result.retry_tokens.append(token)
            result.errors.append(f"unreadable expo ticket for message {index}")

    return result


def _send_chunk(
    tokens: list[str],
    title: str,
    body: str,
    data: dict | None,
) -> PushSendResult:
    """Send up to ``_MAX_MESSAGES_PER_REQUEST`` messages in a single request."""
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
    except httpx.HTTPError as exc:
        # Connect/read timeouts, DNS failures, connection resets — nothing was
        # delivered and the next attempt may well succeed.
        logger.warning(
            "push_notifications: transport error sending to %d token(s): %s", len(tokens), exc
        )
        return PushSendResult(retry_tokens=list(tokens), errors=[f"transport error: {exc}"])

    try:
        payload: object = resp.json()
    except ValueError:
        payload = None

    if resp.status_code != 200:
        codes = _request_error_codes(payload)
        message = f"expo returned HTTP {resp.status_code} (codes={codes or 'none'})"
        retryable = (
            resp.status_code == 429
            or resp.status_code >= 500
            or _REQUEST_ERROR_TOO_MANY_REQUESTS in codes
        )
        if retryable:
            logger.warning("push_notifications: %s — will retry %d token(s)", message, len(tokens))
            return PushSendResult(
                retry_tokens=list(tokens),
                errors=[message],
                retry_after_s=_retry_after_seconds(resp),
            )
        # A 4xx that is not a rate limit means the request itself is wrong;
        # resending an identical body cannot help.
        logger.error("push_notifications: %s — not retrying", message)
        return PushSendResult(
            failed_tokens=[(t, f"HTTP {resp.status_code}") for t in tokens],
            errors=[message],
        )

    # HTTP 200. A top-level errors array here still means nothing was delivered.
    codes = _request_error_codes(payload)
    if codes:
        message = f"expo returned request errors {codes}"
        if _REQUEST_ERROR_TOO_MANY_REQUESTS in codes:
            logger.warning("push_notifications: %s — will retry", message)
            return PushSendResult(
                retry_tokens=list(tokens),
                errors=[message],
                retry_after_s=_retry_after_seconds(resp),
            )
        logger.error("push_notifications: %s — not retrying", message)
        return PushSendResult(
            failed_tokens=[(t, codes[0] or "UnknownRequestError") for t in tokens],
            errors=[message],
        )

    if payload is None:
        message = "expo returned HTTP 200 with an unparseable body"
        logger.warning("push_notifications: %s — will retry %d token(s)", message, len(tokens))
        return PushSendResult(retry_tokens=list(tokens), errors=[message])

    return _classify_tickets(tokens, payload)


def send_push_notifications(
    tokens: list[str],
    title: str,
    body: str,
    data: dict | None = None,
) -> PushSendResult:
    """
    Send the same notification to one or more Expo push tokens.

    Returns a :class:`PushSendResult` describing the outcome per token.  Never
    raises for a delivery failure; the caller is responsible for acting on
    ``expired_tokens`` (delete) and ``retry_tokens`` (resend after a backoff).
    """
    # De-duplicate while preserving order: a token repeated in one request would
    # give the device two banners and confuse the ticket-to-token mapping.
    unique: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token and token not in seen:
            seen.add(token)
            unique.append(token)

    result = PushSendResult()
    if not unique:
        return result

    for start in range(0, len(unique), _MAX_MESSAGES_PER_REQUEST):
        chunk = unique[start : start + _MAX_MESSAGES_PER_REQUEST]
        result._merge(_send_chunk(chunk, title, body, data))

    logger.info(
        "push_notifications: %r → %d accepted, %d expired, %d to retry, %d failed",
        title,
        len(result.accepted),
        len(result.expired_tokens),
        len(result.retry_tokens),
        len(result.failed_tokens),
    )
    for token, code in result.failed_tokens:
        logger.error(
            "push_notifications: permanent failure for token %s…: %s", token[:24], code
        )

    return result
