"""Tests for the OfferToday transport contract.

These tests verify the transport interface definition and parsing logic
without requiring live network access.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure scrapy_project is importable
SCRAPY_PROJECT_DIR = str(Path(__file__).resolve().parents[1] / "scrapy_project")
if SCRAPY_PROJECT_DIR not in sys.path:
    sys.path.insert(0, SCRAPY_PROJECT_DIR)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "crawler"


class TestTransportInterface:
    def test_transport_is_abstract(self) -> None:
        from job_scraper_spiders.downloaders.offertoday_transport import (
            OfferTodayTransport,
        )

        # Cannot instantiate abstract class directly
        with pytest.raises(TypeError):
            OfferTodayTransport()  # type: ignore[abstract]

    def test_minimal_concrete_transport(self) -> None:
        """A minimal concrete transport should work."""
        from job_scraper_spiders.downloaders.offertoday_transport import (
            OfferTodayTransport,
        )

        class MinimalTransport(OfferTodayTransport):
            async def fetch_listing(self, payload):
                return {"code": 0, "data": {"resultList": []}}

            async def fetch_detail(self, encrypted_id):
                return {"code": 0, "data": {}}

        transport = MinimalTransport()
        assert isinstance(transport, OfferTodayTransport)


class TestPlaywrightPageTransport:
    def test_transport_accepts_page(self) -> None:
        from job_scraper_spiders.downloaders.offertoday_transport import (
            PlaywrightPageTransport,
        )

        page = MagicMock()
        transport = PlaywrightPageTransport(page)
        assert transport._page is page

    @pytest.mark.asyncio
    async def test_fetch_listing_calls_page_evaluate(self) -> None:
        from job_scraper_spiders.downloaders.offertoday_transport import (
            PlaywrightPageTransport,
        )

        page = AsyncMock()
        page.evaluate = AsyncMock(
            return_value={"code": 0, "data": {"resultList": [{"jobId": "abc123=="}]}}
        )
        transport = PlaywrightPageTransport(page)

        result = await transport.fetch_listing({"page": 1, "pageSize": 10})
        assert result["code"] == 0
        assert len(result["data"]["resultList"]) == 1
        page.evaluate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_detail_calls_page_evaluate(self) -> None:
        from job_scraper_spiders.downloaders.offertoday_transport import (
            PlaywrightPageTransport,
        )

        page = AsyncMock()
        page.evaluate = AsyncMock(
            return_value={
                "code": 0,
                "data": {"jobId": "abc123==", "jobName": "Engineer"},
            }
        )
        transport = PlaywrightPageTransport(page)

        result = await transport.fetch_detail("abc123==")
        assert result["code"] == 0
        assert result["data"]["jobName"] == "Engineer"
        page.evaluate.assert_awaited_once()


class TestScraplingAdapter:
    def test_is_scrapling_available_returns_bool(self) -> None:
        from job_scraper_spiders.downloaders.scrapling_adapter import (
            is_scrapling_available,
        )

        result = is_scrapling_available()
        # Should return True or False without raising
        assert isinstance(result, bool)
