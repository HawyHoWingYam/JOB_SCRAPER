from __future__ import annotations

import httpx

from app.scraper.category_scraper import CategoryListScraper
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
        emit_item_emitted,
    ):
        category_ids = list(request_payload.get("category_ids") or [])
        max_pages = max(1, int(request_payload.get("max_pages") or 1))
        list_scraper = CategoryListScraper()
        pages_processed = 0
        items_emitted = 0

        async with httpx.AsyncClient(timeout=30.0) as client:
            async with JobsDBBrowserDetailScraper() as detail_scraper:
                for category_id in category_ids:
                    seen_jobs: dict[str, dict] = {}
                    total_pages = max_pages
                    for page in range(1, max_pages + 1):
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
                            if not job_id or job_id in seen_jobs:
                                continue
                            seen_jobs[job_id] = dict(job)

                        pages_processed += 1
                        emit_page_processed(
                            {
                                "current_page": page,
                                "total_pages": total_pages,
                                "job_ids_collected": len(seen_jobs),
                                "updated_at": utc_now().isoformat(),
                            }
                        )

                    for job_id in seen_jobs:
                        detail = await detail_scraper.fetch_job_detail(job_id)
                        if not detail:
                            continue
                        item = build_jobsdb_canonical_job(
                            detail,
                            source_url=f"{settings.jobsdb_base_url}/job/{job_id}",
                        )
                        emit_item_emitted(item.to_dict())
                        items_emitted += 1

        return {"pages_processed": pages_processed, "items_emitted": items_emitted}
