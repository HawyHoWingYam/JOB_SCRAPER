"""
LLM Client Factory

Provides a unified interface for multiple LLM providers:
- Anthropic Claude
- Google Gemini
- Zhipu (ChatGLM)
- Mock (for testing)
"""

import asyncio
import hashlib
import inspect
import json
import logging
import importlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable

from app.services.ai_runtime_settings_service import (
    EffectiveAIRuntimeSettings,
    AIRuntimeSettingsService,
    get_effective_runtime_settings,
)
from app.database import SessionLocal

logger = logging.getLogger(__name__)

DEFAULT_ANTHROPIC_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
TRANSIENT_ERROR_TERMS = (
    "timeout",
    "timed out",
    "connection reset",
    "connection aborted",
    "connection refused",
    "connection error",
    "server disconnected",
    "peer closed",
    "incomplete body",
    "temporarily unavailable",
    "try again later",
    "rate limit",
    "too many requests",
    "resource_exhausted",
    "unavailable",
)
TRANSIENT_EXCEPTION_CLASS_NAMES = {
    "ConnectError",
    "ConnectTimeout",
    "ConnectionError",
    "NetworkError",
    "PoolTimeout",
    "ReadError",
    "ReadTimeout",
    "RemoteProtocolError",
    "TimeoutError",
    "WriteError",
    "WriteTimeout",
}
RETRY_DELAYS_SECONDS = (0.5, 1.0, 2.0)
CUSTOM_RETRY_DELAYS_SECONDS = (1.0,)
DEFAULT_CUSTOM_RESPONSE_TIMEOUT_SECONDS = 120.0
WEB_SEARCH_CUSTOM_RESPONSE_TIMEOUT_SECONDS = 180.0
DEFAULT_CUSTOM_MAX_OUTPUT_TOKENS = 4096


class LLMUpstreamError(RuntimeError):
    """Raised when an upstream LLM request fails."""

    def __init__(
        self,
        message: str,
        *,
        provider_name: str,
        retryable: bool,
        status_code: Optional[int] = None,
    ):
        super().__init__(message)
        self.provider_name = provider_name
        self.retryable = retryable
        self.status_code = status_code


class LLMCapabilityError(RuntimeError):
    """Raised when a caller requests an unsupported LLM capability."""


class LLMProfileNotReadyError(RuntimeError):
    """Raised when a runtime profile is not ready to serve requests."""

    def __init__(self, scope: str, message: str, *, code: str):
        super().__init__(message)
        self.scope = scope
        self.code = code


def _safe_raw_response_preview(value: Optional[str]) -> str:
    """Describe raw provider output without exposing generated or echoed content."""
    if value is None:
        return "<empty>"
    text = value.strip()
    if not text:
        return "<empty>"
    if text in {"{}", "[]"}:
        return text
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return f"<non-json body length={len(text.encode('utf-8'))}>"
    if isinstance(payload, dict):
        keys = sorted(str(key) for key in payload.keys())[:20]
        return f"<json object keys={keys}>"
    if isinstance(payload, list):
        return f"<json array items={len(payload)}>"
    return f"<json {type(payload).__name__}>"


class LLMResponseFormatError(LLMUpstreamError):
    """Raised when an LLM returns a non-JSON payload for a JSON request."""

    def __init__(
        self,
        *,
        provider_name: str,
        raw_response: str,
        extracted_text: str,
    ):
        raw_preview = _safe_raw_response_preview(raw_response)
        body_hash = hashlib.sha256(raw_response.encode("utf-8")).hexdigest()
        message = (
            f"{provider_name} response was not valid JSON. "
            f"Extracted text shape: {_safe_raw_response_preview(extracted_text)}. "
            f"Raw response preview: {raw_preview}. body_sha256={body_hash}"
        )
        super().__init__(
            message,
            provider_name=provider_name,
            retryable=False,
            status_code=None,
        )
        self.raw_response = raw_response
        self.extracted_text = extracted_text


class LLMResponseShapeError(LLMUpstreamError):
    """Raised when a successful provider response has no usable final output."""

    def __init__(self, *, provider_name: str, detail: str, raw_response: str):
        body_hash = hashlib.sha256(raw_response.encode("utf-8")).hexdigest()
        super().__init__(
            (
                f"{provider_name} response shape was invalid: {detail}. "
                f"Raw response preview: {_safe_raw_response_preview(raw_response)}. "
                f"body_sha256={body_hash}"
            ),
            provider_name=provider_name,
            retryable=False,
            status_code=None,
        )
        self.raw_response = raw_response


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _extract_status_code(exc: Exception) -> Optional[int]:
    """Best-effort extraction of an HTTP-ish status code."""
    for attr_name in ("status_code", "status", "code"):
        status_code = _coerce_int(getattr(exc, attr_name, None))
        if status_code is not None:
            return status_code

    response = getattr(exc, "response", None)
    if response is not None:
        status_code = _coerce_int(getattr(response, "status_code", None))
        if status_code is not None:
            return status_code

    return None


def _is_transient_upstream_exception(exc: Exception) -> bool:
    status_code = _extract_status_code(exc)
    if status_code in TRANSIENT_STATUS_CODES:
        return True

    if any(
        cls.__name__ in TRANSIENT_EXCEPTION_CLASS_NAMES
        for cls in type(exc).__mro__
    ):
        return True

    message = str(exc).lower()
    return any(term in message for term in TRANSIENT_ERROR_TERMS)


