from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.scraper.category_scraper import CategoryListScraper


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"data": [], "totalCount": 0}


class _FakeAsyncClient:
    def __init__(self):
        self.calls: list[dict] = []

    async def get(self, url, *, params=None, headers=None):
        self.calls.append(
            {
                "url": url,
                "params": dict(params or {}),
                "headers": dict(headers or {}),
            }
        )
        return _FakeResponse()


@pytest.mark.asyncio
async def test_category_list_scraper_fetch_page_requests_listed_date_sort():
    scraper = CategoryListScraper()
    client = _FakeAsyncClient()

    await scraper.fetch_page(6281, page=2, client=client)

    assert client.calls == [
        {
            "url": scraper.BASE_URL,
            "params": {
                "siteKey": "HK-Main",
                "sourcesystem": "houston",
                "classification": 6281,
                "pageSize": scraper.PAGE_SIZE,
                "page": 2,
                "locale": "en-HK",
                "sortmode": "ListedDate",
            },
            "headers": scraper.headers,
        }
    ]
