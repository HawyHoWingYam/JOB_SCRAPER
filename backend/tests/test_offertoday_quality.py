from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime
from app.services.crawl_cancellation_token import CrawlCancellationRequested


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


async def _no_csrf_token() -> None:
    return None
