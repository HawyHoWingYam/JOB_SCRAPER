"""Production CTgoodjobs list scraper (SSR HTML-first).

Parsing logic is extracted from the validated research probe implementation.
"""

from __future__ import annotations

import httpx
from typing import Any

from app.sources.ctgoodjobs.parsers import parse_category_page as parse_ctgoodjobs_category_page


def category_page_url(base_url: str, *, page: int) -> str:
    if page <= 1:
        return base_url
    if "?" in base_url:
        return f"{base_url}&page={page}"
    return f"{base_url}?page={page}"


async def fetch_category_page_html(
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


def parse_category_page(
    page_html: str,
    *,
    category_slug: str,
    source_classification_id: str,
    source_classification_name: str,
    page: int,
    url: str,
) -> dict[str, Any]:
    """Parse a CTgoodjobs category page into a stable list-summary payload."""

    return parse_ctgoodjobs_category_page(
        page_html,
        category_slug=category_slug,
        source_classification_id=source_classification_id,
        source_classification_name=source_classification_name,
        page=page,
        url=url,
    )
