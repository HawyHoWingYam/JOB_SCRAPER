"""JobsDB parser — wraps existing app.sources.jobsdb.parsers for Scrapy items."""

from __future__ import annotations

from typing import Any

from app.sources.jobsdb.parsers import (
    parse_search_response as _parse_search_response,
    parse_detail_page as _parse_detail_page,
)
from app.sources.contracts import build_jobsdb_canonical_job


def parse_listing_search(data: dict[str, Any]) -> dict[str, Any]:
    """Parse the JobsDB listing API response.

    Returns: {"total_count": int, "jobs": list[dict], "raw_data": dict}
    """
    return _parse_search_response(data)


def parse_detail_html(html: str, *, job_id: str) -> dict[str, Any] | None:
    """Parse a JobsDB detail page HTML into a parsed dict."""
    return _parse_detail_page(html, job_id=job_id)


def to_canonical(parsed_job: dict[str, Any], *, source_url: str) -> dict[str, Any]:
    """Convert a parsed JobsDB job to the canonical output format."""
    return build_jobsdb_canonical_job(parsed_job, source_url=source_url).to_dict()


__all__ = ["parse_listing_search", "parse_detail_html", "to_canonical"]
