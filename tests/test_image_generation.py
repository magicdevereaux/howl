"""Unit tests for app/services/image_generation.py."""

from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from app.services import image_generation as img_gen

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_openai_response(url: str) -> MagicMock:
    image_data = MagicMock()
    image_data.url = url
    response = MagicMock()
    response.data = [image_data]
    return response


def _configure_r2(monkeypatch, **overrides):
    """Set all four required R2_* settings to valid-looking defaults."""
    values = {
        "r2_endpoint_url": "https://acct123.r2.cloudflarestorage.com",
        "r2_access_key_id": "AKIATESTKEY",
        "r2_secret_access_key": "test-secret",
        "r2_bucket_name": "howl-avatars",
        "r2_public_url": None,
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setattr(f"app.services.image_generation.settings.{key}", value)


@pytest.fixture(autouse=True)
def _reset_r2_client_cache():
    """`_get_r2_client()` memoises its result in module globals for the life
    of the process (`_r2_client` / `_r2_init_done`) so avatar generation never
    re-checks env vars per request. Left alone, whichever test runs first
    permanently decides R2 availability for every test that runs after it in
    the same pytest session. Reset before *and* after every test in this file
    (not just the new R2 ones) so test order can never matter."""
    img_gen._r2_client = None
    img_gen._r2_init_done = False
    yield
    img_gen._r2_client = None
    img_gen._r2_init_done = False


# ---------------------------------------------------------------------------
# No API key configured
# ---------------------------------------------------------------------------

def test_returns_none_when_no_api_key(monkeypatch):
    monkeypatch.setattr("app.services.image_generation.settings.openai_api_key", None)
    from app.services.image_generation import generate_avatar_image
    assert generate_avatar_image("a prompt", "wolf") is None


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_returns_url_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.image_generation.settings.openai_api_key", "sk-test")
    monkeypatch.setattr("app.services.image_generation.AVATAR_DIR", tmp_path)
    monkeypatch.setattr("app.services.image_generation.AVATAR_URL_PREFIX", "/avatars")

    fake_image_bytes = b"\x89PNG fake image bytes"

    mock_http_response = MagicMock()
    mock_http_response.content = fake_image_bytes
    mock_http_response.raise_for_status.return_value = mock_http_response

    with (
        patch("app.services.image_generation.OpenAI") as MockOpenAI,
        patch("app.services.image_generation.httpx.Client") as MockHttpx,
    ):
        MockOpenAI.return_value.images.generate.return_value = _mock_openai_response(
            "https://oaidalleapiprodscus.blob.core.windows.net/fake.png"
        )
        MockHttpx.return_value.__enter__.return_value.get.return_value = mock_http_response

        from app.services.image_generation import generate_avatar_image
        result = generate_avatar_image("a mystical wolf spirit", "wolf")

    assert result is not None
    assert result.startswith("/avatars/")
    assert result.endswith(".png")
    # File was actually written
    written = list(tmp_path.glob("*.png"))
    assert len(written) == 1
    assert written[0].read_bytes() == fake_image_bytes


# ---------------------------------------------------------------------------
# Failure paths — all return None, never raise
# ---------------------------------------------------------------------------

def test_returns_none_on_openai_api_error(monkeypatch):
    monkeypatch.setattr("app.services.image_generation.settings.openai_api_key", "sk-test")

    with patch("app.services.image_generation.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.images.generate.side_effect = Exception("API error")
        from app.services.image_generation import generate_avatar_image
        result = generate_avatar_image("a prompt", "fox")

    assert result is None


def test_returns_none_on_http_download_error(monkeypatch):
    monkeypatch.setattr("app.services.image_generation.settings.openai_api_key", "sk-test")

    with (
        patch("app.services.image_generation.OpenAI") as MockOpenAI,
        patch("app.services.image_generation.httpx.Client") as MockHttpx,
    ):
        MockOpenAI.return_value.images.generate.return_value = _mock_openai_response(
            "https://example.com/image.png"
        )
        MockHttpx.return_value.__enter__.return_value.get.side_effect = Exception("timeout")

        from app.services.image_generation import generate_avatar_image
        result = generate_avatar_image("a prompt", "bear")

    assert result is None


def test_returns_none_on_disk_write_error(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.image_generation.settings.openai_api_key", "sk-test")
    monkeypatch.setattr("app.services.image_generation.AVATAR_DIR", tmp_path)

    mock_http_response = MagicMock()
    mock_http_response.content = b"PNG"
    mock_http_response.raise_for_status.return_value = mock_http_response

    with (
        patch("app.services.image_generation.OpenAI") as MockOpenAI,
        patch("app.services.image_generation.httpx.Client") as MockHttpx,
        patch("pathlib.Path.write_bytes", side_effect=OSError("disk full")),
    ):
        MockOpenAI.return_value.images.generate.return_value = _mock_openai_response(
            "https://example.com/image.png"
        )
        MockHttpx.return_value.__enter__.return_value.get.return_value = mock_http_response

        from app.services.image_generation import generate_avatar_image
        result = generate_avatar_image("a prompt", "owl")

    assert result is None


# ---------------------------------------------------------------------------
# Integration with the Celery task: image_prompt fallback
# ---------------------------------------------------------------------------

def test_task_uses_fallback_prompt_when_claude_omits_image_prompt():
    """generate_avatar task should not crash if Claude's JSON lacks image_prompt."""
    import json
    from unittest.mock import MagicMock, patch

    payload_without_image_prompt = {
        "animal": "fox",
        "personality_traits": ["clever"],
        "avatar_description": "A clever fox.",
        # no image_prompt key
    }

    user = MagicMock()
    user.id = 1
    user.bio = "A clever fox who loves the forest."
    db = MagicMock()
    db.get.return_value = user

    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload_without_image_prompt)
    claude_response = MagicMock()
    claude_response.content = [block]

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClaude,
        patch("app.tasks.avatar.generate_avatar_image", return_value=None) as mock_img,
    ):
        MockClaude.return_value.messages.create.return_value = claude_response
        from app.tasks.avatar import generate_avatar
        generate_avatar(1)

    # Image generation was called with a fallback prompt containing the animal name
    mock_img.assert_called_once()
    call_args = mock_img.call_args[0]
    assert "fox" in call_args[0].lower()  # fallback prompt contains animal
    assert call_args[1] == "fox"          # animal_name arg


def test_task_uses_claude_image_prompt_when_provided():
    """generate_avatar task forwards Claude's image_prompt to image generation."""
    import json
    from unittest.mock import MagicMock, patch

    custom_prompt = "A rust-furred fox spirit with glowing amber eyes, fantasy art"
    payload = {
        "animal": "fox",
        "personality_traits": ["clever"],
        "avatar_description": "A clever fox.",
        "image_prompt": custom_prompt,
    }

    user = MagicMock()
    user.id = 1
    user.bio = "A clever fox who loves the forest."
    db = MagicMock()
    db.get.return_value = user

    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload)
    claude_response = MagicMock()
    claude_response.content = [block]

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClaude,
        patch("app.tasks.avatar.generate_avatar_image", return_value="/avatars/test.png") as mock_img,
    ):
        MockClaude.return_value.messages.create.return_value = claude_response
        from app.tasks.avatar import generate_avatar
        generate_avatar(1)

    mock_img.assert_called_once_with(custom_prompt, "fox")
    assert user.avatar_url == "/avatars/test.png"


