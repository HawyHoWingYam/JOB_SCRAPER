"""
LLM Client Factory

Provides a unified interface for multiple LLM providers:
- Anthropic Claude
- Google Gemini
- Zhipu (ChatGLM)
- Mock (for testing)
"""

import asyncio
import inspect
import json
import logging
import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable

from app.config import settings

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
    "temporarily unavailable",
    "try again later",
    "rate limit",
    "too many requests",
    "resource_exhausted",
    "unavailable",
)
RETRY_DELAYS_SECONDS = (0.5, 1.0, 2.0)


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


def _preview_text(value: Optional[str], limit: int = 1000) -> str:
    """Format raw provider output for logs and error messages."""
    if value is None:
        return "<empty>"

    text = value.strip()
    if not text:
        return "<empty>"
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated>"


class LLMResponseFormatError(LLMUpstreamError):
    """Raised when an LLM returns a non-JSON payload for a JSON request."""

    def __init__(
        self,
        *,
        provider_name: str,
        raw_response: str,
        extracted_text: str,
    ):
        raw_preview = _preview_text(raw_response)
        extracted_preview = _preview_text(extracted_text)
        message = (
            f"{provider_name} response was not valid JSON. "
            f"Extracted text preview: {extracted_preview}. "
            f"Raw response preview: {raw_preview}"
        )
        super().__init__(
            message,
            provider_name=provider_name,
            retryable=False,
            status_code=None,
        )
        self.raw_response = raw_response
        self.extracted_text = extracted_text


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

    message = str(exc).lower()
    return any(term in message for term in TRANSIENT_ERROR_TERMS)


def _raise_upstream_error(provider_name: str, exc: Exception) -> None:
    status_code = _extract_status_code(exc)
    retryable = _is_transient_upstream_exception(exc)
    detail = str(exc).strip()
    message = f"{provider_name} upstream request failed"
    if status_code is not None:
        message += f" with status {status_code}"
    if detail:
        message += f": {detail}"
    raise LLMUpstreamError(
        message,
        provider_name=provider_name,
        retryable=retryable,
        status_code=status_code,
    ) from exc


async def _call_with_retry(provider_name: str, operation: Callable[[], Any]) -> Any:
    """Retry transient upstream failures with bounded backoff."""
    max_attempts = len(RETRY_DELAYS_SECONDS) + 1

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

            delay = RETRY_DELAYS_SECONDS[attempt - 1]
            logger.warning(
                "Transient %s upstream error on attempt %s/%s: %s. Retrying in %.1fs",
                provider_name,
                attempt,
                max_attempts,
                exc,
                delay,
            )
            await asyncio.sleep(delay)


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
            "Failed to parse JSON from %s response. Extracted text preview: %s | Raw response preview: %s",
            provider_name,
            _preview_text(text),
            _preview_text(raw_payload),
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
        try:
            client = self._get_client()
            response = await _call_with_retry(
                "gemini",
                lambda: client.models.generate_content(model=self.model, contents=prompt),
            )
            return response.text
        except LLMUpstreamError:
            raise
        except Exception as e:
            logger.error(f"Gemini generation error: {e}")
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
        self._client = None

    def _get_client(self):
        """Lazy initialization of Zhipu client."""
        if self._client is None:
            from zhipuai import ZhipuAI
            self._client = ZhipuAI(api_key=self.api_key)
        return self._client

    async def generate(self, prompt: str, **kwargs) -> str:
        """Generate text using Zhipu."""
        _consume_web_search_flag(kwargs, provider_name="zhipu", supported=False)
        try:
            client = self._get_client()
            response = await _call_with_retry(
                "zhipu",
                lambda: client.chat.completions.create(
                    model="glm-4-flash",
                    messages=[{"role": "user", "content": prompt}],
                ),
            )
            return response.choices[0].message.content
        except LLMUpstreamError:
            raise
        except Exception as e:
            logger.error(f"Zhipu generation error: {e}")
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

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5", base_url: str = None, default_headers: Dict[str, str] = None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.default_headers = default_headers
        self._client = None

    def _get_client(self):
        """Lazy initialization of Anthropic client."""
        if self._client is None:
            from anthropic import AsyncAnthropic
            kwargs = {"api_key": self.api_key}
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
        max_tokens = kwargs.pop("max_tokens", self._DEFAULT_TEXT_MAX_TOKENS)
        try:
            client = self._get_client()
            message = await _call_with_retry(
                "anthropic",
                lambda: client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                ),
            )
            return self._extract_text_content(message)
        except LLMUpstreamError:
            raise
        except Exception as e:
            logger.error(f"Anthropic generation error: {e}")
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
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": prompt,
            "stream": False,
            "max_output_tokens": kwargs.get("max_output_tokens", 1024),
        }
        if web_search:
            payload["tools"] = [{"type": "web_search"}]

        async def do_request():
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/responses",
                    headers=headers,
                    json=payload,
                )
            response.raise_for_status()
            return response

        response = await _call_with_retry("custom", do_request)
        return response.text

    async def generate(self, prompt: str, **kwargs) -> str:
        """Generate text using an OpenAI-compatible Responses endpoint."""
        try:
            raw_response = await self._request_response_text(prompt, **kwargs)
            return self._extract_response_text(raw_response)
        except LLMUpstreamError:
            raise
        except Exception as e:
            logger.error(f"OpenAI responses generation error: {e}")
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

    def _extract_response_text(self, text: str) -> str:
        """Extract the final response text from JSON or SSE event streams."""
        parsed_text = self._extract_response_text_from_json_payload(text)
        if parsed_text is not None:
            return parsed_text

        deltas = []
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            parsed_text = self._extract_response_text_from_json_payload(payload)
            if parsed_text is not None:
                return parsed_text
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "response.output_text.delta":
                delta = event.get("delta")
                if delta:
                    deltas.append(delta)

        return "".join(deltas).strip()

    def _extract_response_text_from_json_payload(self, payload: str) -> Optional[str]:
        """Extract text from a JSON payload when present."""
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None

        if data.get("type") == "response.output_text.done":
            return (data.get("text") or "").strip()

        message = ((data.get("choices") or [{}])[0].get("message") or {})
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

        response = data.get("response") or {}
        output = response.get("output") or []
        if not output:
            output = data.get("output") or []
        for item in output:
            if item.get("type") != "message":
                continue
            for part in item.get("content") or []:
                if part.get("type") == "output_text" and part.get("text"):
                    return part["text"].strip()

        return None


