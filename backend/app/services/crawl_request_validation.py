from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from pydantic import StrictInt, StrictStr

from app.crawl_modes import resolve_crawl_mode
from app.crawl_phases import resolve_crawl_phase

CategoryId = StrictInt | StrictStr


@dataclass(frozen=True)
class ValidatedCrawlRequest:
    source_site: str
    crawl_phase: str
    crawl_mode: str
    category_ids: list[CategoryId] | None
    source_listing_crawl_job_id: UUID | None


def validate_crawl_request(
    *,
    source_site: str | None,
    crawl_phase: str | None,
    crawl_mode: str | None,
    category_ids: Sequence[CategoryId] | None,
    source_listing_crawl_job_id: UUID | None,
) -> ValidatedCrawlRequest:
    normalized_source = normalize_source_site(source_site)
    resolved_phase = resolve_crawl_phase(crawl_phase)
    resolved_mode = resolve_crawl_mode(normalized_source, crawl_mode)
    normalized_categories = list(category_ids) if category_ids else None

    if resolved_phase == "listing":
        if not normalized_categories:
            raise ValueError("listing runs require category_ids")
        validate_category_ids_for_source_site(normalized_source, normalized_categories)
    else:
        if source_listing_crawl_job_id is None and not normalized_categories:
            raise ValueError("detail runs require source_listing_crawl_job_id or category_ids")
        if normalized_categories:
            validate_category_ids_for_source_site(normalized_source, normalized_categories)

    return ValidatedCrawlRequest(
        source_site=normalized_source,
        crawl_phase=resolved_phase,
        crawl_mode=resolved_mode,
        category_ids=normalized_categories,
        source_listing_crawl_job_id=source_listing_crawl_job_id,
    )


def normalize_source_site(source_site: str | None) -> str:
    return (source_site or "").strip().lower() or "jobsdb"


def validate_category_ids_for_source_site(
    source_site: str | None,
    category_ids: Sequence[CategoryId] | None,
) -> None:
    normalized_source_site = normalize_source_site(source_site)
    if normalized_source_site == "ctgoodjobs" and not category_ids:
        raise ValueError("CTGoodJobs category_ids must be provided")
    if not category_ids:
        return
    if normalized_source_site == "jobsdb":
        if any(not isinstance(category_id, int) for category_id in category_ids):
            raise ValueError("JobsDB category_ids must be integers")
    if normalized_source_site == "ctgoodjobs":
        if any(
            not isinstance(category_id, str) or not category_id.startswith("ctgoodjobs:")
            for category_id in category_ids
        ):
            raise ValueError("CTGoodJobs category_ids must be strings with the ctgoodjobs: prefix")
