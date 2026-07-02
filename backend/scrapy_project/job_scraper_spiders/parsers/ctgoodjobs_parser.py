"""CTGoodJobs parser — wraps existing ctgoodjobs parsers for Scrapy items."""

from __future__ import annotations

from typing import Any

from app.sources.ctgoodjobs.parsers import (
    parse_category_page as _parse_category_page,
    parse_detail_page as _parse_detail_page,
)
from app.sources.contracts import build_ctgoodjobs_canonical_job


def parse_category(
    html: str,
    *,
    category_slug: str,
    source_classification_id: str,
    source_classification_name: str,
    page: int,
    url: str,
) -> dict[str, Any]:
    """Parse a CTGoodJobs category listing page."""
    return _parse_category_page(
        html,
        category_slug=category_slug,
        source_classification_id=source_classification_id,
        source_classification_name=source_classification_name,
        page=page,
        url=url,
    )


def parse_detail(
    html: str,
    *,
    source_classification_id: str,
    source_classification_name: str,
    source_classification_slug: str,
    url: str,
) -> dict[str, Any]:
    """Parse a CTGoodJobs detail page HTML."""
    return _parse_detail_page(
        html,
        source_classification_id=source_classification_id,
        source_classification_name=source_classification_name,
        source_classification_slug=source_classification_slug,
        url=url,
    )


def to_canonical(parsed_job: dict[str, Any]) -> dict[str, Any]:
    """Convert a parsed CTGoodJobs job to the canonical output format."""
    return build_ctgoodjobs_canonical_job(parsed_job).to_dict()


__all__ = ["parse_category", "parse_detail", "to_canonical"]
