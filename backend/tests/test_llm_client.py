from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.ai import llm_client


class _FakeAsyncClient:
    def __init__(self, recorder: dict, response_payload: dict, *, timeout: float):
        self.recorder = recorder
        self.response_payload = response_payload
        self.recorder["timeout"] = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return None

    async def post(self, url: str, *, headers: dict, json: dict):
        self.recorder["post_count"] = self.recorder.get("post_count", 0) + 1
        self.recorder["url"] = url
        self.recorder["headers"] = headers
        self.recorder["json"] = json
        return httpx.Response(
            200,
            json=self.response_payload,
            headers={"x-request-id": "request-1"},
            request=httpx.Request("POST", url),
        )


def _fake_httpx(monkeypatch, response_payload: dict):
    recorder: dict = {}

    def async_client(*, timeout: float):
        return _FakeAsyncClient(recorder, response_payload, timeout=timeout)

    monkeypatch.setattr(
        llm_client,
        "_import_httpx",
        lambda: SimpleNamespace(AsyncClient=async_client),
    )
    return recorder


@pytest.mark.asyncio
async def test_chat_completions_generate_json_uses_verified_ordinary_contract(
    monkeypatch,
):
    recorder = _fake_httpx(
        monkeypatch,
        {
            "choices": [
                {"message": {"content": '{"status":"ok","count":3}'}}
            ]
        },
    )
    client = llm_client.OpenAIChatCompletionsClient(
        "secret-key", "grok-4.5", "https://relay.example/v1/"
    )

    result = await client.generate_json("Return JSON")

    assert result == {"status": "ok", "count": 3}
    assert recorder["url"] == "https://relay.example/v1/chat/completions"
    assert recorder["timeout"] == 120.0
    assert recorder["json"]["model"] == "grok-4.5"
    assert recorder["json"]["max_tokens"] == 4096
    assert recorder["json"]["messages"][0]["role"] == "user"
    assert "tools" not in recorder["json"]


@pytest.mark.asyncio
async def test_chat_client_routes_explicit_web_search_to_typed_responses(
    monkeypatch,
):
    recorder = _fake_httpx(
        monkeypatch,
        {
            "output": [
                {"type": "reasoning"},
                {"type": "web_search_call", "status": "completed"},
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Verified description"}],
                },
            ]
        },
    )
    client = llm_client.OpenAIChatCompletionsClient(
        "secret-key", "grok-4.5", "https://relay.example/v1"
    )

    result = await client.generate("Describe the company", web_search=True)

    assert result == "Verified description"
    assert recorder["url"] == "https://relay.example/v1/responses"
    assert recorder["timeout"] == 180.0
    assert recorder["json"]["tools"] == [{"type": "web_search"}]
    assert recorder["json"]["reasoning"] == {"effort": "low"}
    assert recorder["json"]["max_output_tokens"] == 4096


@pytest.mark.asyncio
async def test_web_search_probe_requires_search_call_and_final_message(monkeypatch):
    _fake_httpx(
        monkeypatch,
        {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "No search used"}],
                }
            ]
        },
    )
    client = llm_client.OpenAIResponsesClient(
        "secret-key", "grok-4.5", "https://relay.example/v1"
    )

    with pytest.raises(
        llm_client.LLMResponseShapeError,
        match="no web_search_call item",
    ):
        await client.probe_web_search("Probe")


@pytest.mark.asyncio
async def test_chat_missing_final_content_returns_bounded_sanitized_shape_error(
    monkeypatch,
):
    _fake_httpx(monkeypatch, {})
    client = llm_client.OpenAIChatCompletionsClient(
        "secret-key", "grok-4.5", "https://relay.example/v1"
    )

    with pytest.raises(llm_client.LLMResponseShapeError) as raised:
        await client.generate("private job prompt")

    message = str(raised.value)
    assert "Raw response preview: {}" in message
    assert "body_sha256=" in message
    assert "secret-key" not in message
    assert "private job prompt" not in message


def test_custom_client_factory_keeps_existing_formats_and_adds_chat():
    runtime = SimpleNamespace(
        custom_api_key="key",
        custom_model="grok-4.5",
        custom_base_url="https://relay.example/v1",
        custom_api_format="openai_chat_completions",
    )

    assert isinstance(
        llm_client._build_custom_client(runtime),
        llm_client.OpenAIChatCompletionsClient,
    )

    runtime.custom_api_format = "openai_responses"
    assert isinstance(
        llm_client._build_custom_client(runtime),
        llm_client.OpenAIResponsesClient,
    )