# ---------------------------------------------------------------------------
# R2 upload path (GAPS #30) — _get_r2_client()
# ---------------------------------------------------------------------------
#
# This is the production avatar-persistence path. It had never executed once
# before this file: boto3 wasn't installed locally and R2_* env vars are unset
# in every dev/test .env, so `_get_r2_client()` always short-circuited to None
# and every existing test above only ever exercised the local-disk fallback.
#
# NOTE on moto's real limitation, discovered empirically while writing this:
# moto's @mock_aws intercepts botocore calls by matching known *.amazonaws.com
# -style hostnames. A boto3 client built with a custom `endpoint_url` pointing
# at a non-AWS host (R2's `*.r2.cloudflarestorage.com`) is NOT intercepted —
# it attempts a genuine TLS handshake to that host and fails. This means moto
# cannot validate that a *real* R2 endpoint round-trips correctly; nothing
# can, short of live R2 credentials. What the tests below verify instead,
# split at the `_get_r2_client()` seam:
#   1. `_get_r2_client()` passes the right endpoint_url/keys/region to
#      boto3.client() and caches the result (mocked boto3.client).
#   2. Everything downstream of client construction — put_object/get_object/
#      delete_object args, key naming, content-type, URL shape, and the
#      generate_avatar_image() integration — runs against a REAL boto3 S3
#      client that moto backs at its default (AWS-style) endpoint, injected
#      via the `_get_r2_client` seam. That is exactly the same boto3 S3 API
#      surface R2 implements, so this proves the application's S3 usage is
#      correct even though the specific R2 hostname was never dialed.


