from __future__ import annotations

import logging

import httpx

from app.crawl_phases import resolve_crawl_phase
from app.scraper.ctgoodjobs.category_registry import (
    CTGOODJOBS_BASE_URL,
    get_static_ctgoodjobs_categories,
    parse_category_registry,
)
from app.scraper.ctgoodjobs.html_fetcher import CTGoodJobsFetchError
from app.scraper.ctgoodjobs.detail_scraper import fetch_detail_page_html
from app.scraper.ctgoodjobs.list_scraper import category_page_url, fetch_category_page_html
from app.sources.contracts import CanonicalScrapedJob, build_ctgoodjobs_canonical_job
from app.sources.ctgoodjobs.parsers import parse_category_page, parse_detail_page
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


def build_canonical_job(parsed_job: dict) -> CanonicalScrapedJob:
    return build_ctgoodjobs_canonical_job(parsed_job)


class CTGoodJobsSpider:
    source_site = "ctgoodjobs"

    async def crawl(
        self,
        *,
        crawl_job_id: str,
        request_payload: dict,
        emit_page_processed,
        emit_detail_progress=None,
        emit_item_emitted,
        emit_listing_emitted=None,
        mark_detail_running=None,
        mark_detail_completed=None,
        mark_detail_failed=None,
    ):
        crawl_phase = resolve_crawl_phase(request_payload.get("crawl_phase"))
        category_ids = list(request_payload.get("category_ids") or [])
        max_pages = max(1, int(request_payload.get("max_pages") or 1))
        pages_processed = 0
        items_emitted = 0
        detail_pages_skipped = 0
        listing_rank = 0

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                registry_html = await fetch_category_page_html(f"{CTGOODJOBS_BASE_URL}/jobs", client=client)
                registry = {category.source_classification_id: category for category in parse_category_registry(registry_html)}
            except Exception:
                registry = {
                    category.source_classification_id: category
                    for category in get_static_ctgoodjobs_categories()
                }

            if crawl_phase == "detail":
                import time

                detail_targets = list(request_payload.get("detail_targets") or [])
                detail_started_at = None
                for index, target in enumerate(detail_targets, start=1):
                    job_id = str(target.get("source_job_id") or "").strip()
                    job_url = str(target.get("source_url") or "")
                    listing_payload = dict(target.get("listing_payload") or {})
                    source_classification_id = str(
                        target.get("source_classification_id")
                        or listing_payload.get("source_classification_id")
                        or ""
                    )
                    category = registry.get(source_classification_id)
                    if not job_id or not job_url or category is None:
                        if mark_detail_failed is not None:
                            mark_detail_failed(target, "missing CTGoodJobs detail target metadata")
                        continue
                    if mark_detail_running is not None:
                        mark_detail_running(target)
                    if emit_detail_progress is not None:
                        detail_started_at = detail_started_at or time.perf_counter()
                        elapsed_detail_seconds = max(time.perf_counter() - detail_started_at, 0.001)
                        detail_rate = index / elapsed_detail_seconds
                        remaining_jobs = max(len(detail_targets) - index, 0)
                        emit_detail_progress(
                            {
                                "phase": 2,
                                "current_job_title": f"Job {job_id}",
                                "detail_job_index": index,
                                "detail_job_total": len(detail_targets),
                                "jobs_scraped": items_emitted,
                                "total_jobs": len(detail_targets),
                                "phase_rate": detail_rate,
                                "eta_seconds": int(remaining_jobs / detail_rate) if detail_rate > 0 else 0,
                                "updated_at": utc_now().isoformat(),
                            }
                        )
                    try:
                        detail_html = await fetch_detail_page_html(job_url, client=client, referer=category.url)
                    except CTGoodJobsFetchError as exc:
                        detail_pages_skipped += 1
                        logger.warning(
                            "Skipping CTGoodJobs detail page after retry exhaustion: category_id=%s job_id=%s job_url=%s error=%s",
                            category.source_classification_id,
                            job_id,
                            job_url,
                            exc,
                        )
                        if mark_detail_failed is not None:
                            mark_detail_failed(target, str(exc))
                        continue
                    parsed_detail = parse_detail_page(
                        detail_html,
                        source_classification_id=category.source_classification_id,
                        source_classification_name=category.name,
                        source_classification_slug=category.slug,
                        url=job_url,
                    )
                    item = build_canonical_job(parsed_detail)
                    if mark_detail_completed is not None:
                        mark_detail_completed(target, item.to_dict())
                    emit_item_emitted(
                        {
                            "listing_id": target.get("listing_id"),
                            "source_listing_crawl_job_id": target.get("source_listing_crawl_job_id"),
                            "job": item.to_dict(),
                        }
                    )
                    items_emitted += 1
                return {
                    "pages_processed": pages_processed,
                    "items_emitted": items_emitted,
                    "detail_pages_skipped": detail_pages_skipped,
                }

            seen_job_ids: set[str] = set()
            for category_id in category_ids:
                category = registry.get(str(category_id))
                if category is None:
                    continue

                total_pages = max_pages
                page_range = range(max_pages, 0, -1) if crawl_phase == "listing" else range(1, max_pages + 1)
                for page in page_range:
                    url = category_page_url(category.url, page=page)
                    page_html = await fetch_category_page_html(url, client=client)
                    parsed_page = parse_category_page(
                        page_html,
                        category_slug=category.slug,
                        source_classification_id=category.source_classification_id,
                        source_classification_name=category.name,
                        page=page,
                        url=url,
                    )
                    page_job_urls: list[tuple[str, str]] = []
                    for job_id, job_url in zip(parsed_page.get("job_ids") or [], parsed_page.get("job_urls") or []):
                        normalized_job_id = str(job_id)
                        if normalized_job_id in seen_job_ids:
                            continue
                        seen_job_ids.add(normalized_job_id)
                        page_job_urls.append((normalized_job_id, str(job_url)))

                    pages_processed += 1
                    emit_page_processed(
                        {
                            "current_page": page,
                            "total_pages": total_pages,
                            "job_ids_collected": len(seen_job_ids),
                            "updated_at": utc_now().isoformat(),
                        }
                    )

                    if crawl_phase == "listing":
                        for job_id, job_url in page_job_urls:
                            listing_rank += 1
                            if emit_listing_emitted is not None:
                                emit_listing_emitted(
                                    {
                                        "source_site": "ctgoodjobs",
                                        "source_job_id": job_id,
                                        "source_url": job_url,
                                        "source_classification_id": category.source_classification_id,
                                        "source_classification_name": category.name,
                                        "listing_page": page,
                                        "listing_rank": listing_rank,
                                        "listing_payload": {
                                            "job_id": job_id,
                                            "job_url": job_url,
                                            "category_slug": category.slug,
                                            "source_classification_id": category.source_classification_id,
                                            "source_classification_name": category.name,
                                        },
                                    }
                                )

        return {
            "pages_processed": pages_processed,
            "items_emitted": items_emitted,
            "detail_pages_skipped": detail_pages_skipped,
        }
