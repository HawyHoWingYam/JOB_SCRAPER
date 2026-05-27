from __future__ import annotations

import httpx

from app.crawl_phases import resolve_crawl_phase
from app.scraper.category_scraper import CategoryListScraper
from app.scraper.manual_action import ManualActionRequiredError
from app.scraper.jobsdb_browser_detail_scraper import JobsDBBrowserDetailScraper
from app.sources.contracts import build_jobsdb_canonical_job
from app.sources.jobsdb.parsers import parse_search_response
from app.utils.time import utc_now
from app.config import settings


class JobsDBHeadedSpider:
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
        resume_context = dict(request_payload.get("resume_context") or {})
        resume_listing = bool(request_payload.get("is_resume")) and resume_context.get("crawl_phase") == "listing"
        normalized_resume_category_id = str(resume_context.get("category_id") or "").strip()
        category_id_anchor_available = normalized_resume_category_id and any(
            str(category_id).strip() == normalized_resume_category_id for category_id in category_ids
        )
        max_pages = max(1, int(request_payload.get("max_pages") or 1))
        list_scraper = CategoryListScraper()
        pages_processed = 0
        items_emitted = 0
        listing_rank = int(resume_context.get("listing_rank") or 0) if resume_listing else 0

        if crawl_phase == "listing":
            resume_category_index = int(resume_context.get("category_index") or 0)
            resume_page = max(1, int(resume_context.get("page") or max_pages))
            seeded_seen_job_ids = {
                str(job_id).strip()
                for job_id in (resume_context.get("seen_job_ids") or [])
                if str(job_id).strip()
            }
            seen_job_ids: set[str] = set(seeded_seen_job_ids)
            resume_anchor_reached = not resume_listing
            async with httpx.AsyncClient(timeout=30.0) as client:
                for category_index, category_id in enumerate(category_ids):
                    is_resume_target_category = False
                    if resume_listing:
                        if category_id_anchor_available:
                            if not resume_anchor_reached:
                                if str(category_id).strip() != normalized_resume_category_id:
                                    continue
                                resume_anchor_reached = True
                                is_resume_target_category = True
                        else:
                            if category_index < resume_category_index:
                                continue
                            is_resume_target_category = category_index == resume_category_index
                            resume_anchor_reached = True

                    total_pages = max_pages
                    if is_resume_target_category:
                        page_range = range(resume_page, 0, -1)
                    else:
                        page_range = range(max_pages, 0, -1)
                    for page in page_range:
                        try:
                            payload = await list_scraper.fetch_page(int(category_id), page, client)
                        except ManualActionRequiredError as exc:
                            exc.resume_context.update(
                                {
                                    "crawl_phase": "listing",
                                    "category_id": int(category_id),
                                    "category_index": category_index,
                                    "page": page,
                                    "page_direction": "descending",
                                }
                            )
                            raise
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
        async with JobsDBBrowserDetailScraper() as detail_scraper:
            detail_started_at = None
            for index, target in enumerate(detail_targets, start=1):
                import time

                job_id = str(target.get("source_job_id") or "").strip()
                listing_payload = dict(target.get("listing_payload") or {})
                if not job_id:
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
                            "current_job_title": str(listing_payload.get("title") or job_id),
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
                    detail = await detail_scraper.fetch_job_detail(job_id)
                except ManualActionRequiredError as exc:
                    exc.resume_context.update(
                        {
                            "crawl_phase": "detail",
                            "listing_id": str(target.get("listing_id") or ""),
                            "source_listing_crawl_job_id": str(target.get("source_listing_crawl_job_id") or ""),
                            "source_job_id": job_id,
                        }
                    )
                    raise
                if not detail:
                    if mark_detail_failed is not None:
                        mark_detail_failed(target, "detail fetch returned no result")
                    continue
                item = build_jobsdb_canonical_job(
                    detail,
                    source_url=str(target.get("source_url") or f"{settings.jobsdb_base_url}/job/{job_id}"),
                )
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