def test_get_r2_client_returns_none_when_boto3_not_installed(monkeypatch):
    monkeypatch.setattr(img_gen, "_BOTO3_AVAILABLE", False)
    _configure_r2(monkeypatch)
    assert img_gen._get_r2_client() is None


@pytest.mark.parametrize(
    "missing",
    ["r2_endpoint_url", "r2_access_key_id", "r2_secret_access_key", "r2_bucket_name"],
)
def test_get_r2_client_returns_none_when_config_incomplete(monkeypatch, missing):
    _configure_r2(monkeypatch, **{missing: None})
    assert img_gen._get_r2_client() is None


def test_get_r2_client_builds_client_with_correct_args(monkeypatch):
    _configure_r2(monkeypatch)
    captured = {}

    class _FakeClient:
        pass

    def fake_boto3_client(service_name, **kwargs):
        captured["service_name"] = service_name
        captured.update(kwargs)
        return _FakeClient()

    monkeypatch.setattr(img_gen.boto3, "client", fake_boto3_client)

    client = img_gen._get_r2_client()

    assert isinstance(client, _FakeClient)
    assert captured["service_name"] == "s3"
    assert captured["endpoint_url"] == "https://acct123.r2.cloudflarestorage.com"
    assert captured["aws_access_key_id"] == "AKIATESTKEY"
    assert captured["aws_secret_access_key"] == "test-secret"
    assert captured["region_name"] == "auto"


def test_get_r2_client_caches_across_calls(monkeypatch):
    _configure_r2(monkeypatch)
    call_count = {"n": 0}

    def fake_boto3_client(*a, **kw):
        call_count["n"] += 1
        return MagicMock()

    monkeypatch.setattr(img_gen.boto3, "client", fake_boto3_client)

    first = img_gen._get_r2_client()
    second = img_gen._get_r2_client()

    assert first is second
    assert call_count["n"] == 1


def test_get_r2_client_returns_none_when_boto3_client_construction_raises(monkeypatch):
    _configure_r2(monkeypatch)

    def raise_on_init(*a, **kw):
        raise Exception("malformed credentials")

    monkeypatch.setattr(img_gen.boto3, "client", raise_on_init)

    assert img_gen._get_r2_client() is None


# ---------------------------------------------------------------------------
# _r2_public_base()
# ---------------------------------------------------------------------------


def test_r2_public_base_prefers_explicit_public_url(monkeypatch):
    monkeypatch.setattr(img_gen.settings, "r2_public_url", "https://pub-xxx.r2.dev/")
    assert img_gen._r2_public_base() == "https://pub-xxx.r2.dev"


def test_r2_public_base_falls_back_to_endpoint_plus_bucket(monkeypatch):
    monkeypatch.setattr(img_gen.settings, "r2_public_url", None)
    monkeypatch.setattr(
        img_gen.settings, "r2_endpoint_url", "https://acct123.r2.cloudflarestorage.com/"
    )
    monkeypatch.setattr(img_gen.settings, "r2_bucket_name", "howl-avatars")
    assert (
        img_gen._r2_public_base()
        == "https://acct123.r2.cloudflarestorage.com/howl-avatars"
    )


# ---------------------------------------------------------------------------
# _upload_to_r2() — unit level, client fully mocked
# ---------------------------------------------------------------------------


def test_upload_to_r2_returns_none_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: None)
    assert img_gen._upload_to_r2(b"bytes", "f.png") is None


def test_upload_to_r2_puts_correct_bucket_key_body_content_type(monkeypatch):
    monkeypatch.setattr(img_gen.settings, "r2_bucket_name", "howl-avatars")
    fake_client = MagicMock()
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: fake_client)
    monkeypatch.setattr(img_gen, "_r2_public_base", lambda: "https://pub-xxx.r2.dev")

    result = img_gen._upload_to_r2(b"\x89PNG-bytes", "abc123.png")

    fake_client.put_object.assert_called_once_with(
        Bucket="howl-avatars",
        Key="abc123.png",
        Body=b"\x89PNG-bytes",
        ContentType="image/png",
    )
    assert result == "https://pub-xxx.r2.dev/abc123.png"


def test_upload_to_r2_returns_none_on_boto_client_error(monkeypatch):
    """Simulates a real credentials/permission failure (e.g. AccessDenied)."""
    _configure_r2(monkeypatch)
    fake_client = MagicMock()
    fake_client.put_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "PutObject"
    )
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: fake_client)

    assert img_gen._upload_to_r2(b"bytes", "f.png") is None


