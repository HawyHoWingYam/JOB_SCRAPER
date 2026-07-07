from __future__ import annotations

from app.api.settings import _build_ai_settings_response

EXPECTED_PROVIDER_ORDER = [
    "anthropic",
    "gemini",
    "custom",
    "zhipu",
    "mock",
]

EXPECTED_CUSTOM_PROVIDER = {
    "key": "custom",
    "label": "Custom",
    "description": "Custom OpenAI or Anthropic endpoint",
    "fields": [
        {"key": "model", "label": "Model", "request_key": "custom_model"},
        {"key": "base_url", "label": "Base URL", "request_key": "custom_base_url"},
        {"key": "api_format", "label": "API Format", "request_key": "custom_api_format"},
    ],
    "secret_request_key": "custom_api_key",
}


class StubRuntimeSettingsService:
    def serialize_persisted_config(self) -> dict:
        return {"llm_provider": "mock"}

    def serialize_effective_config(self) -> dict:
        return {"llm_provider": "mock"}


def test_build_ai_settings_response_includes_real_provider_catalog_contract(monkeypatch):
    monkeypatch.setattr(
        "app.api.settings.refresh_llm_status",
        lambda scope="jobs": {"scope": scope, "is_ready": scope == "jobs"},
    )

    payload = _build_ai_settings_response(StubRuntimeSettingsService())
    provider_catalog = payload["provider_catalog"]

    assert payload["runtime_status"] == {"scope": "jobs", "is_ready": True}
    assert payload["company_runtime_status"] == {
        "scope": "companies",
        "is_ready": False,
    }
    assert [provider["key"] for provider in provider_catalog["providers"]] == EXPECTED_PROVIDER_ORDER
    assert provider_catalog["providers_by_key"]["custom"] == EXPECTED_CUSTOM_PROVIDER
    assert provider_catalog["custom_api_format_options"] == [
        {"value": "anthropic", "label": "Anthropic"},
        {"value": "openai_responses", "label": "OpenAI Responses"},
    ]
