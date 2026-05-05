import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.ai.llm_client as llm_client_module
from app.ai.llm_client import AnthropicClient


class FakeMessages:
    async def create(self, **_kwargs):
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking="internal reasoning"),
                SimpleNamespace(type="text", text="hello Hawy"),
            ]
        )


class RecordingMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeAnthropicSdk:
    messages = FakeMessages()


@pytest.mark.asyncio
async def test_anthropic_generate_skips_non_text_blocks_before_text():
    client = AnthropicClient("test-key", "test-model")
    client._get_client = lambda: FakeAnthropicSdk()

    result = await client.generate("Say hello")

    assert result == "hello Hawy"


@pytest.mark.asyncio
async def test_anthropic_generate_honors_max_tokens_override():
    messages = RecordingMessages(
        [
            SimpleNamespace(
                content=[SimpleNamespace(type="text", text='{"ok":true}')]
            )
        ]
    )
    client = AnthropicClient("test-key", "test-model")
    client._get_client = lambda: SimpleNamespace(messages=messages)

    await client.generate("Return JSON", max_tokens=2048)

    assert messages.calls[0]["max_tokens"] == 2048


@pytest.mark.asyncio
async def test_anthropic_generate_json_retries_after_empty_response():
    messages = RecordingMessages(
        [
            SimpleNamespace(content=[]),
            SimpleNamespace(
                content=[SimpleNamespace(type="text", text='{"ok":true}')]
            ),
        ]
    )
    client = AnthropicClient("test-key", "test-model")
    client._get_client = lambda: SimpleNamespace(messages=messages)

    result = await client.generate_json("Return JSON")

    assert result == {"ok": True}
    assert len(messages.calls) == 2
    assert messages.calls[0]["max_tokens"] == 4096
    assert messages.calls[1]["max_tokens"] == 4096


def test_get_llm_client_raises_when_runtime_settings_resolution_fails(monkeypatch):
    llm_client_module.reset_client()
    try:
        monkeypatch.setattr(
            llm_client_module,
            "get_effective_runtime_settings",
            lambda: (_ for _ in ()).throw(RuntimeError("settings table missing")),
        )

        with pytest.raises(llm_client_module.LLMProfileNotReadyError) as exc_info:
            llm_client_module.get_llm_client()

        status = llm_client_module.get_llm_status()
        assert status["configured_provider"] == "unknown"
        assert status["active_provider"] in {"", None}
        assert status["is_degraded"] is True
        assert "runtime settings resolution failed" in status["degradation_reason"].lower()
        assert "settings table missing" in status["degradation_reason"]
        assert exc_info.value.code == "runtime_settings_resolution_failed"
    finally:
        llm_client_module.reset_client()


def test_get_llm_client_caches_per_scope_and_tracks_independent_status(monkeypatch):
    llm_client_module.reset_client()
    try:
        job_effective = llm_client_module.EffectiveAIRuntimeSettings(
            llm_provider="gemini",
            ai_enrichment_run_concurrency=10,
            anthropic_api_key=None,
            anthropic_model="claude-sonnet-4-5",
            anthropic_base_url=None,
            gemini_api_key="gemini-secret",
            gemini_model="gemini-jobs",
            custom_api_key=None,
            custom_model="custom-model",
            custom_base_url=None,
            custom_api_format="anthropic",
            zhipu_api_key=None,
        )
        company_effective = llm_client_module.EffectiveAIRuntimeSettings(
            llm_provider="anthropic",
            ai_enrichment_run_concurrency=10,
            anthropic_api_key="anthropic-secret",
            anthropic_model="claude-sonnet-4-5",
            anthropic_base_url="https://api.anthropic.com",
            gemini_api_key=None,
            gemini_model="gemini-company",
            custom_api_key=None,
            custom_model="custom-model",
            custom_base_url=None,
            custom_api_format="anthropic",
            zhipu_api_key=None,
        )
        monkeypatch.setattr(
            llm_client_module,
            "_load_profile_metadata",
            lambda scope="jobs": type(
                "Meta",
                (),
                {
                    "is_ready": True,
                    "requires_test": False,
                    "last_test_status": "passed",
                    "last_tested_at": None,
                    "last_test_error": None,
                    "last_test_fingerprint": f"{scope}:fingerprint",
                    "last_successful_test_fingerprint": f"{scope}:fingerprint",
                },
            )(),
        )
        monkeypatch.setattr(
            llm_client_module,
            "get_effective_runtime_settings",
            lambda scope="jobs": company_effective if scope == "companies" else job_effective,
        )

        job_client = llm_client_module.get_llm_client()
        company_client = llm_client_module.get_llm_client("companies")
        job_status = llm_client_module.get_llm_status()
        company_status = llm_client_module.get_llm_status("companies")

        assert type(job_client).__name__ == "GeminiClient"
        assert type(company_client).__name__ == "AnthropicClient"
        assert job_status["configured_provider"] == "gemini"
        assert job_status["active_provider"] == "gemini"
        assert job_status["active_model"] == "gemini-jobs"
        assert company_status["configured_provider"] == "anthropic"
        assert company_status["active_provider"] == "anthropic"
        assert company_status["active_model"] == "claude-sonnet-4-5"
    finally:
        llm_client_module.reset_client()
