from __future__ import annotations

from app.core.config import Settings
from app.services.provider_client import resolve_provider_options


def test_openai_provider_uses_openai_key() -> None:
    settings = Settings(
        _env_file=None,
        ai_provider="openai",
        openai_api_key="openai-secret",
        openrouter_api_key="openrouter-secret",
    )

    options = resolve_provider_options(settings)

    assert options.api_key == "openai-secret"
    assert options.base_url is None
    assert settings.active_chat_model == "gpt-4.1-mini"
    assert settings.active_embedding_model == "text-embedding-3-small"


def test_openrouter_provider_sets_headers_and_defaults() -> None:
    settings = Settings(
        _env_file=None,
        ai_provider="openrouter",
        openrouter_api_key="openrouter-secret",
        openrouter_site_url="https://demo.example.com",
        openrouter_app_name="GTU Demo",
    )

    options = resolve_provider_options(settings)

    assert options.api_key == "openrouter-secret"
    assert options.base_url == "https://openrouter.ai/api/v1"
    assert options.default_headers == {
        "HTTP-Referer": "https://demo.example.com",
        "X-OpenRouter-Title": "GTU Demo",
    }
    assert settings.active_chat_model == "openai/gpt-4.1-mini"
    assert settings.active_embedding_model == "openai/text-embedding-3-small"