def _raise_upstream_error(provider_name: str, exc: Exception) -> None:
    status_code = _extract_status_code(exc)
    retryable = _is_transient_upstream_exception(exc)
    message = f"{provider_name} upstream request failed"
    if status_code is not None:
        message += f" with status {status_code}"
    message += f" (error_type={type(exc).__name__})"
    raise LLMUpstreamError(
        message,
        provider_name=provider_name,
        retryable=retryable,
        status_code=status_code,
    ) from exc


async def _call_with_retry(
    provider_name: str,
    operation: Callable[[], Any],
    *,
    retry_delays: tuple[float, ...] = RETRY_DELAYS_SECONDS,
) -> Any:
    """Retry transient upstream failures with bounded backoff."""
    max_attempts = len(retry_delays) + 1

    for attempt in range(1, max_attempts + 1):
        try:
            result = operation()
            if inspect.isawaitable(result):
                result = await result
            return result
        except Exception as exc:
            retryable = _is_transient_upstream_exception(exc)
            if not retryable or attempt == max_attempts:
                _raise_upstream_error(provider_name, exc)

            delay = retry_delays[attempt - 1]
            logger.warning(
                "Transient %s upstream error on attempt %s/%s "
                "error_type=%s status=%s; retrying in %.1fs",
                provider_name,
                attempt,
                max_attempts,
                type(exc).__name__,
                _extract_status_code(exc),
                delay,
            )
            await asyncio.sleep(delay)


def _log_custom_response_metadata(
    response: Any,
    *,
    endpoint_kind: str,
    elapsed_ms: int,
) -> None:
    """Log bounded response metadata without prompts, credentials, or full bodies."""
    body = response.text or ""
    headers = response.headers
    logger.debug(
        "Custom LLM response endpoint=%s status=%s content_type=%s "
        "content_length=%s received_length=%s request_id=%s elapsed_ms=%s body_sha256=%s",
        endpoint_kind,
        response.status_code,
        headers.get("content-type"),
        headers.get("content-length"),
        len(body.encode("utf-8")),
        headers.get("x-request-id") or headers.get("request-id"),
        elapsed_ms,
        hashlib.sha256(body.encode("utf-8")).hexdigest(),
    )


def safe_llm_error_message(exc: Exception) -> str:
    """Return a bounded error summary safe for logs, APIs, and persistence."""
    if isinstance(exc, LLMUpstreamError):
        return str(exc)
    status_code = _extract_status_code(exc)
    summary = f"LLM operation failed (error_type={type(exc).__name__}"
    if status_code is not None:
        summary += f", status={status_code}"
    return f"{summary})"


def _import_google_genai():
    return importlib.import_module("google.genai")


def _import_httpx():
    return importlib.import_module("httpx")


def _consume_web_search_flag(
    kwargs: Dict[str, Any],
    *,
    provider_name: str,
    supported: bool,
) -> bool:
    """Consume the opt-in web search flag and enforce provider capability."""
    web_search = bool(kwargs.pop("web_search", False))
    if web_search and not supported:
        raise LLMCapabilityError(
            f"{provider_name} client does not support web_search requests"
        )
    return web_search


def _consume_image_kwargs(
    kwargs: Dict[str, Any],
    *,
    provider_name: str,
    supported: bool,
) -> Optional[Dict[str, str]]:
    image_base64 = kwargs.pop("image_base64", None)
    image_media_type = kwargs.pop("image_media_type", None)

    if image_base64 is None:
        return None

    if not supported:
        raise LLMCapabilityError(
            f"{provider_name} client does not support image-assisted requests"
        )

    normalized_image = str(image_base64).strip()
    if not normalized_image:
        return None

    normalized_media_type = str(image_media_type or "image/png").strip() or "image/png"
    return {
        "image_base64": normalized_image,
        "image_media_type": normalized_media_type,
    }