def test_raw_response_preview_exposes_shape_but_not_provider_content():
    raw_response = '{"error":{"message":"echoed private job description"}}'

    error = llm_client.LLMResponseShapeError(
        provider_name="custom",
        detail="missing output",
        raw_response=raw_response,
    )

    assert "keys=['error']" in str(error)
    assert "echoed private job description" not in str(error)


def test_json_format_error_exposes_shape_and_hash_but_not_model_content():
    private_text = "private job description from the provider"

    with pytest.raises(llm_client.LLMResponseFormatError) as raised:
        llm_client.MockClient()._extract_json(
            private_text,
            provider_name="custom",
            raw_response=private_text,
        )

    message = str(raised.value)
    assert "<non-json body length=" in message
    assert "body_sha256=" in message
    assert private_text not in message


@pytest.mark.asyncio
async def test_transient_exception_details_are_not_logged_or_returned(
    monkeypatch,
    caplog,
):
    leaked_detail = "secret-key private job prompt echoed provider body"

    class FailingClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return None

        async def post(self, _url: str, *, headers: dict, json: dict):
            raise httpx.ReadError(leaked_detail)

    monkeypatch.setattr(
        llm_client,
        "_import_httpx",
        lambda: SimpleNamespace(AsyncClient=FailingClient),
    )
    monkeypatch.setattr(llm_client.asyncio, "sleep", lambda _delay: _AsyncNoop())
    client = llm_client.OpenAIChatCompletionsClient(
        "secret-key", "grok-4.5", "https://relay.example/v1"
    )

    with pytest.raises(llm_client.LLMUpstreamError) as raised:
        await client.generate("private job prompt")

    combined = f"{raised.value}\n{caplog.text}"
    assert "error_type=ReadError" in combined
    assert leaked_detail not in combined
    assert "private job prompt" not in combined
    assert "secret-key" not in combined


def test_responses_rejects_non_object_and_incomplete_sse_envelopes():
    client = llm_client.OpenAIResponsesClient(
        "secret-key", "grok-4.5", "https://relay.example/v1"
    )

    with pytest.raises(llm_client.LLMResponseShapeError, match="not a JSON object"):
        client._extract_response_text("[]")

    with pytest.raises(llm_client.LLMResponseShapeError, match="malformed SSE event"):
        client._extract_response_text(
            'data: {"type":"response.output_text.delta","delta":"partial"}\n'
            "data: {truncated"
        )

    with pytest.raises(llm_client.LLMResponseShapeError, match="missing terminal"):
        client._extract_response_text(
            'data: {"type":"response.output_text.delta","delta":"partial"}'
        )


@pytest.mark.asyncio
async def test_truncated_json_output_fails_without_retry(monkeypatch):
    recorder = _fake_httpx(
        monkeypatch,
        {"choices": [{"message": {"content": '{"status":'}}]},
    )
    client = llm_client.OpenAIChatCompletionsClient(
        "secret-key", "grok-4.5", "https://relay.example/v1"
    )

    with pytest.raises(llm_client.LLMResponseFormatError):
        await client.generate_json("Return JSON")

    assert recorder["post_count"] == 1


@pytest.mark.asyncio
async def test_incomplete_read_retries_once_then_succeeds(monkeypatch):
    recorder = {"post_count": 0}

    class SequencedClient:
        def __init__(self, *, timeout):
            recorder["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return None

        async def post(self, url: str, *, headers: dict, json: dict):
            recorder["post_count"] += 1
            if recorder["post_count"] == 1:
                raise httpx.ReadError("peer closed connection without complete body")
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "Recovered"}}]},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(
        llm_client,
        "_import_httpx",
        lambda: SimpleNamespace(AsyncClient=SequencedClient),
    )
    monkeypatch.setattr(llm_client.asyncio, "sleep", lambda _delay: _AsyncNoop())
    client = llm_client.OpenAIChatCompletionsClient(
        "secret-key", "grok-4.5", "https://relay.example/v1"
    )

    assert await client.generate("Hello") == "Recovered"
    assert recorder["post_count"] == 2


class _AsyncNoop:
    def __await__(self):
        if False:
            yield None
        return None