class MockClient(LLMClient):
    """Mock LLM client for testing."""

    async def generate(self, prompt: str, **kwargs) -> str:
        """Return mock response."""
        _consume_web_search_flag(kwargs, provider_name="mock", supported=False)
        return "Mock LLM response for testing purposes."

    async def generate_json(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Return mock JSON response based on prompt content."""
        _consume_web_search_flag(kwargs, provider_name="mock", supported=False)
        # Detect what kind of response is expected
        prompt_lower = prompt.lower()

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
                "confidence": 0.9
            }
        else:
            return {"result": "mock_response", "status": "success"}


@dataclass(frozen=True)
class ProviderSpec:
    """Configuration for a supported LLM provider."""

    name: str
    required_settings: tuple[tuple[str, str], ...]
    builder: Callable[[], LLMClient]


def _build_anthropic_client() -> LLMClient:
    return AnthropicClient(
        settings.anthropic_api_key,
        settings.anthropic_model,
        settings.anthropic_base_url,
    )


def _build_custom_client() -> LLMClient:
    if settings.custom_api_format == "openai_responses":
        return OpenAIResponsesClient(
            settings.custom_api_key,
            settings.custom_model,
            settings.custom_base_url,
        )

    return AnthropicClient(
        settings.custom_api_key,
        settings.custom_model,
        settings.custom_base_url,
        DEFAULT_ANTHROPIC_HEADERS,
    )


def _build_gemini_client() -> LLMClient:
    return GeminiClient(settings.gemini_api_key, settings.gemini_model)


def _build_zhipu_client() -> LLMClient:
    return ZhipuClient(settings.zhipu_api_key)


def _build_mock_client() -> LLMClient:
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
    "mock": ProviderSpec(name="mock", required_settings=tuple(), builder=_build_mock_client),
}


def _get_missing_settings(spec: ProviderSpec) -> list[str]:
    missing = []

    for attr_name, env_name in spec.required_settings:
        if not getattr(settings, attr_name):
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


# Factory function
_client_instance: Optional[LLMClient] = None
_provider_name: str = ""
_is_degraded: bool = False
_degradation_reason: Optional[str] = None


def get_llm_client() -> LLMClient:
    """
    Factory function to get the configured LLM client.

    Returns a singleton instance based on settings.llm_provider:
    - "anthropic"/"claude": Anthropic Claude (requires ANTHROPIC_API_KEY)
    - "custom": Custom Anthropic-compatible endpoint (requires CUSTOM_API_KEY)
    - "gemini": Google Gemini (requires GEMINI_API_KEY)
    - "zhipu": Zhipu ChatGLM (requires ZHIPU_API_KEY)
    - "mock": Mock client for testing (default)
    """
    global _client_instance, _provider_name, _is_degraded, _degradation_reason

    if _client_instance is not None:
        return _client_instance

    provider = settings.llm_provider.lower()
    spec = PROVIDER_REGISTRY.get(provider)

    if spec is None:
        reason = f"Unsupported LLM provider: {provider}"
        logger.error("%s, falling back to mock", reason)
        _client_instance = MockClient()
        _provider_name = "mock"
        _is_degraded = True
        _degradation_reason = reason
        logger.info("Initialized LLM provider 'mock'")
        return _client_instance

    missing_settings = _get_missing_settings(spec)
    if missing_settings:
        reason = f"Provider '{spec.name}' missing required settings: {', '.join(missing_settings)}"
        logger.error("%s. Falling back to mock", reason)
        _client_instance = MockClient()
        _provider_name = "mock"
        _is_degraded = True
        _degradation_reason = reason
        logger.info("Initialized LLM provider 'mock'")
        return _client_instance

    try:
        _client_instance = spec.builder()
        _provider_name = spec.name
        _is_degraded = False
        _degradation_reason = None
        _log_provider_initialized(spec.name, _client_instance)
    except Exception as exc:
        reason = f"Failed to initialize provider '{spec.name}': {exc}"
        logger.error("%s. Falling back to mock", reason)
        _client_instance = MockClient()
        _provider_name = "mock"
        _is_degraded = True
        _degradation_reason = reason
        logger.info("Initialized LLM provider 'mock'")

    return _client_instance


def get_llm_status() -> Dict[str, Any]:
    """
    Get the current LLM provider status.

    Returns:
        Dict with keys:
        - provider: str - actual provider being used
        - is_degraded: bool - whether fallback to mock occurred
        - degradation_reason: Optional[str] - why degradation happened
    """
    return {
        "provider": _provider_name,
        "is_degraded": _is_degraded,
        "degradation_reason": _degradation_reason,
    }


def reset_client():
    """Reset the singleton client (useful for testing)."""
    global _client_instance, _provider_name, _is_degraded, _degradation_reason
    _client_instance = None
    _provider_name = ""
    _is_degraded = False
    _degradation_reason = None
