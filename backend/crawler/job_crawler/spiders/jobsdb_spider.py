from __future__ import annotations

import httpx

from app.crawl_phases import resolve_crawl_phase
from app.scraper.category_scraper import CategoryListScraper
from app.scraper.job_detail_scraper import JobDetailScraper
from app.sources.contracts import (
    CanonicalScrapedJob,
    build_jobsdb_canonical_job,
    build_jobsdb_listing_canonical_job,
)
from app.sources.jobsdb.parsers import parse_search_response
from app.utils.time import utc_now
from app.config import settings


def build_canonical_job(parsed_job: dict, *, source_url: str) -> CanonicalScrapedJob:
    return build_jobsdb_canonical_job(parsed_job, source_url=source_url)


class JobsDBSpider:
    source_site = "jobsdb"

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
        list_scraper = CategoryListScraper()
        pages_processed = 0
        items_emitted = 0
        listing_rank = 0

        if crawl_phase == "listing":
            async with httpx.AsyncClient(timeout=30.0) as client:
                seen_job_ids: set[str] = set()
                for category_id in category_ids:
                    total_pages = max_pages
                    for page in range(max_pages, 0, -1):
                        payload = await list_scraper.fetch_page(int(category_id), page, client)
                        parsed = parse_search_response(payload)
                        total_count = int(parsed.get("total_count") or 0)
                        if total_count > 0:
                            total_pages = min(
                                max_pages,
                                (total_count + list_scraper.PAGE_SIZE - 1) // list_scraper.PAGE_SIZE,
                            )

                        jobs = parsed.get("jobs") or []
                        for job in jobs:
                            job_id = str(job.get("external_id") or "").strip()
                            if not job_id or job_id in seen_job_ids:
                                continue
                            seen_job_ids.add(job_id)
                            listing_rank += 1
                            if emit_listing_emitted is not None:
                                emit_listing_emitted(
                                    {
                                        "source_site": "jobsdb",
                                        "source_job_id": job_id,
                                        "source_url": f"{settings.jobsdb_base_url}/job/{job_id}",
                                        "source_classification_id": job.get("classification_id"),
                                        "source_classification_name": job.get("classification_name"),
                                        "listing_page": page,
                                        "listing_rank": listing_rank,
                                        "listing_payload": dict(job),
                                    }
                                )

                        pages_processed += 1
                        emit_page_processed(
                            {
                                "current_page": page,
                                "total_pages": total_pages,
                                "job_ids_collected": len(seen_job_ids),
                                "updated_at": utc_now().isoformat(),
                            }
                        )
            return {"pages_processed": pages_processed, "items_emitted": items_emitted}

        detail_targets = list(request_payload.get("detail_targets") or [])
        detail_started_at = None
        async with httpx.AsyncClient(timeout=30.0) as client:
            detail_scraper = JobDetailScraper()
            for index, target in enumerate(detail_targets, start=1):
                job_id = str(target.get("source_job_id") or "").strip()
                listing_job = dict(target.get("listing_payload") or {})
                if not job_id:
                    continue
                if mark_detail_running is not None:
                    mark_detail_running(target)
                if emit_detail_progress is not None:
                    import time

                    detail_started_at = detail_started_at or time.perf_counter()
                    elapsed_detail_seconds = max(time.perf_counter() - detail_started_at, 0.001)
                    detail_rate = index / elapsed_detail_seconds
                    remaining_jobs = max(len(detail_targets) - index, 0)
                    emit_detail_progress(
                        {
                            "phase": 2,
                            "current_job_title": str(listing_job.get("title") or job_id),
                            "detail_job_index": index,
                            "detail_job_total": len(detail_targets),
                            "jobs_scraped": items_emitted,
                            "total_jobs": len(detail_targets),
                            "phase_rate": detail_rate,
                            "eta_seconds": int(remaining_jobs / detail_rate) if detail_rate > 0 else 0,
                            "updated_at": utc_now().isoformat(),
                        }
                    )
                detail = await detail_scraper.fetch_job_detail(job_id, client)
                if not detail:
                    if mark_detail_failed is not None:
                        mark_detail_failed(target, "detail fetch returned no result")
                    continue
                source_url = str(target.get("source_url") or f"{settings.jobsdb_base_url}/job/{job_id}")
                item = build_canonical_job(detail, source_url=source_url)
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

        return {"pages_processed": pages_processed, "items_emitted": items_emitted}

