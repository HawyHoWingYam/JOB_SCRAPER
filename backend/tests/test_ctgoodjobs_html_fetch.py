from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.scraper.ctgoodjobs.detail_scraper import fetch_detail_page_html
from app.scraper.ctgoodjobs.list_scraper import fetch_category_page_html
from app.utils import anti_detection


class _SequencedAsyncClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def get(self, url: str, headers=None):
        self.calls.append({"url": url, "headers": headers})
        if not self._responses:
            raise AssertionError(f"Unexpected GET: {url}")

        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response

        status_code, body = response
        request = httpx.Request("GET", url, headers=headers)
        return httpx.Response(status_code, text=body, request=request)


@pytest.mark.asyncio
async def test_fetch_category_page_html_retries_transient_504_and_sends_browser_headers(monkeypatch):
    async def _no_wait(self, attempt: int) -> None:
        return None

    monkeypatch.setattr(anti_detection.ExponentialBackoff, "wait", _no_wait)
    client = _SequencedAsyncClient([(504, "gateway timeout"), (200, "<html>ok</html>")])

    html = await fetch_category_page_html("https://jobs.ctgoodjobs.hk/jobs", client=client)

    assert html == "<html>ok</html>"
    assert len(client.calls) == 2
    headers = client.calls[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["Accept"].startswith("text/html")
    assert "User-Agent" in headers


@pytest.mark.asyncio
async def test_fetch_category_page_html_does_not_retry_non_transient_404(monkeypatch):
    waits: list[int] = []

    async def _record_wait(self, attempt: int) -> None:
        waits.append(attempt)

    monkeypatch.setattr(anti_detection.ExponentialBackoff, "wait", _record_wait)
    client = _SequencedAsyncClient([(404, "missing")])

    with pytest.raises(Exception, match=r"registry.*404.*https://jobs\.ctgoodjobs\.hk/jobs"):
        await fetch_category_page_html("https://jobs.ctgoodjobs.hk/jobs", client=client)

    assert len(client.calls) == 1
    assert waits == []


@pytest.mark.asyncio
async def test_fetch_detail_page_html_raises_context_after_retry_exhaustion(monkeypatch):
    async def _no_wait(self, attempt: int) -> None:
        return None

    monkeypatch.setattr(anti_detection.ExponentialBackoff, "wait", _no_wait)
    client = _SequencedAsyncClient(
        [
            httpx.RemoteProtocolError("peer closed connection"),
            httpx.RemoteProtocolError("peer closed connection"),
            httpx.RemoteProtocolError("peer closed connection"),
        ]
    )

    with pytest.raises(
        Exception,
        match=r"detail_page.*RemoteProtocolError.*https://jobs\.ctgoodjobs\.hk/job/1234",
    ):
        await fetch_detail_page_html("https://jobs.ctgoodjobs.hk/job/1234", client=client)

    assert len(client.calls) == 3
