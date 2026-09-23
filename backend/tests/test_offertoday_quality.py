from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime
from app.services.crawl_cancellation_token import CrawlCancellationRequested
from app.sources.offertoday.response_policy import OfferTodayTransportError


@pytest.mark.asyncio
async def test_offertoday_cancellation_gate_runs_immediately_before_fetch() -> None:
    page = SimpleNamespace(evaluate_calls=0)

    async def evaluate(*_args, **_kwargs):
        page.evaluate_calls += 1
        return None

    page.evaluate = evaluate

    class _CancelledToken:
        @staticmethod
        def raise_if_cancelled() -> None:
            raise CrawlCancellationRequested("cancelled")

    runtime = OfferTodayBrowserRuntime(cancellation_token=_CancelledToken())
    runtime._page = page
    runtime._read_csrf_token = _no_csrf_token

    with pytest.raises(CrawlCancellationRequested):
        await runtime._fetch_json_response(
            "https://api.offertoday.com/api/job/jobList/search",
            method="POST",
            payload={},
        )

    assert page.evaluate_calls == 0


@pytest.mark.asyncio
async def test_offertoday_browser_request_has_a_deadline_that_aborts_body_read() -> None:
    page = SimpleNamespace(url="https://www.offertoday.com/hk/search")

    async def evaluate(script, argument=None):
        if "document.cookie" in script:
            return None
        assert "AbortController" in script
        assert "await response.text()" in script
        assert argument["requestTimeoutMs"] == 25
        raise RuntimeError("Page.evaluate: AbortError: The operation was aborted")

    page.evaluate = evaluate
    runtime = OfferTodayBrowserRuntime(
        headed=False,
        request_timeout_ms=25,
    )
    runtime._page = page

    with pytest.raises(OfferTodayTransportError) as raised:
        await runtime._fetch_json_response(
            "https://www.offertoday.com/wapi/geek/recommend/search/list",
            method="POST",
            payload={"page": 29},
        )

    assert raised.value.error_kind == "network"
    assert "timed out" in str(raised.value).lower()


async def _no_csrf_token() -> None:
    return None
