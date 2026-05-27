from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.scraper.ctgoodjobs.html_fetcher import CTGoodJobsFetchError, fetch_html_document
from app.scraper.proxy_rotation import (
    CTGoodJobsProxyRuntime,
    InMemoryProxyHealthService,
    ProxyLease,
    ProxyPoolApiProvider,
    ProxySelectionPolicy,
    StaticProxyProvider,
)


class FakeProxyProvider:
    def __init__(self, leases: list[ProxyLease]) -> None:
        self._leases = list(leases)
        self.acquired: list[str | None] = []

    async def acquire_lease(self) -> ProxyLease:
        lease = self._leases.pop(0)
        self.acquired.append(lease.identity)
        return lease

    async def quarantine(self, lease: ProxyLease) -> None:
        return None


def test_proxy_health_service_quarantines_after_two_challenges():
    health = InMemoryProxyHealthService(quarantine_minutes_challenge=15)
    lease = ProxyLease(
        proxy_url="http://proxy-a:8080",
        provider_name="pool_api",
        identity="proxy-a",
    )
    start = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)

    health.mark_lease_used(lease, now=start)
    assert health.record_challenge(lease, now=start) is False
    assert health.record_challenge(lease, now=start + timedelta(minutes=1)) is True

    state = health.get_state("proxy-a")
    assert state is not None
    assert state.challenge_count == 2
    assert state.quarantine_until == start + timedelta(minutes=16)


def test_proxy_health_service_quarantines_after_two_network_failures():
    health = InMemoryProxyHealthService(quarantine_minutes_network=10)
    lease = ProxyLease(
        proxy_url="http://proxy-b:8080",
        provider_name="pool_api",
        identity="proxy-b",
    )
    start = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)

    health.mark_lease_used(lease, now=start)
    assert health.record_network_failure(lease, now=start) is False
    assert health.record_network_failure(lease, now=start + timedelta(minutes=1)) is True

    state = health.get_state("proxy-b")
    assert state is not None
    assert state.network_fail_count == 2
    assert state.quarantine_until == start + timedelta(minutes=11)


def test_proxy_health_service_tracks_http_403_429_penalties():
    health = InMemoryProxyHealthService()
    lease = ProxyLease(
        proxy_url="http://proxy-c:8080",
        provider_name="pool_api",
        identity="proxy-c",
    )

    assert health.record_http_failure(lease, status_code=429) is False

    state = health.get_state("proxy-c")
    assert state is not None
    assert state.http_403_429_count == 1
    assert state.score == -3


@pytest.mark.asyncio
async def test_selection_policy_deprioritizes_proxies_with_poor_recent_success_rate():
    health = InMemoryProxyHealthService()
    weak_lease = ProxyLease(
        proxy_url="http://proxy-weak:8080",
        provider_name="pool_api",
        identity="proxy-weak",
    )
    strong_lease = ProxyLease(
        proxy_url="http://proxy-strong:8080",
        provider_name="pool_api",
        identity="proxy-strong",
    )

    health.record_challenge(weak_lease)
    health.record_network_failure(weak_lease)
    health.record_http_failure(weak_lease, status_code=429)
    health.record_http_failure(weak_lease, status_code=503)

    provider = FakeProxyProvider([weak_lease, strong_lease])
    policy = ProxySelectionPolicy()

    selected = await policy.acquire_lease(provider, health)

    assert selected.identity == "proxy-strong"
    assert provider.acquired == ["proxy-weak", "proxy-strong"]


@pytest.mark.asyncio
async def test_proxy_pool_provider_parses_proxy_pool_get_response():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "proxy": "http://10.0.0.5:9000",
                "id": "pool-proxy-1",
                "https": True,
            },
        )
    )
    client = httpx.AsyncClient(transport=transport)
    provider = ProxyPoolApiProvider(
        api_base_url="http://pool.local",
        get_path="/get",
        delete_path="/delete",
        client=client,
    )

    lease = await provider.acquire_lease()

    assert lease.proxy_url == "http://10.0.0.5:9000"
    assert lease.identity == "pool-proxy-1"
    assert lease.metadata["https_capable"] is True

    await client.aclose()


@pytest.mark.asyncio
async def test_proxy_pool_provider_uses_delete_endpoint_when_quarantining():
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(f"{request.url.path}?{request.url.query.decode()}")
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ProxyPoolApiProvider(
        api_base_url="http://pool.local",
        get_path="/get",
        delete_path="/delete",
        client=client,
    )

    await provider.quarantine(
        ProxyLease(
            proxy_url="http://10.0.0.6:9000",
            provider_name="pool_api",
            identity="pool-proxy-2",
            metadata={"raw_proxy": "10.0.0.6:9000"},
        )
    )

    assert requested_paths == ["/delete?proxy=10.0.0.6%3A9000"]

    await client.aclose()


