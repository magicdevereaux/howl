"""
Unit tests for app/services/push_notifications.py.

This module used to be entirely unexercised (GAPS #30 — "never called, only
mocked at their call sites"), so these are its first real tests.  ``httpx.post``
is patched at its use site inside the service; nothing here touches the network.

The interesting behaviour is the classification of Expo's *push tickets*, which
arrive inside an HTTP 200 body and can report per-message errors while the
request as a whole succeeded.
"""

from unittest.mock import patch

import httpx
import pytest

from app.services.push_notifications import (
    _EXPO_PUSH_URL,
    _MAX_MESSAGES_PER_REQUEST,
    PushSendResult,
    send_push_notifications,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQUEST = httpx.Request("POST", _EXPO_PUSH_URL)


def _response(status_code: int = 200, payload=None, *, text=None, headers=None) -> httpx.Response:
    if text is not None:
        return httpx.Response(status_code, text=text, headers=headers, request=_REQUEST)
    return httpx.Response(status_code, json=payload, headers=headers, request=_REQUEST)


def _ok_ticket(ticket_id: str = "ticket-1") -> dict:
    return {"status": "ok", "id": ticket_id}


def _error_ticket(code: str) -> dict:
    return {"status": "error", "message": f"something about {code}", "details": {"error": code}}


def _tickets(*items) -> dict:
    return {"data": list(items)}


def _send(response=None, *, side_effect=None, tokens=("ExponentPushToken[a]",)):
    """Run send_push_notifications with httpx.post patched; returns (result, mock)."""
    kwargs = {"side_effect": side_effect} if side_effect else {"return_value": response}
    with patch("app.services.push_notifications.httpx.post", **kwargs) as post:
        result = send_push_notifications(
            list(tokens), title="New match!", body="You matched with an owl",
            data={"type": "match", "match_id": 7},
        )
    return result, post


# ---------------------------------------------------------------------------
# Request construction
# ---------------------------------------------------------------------------

def test_no_request_made_for_empty_token_list():
    result, post = _send(_response(200, _tickets()), tokens=[])
    assert post.call_count == 0
    assert result == PushSendResult()


def test_blank_tokens_are_dropped_without_a_request():
    result, post = _send(_response(200, _tickets()), tokens=["", None])
    assert post.call_count == 0
    assert result.accepted == []


def test_message_payload_shape():
    _, post = _send(_response(200, _tickets(_ok_ticket())), tokens=["ExponentPushToken[a]"])

    messages = post.call_args.kwargs["json"]
    assert messages == [{
        "to": "ExponentPushToken[a]",
        "title": "New match!",
        "body": "You matched with an owl",
        "data": {"type": "match", "match_id": 7},
        "sound": "default",
    }]


def test_duplicate_tokens_are_sent_once():
    """A repeated token would double-notify the device and skew ticket mapping."""
    result, post = _send(
        _response(200, _tickets(_ok_ticket())),
        tokens=["ExponentPushToken[a]", "ExponentPushToken[a]"],
    )
    assert len(post.call_args.kwargs["json"]) == 1
    assert result.accepted == ["ExponentPushToken[a]"]


def test_requests_are_chunked_at_the_expo_limit():
    """Expo rejects >100 messages per request (PUSH_TOO_MANY_NOTIFICATIONS)."""
    tokens = [f"ExponentPushToken[{i}]" for i in range(_MAX_MESSAGES_PER_REQUEST + 5)]
    responses = [
        _response(200, _tickets(*[_ok_ticket() for _ in range(_MAX_MESSAGES_PER_REQUEST)])),
        _response(200, _tickets(*[_ok_ticket() for _ in range(5)])),
    ]
    result, post = _send(side_effect=responses, tokens=tokens)

    assert post.call_count == 2
    assert len(post.call_args_list[0].kwargs["json"]) == _MAX_MESSAGES_PER_REQUEST
    assert len(post.call_args_list[1].kwargs["json"]) == 5
    assert len(result.accepted) == len(tokens)


# ---------------------------------------------------------------------------
# Ticket classification
# ---------------------------------------------------------------------------

def test_all_ok_tickets_are_accepted():
    result, _ = _send(
        _response(200, _tickets(_ok_ticket("t1"), _ok_ticket("t2"))),
        tokens=["ExponentPushToken[a]", "ExponentPushToken[b]"],
    )
    assert result.accepted == ["ExponentPushToken[a]", "ExponentPushToken[b]"]
    assert result.expired_tokens == []
    assert result.should_retry is False


def test_device_not_registered_marks_token_expired():
    result, _ = _send(
        _response(200, _tickets(_error_ticket("DeviceNotRegistered"))),
        tokens=["ExponentPushToken[dead]"],
    )
    assert result.expired_tokens == ["ExponentPushToken[dead]"]
    assert result.accepted == []
    # A dead token must never be retried — that is the bug this replaces.
    assert result.should_retry is False


def test_ticket_errors_map_to_the_right_token_by_position():
    """Expo returns tickets in the order the messages were sent."""
    result, _ = _send(
        _response(200, _tickets(
            _ok_ticket(), _error_ticket("DeviceNotRegistered"), _ok_ticket(),
        )),
        tokens=["ExponentPushToken[a]", "ExponentPushToken[dead]", "ExponentPushToken[c]"],
    )
    assert result.expired_tokens == ["ExponentPushToken[dead]"]
    assert result.accepted == ["ExponentPushToken[a]", "ExponentPushToken[c]"]


def test_message_rate_exceeded_backs_off_and_does_not_prune():
    result, _ = _send(
        _response(200, _tickets(_error_ticket("MessageRateExceeded"))),
        tokens=["ExponentPushToken[busy]"],
    )
    assert result.retry_tokens == ["ExponentPushToken[busy]"]
    assert result.expired_tokens == []      # the token is valid — do not delete it
    assert result.failed_tokens == []
    assert result.should_retry is True


@pytest.mark.parametrize("code", ["MessageTooBig", "InvalidCredentials", "MismatchSenderId"])
def test_permanent_ticket_errors_are_neither_retried_nor_pruned(code):
    result, _ = _send(
        _response(200, _tickets(_error_ticket(code))), tokens=["ExponentPushToken[a]"],
    )
    assert result.failed_tokens == [("ExponentPushToken[a]", code)]
    assert result.expired_tokens == []
    assert result.should_retry is False


def test_unknown_ticket_error_code_is_terminal_not_retried_forever():
    result, _ = _send(
        _response(200, _tickets(_error_ticket("SomeBrandNewExpoError"))),
        tokens=["ExponentPushToken[a]"],
    )
    assert result.failed_tokens == [("ExponentPushToken[a]", "SomeBrandNewExpoError")]
    assert result.should_retry is False
    assert any("SomeBrandNewExpoError" in e for e in result.errors)


def test_error_ticket_without_details_is_retried_as_unknown_outcome():
    result, _ = _send(
        _response(200, {"data": [{"status": "error", "message": "no details here"}]}),
        tokens=["ExponentPushToken[a]"],
    )
    assert result.retry_tokens == ["ExponentPushToken[a]"]
    assert result.expired_tokens == []


def test_missing_ticket_for_a_message_is_retried():
    result, _ = _send(
        _response(200, _tickets(_ok_ticket())),
        tokens=["ExponentPushToken[a]", "ExponentPushToken[b]"],
    )
    assert result.accepted == ["ExponentPushToken[a]"]
    assert result.retry_tokens == ["ExponentPushToken[b]"]


# ---------------------------------------------------------------------------
# Malformed responses must not crash
# ---------------------------------------------------------------------------

def test_unparseable_body_does_not_crash_and_is_retried():
    result, _ = _send(_response(200, text="<html>502 from a proxy</html>"))
    assert result.retry_tokens == ["ExponentPushToken[a]"]
    assert result.errors


def test_missing_data_array_does_not_crash_and_is_retried():
    result, _ = _send(_response(200, {"unexpected": True}))
    assert result.retry_tokens == ["ExponentPushToken[a]"]


def test_non_dict_ticket_does_not_crash():
    result, _ = _send(_response(200, {"data": ["not-a-ticket"]}))
    assert result.retry_tokens == ["ExponentPushToken[a]"]


def test_data_as_dict_instead_of_list_does_not_crash():
    """getReceipts returns a mapping; if send ever did, don't treat it as tickets."""
    result, _ = _send(_response(200, {"data": {"id": {"status": "ok"}}}))
    assert result.retry_tokens == ["ExponentPushToken[a]"]


def test_null_body_does_not_crash():
    result, _ = _send(_response(200, text="null"))
    assert result.retry_tokens == ["ExponentPushToken[a]"]


# ---------------------------------------------------------------------------
# Request-level failures
# ---------------------------------------------------------------------------

def test_transport_error_is_retryable():
    result, _ = _send(side_effect=httpx.ConnectError("dns go boom", request=_REQUEST))
    assert result.retry_tokens == ["ExponentPushToken[a]"]
    assert result.failed_tokens == []
    assert any("transport error" in e for e in result.errors)


def test_timeout_is_retryable():
    result, _ = _send(side_effect=httpx.ReadTimeout("too slow", request=_REQUEST))
    assert result.should_retry is True


def test_server_error_is_retryable():
    result, _ = _send(_response(503, {"errors": [{"code": "InternalServerError"}]}))
    assert result.retry_tokens == ["ExponentPushToken[a]"]


def test_too_many_requests_is_retryable_and_honours_retry_after():
    result, _ = _send(
        _response(
            429,
            {"errors": [{"code": "TOO_MANY_REQUESTS", "message": "slow down"}]},
            headers={"Retry-After": "42"},
        )
    )
    assert result.should_retry is True
    assert result.retry_after_s == 42


def test_non_numeric_retry_after_is_ignored():
    result, _ = _send(
        _response(429, {"errors": []}, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    )
    assert result.should_retry is True
    assert result.retry_after_s is None


def test_bad_request_is_not_retryable():
    """A 4xx that isn't a rate limit means our request is wrong; resending cannot help."""
    result, _ = _send(_response(400, {"errors": [{"code": "PUSH_TOO_MANY_EXPERIENCE_IDS"}]}))
    assert result.should_retry is False
    assert result.failed_tokens == [("ExponentPushToken[a]", "HTTP 400")]


def test_request_errors_inside_a_200_are_surfaced():
    result, _ = _send(_response(200, {"errors": [{"code": "PUSH_TOO_MANY_NOTIFICATIONS"}]}))
    assert result.should_retry is False
    assert result.failed_tokens == [("ExponentPushToken[a]", "PUSH_TOO_MANY_NOTIFICATIONS")]


def test_rate_limit_error_inside_a_200_is_retried():
    result, _ = _send(_response(200, {"errors": [{"code": "TOO_MANY_REQUESTS"}]}))
    assert result.retry_tokens == ["ExponentPushToken[a]"]


def test_chunk_outcomes_are_merged_across_requests():
    tokens = [f"ExponentPushToken[{i}]" for i in range(_MAX_MESSAGES_PER_REQUEST + 1)]
    responses = [
        _response(200, _tickets(*[_ok_ticket() for _ in range(_MAX_MESSAGES_PER_REQUEST)])),
        _response(200, _tickets(_error_ticket("DeviceNotRegistered"))),
    ]
    result, _ = _send(side_effect=responses, tokens=tokens)

    assert len(result.accepted) == _MAX_MESSAGES_PER_REQUEST
    assert result.expired_tokens == [tokens[-1]]
