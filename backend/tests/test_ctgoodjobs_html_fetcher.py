from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class _StubAsyncClient:
    def __init__(self, responses: list[tuple[int, str]]):
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def aclose(self) -> None:
        return None

    async def get(self, url: str, headers=None):
        self.calls.append({"url": url, "headers": headers})
        if not self._responses:
            raise AssertionError(f"Unexpected GET: {url}")
        status_code, body = self._responses.pop(0)
        request = httpx.Request("GET", url, headers=headers)
        return httpx.Response(status_code, text=body, request=request)


@pytest.mark.asyncio
async def test_ctgoodjobs_html_fetcher_rejects_human_verification_interstitial():
    from app.scraper.ctgoodjobs.html_fetcher import fetch_html_document

    client = _StubAsyncClient(
        [
            (
                200,
                """
                <html>
                  <body>
                    <h1>Let's confirm you are human</h1>
                    <p>Complete the security check before continuing.</p>
                  </body>
                </html>
                """,
            )
        ]
    )

    with pytest.raises(Exception, match=r"registry.*InterstitialChallenge.*ctgoodjobs.hk/jobs"):
        await fetch_html_document(
            "https://jobs.ctgoodjobs.hk/jobs",
            stage="registry",
            client=client,
            max_attempts=1,
        )