@pytest.mark.asyncio
async def test_proxy_pool_provider_internal_client_disables_env_proxy_resolution(monkeypatch):
    created_clients: list[dict] = []

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            created_clients.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def request(self, method, url, headers=None, timeout=None, **kwargs):
            return httpx.Response(
                200,
                json={"proxy": "http://10.0.0.9:9000", "id": "pool-proxy-9"},
                request=httpx.Request(method, url, headers=headers),
            )

    monkeypatch.setattr("app.scraper.proxy_rotation.httpx.AsyncClient", FakeAsyncClient)

    provider = ProxyPoolApiProvider(
        api_base_url="http://pool.local",
        get_path="/get",
    )

    lease = await provider.acquire_lease()

    assert lease.identity == "pool-proxy-9"
    assert created_clients == [{"trust_env": False}]


@pytest.mark.asyncio
async def test_fetch_html_document_retries_with_fresh_proxy_leases_and_tracks_metrics(monkeypatch):
    leases = [
        ProxyLease(
            proxy_url="http://proxy-a:8080",
            provider_name="pool_api",
            identity="proxy-a",
        ),
        ProxyLease(
            proxy_url="http://proxy-b:8080",
            provider_name="pool_api",
            identity="proxy-b",
        ),
    ]
    provider = FakeProxyProvider(leases)
    runtime = CTGoodJobsProxyRuntime(
        provider=provider,
        health_service=InMemoryProxyHealthService(),
        selection_policy=ProxySelectionPolicy(),
    )

    responses = iter(
        [
            httpx.Response(200, text="Just a moment"),
            httpx.Response(200, text="<html>ok</html>"),
        ]
    )
    created_clients: list[dict] = []

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            created_clients.append(kwargs)

        async def get(self, url, headers=None):
            response = next(responses)
            response.request = httpx.Request("GET", url, headers=headers)
            return response

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("app.scraper.ctgoodjobs.html_fetcher.httpx.AsyncClient", FakeAsyncClient)

    html = await fetch_html_document(
        "https://jobs.ctgoodjobs.hk/job/1001",
        stage="detail_page",
        timeout_s=12.0,
        max_attempts=2,
        proxy_runtime=runtime,
    )

    assert html == "<html>ok</html>"
    assert provider.acquired == ["proxy-a", "proxy-b"]
    assert [client_kwargs["proxy"] for client_kwargs in created_clients] == [
        "http://proxy-a:8080",
        "http://proxy-b:8080",
    ]
    assert all(client_kwargs["trust_env"] is False for client_kwargs in created_clients)

    metrics = runtime.metrics_snapshot()
    assert metrics["proxy_requests_total"] == 2
    assert metrics["proxy_requests_success"] == 1
    assert metrics["proxy_requests_challenge"] == 1
    assert metrics["proxy_metrics_by_stage"]["detail_page"]["proxy_requests_total"] == 2


@pytest.mark.asyncio
async def test_fetch_html_document_owned_client_disables_env_proxy_resolution(monkeypatch):
    runtime = CTGoodJobsProxyRuntime(enabled=False, provider_name="disabled")
    created_clients: list[dict] = []

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            created_clients.append(kwargs)

        async def get(self, url, headers=None):
            response = httpx.Response(200, text="<html>ok</html>")
            response.request = httpx.Request("GET", url, headers=headers)
            return response

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("app.scraper.ctgoodjobs.html_fetcher.httpx.AsyncClient", FakeAsyncClient)

    html = await fetch_html_document(
        "https://jobs.ctgoodjobs.hk/job/1005",
        stage="detail_page",
        timeout_s=12.0,
        proxy_runtime=runtime,
    )

    assert html == "<html>ok</html>"
    assert created_clients == [{"timeout": 12.0, "follow_redirects": True, "trust_env": False}]


@pytest.mark.asyncio
async def test_playwright_proxy_config_splits_credentials_from_proxy_url():
    lease = await StaticProxyProvider(
        proxy_url="http://user-1:pass-2@proxy.example.com:8080",
    ).acquire_lease()
    runtime = CTGoodJobsProxyRuntime(enabled=True, provider_name="static")

    assert runtime.build_playwright_proxy_config(lease) == {
        "server": "http://proxy.example.com:8080",
        "username": "user-1",
        "password": "pass-2",
    }


@pytest.mark.asyncio
async def test_static_http_proxy_is_treated_as_https_capable_for_tunneling():
    lease = await StaticProxyProvider(
        proxy_url="http://proxy.example.com:8080",
    ).acquire_lease()

    assert lease.metadata["https_capable"] is True


@pytest.mark.asyncio
async def test_proxy_pool_provider_defaults_http_proxy_strings_to_https_capable():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text="http://10.0.0.5:9000",
        )
    )
    client = httpx.AsyncClient(transport=transport)
    provider = ProxyPoolApiProvider(
        api_base_url="http://pool.local",
        get_path="/get",
        delete_path="/delete",
        client=client,
    )

    lease = await provider.acquire_lease()

    assert lease.metadata["https_capable"] is True

    await client.aclose()


