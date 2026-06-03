import asyncio
import json
from types import SimpleNamespace

import pytest

from app.ai import llm_client
from app.ai.llm_client import LLMUpstreamError, OpenAIResponsesClient, _call_with_retry


def test_openai_responses_client_extracts_last_output_message_text():
    client = OpenAIResponsesClient("test-key", "gpt-5.4", "https://api.example.com/v1")
    payload = json.dumps(
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Searching current public sources first.",
                        }
                    ],
                },
                {
                    "type": "web_search_call",
                    "status": "completed",
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Example Co is a Hong Kong technology company.",
                        }
                    ],
                },
            ],
        }
    )

    assert client._extract_response_text(payload) == "Example Co is a Hong Kong technology company."


def test_call_with_retry_surfaces_exception_type_when_upstream_detail_is_empty():
    class ReadTimeout(Exception):
        pass

    async def raise_timeout():
        raise ReadTimeout()

    with pytest.raises(LLMUpstreamError, match="ReadTimeout"):
        asyncio.run(_call_with_retry("custom", raise_timeout))


def test_openai_responses_client_uses_longer_timeout_for_web_search_requests(monkeypatch):
    captured = {}

    class FakeResponse:
        text = json.dumps(
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Example Co is a Hong Kong technology company.",
                            }
                        ],
                    }
                ],
            }
        )

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            captured["url"] = url
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(
        llm_client,
        "_import_httpx",
        lambda: SimpleNamespace(AsyncClient=FakeAsyncClient),
    )

    client = OpenAIResponsesClient("test-key", "gpt-5.4", "https://api.example.com/v1")
    raw = asyncio.run(client._request_response_text("Prompt", web_search=True))

    assert json.loads(raw)["status"] == "completed"
    assert captured["timeout"] == 120.0
    assert captured["payload"]["tools"] == [{"type": "web_search"}]
