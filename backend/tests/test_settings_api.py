from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import settings as settings_api
from app.database import get_db


class _FakeDB:
    def commit(self):
        return None

    def rollback(self):
        return None


class _FakeClient:
    def __init__(self, *, model="fake-model", supports_web_search=False, web_search_error=None):
        self.model = model
        self._supports_web_search = supports_web_search
        self._web_search_error = web_search_error
        self.calls = []

    def supports_web_search(self):
        return self._supports_web_search

    async def generate(self, prompt: str, **kwargs):
        self.calls.append({"prompt": prompt, "kwargs": dict(kwargs)})
        if kwargs.get("web_search"):
            if self._web_search_error:
                raise RuntimeError(self._web_search_error)
            return "WEB SEARCH OK"
        return "OK"


def _make_client(fake_client, recorded_results):
    app = FastAPI()
    app.include_router(settings_api.router)

    class _FakeService:
        def __init__(self, db):
            self.db = db

        def draft_profile_values_from_payload(self, scope, payload):
            return {
                "scope": scope,
                "llm_provider": payload.get("llm_provider"),
            }

        def _validate_profile(self, draft_values, scope):
            return []

        def _build_effective_settings(self, draft_values, scope):
            return SimpleNamespace(llm_provider=draft_values.get("llm_provider"))

        def _validate_effective_settings(self, scope, effective):
            return None

        def build_config_fingerprint(self, scope, draft_values):
            return f"{scope}:fingerprint"

        def build_draft_client(self, scope, draft_values):
            return fake_client

        def record_profile_test_result(self, scope, **kwargs):
            recorded_results.append({"scope": scope, **kwargs})
            return None

    def override_get_db():
        yield _FakeDB()

    app.dependency_overrides[get_db] = override_get_db
    settings_api.AIRuntimeSettingsService = _FakeService
    return TestClient(app)


def test_companies_probe_returns_warning_when_provider_does_not_support_web_search():
    fake_client = _FakeClient(model="claude-sonnet-4-5", supports_web_search=False)
    recorded_results = []
    client = _make_client(fake_client, recorded_results)

    response = client.post(
        "/api/v1/settings/ai/test",
        json={
            "scope": "companies",
            "profile": {
                "llm_provider": "anthropic",
                "anthropic_api_key": "test-key",
                "anthropic_model": "claude-sonnet-4-5",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["model_check"]["ok"] is True
    assert payload["web_search_check"] == {
        "attempted": False,
        "supported": False,
        "ok": False,
        "latency_ms": None,
        "error_message": "This provider does not support web search.",
    }
    assert len(fake_client.calls) == 1
    assert recorded_results[0]["ok"] is True


def test_companies_probe_reports_web_search_success_when_supported():
    fake_client = _FakeClient(model="gpt-5.2", supports_web_search=True)
    recorded_results = []
    client = _make_client(fake_client, recorded_results)

    response = client.post(
        "/api/v1/settings/ai/test",
        json={
            "scope": "companies",
            "profile": {
                "llm_provider": "custom",
                "custom_api_key": "test-key",
                "custom_model": "gpt-5.2",
                "custom_base_url": "https://api.example.com/v1",
                "custom_api_format": "openai_responses",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["model_check"]["ok"] is True
    assert payload["web_search_check"]["attempted"] is True
    assert payload["web_search_check"]["supported"] is True
    assert payload["web_search_check"]["ok"] is True
    assert payload["web_search_check"]["error_message"] is None
    assert len(fake_client.calls) == 2
    assert fake_client.calls[1]["kwargs"]["web_search"] is True
    assert recorded_results[0]["ok"] is True


def test_companies_probe_keeps_success_but_returns_warning_when_web_search_probe_fails():
    fake_client = _FakeClient(
        model="gpt-5.2",
        supports_web_search=True,
        web_search_error="search backend unavailable",
    )
    recorded_results = []
    client = _make_client(fake_client, recorded_results)

    response = client.post(
        "/api/v1/settings/ai/test",
        json={
            "scope": "companies",
            "profile": {
                "llm_provider": "custom",
                "custom_api_key": "test-key",
                "custom_model": "gpt-5.2",
                "custom_base_url": "https://api.example.com/v1",
                "custom_api_format": "openai_responses",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["model_check"]["ok"] is True
    assert payload["web_search_check"] == {
        "attempted": True,
        "supported": True,
        "ok": False,
        "latency_ms": None,
        "error_message": "search backend unavailable",
    }
    assert len(fake_client.calls) == 2
    assert recorded_results[0]["ok"] is True