@pytest.mark.asyncio
async def test_fetch_html_document_marks_challenge_exhaustion_errors(monkeypatch):
    provider = FakeProxyProvider(
        [
            ProxyLease(
                proxy_url="http://proxy-a:8080",
                provider_name="pool_api",
                identity="proxy-a",
            ),
        ]
    )
    runtime = CTGoodJobsProxyRuntime(
        provider=provider,
        health_service=InMemoryProxyHealthService(),
        selection_policy=ProxySelectionPolicy(),
    )

    class FakeAsyncClient:
        def __init__(self, **_kwargs) -> None:
            return None

        async def get(self, url, headers=None):
            response = httpx.Response(200, text="Just a moment")
            response.request = httpx.Request("GET", url, headers=headers)
            return response

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("app.scraper.ctgoodjobs.html_fetcher.httpx.AsyncClient", FakeAsyncClient)

    with pytest.raises(CTGoodJobsFetchError) as exc_info:
        await fetch_html_document(
            "https://jobs.ctgoodjobs.hk/job/1004",
            stage="detail_page",
            max_attempts=1,
            proxy_runtime=runtime,
        )

    assert exc_info.value.challenge_detected is True


@pytest.mark.asyncio
async def test_fetch_html_document_retries_after_network_failure_with_new_proxy_lease(monkeypatch):
    provider = FakeProxyProvider(
        [
            ProxyLease(
                proxy_url="http://proxy-a:8080",
                provider_name="pool_api",
                identity="proxy-a",
            ),
            ProxyLease(
                proxy_url="http://proxy-b:8080",
                provider_name="pool_api",
                identity="proxy-b",
            ),
        ]
    )
    runtime = CTGoodJobsProxyRuntime(
        provider=provider,
        health_service=InMemoryProxyHealthService(),
        selection_policy=ProxySelectionPolicy(),
    )
    created_clients: list[dict] = []

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            created_clients.append(kwargs)
            self.calls = 0

        async def get(self, url, headers=None):
            self.calls += 1
            if len(created_clients) == 1:
                raise httpx.ConnectError("proxy failed", request=httpx.Request("GET", url, headers=headers))
            response = httpx.Response(200, text="<html>ok</html>")
            response.request = httpx.Request("GET", url, headers=headers)
            return response

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("app.scraper.ctgoodjobs.html_fetcher.httpx.AsyncClient", FakeAsyncClient)

    html = await fetch_html_document(
        "https://jobs.ctgoodjobs.hk/job/1003",
        stage="detail_page",
        max_attempts=2,
        proxy_runtime=runtime,
    )

    assert html == "<html>ok</html>"
    assert provider.acquired == ["proxy-a", "proxy-b"]
    assert [client_kwargs["proxy"] for client_kwargs in created_clients] == [
        "http://proxy-a:8080",
        "http://proxy-b:8080",
    ]

    metrics = runtime.metrics_snapshot()
    assert metrics["proxy_requests_total"] == 2
    assert metrics["proxy_requests_network_fail"] == 1
    assert metrics["proxy_requests_success"] == 1


@pytest.mark.asyncio
async def test_fetch_html_document_does_not_reuse_proxy_leases_across_calls(monkeypatch):
    provider = FakeProxyProvider(
        [
            ProxyLease(
                proxy_url="http://proxy-a:8080",
                provider_name="pool_api",
                identity="proxy-a",
            ),
            ProxyLease(
                proxy_url="http://proxy-b:8080",
                provider_name="pool_api",
                identity="proxy-b",
            ),
        ]
    )
    runtime = CTGoodJobsProxyRuntime(
        provider=provider,
        health_service=InMemoryProxyHealthService(),
        selection_policy=ProxySelectionPolicy(),
    )
    created_clients: list[dict] = []

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            created_clients.append(kwargs)

        async def get(self, url, headers=None):
            response = httpx.Response(200, text="<html>ok</html>")
            response.request = httpx.Request("GET", url, headers=headers)
            return response

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("app.scraper.ctgoodjobs.html_fetcher.httpx.AsyncClient", FakeAsyncClient)

    await fetch_html_document(
        "https://jobs.ctgoodjobs.hk/jobs",
        stage="registry",
        proxy_runtime=runtime,
    )
    await fetch_html_document(
        "https://jobs.ctgoodjobs.hk/job/1002",
        stage="detail_page",
        proxy_runtime=runtime,
    )

    assert provider.acquired == ["proxy-a", "proxy-b"]
    assert [client_kwargs["proxy"] for client_kwargs in created_clients] == [
        "http://proxy-a:8080",
        "http://proxy-b:8080",
    ]