class LLMClient(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> str:
        """Generate text from a prompt."""
        pass

    @abstractmethod
    async def generate_json(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Generate structured JSON from a prompt."""
        pass

    def supports_web_search(self) -> bool:
        """Return whether this client supports the web_search generation flag."""
        return False

    async def probe_web_search(self, prompt: str) -> Dict[str, Any]:
        """Attempt and verify the provider's native web-search contract."""
        raise LLMCapabilityError("This provider does not support web search")

    def _extract_json(
        self,
        text: str,
        *,
        provider_name: str,
        raw_response: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Extract JSON from LLM response text."""
        # Try to find JSON in the response
        text = text.strip()

        # Handle markdown code blocks
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            text = text[start:end].strip()

        # Try to parse as JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass

        raw_payload = raw_response if raw_response is not None else text
        logger.warning(
            "Failed to parse JSON from %s response. "
            "Extracted text shape: %s | Raw response preview: %s",
            provider_name,
            _safe_raw_response_preview(text),
            _safe_raw_response_preview(raw_payload),
        )
        raise LLMResponseFormatError(
            provider_name=provider_name,
            raw_response=raw_payload,
            extracted_text=text,
        )


class GeminiClient(LLMClient):
    """Google Gemini LLM client."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model = model
        self._client = None

    def _get_client(self):
        """Lazy initialization of Gemini SDK client."""
        if self._client is None:
            genai = _import_google_genai()
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    async def generate(self, prompt: str, **kwargs) -> str:
        """Generate text using Gemini."""
        _consume_web_search_flag(kwargs, provider_name="gemini", supported=False)
        _consume_image_kwargs(kwargs, provider_name="gemini", supported=False)
        try:
            client = self._get_client()
            response = await _call_with_retry(
                "gemini",
                lambda: client.models.generate_content(
                    model=self.model, contents=prompt
                ),
            )
            return response.text
        except LLMUpstreamError:
            raise
        except Exception as e:
            logger.error("Gemini generation error: %s", safe_llm_error_message(e))
            raise

    async def generate_json(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Generate JSON using Gemini."""
        json_prompt = f"{prompt}\n\nRespond with valid JSON only, no markdown."
        text = await self.generate(json_prompt, **kwargs)
        return self._extract_json(
            text,
            provider_name="gemini",
            raw_response=text,
        )


class ZhipuClient(LLMClient):
    """Zhipu (ChatGLM) LLM client."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.model = "glm-4-flash"
        self._client = None

    def _get_client(self):
        """Lazy initialization of Zhipu client."""
        if self._client is None:
            from zhipuai import ZhipuAI  # type: ignore[import-untyped]

            self._client = ZhipuAI(api_key=self.api_key)
        return self._client

    async def generate(self, prompt: str, **kwargs) -> str:
        """Generate text using Zhipu."""
        _consume_web_search_flag(kwargs, provider_name="zhipu", supported=False)
        _consume_image_kwargs(kwargs, provider_name="zhipu", supported=False)
        try:
            client = self._get_client()
            response = await _call_with_retry(
                "zhipu",
                lambda: client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                ),
            )
            return response.choices[0].message.content
        except LLMUpstreamError:
            raise
        except Exception as e:
            logger.error("Zhipu generation error: %s", safe_llm_error_message(e))
            raise

    async def generate_json(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Generate JSON using Zhipu."""
        json_prompt = f"{prompt}\n\nRespond with valid JSON only, no markdown."
        text = await self.generate(json_prompt, **kwargs)
        return self._extract_json(
            text,
            provider_name="zhipu",
            raw_response=text,
        )


class AnthropicClient(LLMClient):
    """Anthropic Claude LLM client."""

    _DEFAULT_TEXT_MAX_TOKENS = 1024
    _DEFAULT_JSON_MAX_TOKENS = 4096

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5",
        base_url: Optional[str] = None,
        default_headers: Optional[Dict[str, str]] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.default_headers = default_headers
        self._client = None

    def _get_client(self):
        """Lazy initialization of Anthropic client."""
        if self._client is None:
            from anthropic import AsyncAnthropic

            kwargs: Dict[str, Any] = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            if self.default_headers:
                kwargs["default_headers"] = self.default_headers
            self._client = AsyncAnthropic(**kwargs)
        return self._client

    @staticmethod
    def _extract_text_content(message: Any) -> str:
        """Return text blocks from an Anthropic-style message response."""
        text_parts = []

        for block in getattr(message, "content", []) or []:
            text = getattr(block, "text", None)
            if text is None and isinstance(block, dict):
                text = block.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())

        return "\n".join(text_parts)

    async def generate(self, prompt: str, **kwargs) -> str:
        """Generate text using Claude."""
        _consume_web_search_flag(kwargs, provider_name="anthropic", supported=False)
        image_payload = _consume_image_kwargs(
            kwargs, provider_name="anthropic", supported=True
        )
        max_tokens = kwargs.pop("max_tokens", self._DEFAULT_TEXT_MAX_TOKENS)
        user_content: Any = prompt
        if image_payload is not None:
            user_content = [
                {"type": "text", "text": prompt},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image_payload["image_media_type"],
                        "data": image_payload["image_base64"],
                    },
                },
            ]
        try:
            client = self._get_client()
            message = await _call_with_retry(
                "anthropic",
                lambda: client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": user_content}],
                ),
            )
            return self._extract_text_content(message)
        except LLMUpstreamError:
            raise
        except Exception as e:
            logger.error("Anthropic generation error: %s", safe_llm_error_message(e))
            raise

    async def generate_json(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Generate JSON using Claude."""
        json_prompt = (
            f"{prompt}\n\n"
            "Respond with valid JSON only, no markdown. "
            "Return compact single-line JSON with no extra commentary."
        )
        request_kwargs = dict(kwargs)
        request_kwargs["max_tokens"] = max(
            int(request_kwargs.get("max_tokens") or 0),
            self._DEFAULT_JSON_MAX_TOKENS,
        )

        try:
            text = await self.generate(json_prompt, **dict(request_kwargs))
            return self._extract_json(
                text,
                provider_name="anthropic",
                raw_response=text,
            )
        except LLMResponseFormatError as exc:
            logger.warning(
                "Retrying anthropic JSON generation after format error: %s",
                exc,
            )
            retry_text = await self.generate(json_prompt, **dict(request_kwargs))
            return self._extract_json(
                retry_text,
                provider_name="anthropic",
                raw_response=retry_text,
            )


class OpenAIResponsesClient(LLMClient):
    """OpenAI-compatible client using the Responses API."""

    def __init__(self, api_key: str, model: str, base_url: str):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    async def _request_response_text(self, prompt: str, **kwargs) -> str:
        """Send a prompt to the configured Responses endpoint and return the raw payload."""
        httpx = _import_httpx()
        web_search = _consume_web_search_flag(
            kwargs,
            provider_name="custom",
            supported=True,
        )
        image_payload = _consume_image_kwargs(
            kwargs, provider_name="custom", supported=True
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        input_payload: Any = prompt
        if image_payload is not None:
            input_payload = [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": (
                                f"data:{image_payload['image_media_type']};base64,"
                                f"{image_payload['image_base64']}"
                            ),
                        },
                    ],
                }
            ]
        payload = {
            "model": self.model,
            "input": input_payload,
            "stream": False,
            "max_output_tokens": kwargs.get(
                "max_output_tokens", DEFAULT_CUSTOM_MAX_OUTPUT_TOKENS
            ),
        }
        if web_search:
            payload["tools"] = [{"type": "web_search"}]
            payload["reasoning"] = {"effort": "low"}

        async def do_request():
            timeout_seconds = (
                WEB_SEARCH_CUSTOM_RESPONSE_TIMEOUT_SECONDS
                if web_search
                else DEFAULT_CUSTOM_RESPONSE_TIMEOUT_SECONDS
            )
            started_at = time.perf_counter()
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/responses",
                    headers=headers,
                    json=payload,
                )
            _log_custom_response_metadata(
                response,
                endpoint_kind="responses_web_search" if web_search else "responses",
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            )
            response.raise_for_status()
            return response

        response = await _call_with_retry(
            "custom",
            do_request,
            retry_delays=CUSTOM_RETRY_DELAYS_SECONDS,
        )
        return response.text

    async def generate(self, prompt: str, **kwargs) -> str:
        """Generate text using an OpenAI-compatible Responses endpoint."""
        try:
            raw_response = await self._request_response_text(prompt, **kwargs)
            text = self._extract_response_text(raw_response)
            if not text:
                raise LLMResponseShapeError(
                    provider_name="custom",
                    detail="missing final message text",
                    raw_response=raw_response,
                )
            return text
        except LLMUpstreamError:
            raise
        except Exception as e:
            logger.error(
                "OpenAI responses generation error: %s",
                safe_llm_error_message(e),
            )
            raise

    async def generate_json(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Generate JSON using an OpenAI-compatible Responses endpoint."""
        json_prompt = f"{prompt}\n\nRespond with valid JSON only, no markdown."
        raw_response = await self._request_response_text(json_prompt, **kwargs)
        text = self._extract_response_text(raw_response)
        return self._extract_json(
            text,
            provider_name="custom",
            raw_response=raw_response,
        )

    async def probe_web_search(self, prompt: str) -> Dict[str, Any]:
        """Verify that Responses executed search and returned a final message."""
        raw_response = await self._request_response_text(prompt, web_search=True)
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise LLMResponseShapeError(
                provider_name="custom",
                detail="web search probe returned non-JSON output",
                raw_response=raw_response,
            ) from exc

        if not isinstance(payload, dict):
            raise LLMResponseShapeError(
                provider_name="custom",
                detail="web search probe returned a non-object JSON envelope",
                raw_response=raw_response,
            )

        response_envelope = payload.get("response") or {}
        if not isinstance(response_envelope, dict):
            response_envelope = {}
        output = response_envelope.get("output") or payload.get("output") or []
        if not isinstance(output, list):
            output = []
        output_types = [
            str(item.get("type") or "") for item in output if isinstance(item, dict)
        ]
        if "web_search_call" not in output_types:
            raise LLMResponseShapeError(
                provider_name="custom",
                detail="web search probe returned no web_search_call item",
                raw_response=raw_response,
            )

        final_text = self._extract_response_text(raw_response)
        if not final_text:
            raise LLMResponseShapeError(
                provider_name="custom",
                detail="web search probe returned no final message",
                raw_response=raw_response,
            )
        return {
            "ok": True,
            "output_types": output_types,
        }

    def _extract_response_text(self, text: str) -> str:
        """Extract the final response text from JSON or SSE event streams."""
        parsed_text = self._extract_response_text_from_json_payload(text)
        if parsed_text is not None:
            return parsed_text

        deltas = []
        saw_terminal_event = False
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload:
                continue
            if payload == "[DONE]":
                saw_terminal_event = True
                continue
            parsed_text = self._extract_response_text_from_json_payload(payload)
            if parsed_text is not None:
                return parsed_text
            try:
                event = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise LLMResponseShapeError(
                    provider_name="custom",
                    detail="malformed SSE event",
                    raw_response=text,
                ) from exc
            if not isinstance(event, dict):
                raise LLMResponseShapeError(
                    provider_name="custom",
                    detail="SSE event was not a JSON object",
                    raw_response=text,
                )
            if event.get("type") == "response.output_text.delta":
                delta = event.get("delta")
                if isinstance(delta, str) and delta:
                    deltas.append(delta)
            elif event.get("type") in {"response.completed", "response.done"}:
                saw_terminal_event = True

        if deltas and not saw_terminal_event:
            raise LLMResponseShapeError(
                provider_name="custom",
                detail="incomplete SSE stream missing terminal event",
                raw_response=text,
            )
        return "".join(deltas).strip()

    def _extract_response_text_from_json_payload(self, payload: str) -> Optional[str]:
        """Extract text from a JSON payload when present."""
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None

        if not isinstance(data, dict):
            raise LLMResponseShapeError(
                provider_name="custom",
                detail="response envelope was not a JSON object",
                raw_response=payload,
            )

        if data.get("type") == "response.output_text.done":
            return (data.get("text") or "").strip()

        choices = data.get("choices") or []
        first_choice = choices[0] if isinstance(choices, list) and choices else {}
        if not isinstance(first_choice, dict):
            first_choice = {}
        message = first_choice.get("message") or {}
        if not isinstance(message, dict):
            message = {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

        response = data.get("response") or {}
        if not isinstance(response, dict):
            response = {}
        output = response.get("output") or []
        if not output:
            output = data.get("output") or []
        if not isinstance(output, list):
            output = []
        last_message_text = None
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "message":
                continue
            message_parts = []
            for part in item.get("content") or []:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "output_text" and part.get("text"):
                    message_parts.append(part["text"].strip())
            if message_parts:
                last_message_text = " ".join(
                    part for part in message_parts if part
                ).strip()

        if last_message_text:
            return last_message_text

        return None

    def supports_web_search(self) -> bool:
        return True


class OpenAIChatCompletionsClient(LLMClient):
    """OpenAI-compatible Chat Completions with opt-in Responses Web Search."""

    def __init__(self, api_key: str, model: str, base_url: str):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._responses_client = OpenAIResponsesClient(api_key, model, base_url)

    async def _request_chat_text(self, prompt: str, **kwargs) -> str:
        _consume_web_search_flag(
            kwargs,
            provider_name="custom chat completions",
            supported=False,
        )
        _consume_image_kwargs(
            kwargs,
            provider_name="custom chat completions",
            supported=False,
        )
        httpx = _import_httpx()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": kwargs.get("max_tokens", DEFAULT_CUSTOM_MAX_OUTPUT_TOKENS),
        }

        async def do_request():
            started_at = time.perf_counter()
            async with httpx.AsyncClient(
                timeout=DEFAULT_CUSTOM_RESPONSE_TIMEOUT_SECONDS
            ) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
            _log_custom_response_metadata(
                response,
                endpoint_kind="chat_completions",
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            )
            response.raise_for_status()
            return response

        response = await _call_with_retry(
            "custom chat completions",
            do_request,
            retry_delays=CUSTOM_RETRY_DELAYS_SECONDS,
        )
        raw_response = response.text
        try:
            data = response.json()
        except (TypeError, ValueError) as exc:
            raise LLMResponseShapeError(
                provider_name="custom chat completions",
                detail="response body was not JSON",
                raw_response=raw_response,
            ) from exc

        if not isinstance(data, dict):
            raise LLMResponseShapeError(
                provider_name="custom chat completions",
                detail="response envelope was not a JSON object",
                raw_response=raw_response,
            )

        choices = data.get("choices") or []
        message = choices[0].get("message") if choices else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseShapeError(
                provider_name="custom chat completions",
                detail="missing choices[0].message.content",
                raw_response=raw_response,
            )
        return content.strip()

    async def generate(self, prompt: str, **kwargs) -> str:
        if bool(kwargs.pop("web_search", False)):
            return await self._responses_client.generate(
                prompt,
                web_search=True,
                **kwargs,
            )
        return await self._request_chat_text(prompt, **kwargs)

    async def generate_json(self, prompt: str, **kwargs) -> Dict[str, Any]:
        if bool(kwargs.pop("web_search", False)):
            return await self._responses_client.generate_json(
                prompt,
                web_search=True,
                **kwargs,
            )
        json_prompt = f"{prompt}\n\nRespond with valid JSON only, no markdown."
        text = await self._request_chat_text(json_prompt, **kwargs)
        return self._extract_json(
            text,
            provider_name="custom chat completions",
            raw_response=text,
        )

    async def probe_web_search(self, prompt: str) -> Dict[str, Any]:
        return await self._responses_client.probe_web_search(prompt)

    def supports_web_search(self) -> bool:
        return True


class MockClient(LLMClient):
    """Mock LLM client for testing."""

    async def generate(self, prompt: str, **kwargs) -> str:
        """Return mock response."""
        _consume_web_search_flag(kwargs, provider_name="mock", supported=False)
        _consume_image_kwargs(kwargs, provider_name="mock", supported=True)
        return "Mock LLM response for testing purposes."

    async def generate_json(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Return mock JSON response based on prompt content."""
        _consume_web_search_flag(kwargs, provider_name="mock", supported=False)
        _consume_image_kwargs(kwargs, provider_name="mock", supported=True)
        # Detect what kind of response is expected
        prompt_lower = prompt.lower()

        if (
            "manual-verification" in prompt_lower
            or "manual verification" in prompt_lower
        ):
            return {
                "challenge_type": "unknown",
                "confidence": 0.5,
                "summary": "Mock manual-action analysis result.",
                "recommended_actions": [
                    "Open the verification browser and inspect the challenge."
                ],
                "should_resume": False,
            }

        if "allowed governed stable-code targets" in prompt_lower:
            target_code = next(
                (
                    line[2:].split(" | ", 1)[0].strip()
                    for line in prompt.splitlines()
                    if line.startswith("- ") and " | " in line
                ),
                None,
            )
            return {
                "classification": {
                    "decision": "select_existing" if target_code else "invalid",
                    "target_code": target_code,
                    "confidence": 0.85,
                    "reasoning": "Mock canonical classification",
                },
                "summary": "Mock job insight summary.",
                "skills": [],
                "experience": {
                    "experience_level": "not_specified",
                    "experience_min_years": None,
                    "experience_max_years": None,
                    "summary": None,
                    "evidence": [],
                },
                "confidence": 0.85,
            }

        if "category" in prompt_lower or "classify" in prompt_lower:
            final_decision = {
                "domain": "Information & Communication Technology",
                "category": "Software Development",
                "subcategory": "Backend Development",
                "resolution": "match_existing",
            }
            return {
                "source_path_decision": dict(final_decision),
                "final_taxonomy_decision": dict(final_decision),
                "taxonomy_decision": dict(final_decision),
                "compatibility_category": (
                    "Information & Communication Technology / "
                    "Software Development / Backend Development"
                ),
                "cross_domain": False,
                "cross_domain_confidence": 1.0,
                "cross_domain_reason": "",
                "confidence": 0.85,
                "reasoning": "Mock classification based on job description",
            }
        elif "skill" in prompt_lower or "extract" in prompt_lower:
            return {
                "skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "Redis"],
                "confidence": 0.9,
            }
        else:
            return {"result": "mock_response", "status": "success"}


@dataclass(frozen=True)
class ProviderSpec:
    """Configuration for a supported LLM provider."""

    name: str
    required_settings: tuple[tuple[str, str], ...]
    builder: Callable[[EffectiveAIRuntimeSettings], LLMClient]


def _required_runtime_value(value: Optional[str], field_name: str) -> str:
    if not value:
        raise ValueError(f"Missing required runtime setting: {field_name}")
    return value


def _build_anthropic_client(runtime_settings: EffectiveAIRuntimeSettings) -> LLMClient:
    return AnthropicClient(
        _required_runtime_value(
            runtime_settings.anthropic_api_key, "anthropic_api_key"
        ),
        _required_runtime_value(runtime_settings.anthropic_model, "anthropic_model"),
        runtime_settings.anthropic_base_url,
    )


def _build_custom_client(runtime_settings: EffectiveAIRuntimeSettings) -> LLMClient:
    if runtime_settings.custom_api_format == "openai_responses":
        return OpenAIResponsesClient(
            _required_runtime_value(runtime_settings.custom_api_key, "custom_api_key"),
            _required_runtime_value(runtime_settings.custom_model, "custom_model"),
            _required_runtime_value(runtime_settings.custom_base_url, "custom_base_url"),
        )
    if runtime_settings.custom_api_format == "openai_chat_completions":
        return OpenAIChatCompletionsClient(
            _required_runtime_value(runtime_settings.custom_api_key, "custom_api_key"),
            _required_runtime_value(runtime_settings.custom_model, "custom_model"),
            _required_runtime_value(runtime_settings.custom_base_url, "custom_base_url"),
        )

    return AnthropicClient(
        _required_runtime_value(runtime_settings.custom_api_key, "custom_api_key"),
        _required_runtime_value(runtime_settings.custom_model, "custom_model"),
        runtime_settings.custom_base_url,
        DEFAULT_ANTHROPIC_HEADERS,
    )


def _build_gemini_client(runtime_settings: EffectiveAIRuntimeSettings) -> LLMClient:
    return GeminiClient(
        _required_runtime_value(runtime_settings.gemini_api_key, "gemini_api_key"),
        _required_runtime_value(runtime_settings.gemini_model, "gemini_model"),
    )


def _build_zhipu_client(runtime_settings: EffectiveAIRuntimeSettings) -> LLMClient:
    return ZhipuClient(
        _required_runtime_value(runtime_settings.zhipu_api_key, "zhipu_api_key")
    )


def _build_mock_client(runtime_settings: EffectiveAIRuntimeSettings) -> LLMClient:
    return MockClient()


PROVIDER_REGISTRY = {
    "anthropic": ProviderSpec(
        name="anthropic",
        required_settings=(("anthropic_api_key", "ANTHROPIC_API_KEY"),),
        builder=_build_anthropic_client,
    ),
    "claude": ProviderSpec(
        name="anthropic",
        required_settings=(("anthropic_api_key", "ANTHROPIC_API_KEY"),),
        builder=_build_anthropic_client,
    ),
    "custom": ProviderSpec(
        name="custom",
        required_settings=(("custom_api_key", "CUSTOM_API_KEY"),),
        builder=_build_custom_client,
    ),
    "gemini": ProviderSpec(
        name="gemini",
        required_settings=(("gemini_api_key", "GEMINI_API_KEY"),),
        builder=_build_gemini_client,
    ),
    "zhipu": ProviderSpec(
        name="zhipu",
        required_settings=(("zhipu_api_key", "ZHIPU_API_KEY"),),
        builder=_build_zhipu_client,
    ),
    "mock": ProviderSpec(
        name="mock", required_settings=tuple(), builder=_build_mock_client
    ),
}


def _get_missing_settings(
    spec: ProviderSpec,
    runtime_settings: EffectiveAIRuntimeSettings,
) -> list[str]:
    missing = []
    values = runtime_settings.__dict__

    for attr_name, env_name in spec.required_settings:
        if not values.get(attr_name):
            missing.append(env_name)

    return missing


def _log_provider_initialized(provider_name: str, client: LLMClient) -> None:
    if hasattr(client, "model"):
        logger.info(
            "Initialized LLM provider '%s' with model '%s'",
            provider_name,
            client.model,
        )
        return

    logger.info("Initialized LLM provider '%s'", provider_name)


def _load_effective_runtime_settings(scope: str):
    try:
        return get_effective_runtime_settings(scope)
    except TypeError:
        return get_effective_runtime_settings()


def _load_profile_metadata(scope: str):
    db = SessionLocal()
    try:
        return AIRuntimeSettingsService(db).get_profile_runtime_metadata(scope)
    except Exception as exc:
        safe_error = safe_llm_error_message(exc)
        logger.debug("Profile metadata load failed for scope '%s': %s", scope, safe_error)
        return type(
            "ProfileMetadataFallback",
            (),
            {
                "is_ready": False,
                "requires_test": True,
                "last_test_status": "untested",
                "last_tested_at": None,
                "last_test_error": safe_error,
                "last_test_provider": None,
                "last_test_model": None,
                "last_test_latency_ms": None,
                "last_test_fingerprint": None,
                "last_successful_test_fingerprint": None,
                "web_search_last_test_status": "untested",
                "web_search_last_tested_at": None,
                "web_search_last_test_error": safe_error,
                "web_search_last_test_latency_ms": None,
                "web_search_last_test_fingerprint": None,
                "web_search_available": False,
                "web_search_reason": safe_error,
            },
        )()
    finally:
        db.close()


# Factory function
_client_instances: Dict[str, LLMClient] = {}
_provider_names: Dict[str, str] = {}
_configured_provider_names: Dict[str, str] = {}
_active_models: Dict[str, Optional[str]] = {}
_degraded_states: Dict[str, bool] = {}
_degradation_reasons: Dict[str, Optional[str]] = {}
_ready_states: Dict[str, bool] = {}
_requires_test_states: Dict[str, bool] = {}
_last_test_statuses: Dict[str, Optional[str]] = {}
_last_tested_at: Dict[str, Optional[str]] = {}
_last_test_errors: Dict[str, Optional[str]] = {}
_last_test_fingerprints: Dict[str, Optional[str]] = {}
_last_successful_test_fingerprints: Dict[str, Optional[str]] = {}


def get_llm_client(scope: str = "jobs") -> LLMClient:
    """
    Factory function to get the configured LLM client.

    Returns a singleton instance based on settings.llm_provider:
    - "anthropic"/"claude": Anthropic Claude (requires ANTHROPIC_API_KEY)
    - "custom": Custom Anthropic-compatible endpoint (requires CUSTOM_API_KEY)
    - "gemini": Google Gemini (requires GEMINI_API_KEY)
    - "zhipu": Zhipu ChatGLM (requires ZHIPU_API_KEY)
    - "mock": Mock client for testing (default)
    """
    if scope not in {"jobs", "companies"}:
        raise ValueError(f"Unsupported LLM runtime scope '{scope}'")

    if scope in _client_instances:
        return _client_instances[scope]

    try:
        runtime_settings = _load_effective_runtime_settings(scope)
    except Exception as exc:
        reason = f"Runtime settings resolution failed: {exc}"
        _configured_provider_names[scope] = "unknown"
        _provider_names[scope] = ""
        _active_models[scope] = None
        _degraded_states[scope] = True
        _degradation_reasons[scope] = reason
        raise LLMProfileNotReadyError(
            scope, reason, code="runtime_settings_resolution_failed"
        ) from exc

    provider = (runtime_settings.llm_provider or "").lower()
    _configured_provider_names[scope] = provider
    if not provider:
        reason = "Profile is not configured"
        _provider_names[scope] = ""
        _active_models[scope] = None
        _degraded_states[scope] = True
        _degradation_reasons[scope] = reason
        raise LLMProfileNotReadyError(scope, reason, code="profile_not_configured")

    metadata = _load_profile_metadata(scope)
    _ready_states[scope] = metadata.is_ready
    _requires_test_states[scope] = metadata.requires_test
    _last_test_statuses[scope] = metadata.last_test_status
    _last_tested_at[scope] = metadata.last_tested_at
    _last_test_errors[scope] = metadata.last_test_error
    _last_test_fingerprints[scope] = metadata.last_test_fingerprint
    _last_successful_test_fingerprints[
        scope
    ] = metadata.last_successful_test_fingerprint

    if metadata.requires_test or not metadata.is_ready:
        reason = metadata.last_test_error or (
            "Profile is not configured"
            if not provider
            else "Profile requires a successful test before it can run"
        )
        _provider_names[scope] = ""
        _active_models[scope] = None
        _degraded_states[scope] = True
        _degradation_reasons[scope] = reason
        raise LLMProfileNotReadyError(
            scope,
            reason,
            code="profile_requires_test" if provider else "profile_not_configured",
        )

    spec = PROVIDER_REGISTRY.get(provider)

    if spec is None:
        reason = f"Unsupported LLM provider: {provider}"
        _provider_names[scope] = ""
        _active_models[scope] = None
        _degraded_states[scope] = True
        _degradation_reasons[scope] = reason
        raise LLMProfileNotReadyError(scope, reason, code="unsupported_provider")

    missing_settings = _get_missing_settings(spec, runtime_settings)
    if missing_settings:
        reason = f"Provider '{spec.name}' missing required settings: {', '.join(missing_settings)}"
        _provider_names[scope] = provider
        _active_models[scope] = None
        _degraded_states[scope] = True
        _degradation_reasons[scope] = reason
        raise LLMProfileNotReadyError(scope, reason, code="missing_required_settings")

    try:
        _client_instances[scope] = spec.builder(runtime_settings)
        _provider_names[scope] = spec.name
        _active_models[scope] = getattr(_client_instances[scope], "model", None)
        _degraded_states[scope] = False
        _degradation_reasons[scope] = None
        _log_provider_initialized(spec.name, _client_instances[scope])
    except Exception as exc:
        reason = f"Failed to initialize provider '{spec.name}': {exc}"
        _provider_names[scope] = provider
        _active_models[scope] = None
        _degraded_states[scope] = True
        _degradation_reasons[scope] = reason
        raise LLMProfileNotReadyError(
            scope, reason, code="provider_init_failed"
        ) from exc

    return _client_instances[scope]


def get_llm_status(scope: str = "jobs") -> Dict[str, Any]:
    """
    Get the current LLM provider status.

    Returns:
        Dict with keys:
        - configured_provider: str - provider selected by config/runtime settings
        - active_provider: str - actual provider being used
        - active_model: Optional[str] - active model if available
        - model_version: Optional[str] - pinned runtime model identifier
        - is_degraded: bool - whether fallback to mock occurred
        - degradation_reason: Optional[str] - why degradation happened
    """
    configured_provider = _configured_provider_names.get(scope, "")
    if not configured_provider:
        try:
            configured_provider = (
                _load_effective_runtime_settings(scope).llm_provider or ""
            ).lower()
        except Exception:
            configured_provider = ""

    metadata = None
    try:
        metadata = _load_profile_metadata(scope)
    except Exception:
        metadata = None

    if metadata is not None:
        _ready_states[scope] = metadata.is_ready
        _requires_test_states[scope] = metadata.requires_test
        _last_test_statuses[scope] = metadata.last_test_status
        _last_tested_at[scope] = metadata.last_tested_at
        _last_test_errors[scope] = metadata.last_test_error
        _last_test_fingerprints[scope] = metadata.last_test_fingerprint
        _last_successful_test_fingerprints[
            scope
        ] = metadata.last_successful_test_fingerprint

    web_search_available = bool(
        scope == "companies"
        and metadata is not None
        and getattr(metadata, "web_search_available", False)
    )
    return {
        "provider": _provider_names.get(scope, "") or configured_provider or None,
        "configured_provider": configured_provider or None,
        "active_provider": (
            (_provider_names.get(scope, "") or configured_provider)
            if (
                _ready_states.get(scope)
                and not _degraded_states.get(scope, False)
                and not _requires_test_states.get(scope, False)
            )
            else None
        ),
        "active_model": _active_models.get(scope),
        "model": _active_models.get(scope),
        # The configured provider model identifier is the runtime's stable
        # model-version authority. Classifier provenance must capture it even
        # when the provider does not expose a separate deployment revision.
        "model_version": _active_models.get(scope),
        "is_degraded": _degraded_states.get(scope, False)
        or bool(_requires_test_states.get(scope)),
        "degradation_reason": _degradation_reasons.get(scope),
        "supports_web_search": web_search_available,
        "web_search": {
            "available": web_search_available,
            "reason": (
                getattr(metadata, "web_search_reason", None)
                if metadata is not None
                else "Company Web Search capability is unavailable."
            ),
            "last_test_status": (
                getattr(metadata, "web_search_last_test_status", "untested")
                if metadata is not None
                else "untested"
            ),
            "last_tested_at": (
                getattr(metadata, "web_search_last_tested_at", None)
                if metadata is not None
                else None
            ),
            "last_test_error": (
                getattr(metadata, "web_search_last_test_error", None)
                if metadata is not None
                else None
            ),
            "last_test_latency_ms": (
                getattr(metadata, "web_search_last_test_latency_ms", None)
                if metadata is not None
                else None
            ),
            "last_test_fingerprint": (
                getattr(metadata, "web_search_last_test_fingerprint", None)
                if metadata is not None
                else None
            ),
        },
        "requires_test": _requires_test_states.get(scope, False),
        "is_ready": _ready_states.get(scope, False),
        "last_test_status": _last_test_statuses.get(scope),
        "last_tested_at": _last_tested_at.get(scope),
        "last_test_error": _last_test_errors.get(scope),
        "last_test_fingerprint": _last_test_fingerprints.get(scope),
        "last_successful_test_fingerprint": _last_successful_test_fingerprints.get(
            scope
        ),
    }


def refresh_llm_status(scope: str = "jobs") -> Dict[str, Any]:
    """Force the runtime provider status to be recomputed from current settings."""
    reset_client(scope)
    try:
        get_llm_client(scope)
    except LLMProfileNotReadyError:
        pass
    return get_llm_status(scope)


def reset_client(scope: Optional[str] = None):
    """Reset cached runtime clients (useful for testing)."""
    if scope is None:
        _client_instances.clear()
        _provider_names.clear()
        _configured_provider_names.clear()
        _active_models.clear()
        _degraded_states.clear()
        _degradation_reasons.clear()
        _ready_states.clear()
        _requires_test_states.clear()
        _last_test_statuses.clear()
        _last_tested_at.clear()
        _last_test_errors.clear()
        _last_test_fingerprints.clear()
        _last_successful_test_fingerprints.clear()
        return

    _client_instances.pop(scope, None)
    _provider_names.pop(scope, None)
    _configured_provider_names.pop(scope, None)
    _active_models.pop(scope, None)
    _degraded_states.pop(scope, None)
    _degradation_reasons.pop(scope, None)
    _ready_states.pop(scope, None)
    _requires_test_states.pop(scope, None)
    _last_test_statuses.pop(scope, None)
    _last_tested_at.pop(scope, None)
    _last_test_errors.pop(scope, None)
    _last_test_fingerprints.pop(scope, None)
    _last_successful_test_fingerprints.pop(scope, None)
