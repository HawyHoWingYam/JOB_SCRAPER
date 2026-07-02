"""OfferToday transport interface and candidates for bake-off.

Transport interface:
  - fetch_listing(payload: dict) -> dict    — POST to search/list API
  - fetch_detail(encrypted_id: str) -> dict  — GET job detail API

Three candidates:
  1. playthrough (current) — routes API calls through Playwright browser
  2. scrapy-playwright    — uses Scrapy's scrapy-playwright integration
  3. scrapling            — uses Scrapling's stealth browser session
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

OFFERTODAY_BASE_URL = "https://www.offertoday.com"
OFFERTODAY_LISTING_URL = f"{OFFERTODAY_BASE_URL}/wapi/geek/recommend/search/list"
OFFERTODAY_DETAIL_URL_TEMPLATE = (
    f"{OFFERTODAY_BASE_URL}/wapi/geek/recommend/jobDetail?id={{encrypted_id}}&encryptJobId={{encrypted_id}}"
)

_COMMON_HEADERS = {
    "api-language": "zh_HK",
    "x-requested-with": "XMLHttpRequest",
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json;charset=UTF-8",
}


# ── Transport interface ────────────────────────────────────────────


class OfferTodayTransport(ABC):
    """Abstract transport interface for OfferToday API calls."""

    @abstractmethod
    async def fetch_listing(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to the search/list API with the given payload."""

    @abstractmethod
    async def fetch_detail(self, encrypted_id: str) -> dict[str, Any]:
        """GET a single job detail by its encrypted ID."""


# ── Playwright (current) transport ─────────────────────────────────


class PlaywrightPageTransport(OfferTodayTransport):
    """Routes API calls through a Playwright browser page (current approach).

    Uses page.evaluate() to run fetch() inside the browser context,
    where the TLS fingerprint is trusted by the Alibaba Cloud WAF.
    """

    def __init__(self, page: Any) -> None:
        """page is a playwright.async_api.Page instance."""
        self._page = page

    async def fetch_listing(self, payload: dict[str, Any]) -> dict[str, Any]:
        js = f"""() => {{
            return fetch('{OFFERTODAY_LISTING_URL}', {{
                method: 'POST',
                headers: {json.dumps(_COMMON_HEADERS, ensure_ascii=False)},
                body: JSON.stringify({json.dumps(payload, ensure_ascii=False)})
            }}).then(r => r.json());
        }}"""
        result: dict[str, Any] = await self._page.evaluate(js)
        return result

    async def fetch_detail(self, encrypted_id: str) -> dict[str, Any]:
        detail_url = OFFERTODAY_DETAIL_URL_TEMPLATE.format(encrypted_id=encrypted_id)
        js = f"""() => {{
            return fetch('{detail_url}', {{
                headers: {json.dumps(_COMMON_HEADERS, ensure_ascii=False)}
            }}).then(r => r.json());
        }}"""
        result: dict[str, Any] = await self._page.evaluate(js)
        return result


# ── Scrapy Playwright transport ────────────────────────────────────


class ScrapyPlaywrightTransport(OfferTodayTransport):
    """Uses scrapy-playwright's PlaywrightRequest for API calls.

    Can be integrated into a Scrapy spider's callback chain.
    This implementation is a stub for the bake-off compatibility;
    in Scrapy spider code, use scrapy-playwright's PlaywrightRequest directly.
    """

    def __init__(self) -> None:
        self._last_response: dict[str, Any] | None = None

    async def fetch_listing(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "ScrapyPlaywrightTransport.fetch_listing should not be called directly. "
            "Use PlaywrightRequest in Scrapy spider callbacks instead."
        )

    async def fetch_detail(self, encrypted_id: str) -> dict[str, Any]:
        raise NotImplementedError(
            "ScrapyPlaywrightTransport.fetch_detail should not be called directly. "
            "Use PlaywrightRequest in Scrapy spider callbacks instead."
        )


# ── Scrapling transport (optional) ─────────────────────────────────


class ScraplingTransport(OfferTodayTransport):
    """Uses Scrapling's stealth browser session for API calls.

    Only used if the bake-off proves a clear win over Playwright.
    """

    def __init__(self) -> None:
        self._session: Any = None

    async def _ensure_session(self) -> Any:
        if self._session is not None:
            return self._session
        try:
            from scrapling import AsyncFetcher

            self._session = await AsyncFetcher(save_response_body=True, headless=True).astart()
            return self._session
        except ImportError:
            raise RuntimeError("Scrapling not installed. Install with: pip install scrapling")

    async def fetch_listing(self, payload: dict[str, Any]) -> dict[str, Any]:
        session = await self._ensure_session()
        text = await session.post(
            OFFERTODAY_LISTING_URL,
            headers=_COMMON_HEADERS,
            data=json.dumps(payload, ensure_ascii=False),
        )
        return json.loads(text) if isinstance(text, str) else {}

    async def fetch_detail(self, encrypted_id: str) -> dict[str, Any]:
        session = await self._ensure_session()
        detail_url = OFFERTODAY_DETAIL_URL_TEMPLATE.format(encrypted_id=encrypted_id)
        text = await session.get(detail_url, headers=_COMMON_HEADERS)
        return json.loads(text) if isinstance(text, str) else {}
