from __future__ import annotations

import importlib

from app.api.settings import AISettingsUpdateRequest

EXPECTED_PROVIDER_ORDER = [
    "anthropic",
    "gemini",
    "custom",
    "zhipu",
    "mock",
]

EXPECTED_PROVIDER_KEYS = {
    "key",
    "label",
    "description",
    "fields",
    "secret_request_key",
}

EXPECTED_FIELD_KEYS = {"key", "label", "request_key"}

EXPECTED_PROVIDER_METADATA = {
    "anthropic": {
        "key": "anthropic",
        "label": "Anthropic",
        "description": "Claude-compatible runtime",
        "fields": [
            {"key": "model", "label": "Model", "request_key": "anthropic_model"},
            {
                "key": "base_url",
                "label": "Base URL",
                "request_key": "anthropic_base_url",
            },
        ],
        "secret_request_key": "anthropic_api_key",
    },
    "gemini": {
        "key": "gemini",
        "label": "Gemini",
        "description": "Fast general-purpose model",
        "fields": [
            {"key": "model", "label": "Model", "request_key": "gemini_model"},
        ],
        "secret_request_key": "gemini_api_key",
    },
    "custom": {
        "key": "custom",
        "label": "Custom",
        "description": "Custom OpenAI or Anthropic endpoint",
        "fields": [
            {"key": "model", "label": "Model", "request_key": "custom_model"},
            {
                "key": "base_url",
                "label": "Base URL",
                "request_key": "custom_base_url",
            },
            {
                "key": "api_format",
                "label": "API Format",
                "request_key": "custom_api_format",
            },
        ],
        "secret_request_key": "custom_api_key",
    },
    "zhipu": {
        "key": "zhipu",
        "label": "Zhipu",
        "description": "Credential-only setup",
        "fields": [],
        "secret_request_key": "zhipu_api_key",
    },
    "mock": {
        "key": "mock",
        "label": "Mock",
        "description": "Built-in fallback for testing",
        "fields": [],
        "secret_request_key": None,
    },
}


def test_build_ai_provider_catalog_returns_frontend_provider_shape():
    catalog_module = importlib.import_module("app.services.ai_provider_catalog")

    catalog = catalog_module.build_ai_provider_catalog()
    providers = catalog["providers"]
    providers_by_key = catalog["providers_by_key"]

    assert [provider["key"] for provider in providers] == EXPECTED_PROVIDER_ORDER
    assert list(providers_by_key) == EXPECTED_PROVIDER_ORDER

    for provider in providers:
        provider_key = provider["key"]

        assert set(provider) == EXPECTED_PROVIDER_KEYS
        assert provider == EXPECTED_PROVIDER_METADATA[provider_key]
        assert providers_by_key[provider_key] == provider

        for field in provider["fields"]:
            assert set(field) == EXPECTED_FIELD_KEYS


def test_build_ai_provider_catalog_request_keys_match_ai_settings_update_request():
    catalog_module = importlib.import_module("app.services.ai_provider_catalog")

    catalog = catalog_module.build_ai_provider_catalog()
    request_fields = AISettingsUpdateRequest.model_fields

    for provider in catalog["providers"]:
        secret_request_key = provider["secret_request_key"]

        if secret_request_key is not None:
            assert secret_request_key in request_fields

        for field in provider["fields"]:
            assert field["request_key"] in request_fields


def test_build_ai_provider_catalog_returns_custom_api_format_options():
    catalog_module = importlib.import_module("app.services.ai_provider_catalog")

    catalog = catalog_module.build_ai_provider_catalog()

    assert catalog["custom_api_format_options"] == [
        {"value": "anthropic", "label": "Anthropic"},
        {"value": "openai_responses", "label": "OpenAI Responses"},
    ]
