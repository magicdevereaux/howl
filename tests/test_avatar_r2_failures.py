"""A broken R2 must be distinguishable from an absent one (GAPS-ROUND-2 #62).

`_upload_to_r2` used to return None for both, with one `logger.warning` between
them. Either way the bytes went to `static/avatars/` and the row committed
`ready`, so a wrong `R2_SECRET_ACCESS_KEY` produced avatars that looked
completely healthy until the next redeploy wiped the ephemeral disk and every
avatar generated since the misconfiguration 404'd at once.

The behaviour under test is the *signal*, not the storage: a configured
deployment escalates to Sentry at error level, an unconfigured one stays quiet.
The local fallback is deliberately unchanged — see `_report_r2_failure` for why
alerting beats failing the task.

Follows the seam the existing R2 tests use: real boto3/moto below
`_get_r2_client()`, fakes above it. `sentry_sdk` is patched at the module
boundary because `.env` carries a real DSN, so an unpatched capture would
actually ship an event.
"""

import logging
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from app.services import image_generation as img_gen

R2_SETTINGS = {
    "r2_endpoint_url": "https://acct123.r2.cloudflarestorage.com",
    "r2_access_key_id": "AKIATESTKEY",
    "r2_secret_access_key": "test-secret",
    "r2_bucket_name": "howl-avatars",
    "r2_public_url": "https://pub-test.example.com",
}


@pytest.fixture(autouse=True)
def _reset_r2_client_cache():
    """`_get_r2_client()` memoises in module globals for the life of the
    process, so without this whichever test runs first decides R2 availability
    for everything after it."""
    img_gen._r2_client = None
    img_gen._r2_init_done = False
    yield
    img_gen._r2_client = None
    img_gen._r2_init_done = False


@pytest.fixture()
def sentry(monkeypatch):
    """Intercept Sentry so nothing is shipped and the calls are assertable."""
    fake = MagicMock()
    fake.new_scope.return_value.__enter__.return_value = MagicMock()
    monkeypatch.setattr(img_gen, "sentry_sdk", fake)
    return fake


def _configure_r2(monkeypatch, **overrides):
    values = {**R2_SETTINGS, **overrides}
    for key, value in values.items():
        monkeypatch.setattr(img_gen.settings, key, value)


def _unconfigure_r2(monkeypatch):
    for key in R2_SETTINGS:
        monkeypatch.setattr(img_gen.settings, key, None)


def _reported(sentry) -> bool:
    return bool(sentry.capture_exception.called or sentry.capture_message.called)


# ---------------------------------------------------------------------------
# _r2_is_configured — the distinction the whole item rests on
# ---------------------------------------------------------------------------

def test_r2_is_configured_when_all_four_vars_are_set(monkeypatch):
    _configure_r2(monkeypatch)
    assert img_gen._r2_is_configured() is True


@pytest.mark.parametrize(
    "missing",
    ["r2_endpoint_url", "r2_access_key_id", "r2_secret_access_key", "r2_bucket_name"],
)
def test_r2_is_not_configured_when_any_var_is_missing(monkeypatch, missing):
    _configure_r2(monkeypatch, **{missing: None})
    assert img_gen._r2_is_configured() is False


def test_r2_is_not_configured_without_boto3(monkeypatch):
    """A deployment that sets the vars but ships no boto3 cannot use R2, and
    that is a packaging fact, not a runtime incident."""
    _configure_r2(monkeypatch)
    monkeypatch.setattr(img_gen, "_BOTO3_AVAILABLE", False)
    assert img_gen._r2_is_configured() is False


# ---------------------------------------------------------------------------
# Configured + failing => error + Sentry
# ---------------------------------------------------------------------------

def test_upload_failure_on_a_configured_deployment_is_reported(monkeypatch, sentry):
    """The credential-typo case, which used to be one logger.warning."""
    _configure_r2(monkeypatch)
    denied = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "PutObject"
    )
    fake_client = MagicMock()
    fake_client.put_object.side_effect = denied
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: fake_client)

    assert img_gen._upload_to_r2(b"bytes", "f.png") is None

    sentry.capture_exception.assert_called_once_with(denied)


def test_upload_failure_is_logged_at_error_not_warning(monkeypatch, sentry, caplog):
    """`warning` is why there was no signal: it is not an exception, so no
    Sentry event, and it does not trip a log-level alert either."""
    _configure_r2(monkeypatch)
    fake_client = MagicMock()
    fake_client.put_object.side_effect = ConnectionError("network unreachable")
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: fake_client)

    with caplog.at_level(logging.WARNING, logger=img_gen.logger.name):
        img_gen._upload_to_r2(b"bytes", "f.png")

    levels = {r.levelno for r in caplog.records}
    assert logging.ERROR in levels
    assert levels == {logging.ERROR}, "a fallback that loses data logged below error"


def test_report_names_the_consequence(monkeypatch, sentry, caplog):
    """The operator has to learn what breaks, not just that boto3 raised.

    RUNBOOK's "Avatars 404 after a deploy" entry gives exactly one cause and one
    remedy, so the alert has to carry the bit that entry is missing.
    """
    _configure_r2(monkeypatch)
    fake_client = MagicMock()
    fake_client.put_object.side_effect = Exception("boom")
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: fake_client)

    with caplog.at_level(logging.ERROR, logger=img_gen.logger.name):
        img_gen._upload_to_r2(b"bytes", "abc.png")

    message = caplog.text
    assert "abc.png" in message
    assert "404" in message and "redeploy" in message


