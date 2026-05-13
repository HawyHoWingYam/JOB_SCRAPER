"""Production CTgoodjobs detail scraper (SSR HTML-first).

Parsing logic is extracted from the validated research probe implementation.
"""

from __future__ import annotations

import httpx
from typing import Any

from app.scraper.ctgoodjobs.html_fetcher import fetch_html_document
from app.sources.ctgoodjobs.parsers import parse_detail_page as parse_ctgoodjobs_detail_page


async def fetch_detail_page_html(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 30.0,
    referer: str | None = None,
) -> str:
    return await fetch_html_document(
        url,
        stage="detail_page",
        client=client,
        timeout_s=timeout_s,
        referer=referer,
    )


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
