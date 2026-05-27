from __future__ import annotations

import json
import logging
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

PROXY_STAGES = ("registry", "category_page", "detail_page")
PROXY_METRIC_KEYS = (
    "proxy_requests_total",
    "proxy_requests_success",
    "proxy_requests_challenge",
    "proxy_requests_network_fail",
    "proxy_requests_http_fail",
)
_ACTIVE_PROXY_RUNTIME: ContextVar[CTGoodJobsProxyRuntime | None] = ContextVar(
    "ctgoodjobs_proxy_runtime",
    default=None,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _empty_stage_metrics() -> dict[str, int]:
    return {key: 0 for key in PROXY_METRIC_KEYS}


def _normalize_proxy_url(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("Proxy URL cannot be empty")
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    return normalized


def _parse_provider_auth_header(value: str | None) -> dict[str, str]:
    header = str(value or "").strip()
    if not header or ":" not in header:
        return {}
    name, raw_value = header.split(":", 1)
    if not name.strip() or not raw_value.strip():
        return {}
    return {name.strip(): raw_value.strip()}


def _proxy_url_supports_https_tunneling(proxy_url: str) -> bool:
    scheme = urlsplit(_normalize_proxy_url(proxy_url)).scheme.lower()
    return scheme in {"http", "https", "socks5", "socks5h"}


def _build_playwright_proxy_config_from_url(proxy_url: str) -> dict[str, str]:
    parsed = urlsplit(_normalize_proxy_url(proxy_url))
    netloc_without_auth = parsed.netloc.rsplit("@", 1)[-1]
    config = {
        "server": urlunsplit((parsed.scheme, netloc_without_auth, parsed.path, parsed.query, parsed.fragment)),
    }

    if parsed.username is not None:
        config["username"] = unquote(parsed.username)
    if parsed.password is not None:
        config["password"] = unquote(parsed.password)

    return config


@dataclass(frozen=True)
class ProxyLease:
    proxy_url: str
    provider_name: str
    identity: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ProxyProvider(Protocol):
    async def acquire_lease(self) -> ProxyLease:
        ...

    async def quarantine(self, lease: ProxyLease) -> None:
        ...


class StaticProxyProvider:
    def __init__(self, *, proxy_url: str, provider_name: str = "static") -> None:
        self.proxy_url = _normalize_proxy_url(proxy_url)
        self.provider_name = provider_name

    async def acquire_lease(self) -> ProxyLease:
        return ProxyLease(
            proxy_url=self.proxy_url,
            provider_name=self.provider_name,
            identity=None,
            metadata={
                "https_capable": _proxy_url_supports_https_tunneling(self.proxy_url),
            },
        )

    async def quarantine(self, lease: ProxyLease) -> None:  # pragma: no cover - static endpoint is best-effort
        logger.warning(
            "CTGoodJobs static proxy lease marked unhealthy but cannot be quarantined individually: proxy=%s",
            lease.proxy_url,
        )


class ProxyPoolApiProvider:
    def __init__(
        self,
        *,
        api_base_url: str,
        get_path: str = "/get",
        delete_path: str | None = None,
        client: httpx.AsyncClient | None = None,
        request_headers: dict[str, str] | None = None,
        provider_name: str = "pool_api",
        timeout_s: float = 30.0,
    ) -> None:
        self.api_base_url = str(api_base_url or "").rstrip("/")
        self.get_path = get_path or "/get"
        self.delete_path = delete_path or None
        self.client = client
        self.request_headers = dict(request_headers or {})
        self.provider_name = provider_name
        self.timeout_s = max(float(timeout_s), 1.0)

    async def acquire_lease(self) -> ProxyLease:
        response = await self._request("GET", self.get_path)
        response.raise_for_status()
        payload = self._parse_response_payload(response)
        proxy_url = _normalize_proxy_url(payload["proxy_url"])
        return ProxyLease(
            proxy_url=proxy_url,
            provider_name=self.provider_name,
            identity=payload.get("identity"),
            metadata={
                "https_capable": bool(
                    payload.get("https_capable", _proxy_url_supports_https_tunneling(proxy_url))
                ),
                "raw_proxy": payload.get("raw_proxy") or payload["proxy_url"],
            },
        )

    async def quarantine(self, lease: ProxyLease) -> None:
        if not self.delete_path:
            return
        proxy_value = lease.metadata.get("raw_proxy") or lease.proxy_url
        response = await self._request("GET", self.delete_path, params={"proxy": proxy_value})
        response.raise_for_status()

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if self.client is not None:
            return await self.client.request(
                method,
                urljoin(f"{self.api_base_url}/", path.lstrip("/")),
                headers=self.request_headers,
                **kwargs,
            )

        async with httpx.AsyncClient(trust_env=False) as client:
            return await client.request(
                method,
                urljoin(f"{self.api_base_url}/", path.lstrip("/")),
                headers=self.request_headers,
                timeout=self.timeout_s,
                **kwargs,
            )

    def _parse_response_payload(self, response: httpx.Response) -> dict[str, Any]:
        content_type = str(response.headers.get("content-type") or "").lower()
        if "application/json" in content_type:
            return self._normalize_payload(response.json())

        text = response.text.strip()
        if not text:
            raise ValueError("Proxy pool provider returned an empty lease response")

        try:
            return self._normalize_payload(json.loads(text))
        except json.JSONDecodeError:
            return self._normalize_payload(text)

    def _normalize_payload(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, str):
            return {
                "proxy_url": payload,
                "raw_proxy": payload,
                "identity": payload,
                "https_capable": _proxy_url_supports_https_tunneling(payload),
            }

        if not isinstance(payload, dict):
            raise ValueError(f"Unsupported proxy pool response payload: {payload!r}")

        raw_proxy = payload.get("proxy")
        if not raw_proxy and isinstance(payload.get("https"), str):
            raw_proxy = payload.get("https")
        if not raw_proxy and payload.get("host") and payload.get("port"):
            raw_proxy = f"{payload['host']}:{payload['port']}"
        if not raw_proxy:
            raise ValueError(f"Proxy pool response did not include a proxy address: {payload!r}")

        https_value = payload.get("https_capable", payload.get("https"))
        https_capable = bool(https_value) if not isinstance(https_value, str) else https_value.lower() == "true"
        identity = str(payload.get("id") or payload.get("identity") or raw_proxy)
        return {
            "proxy_url": raw_proxy,
            "raw_proxy": raw_proxy,
            "identity": identity,
            "https_capable": https_capable,
        }


@dataclass
class ProxyHealthRecord:
    success_count: int = 0
    challenge_count: int = 0
    network_fail_count: int = 0
    http_403_429_count: int = 0
    http_5xx_count: int = 0
    last_used_at: datetime | None = None
    quarantine_until: datetime | None = None
    consecutive_challenges: int = 0
    consecutive_network_failures: int = 0
    consecutive_http_403_429_failures: int = 0
    score: int = 0
    recent_outcomes: deque[str] = field(default_factory=lambda: deque(maxlen=10))


class InMemoryProxyHealthService:
    def __init__(
        self,
        *,
        quarantine_minutes_challenge: int = 15,
        quarantine_minutes_network: int = 10,
    ) -> None:
        self.quarantine_minutes_challenge = int(quarantine_minutes_challenge)
        self.quarantine_minutes_network = int(quarantine_minutes_network)
        self._records: dict[str, ProxyHealthRecord] = {}

    def get_state(self, identity: str | None) -> ProxyHealthRecord | None:
        if not identity:
            return None
        return self._records.get(identity)

    def is_quarantined(self, identity: str | None, *, now: datetime | None = None) -> bool:
        state = self.get_state(identity)
        if state is None or state.quarantine_until is None:
            return False
        current_time = now or _utc_now()
        return current_time < state.quarantine_until

    def seconds_since_last_use(self, identity: str | None, *, now: datetime | None = None) -> float | None:
        state = self.get_state(identity)
        if state is None or state.last_used_at is None:
            return None
        current_time = now or _utc_now()
        return max((current_time - state.last_used_at).total_seconds(), 0.0)

    def should_deprioritize(self, identity: str | None) -> bool:
        state = self.get_state(identity)
        if state is None:
            return False
        recent_total = len(state.recent_outcomes)
        if recent_total < 4:
            return False
        recent_successes = sum(1 for outcome in state.recent_outcomes if outcome == "success")
        return (recent_successes / recent_total) < 0.25

    def mark_lease_used(self, lease: ProxyLease, *, now: datetime | None = None) -> None:
        if not lease.identity:
            return
        state = self._records.setdefault(lease.identity, ProxyHealthRecord())
        state.last_used_at = now or _utc_now()

    def record_success(self, lease: ProxyLease, *, now: datetime | None = None) -> bool:
        state = self._ensure_state(lease)
        if state is None:
            return False
        state.success_count += 1
        state.consecutive_challenges = 0
        state.consecutive_network_failures = 0
        state.consecutive_http_403_429_failures = 0
        state.score += 1
        state.recent_outcomes.append("success")
        state.last_used_at = now or _utc_now()
        return False

    def record_challenge(self, lease: ProxyLease, *, now: datetime | None = None) -> bool:
        state = self._ensure_state(lease)
        if state is None:
            return False
        current_time = now or _utc_now()
        state.challenge_count += 1
        state.consecutive_challenges += 1
        state.consecutive_network_failures = 0
        state.consecutive_http_403_429_failures = 0
        state.score -= 3
        state.recent_outcomes.append("challenge")
        state.last_used_at = current_time
        if state.consecutive_challenges >= 2:
            state.quarantine_until = current_time + timedelta(minutes=self.quarantine_minutes_challenge)
            return True
        return False

    def record_network_failure(self, lease: ProxyLease, *, now: datetime | None = None) -> bool:
        state = self._ensure_state(lease)
        if state is None:
            return False
        current_time = now or _utc_now()
        state.network_fail_count += 1
        state.consecutive_network_failures += 1
        state.consecutive_challenges = 0
        state.consecutive_http_403_429_failures = 0
        state.score -= 2
        state.recent_outcomes.append("network_fail")
        state.last_used_at = current_time
        if state.consecutive_network_failures >= 2:
            state.quarantine_until = current_time + timedelta(minutes=self.quarantine_minutes_network)
            return True
        return False

    def record_http_failure(
        self,
        lease: ProxyLease,
        *,
        status_code: int | None,
        now: datetime | None = None,
    ) -> bool:
        state = self._ensure_state(lease)
        if state is None:
            return False
        current_time = now or _utc_now()
        state.consecutive_challenges = 0
        state.consecutive_network_failures = 0
        state.last_used_at = current_time
        if status_code in {403, 429}:
            state.http_403_429_count += 1
            state.consecutive_http_403_429_failures += 1
            state.score -= 3
            state.recent_outcomes.append("http_403_429")
            if state.consecutive_http_403_429_failures >= 2:
                state.quarantine_until = current_time + timedelta(minutes=self.quarantine_minutes_challenge)
                return True
            return False
        state.consecutive_http_403_429_failures = 0
        if status_code is not None and status_code >= 500:
            state.http_5xx_count += 1
            state.score -= 1
            state.recent_outcomes.append("http_5xx")
        else:
            state.recent_outcomes.append("http_fail")
        return False

    def _ensure_state(self, lease: ProxyLease) -> ProxyHealthRecord | None:
        if not lease.identity:
            return None
        return self._records.setdefault(lease.identity, ProxyHealthRecord())


class ProxySelectionPolicy:
    def __init__(
        self,
        *,
        min_seconds_between_reuse: float = 0.0,
        require_https_capable: bool = False,
        max_provider_attempts: int = 5,
    ) -> None:
        self.min_seconds_between_reuse = max(float(min_seconds_between_reuse), 0.0)
        self.require_https_capable = bool(require_https_capable)
        self.max_provider_attempts = max(1, int(max_provider_attempts))

    async def acquire_lease(
        self,
        provider: ProxyProvider,
        health_service: InMemoryProxyHealthService,
    ) -> ProxyLease:
        for _ in range(self.max_provider_attempts):
            lease = await provider.acquire_lease()
            if self.require_https_capable and not bool(lease.metadata.get("https_capable", False)):
                continue
            if lease.identity and health_service.is_quarantined(lease.identity):
                continue
            if lease.identity and self.min_seconds_between_reuse > 0:
                seconds_since_last_use = health_service.seconds_since_last_use(lease.identity)
                if (
                    seconds_since_last_use is not None
                    and seconds_since_last_use < self.min_seconds_between_reuse
                ):
                    continue
            if lease.identity and health_service.should_deprioritize(lease.identity):
                continue
            health_service.mark_lease_used(lease)
            return lease
        raise RuntimeError("Unable to acquire a usable CTGoodJobs proxy lease")


class CTGoodJobsProxyRuntime:
    def __init__(
        self,
        *,
        provider: ProxyProvider | None = None,
        health_service: InMemoryProxyHealthService | None = None,
        selection_policy: ProxySelectionPolicy | None = None,
        request_headers: dict[str, str] | None = None,
        enabled: bool | None = None,
        provider_name: str | None = None,
        request_timeout_s: float = 30.0,
    ) -> None:
        self.provider = provider
        self.health_service = health_service or InMemoryProxyHealthService()
        self.selection_policy = selection_policy or ProxySelectionPolicy()
        self.request_headers = dict(request_headers or {})
        self.enabled = bool(enabled if enabled is not None else provider is not None)
        self.provider_name = provider_name or (
            getattr(provider, "provider_name", None) if provider is not None else "disabled"
        )
        self.request_timeout_s = max(float(request_timeout_s), 1.0)
        self._totals = _empty_stage_metrics()
        self._stage_metrics = {stage: _empty_stage_metrics() for stage in PROXY_STAGES}
        self._quarantined_total = 0

    async def acquire_lease(self) -> ProxyLease | None:
        if not self.enabled or self.provider is None:
            return None
        return await self.selection_policy.acquire_lease(self.provider, self.health_service)

    def build_httpx_client_kwargs(self, lease: ProxyLease | None) -> dict[str, Any]:
        if lease is None:
            return {}
        return {"proxy": lease.proxy_url}

    def build_playwright_proxy_config(self, lease: ProxyLease | None) -> dict[str, str] | None:
        if lease is None:
            return None
        return _build_playwright_proxy_config_from_url(lease.proxy_url)

    def merge_request_headers(self, headers: dict[str, str]) -> dict[str, str]:
        return {
            **headers,
            **self.request_headers,
        }

    def metadata(self) -> dict[str, Any]:
        return {
            "proxy_enabled": bool(self.enabled),
            "proxy_provider": self.provider_name if self.enabled else "disabled",
        }

    def metrics_snapshot(self) -> dict[str, Any]:
        return {
            **self._totals,
            "proxy_quarantined_total": int(self._quarantined_total),
            "proxy_metrics_by_stage": {
                stage: dict(metrics)
                for stage, metrics in self._stage_metrics.items()
            },
        }

    async def report_success(self, *, stage: str, lease: ProxyLease | None) -> None:
        self._record_metric("proxy_requests_total", stage)
        self._record_metric("proxy_requests_success", stage)
        if lease is not None:
            self.health_service.record_success(lease)

    async def report_challenge(self, *, stage: str, lease: ProxyLease | None) -> None:
        self._record_metric("proxy_requests_total", stage)
        self._record_metric("proxy_requests_challenge", stage)
        await self._handle_quarantine(
            lease=lease,
            should_quarantine=self.health_service.record_challenge(lease) if lease is not None else False,
        )

    async def report_network_failure(self, *, stage: str, lease: ProxyLease | None) -> None:
        self._record_metric("proxy_requests_total", stage)
        self._record_metric("proxy_requests_network_fail", stage)
        await self._handle_quarantine(
            lease=lease,
            should_quarantine=self.health_service.record_network_failure(lease) if lease is not None else False,
        )

    async def report_http_failure(
        self,
        *,
        stage: str,
        lease: ProxyLease | None,
        status_code: int | None,
    ) -> None:
        self._record_metric("proxy_requests_total", stage)
        self._record_metric("proxy_requests_http_fail", stage)
        if lease is not None:
            self.health_service.record_http_failure(lease, status_code=status_code)

    def _record_metric(self, key: str, stage: str) -> None:
        if key in self._totals:
            self._totals[key] += 1
        if stage in self._stage_metrics and key in self._stage_metrics[stage]:
            self._stage_metrics[stage][key] += 1

    async def _handle_quarantine(self, *, lease: ProxyLease | None, should_quarantine: bool) -> None:
        if not should_quarantine or lease is None or self.provider is None:
            return
        self._quarantined_total += 1
        try:
            await self.provider.quarantine(lease)
        except Exception:  # pragma: no cover - quarantine cleanup is best-effort
            logger.exception("Failed to quarantine CTGoodJobs proxy lease: %s", lease.proxy_url)


def get_active_ctgoodjobs_proxy_runtime() -> CTGoodJobsProxyRuntime | None:
    return _ACTIVE_PROXY_RUNTIME.get()


@contextmanager
def activate_ctgoodjobs_proxy_runtime(runtime: CTGoodJobsProxyRuntime | None):
    token = _ACTIVE_PROXY_RUNTIME.set(runtime)
    try:
        yield runtime
    finally:
        _ACTIVE_PROXY_RUNTIME.reset(token)


def build_ctgoodjobs_proxy_runtime(
    *,
    settings_source: Any = settings,
    client: httpx.AsyncClient | None = None,
) -> CTGoodJobsProxyRuntime:
    if not bool(getattr(settings_source, "ctgoodjobs_proxy_enabled", False)):
        return CTGoodJobsProxyRuntime(enabled=False, provider_name="disabled")

    provider_name = str(getattr(settings_source, "ctgoodjobs_proxy_provider", "static") or "static").strip().lower()
    request_headers = _parse_provider_auth_header(
        getattr(settings_source, "ctgoodjobs_proxy_provider_auth_header", None)
    )

    if provider_name == "static":
        provider: ProxyProvider = StaticProxyProvider(
            proxy_url=getattr(settings_source, "ctgoodjobs_proxy_static_url", None),
            provider_name=provider_name,
        )
    elif provider_name in {"pool_api", "proxy_pool"}:
        api_base_url = str(getattr(settings_source, "ctgoodjobs_proxy_pool_api_base_url", "") or "").strip()
        if not api_base_url:
            raise ValueError("ctgoodjobs_proxy_pool_api_base_url must be configured for pool_api proxy mode")
        provider = ProxyPoolApiProvider(
            api_base_url=api_base_url,
            get_path=getattr(settings_source, "ctgoodjobs_proxy_pool_get_path", "/get"),
            delete_path=getattr(settings_source, "ctgoodjobs_proxy_pool_delete_path", None),
            client=client,
            request_headers=request_headers,
            provider_name=provider_name,
            timeout_s=getattr(settings_source, "ctgoodjobs_proxy_request_timeout_s", 30.0),
        )
    else:
        raise ValueError(f"Unsupported CTGoodJobs proxy provider: {provider_name}")

    return CTGoodJobsProxyRuntime(
        provider=provider,
        provider_name=provider_name,
        health_service=InMemoryProxyHealthService(
            quarantine_minutes_challenge=getattr(
                settings_source,
                "ctgoodjobs_proxy_quarantine_minutes_challenge",
                15,
            ),
            quarantine_minutes_network=getattr(
                settings_source,
                "ctgoodjobs_proxy_quarantine_minutes_network",
                10,
            ),
        ),
        selection_policy=ProxySelectionPolicy(
            min_seconds_between_reuse=getattr(
                settings_source,
                "ctgoodjobs_proxy_min_seconds_between_reuse",
                0.0,
            ),
            require_https_capable=bool(
                getattr(settings_source, "ctgoodjobs_proxy_require_https_capable", False)
            ),
        ),
        request_headers=request_headers,
        enabled=True,
        request_timeout_s=getattr(settings_source, "ctgoodjobs_proxy_request_timeout_s", 30.0),
    )