def test_unbuildable_client_on_a_configured_deployment_is_reported(monkeypatch, sentry):
    """Malformed credentials fail at client construction, not at put_object.

    `_get_r2_client` memoises, so it logs once per process and every later
    avatar would have fallen back in total silence.
    """
    _configure_r2(monkeypatch)
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: None)

    assert img_gen._upload_to_r2(b"bytes", "f.png") is None

    sentry.capture_message.assert_called_once()
    assert sentry.capture_message.call_args.kwargs["level"] == "error"


# ---------------------------------------------------------------------------
# Not configured => silence. Local storage is the intended behaviour there.
# ---------------------------------------------------------------------------

def test_unconfigured_deployment_reports_nothing(monkeypatch, sentry, caplog):
    _unconfigure_r2(monkeypatch)
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: None)

    with caplog.at_level(logging.WARNING, logger=img_gen.logger.name):
        assert img_gen._upload_to_r2(b"bytes", "f.png") is None

    assert not _reported(sentry)
    assert caplog.records == []


def test_missing_boto3_reports_nothing(monkeypatch, sentry):
    """Local dev: boto3 is not even installed in .venv."""
    _configure_r2(monkeypatch)
    monkeypatch.setattr(img_gen, "_BOTO3_AVAILABLE", False)
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: None)

    assert img_gen._upload_to_r2(b"bytes", "f.png") is None
    assert not _reported(sentry)


# ---------------------------------------------------------------------------
# The user still gets their avatar — alerting is not failing
# ---------------------------------------------------------------------------

def test_a_reported_failure_still_produces_a_usable_avatar(tmp_path, monkeypatch, sentry):
    """The DALL-E image is already paid for and already renders. Failing the
    task here would show the user a broken avatar and offer a "Try Again" that
    buys a second image and fails identically."""
    _configure_r2(monkeypatch)
    monkeypatch.setattr(img_gen, "AVATAR_DIR", tmp_path)
    monkeypatch.setattr(img_gen.settings, "openai_api_key", "sk-test")

    fake_client = MagicMock()
    fake_client.put_object.side_effect = Exception("access denied")
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: fake_client)

    fake_bytes = b"\x89PNG-bytes"
    http_response = MagicMock()
    http_response.content = fake_bytes
    http_response.raise_for_status.return_value = http_response

    with (
        patch("app.services.image_generation.OpenAI") as MockOpenAI,
        patch("app.services.image_generation.httpx.Client") as MockHttpx,
    ):
        image = MagicMock()
        image.url = "https://example.com/x.png"
        MockOpenAI.return_value.images.generate.return_value = MagicMock(data=[image])
        MockHttpx.return_value.__enter__.return_value.get.return_value = http_response

        result = img_gen.generate_avatar_image("a prompt", "owl")

    assert result.startswith("/avatars/")
    assert list(tmp_path.glob("*.png"))[0].read_bytes() == fake_bytes
    assert _reported(sentry), "the avatar silently landed on a disk the next deploy wipes"


def test_a_locally_stored_url_is_the_repair_jobs_query(tmp_path, monkeypatch, sentry):
    """No migration is needed to "flag the row for repair".

    When R2 *is* configured, an `avatar_url` that is a local path is by
    definition a row that failed to upload, so the repair set is already
    expressible as `WHERE avatar_url LIKE '/avatars/%'`. A boolean column would
    duplicate a fact the URL already carries.
    """
    _configure_r2(monkeypatch)
    monkeypatch.setattr(img_gen, "AVATAR_DIR", tmp_path)
    fake_client = MagicMock()
    fake_client.put_object.side_effect = Exception("access denied")
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: fake_client)

    url = img_gen._upload_to_r2(b"x", "f.png") or img_gen._save_locally(b"x", "f.png")

    assert not url.startswith("http"), "a failed upload must not look like an R2 URL"


# ---------------------------------------------------------------------------
# A working R2 stays quiet — against a real S3 API, via moto
# ---------------------------------------------------------------------------

@mock_aws
def test_successful_upload_reports_nothing(monkeypatch, sentry):
    bucket = "howl-avatars-test"
    real_client = boto3.client("s3", region_name="us-east-1")
    real_client.create_bucket(Bucket=bucket)

    _configure_r2(monkeypatch, r2_bucket_name=bucket)
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: real_client)

    url = img_gen._upload_to_r2(b"\x89PNG", "ok.png")

    assert url == "https://pub-test.example.com/ok.png"
    assert not _reported(sentry)


@mock_aws
def test_upload_to_a_missing_bucket_is_reported(monkeypatch, sentry):
    """The deleted-bucket case, driven through a real S3 API rather than a mock
    that raises whatever the test author imagined."""
    real_client = boto3.client("s3", region_name="us-east-1")  # bucket never created

    _configure_r2(monkeypatch, r2_bucket_name="howl-avatars-gone")
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: real_client)

    assert img_gen._upload_to_r2(b"\x89PNG", "orphan.png") is None

    sentry.capture_exception.assert_called_once()
    assert isinstance(sentry.capture_exception.call_args[0][0], ClientError)
