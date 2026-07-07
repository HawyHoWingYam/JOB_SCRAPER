"""Production CTgoodjobs detail scraper (SSR HTML-first).

Parsing logic is extracted from the validated research probe implementation.
"""

from __future__ import annotations

import logging
import httpx
from typing import Any

from app.scraper.ctgoodjobs.html_fetcher import fetch_html_document
from app.scraper.log_events import build_scrape_log_event
from app.sources.ctgoodjobs.parsers import parse_detail_page as parse_ctgoodjobs_detail_page

logger = logging.getLogger(__name__)


async def fetch_detail_page_html(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 30.0,
    referer: str | None = None,
) -> str:
    logger.debug(
        build_scrape_log_event(
            "SCRAPE_DETAIL_START",
            source="ctgoodjobs",
            stage="detail_page",
            url=url,
        )
    )
    html = await fetch_html_document(
        url,
        stage="detail_page",
        client=client,
        timeout_s=timeout_s,
        referer=referer,
    )
    logger.debug(
        build_scrape_log_event(
            "SCRAPE_DETAIL_OK",
            source="ctgoodjobs",
            stage="detail_page",
            url=url,
        )
    )
    return html


def parse_detail_page(
    page_html: str,
    *,
    source_classification_id: str,
    source_classification_name: str,
    source_classification_slug: str,
    url: str,
) -> dict[str, Any]:
    payload = parse_ctgoodjobs_detail_page(
        page_html,
        source_classification_id=source_classification_id,
        source_classification_name=source_classification_name,
        source_classification_slug=source_classification_slug,
        url=url,
    )
    logger.debug(
        build_scrape_log_event(
            "SCRAPE_DETAIL_OK",
            source="ctgoodjobs",
            stage="detail_page",
            source_job_id=payload.get("job_id"),
            url=url,
        )
    )
    return payload
