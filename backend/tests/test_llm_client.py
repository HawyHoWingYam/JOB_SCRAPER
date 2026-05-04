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


def test_get_llm_client_degrades_to_mock_when_runtime_settings_resolution_fails(monkeypatch):
    llm_client_module.reset_client()
    try:
        monkeypatch.setattr(
            llm_client_module,
            "get_effective_runtime_settings",
            lambda: (_ for _ in ()).throw(RuntimeError("settings table missing")),
        )

        client = llm_client_module.get_llm_client()
        status = llm_client_module.get_llm_status()

        assert isinstance(client, llm_client_module.MockClient)
        assert status["configured_provider"] == "unknown"
        assert status["active_provider"] == "mock"
        assert status["is_degraded"] is True
        assert "runtime settings resolution failed" in status["degradation_reason"].lower()
        assert "settings table missing" in status["degradation_reason"]
    finally:
        llm_client_module.reset_client()