def test_upload_to_r2_returns_none_on_network_error(monkeypatch):
    """Simulates a network failure talking to R2."""
    _configure_r2(monkeypatch)
    fake_client = MagicMock()
    fake_client.put_object.side_effect = ConnectionError("network unreachable")
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: fake_client)

    assert img_gen._upload_to_r2(b"bytes", "f.png") is None


# ---------------------------------------------------------------------------
# _upload_to_r2() / generate_avatar_image() — real boto3 S3 semantics via moto
# ---------------------------------------------------------------------------


@mock_aws
def test_upload_to_r2_round_trips_through_a_real_s3_api(monkeypatch):
    """Injects a real boto3 S3 client (backed by moto) at the _get_r2_client
    seam, proving put_object's arguments actually satisfy the S3 API rather
    than just a MagicMock's call recorder."""
    bucket = "howl-avatars-test"
    real_client = boto3.client("s3", region_name="us-east-1")
    real_client.create_bucket(Bucket=bucket)

    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: real_client)
    monkeypatch.setattr(img_gen.settings, "r2_bucket_name", bucket)
    monkeypatch.setattr(img_gen.settings, "r2_public_url", "https://pub-test.example.com")

    url = img_gen._upload_to_r2(b"\x89PNG-fake-bytes", "myavatar.png")

    assert url == "https://pub-test.example.com/myavatar.png"
    obj = real_client.get_object(Bucket=bucket, Key="myavatar.png")
    assert obj["Body"].read() == b"\x89PNG-fake-bytes"
    assert obj["ContentType"] == "image/png"


@mock_aws
def test_generate_avatar_image_stores_to_r2_when_configured(monkeypatch):
    """Full generate_avatar_image() path with R2 "available": proves the
    returned URL is R2-shaped (not a local /avatars/ path) and that the
    object landing in the bucket has the exact bytes DALL-E "returned"."""
    bucket = "howl-avatars-test"
    real_client = boto3.client("s3", region_name="us-east-1")
    real_client.create_bucket(Bucket=bucket)

    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: real_client)
    monkeypatch.setattr(img_gen.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(img_gen.settings, "r2_bucket_name", bucket)
    monkeypatch.setattr(img_gen.settings, "r2_public_url", "https://pub-test.example.com")

    save_locally_spy = MagicMock()
    monkeypatch.setattr(img_gen, "_save_locally", save_locally_spy)

    fake_bytes = b"\x89PNG real-looking bytes"
    mock_http_response = MagicMock()
    mock_http_response.content = fake_bytes
    mock_http_response.raise_for_status.return_value = mock_http_response

    with (
        patch("app.services.image_generation.OpenAI") as MockOpenAI,
        patch("app.services.image_generation.httpx.Client") as MockHttpx,
    ):
        MockOpenAI.return_value.images.generate.return_value = _mock_openai_response(
            "https://oaidalleapiprodscus.blob.core.windows.net/fake.png"
        )
        MockHttpx.return_value.__enter__.return_value.get.return_value = mock_http_response

        result = img_gen.generate_avatar_image("a mystical wolf spirit", "wolf")

    assert result is not None
    assert result.startswith("https://pub-test.example.com/")
    assert result.endswith(".png")
    # R2 succeeded, so the local-disk fallback must never even be attempted.
    save_locally_spy.assert_not_called()

    key = result.rsplit("/", 1)[-1]
    obj = real_client.get_object(Bucket=bucket, Key=key)
    assert obj["Body"].read() == fake_bytes
    assert obj["ContentType"] == "image/png"


def test_generate_avatar_image_falls_back_to_local_when_r2_upload_fails(
    tmp_path, monkeypatch
):
    """R2 configured but erroring (e.g. bad credentials) must still produce a
    usable avatar via the local-disk fallback, not None."""
    monkeypatch.setattr(img_gen, "AVATAR_DIR", tmp_path)
    monkeypatch.setattr(img_gen.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(img_gen.settings, "r2_bucket_name", "howl-avatars")

    fake_client = MagicMock()
    fake_client.put_object.side_effect = Exception("access denied")
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: fake_client)

    fake_bytes = b"PNGDATA"
    mock_http_response = MagicMock()
    mock_http_response.content = fake_bytes
    mock_http_response.raise_for_status.return_value = mock_http_response

    with (
        patch("app.services.image_generation.OpenAI") as MockOpenAI,
        patch("app.services.image_generation.httpx.Client") as MockHttpx,
    ):
        MockOpenAI.return_value.images.generate.return_value = _mock_openai_response(
            "https://example.com/x.png"
        )
        MockHttpx.return_value.__enter__.return_value.get.return_value = mock_http_response

        result = img_gen.generate_avatar_image("a prompt", "owl")

    assert result.startswith("/avatars/")
    written = list(tmp_path.glob("*.png"))
    assert len(written) == 1
    assert written[0].read_bytes() == fake_bytes


# ---------------------------------------------------------------------------
# delete_avatar() (GAPS #10 — must not leak an orphaned R2/local object on
# every avatar regeneration)
# ---------------------------------------------------------------------------


def test_delete_avatar_is_noop_for_none():
    img_gen.delete_avatar(None)  # must not raise, must not touch R2/disk


def test_delete_avatar_removes_local_file(tmp_path, monkeypatch):
    monkeypatch.setattr(img_gen, "AVATAR_DIR", tmp_path)
    f = tmp_path / "toremove.png"
    f.write_bytes(b"x")

    img_gen.delete_avatar("/avatars/toremove.png")

    assert not f.exists()


def test_delete_avatar_local_missing_file_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(img_gen, "AVATAR_DIR", tmp_path)
    img_gen.delete_avatar("/avatars/does-not-exist.png")  # relies on missing_ok=True


def test_delete_avatar_r2_extracts_correct_key_and_deletes(monkeypatch):
    fake_client = MagicMock()
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: fake_client)
    monkeypatch.setattr(img_gen.settings, "r2_public_url", "https://pub-test.example.com")
    monkeypatch.setattr(img_gen.settings, "r2_bucket_name", "howl-avatars")

    img_gen.delete_avatar("https://pub-test.example.com/some-uuid.png")

    fake_client.delete_object.assert_called_once_with(
        Bucket="howl-avatars", Key="some-uuid.png"
    )


