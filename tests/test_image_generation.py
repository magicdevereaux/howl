"""Unit tests for app/services/image_generation.py."""

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_openai_response(url: str) -> MagicMock:
    image_data = MagicMock()
    image_data.url = url
    response = MagicMock()
    response.data = [image_data]
    return response


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
