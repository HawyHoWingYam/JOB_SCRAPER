"""Production CTgoodjobs detail scraper (SSR HTML-first).

Parsing logic is extracted from the validated research probe implementation.
"""

from __future__ import annotations

import httpx
from typing import Any

from app.sources.ctgoodjobs.parsers import parse_detail_page as parse_ctgoodjobs_detail_page


async def fetch_detail_page_html(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 30.0,
) -> str:
    owned = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout_s, follow_redirects=True)
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text
    finally:
        if owned:
            await client.aclose()


def parse_detail_page(
    page_html: str,
    *,
    source_classification_id: str,
    source_classification_name: str,
    source_classification_slug: str,
    url: str,
) -> dict[str, Any]:
    return parse_ctgoodjobs_detail_page(
        page_html,
        source_classification_id=source_classification_id,
        source_classification_name=source_classification_name,
        source_classification_slug=source_classification_slug,
        url=url,
    )
