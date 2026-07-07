from __future__ import annotations

from typing import Any

CUSTOM_API_FORMAT_OPTIONS = (
    {"value": "anthropic", "label": "Anthropic"},
    {"value": "openai_responses", "label": "OpenAI Responses"},
)

_PROVIDER_DEFINITIONS = (
    {
        "key": "anthropic",
        "label": "Anthropic",
        "description": "Claude-compatible runtime",
        "fields": (
            {"key": "model", "label": "Model", "request_key": "anthropic_model"},
            {"key": "base_url", "label": "Base URL", "request_key": "anthropic_base_url"},
        ),
        "secret_request_key": "anthropic_api_key",
    },
    {
        "key": "gemini",
        "label": "Gemini",
        "description": "Fast general-purpose model",
        "fields": (
            {"key": "model", "label": "Model", "request_key": "gemini_model"},
        ),
        "secret_request_key": "gemini_api_key",
    },
    {
        "key": "custom",
        "label": "Custom",
        "description": "Custom OpenAI or Anthropic endpoint",
        "fields": (
            {"key": "model", "label": "Model", "request_key": "custom_model"},
            {"key": "base_url", "label": "Base URL", "request_key": "custom_base_url"},
            {"key": "api_format", "label": "API Format", "request_key": "custom_api_format"},
        ),
        "secret_request_key": "custom_api_key",
    },
    {
        "key": "zhipu",
        "label": "Zhipu",
        "description": "Credential-only setup",
        "fields": (),
        "secret_request_key": "zhipu_api_key",
    },
    {
        "key": "mock",
        "label": "Mock",
        "description": "Built-in fallback for testing",
        "fields": (),
        "secret_request_key": None,
    },
)


def build_ai_provider_catalog() -> dict[str, Any]:
    providers = [
        {
            "key": provider["key"],
            "label": provider["label"],
            "description": provider["description"],
            "fields": [dict(field) for field in provider["fields"]],
            "secret_request_key": provider["secret_request_key"],
        }
        for provider in _PROVIDER_DEFINITIONS
    ]

    return {
        "providers": providers,
        "providers_by_key": {provider["key"]: provider for provider in providers},
        "custom_api_format_options": [dict(option) for option in CUSTOM_API_FORMAT_OPTIONS],
    }
