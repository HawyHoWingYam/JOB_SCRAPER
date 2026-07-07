"""Production CTgoodjobs list scraper (SSR HTML-first).

Parsing logic is extracted from the validated research probe implementation.
"""

from __future__ import annotations

import logging
import httpx
from typing import Any

from app.scraper.ctgoodjobs.category_registry import CTGOODJOBS_BASE_URL
from app.scraper.ctgoodjobs.html_fetcher import fetch_html_document
from app.scraper.log_events import build_scrape_log_event
from app.sources.ctgoodjobs.parsers import parse_category_page as parse_ctgoodjobs_category_page

logger = logging.getLogger(__name__)


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
    stage = "registry" if url.rstrip("/") == f"{CTGOODJOBS_BASE_URL}/jobs" else "category_page"
    referer = f"{CTGOODJOBS_BASE_URL}/" if stage == "registry" else f"{CTGOODJOBS_BASE_URL}/jobs"
    logger.debug(
        build_scrape_log_event(
            "SCRAPE_LISTING_START",
            source="ctgoodjobs",
            stage=stage,
            url=url,
        )
    )
    html = await fetch_html_document(
        url,
        stage=stage,
        client=client,
        timeout_s=timeout_s,
        referer=referer,
    )
    logger.debug(
        build_scrape_log_event(
            "SCRAPE_LISTING_OK",
            source="ctgoodjobs",
            stage=stage,
            url=url,
        )
    )
    return html


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

    payload = parse_ctgoodjobs_category_page(
        page_html,
        category_slug=category_slug,
        source_classification_id=source_classification_id,
        source_classification_name=source_classification_name,
        page=page,
        url=url,
    )
    job_ids = list(payload.get("job_ids") or [])
    logger.info(
        build_scrape_log_event(
            "SCRAPE_LISTING_PAGE",
            source="ctgoodjobs",
            category_id=source_classification_id,
            page=page,
            jobs=len(job_ids),
        )
    )
    for job_id in job_ids:
        logger.debug(
            build_scrape_log_event(
                "SCRAPE_LISTING_JOB",
                source="ctgoodjobs",
                category_id=source_classification_id,
                source_job_id=job_id,
            )
        )
    return payload