@mock_aws
def test_delete_avatar_actually_removes_object_from_real_s3_api(monkeypatch):
    bucket = "howl-avatars-test"
    real_client = boto3.client("s3", region_name="us-east-1")
    real_client.create_bucket(Bucket=bucket)
    real_client.put_object(Bucket=bucket, Key="orphan.png", Body=b"x", ContentType="image/png")

    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: real_client)
    monkeypatch.setattr(img_gen.settings, "r2_bucket_name", bucket)
    monkeypatch.setattr(img_gen.settings, "r2_public_url", "https://pub-test.example.com")

    img_gen.delete_avatar("https://pub-test.example.com/orphan.png")

    with pytest.raises(real_client.exceptions.NoSuchKey):
        real_client.get_object(Bucket=bucket, Key="orphan.png")


def test_delete_avatar_r2_url_but_r2_unavailable_is_silent_noop(monkeypatch):
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: None)
    img_gen.delete_avatar("https://pub-test.example.com/orphan.png")  # must not raise


def test_delete_avatar_swallows_r2_delete_exceptions(monkeypatch):
    fake_client = MagicMock()
    fake_client.delete_object.side_effect = Exception("network down")
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: fake_client)
    monkeypatch.setattr(img_gen.settings, "r2_public_url", "https://pub-test.example.com")

    img_gen.delete_avatar("https://pub-test.example.com/orphan.png")  # must not raise


def test_delete_avatar_key_extraction_breaks_if_public_url_base_has_rotated(monkeypatch):
    """Documents a real gap, not a test to weaken: delete_avatar() extracts
    the object key by stripping `_r2_public_base()` as a string prefix from
    the stored avatar_url. If R2_PUBLIC_URL is ever rotated (custom domain
    migration, etc.) after avatars were already stored under the old base,
    the prefix no longer matches. `str.replace` on a non-matching prefix is a
    silent no-op, so `key` ends up being the *entire old URL* rather than
    just the filename. `delete_object` is then called with that wrong Key —
    no exception, no log line distinguishing this from a real delete — so the
    actual R2 object is never removed and orphans forever. See GAPS #10."""
    fake_client = MagicMock()
    monkeypatch.setattr(img_gen, "_get_r2_client", lambda: fake_client)
    monkeypatch.setattr(img_gen.settings, "r2_public_url", "https://new-domain.example.com")
    monkeypatch.setattr(img_gen.settings, "r2_bucket_name", "howl-avatars")

    old_url = "https://old-domain.example.com/some-uuid.png"
    img_gen.delete_avatar(old_url)

    fake_client.delete_object.assert_called_once_with(
        Bucket="howl-avatars", Key=old_url
    )
