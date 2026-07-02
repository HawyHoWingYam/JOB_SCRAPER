"""OfferToday parser — wraps existing app.sources.offertoday.parsers for Scrapy items.

This module reuses the canonical parsers from the legacy codebase to ensure
output consistency during migration. Once the migration is complete and the
legacy path is retired, these can be extracted into standalone functions.
"""

from __future__ import annotations

from typing import Any

from app.sources.contracts import build_offertoday_canonical_job
from app.sources.offertoday.parsers import (
    build_offertoday_job_url,
    extract_encrypted_job_id,
    parse_offertoday_listing_response,
    parse_offertoday_detail_response,
)


def parse_listing(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse an OfferToday listing API response into raw job dicts.

    Delegates to the canonical parser for output consistency.
    """
    return parse_offertoday_listing_response(data)


def parse_detail(data: dict[str, Any]) -> dict[str, Any]:
    """Parse an OfferToday detail API response into a raw dict.

    Delegates to the canonical parser for output consistency.
    """
    return parse_offertoday_detail_response(data)


def to_canonical(parsed_job: dict[str, Any]) -> dict[str, Any]:
    """Convert a parsed job dict to the canonical output format."""
    return build_offertoday_canonical_job(parsed_job).to_dict()


__all__ = ["parse_listing", "parse_detail", "to_canonical", "extract_encrypted_job_id", "build_offertoday_job_url"]
