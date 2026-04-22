from __future__ import annotations

from dataclasses import dataclass

from openai import OpenAI

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class ProviderClientOptions:
    api_key: str | None
    base_url: str | None = None
    default_headers: dict[str, str] | None = None


def resolve_provider_options(settings: Settings) -> ProviderClientOptions:
    if settings.ai_provider == "openrouter":
        headers: dict[str, str] = {}
        if settings.openrouter_site_url:
            headers["HTTP-Referer"] = settings.openrouter_site_url
        if settings.openrouter_app_name:
            headers["X-OpenRouter-Title"] = settings.openrouter_app_name
        return ProviderClientOptions(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            default_headers=headers,
        )
    return ProviderClientOptions(api_key=settings.openai_api_key)


def create_openai_compatible_client(settings: Settings | None = None) -> OpenAI | None:
    active_settings = settings or get_settings()
    options = resolve_provider_options(active_settings)
    if not options.api_key:
        return None

    client_kwargs: dict[str, object] = {"api_key": options.api_key}
    if options.base_url:
        client_kwargs["base_url"] = options.base_url
    if options.default_headers:
        client_kwargs["default_headers"] = options.default_headers
    return OpenAI(**client_kwargs)
