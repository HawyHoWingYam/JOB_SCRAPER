from __future__ import annotations

import httpx

from app.scraper.ctgoodjobs.category_registry import CTGOODJOBS_BASE_URL, parse_category_registry
from app.scraper.ctgoodjobs.detail_scraper import fetch_detail_page_html
from app.scraper.ctgoodjobs.list_scraper import category_page_url, fetch_category_page_html
from app.sources.contracts import CanonicalScrapedJob, build_ctgoodjobs_canonical_job
from app.sources.ctgoodjobs.parsers import parse_category_page, parse_detail_page
from app.utils.time import utc_now


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
        emit_item_emitted,
    ):
        category_ids = list(request_payload.get("category_ids") or [])
        max_pages = max(1, int(request_payload.get("max_pages") or 1))
        pages_processed = 0
        items_emitted = 0

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            registry_html = await fetch_category_page_html(f"{CTGOODJOBS_BASE_URL}/jobs", client=client)
            registry = {category.source_classification_id: category for category in parse_category_registry(registry_html)}

            for category_id in category_ids:
                category = registry.get(str(category_id))
                if category is None:
                    continue

                job_urls: dict[str, str] = {}
                for page in range(1, max_pages + 1):
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
                    for job_id, job_url in zip(parsed_page.get("job_ids") or [], parsed_page.get("job_urls") or []):
                        job_urls[str(job_id)] = str(job_url)

                    pages_processed += 1
                    emit_page_processed(
                        {
                            "current_page": page,
                            "total_pages": max_pages,
                            "job_ids_collected": len(job_urls),
                            "updated_at": utc_now().isoformat(),
                        }
                    )

                for job_id, job_url in job_urls.items():
                    detail_html = await fetch_detail_page_html(job_url, client=client)
                    parsed_detail = parse_detail_page(
                        detail_html,
                        source_classification_id=category.source_classification_id,
                        source_classification_name=category.name,
                        source_classification_slug=category.slug,
                        url=job_url,
                    )
                    item = build_canonical_job(parsed_detail)
                    emit_item_emitted(item.to_dict())
                    items_emitted += 1

        return {"pages_processed": pages_processed, "items_emitted": items_emitted}
