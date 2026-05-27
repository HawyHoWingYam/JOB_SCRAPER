"""
Category List Scraper

Paginates through JobsDB categories to collect all job IDs.
Phase 1 of the two-phase scraping approach.
"""

import asyncio
import random
from typing import List, Dict, Any, Optional

import httpx

from app.config import settings
from app.scraper.categories import JOBSDB_CATEGORIES, get_category_by_id, get_category_name
from app.scraper.manual_action import ManualActionRequiredError
from app.utils.time import utc_now


class CategoryListScraper:
    """Scrapes job listings from JobsDB by category."""

    BASE_URL = "https://hk.jobsdb.com/api/jobsearch/v5/search"
    PAGE_SIZE = 32  # Max allowed by API

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-HK,en;q=0.9",
        }
        self.min_delay = getattr(settings, 'scrape_min_delay', 2.0)
        self.max_delay = getattr(settings, 'scrape_max_delay', 5.0)

    async def fetch_page(
        self,
        classification_id: int,
        page: int = 1,
        client: Optional[httpx.AsyncClient] = None
    ) -> Dict[str, Any]:
        """Fetch a single page of job listings for a category."""
        params = {
            "siteKey": "HK-Main",
            "sourcesystem": "houston",
            "classification": classification_id,
            "pageSize": self.PAGE_SIZE,
            "page": page,
            "locale": "en-HK",
            "sortmode": "ListedDate",
        }

        should_close = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=30.0)

        try:
            response = await client.get(
                self.BASE_URL,
                params=params,
                headers=self.headers,
            )
            response.raise_for_status()
            try:
                return response.json()
            except ValueError as exc:
                if self._looks_like_interstitial_response(response):
                    raise ManualActionRequiredError(
                        source_site="jobsdb",
                        stage="category_page",
                        blocked_url=self._build_category_page_url(classification_id, page=page),
                        referer=settings.jobsdb_base_url,
                        message="JobsDB listing fetch blocked by human verification",
                        instructions=[
                            "Open the headed browser profile.",
                            "Complete the human verification challenge.",
                            "Return to the app and click Resume.",
                        ],
                    ) from exc
                raise
        finally:
            if should_close:
                await client.aclose()

    def _looks_like_interstitial_response(self, response: httpx.Response) -> bool:
        content_type = str(response.headers.get("content-type") or "").lower()
        if "application/json" in content_type:
            return False

        lowered = str(getattr(response, "text", "") or "").lower()
        return (
            "just a moment" in lowered
            or "cf-challenge" in lowered
            or "challenges.cloudflare.com" in lowered
        )

    def _build_category_page_url(self, classification_id: int, *, page: int) -> str:
        category = get_category_by_id(int(classification_id))
        if category is None:
            return settings.jobsdb_base_url

        base_url = f"{settings.jobsdb_base_url}/jobs-in-{category.slug}"
        if int(page or 1) > 1:
            return f"{base_url}?page={int(page)}"
        return base_url

    async def scrape_category(
        self,
        classification_id: int,
        max_pages: Optional[int] = None,
        on_progress: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        Scrape all job IDs from a category.

        Args:
            classification_id: The category ID to scrape
            max_pages: Optional limit on pages to scrape
            on_progress: Optional callback(current_page, total_pages, jobs_found)

        Returns:
            Dict with job_ids, total_count, pages_scraped, category info
        """
        job_ids: List[str] = []
        page = 1
        total_count = 0
        category_name = get_category_name(classification_id) or f"Category {classification_id}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            # First request to get total count
            result = await self.fetch_page(classification_id, page, client)
            total_count = result.get("totalCount", 0)

            if total_count == 0:
                return {
                    "classification_id": classification_id,
                    "category_name": category_name,
                    "job_ids": [],
                    "total_count": 0,
                    "pages_scraped": 0,
                }

            # Calculate total pages
            total_pages = (total_count + self.PAGE_SIZE - 1) // self.PAGE_SIZE
            if max_pages:
                total_pages = min(total_pages, max_pages)

            # Start from last page and iterate backwards
            page = total_pages
            result = await self.fetch_page(classification_id, page, client)
            jobs = result.get("data", [])
            job_ids.extend([job["id"] for job in jobs])

            if on_progress:
                on_progress(page, total_pages, len(job_ids))

            # Continue with remaining pages in reverse order
            while page > 1:
                page -= 1

                # Rate limiting
                delay = random.uniform(self.min_delay, self.max_delay)
                await asyncio.sleep(delay)

                result = await self.fetch_page(classification_id, page, client)
                jobs = result.get("data", [])

                if not jobs:
                    break

                job_ids.extend([job["id"] for job in jobs])

                if on_progress:
                    on_progress(page, total_pages, len(job_ids))

        return {
            "classification_id": classification_id,
            "category_name": category_name,
            "job_ids": job_ids,
            "total_count": total_count,
            "pages_scraped": page,
            "scraped_at": utc_now().isoformat(),
        }

    async def get_category_stats(self, classification_id: int) -> Dict[str, Any]:
        """Get job count for a category without full scraping."""
        result = await self.fetch_page(classification_id, page=1)
        return {
            "classification_id": classification_id,
            "category_name": get_category_name(classification_id),
            "total_count": result.get("totalCount", 0),
        }

    async def get_all_category_stats(self) -> List[Dict[str, Any]]:
        """Get job counts for all categories."""
        stats = []
        for cat_id in JOBSDB_CATEGORIES.keys():
            stat = await self.get_category_stats(cat_id)
            stats.append(stat)
            await asyncio.sleep(0.5)  # Brief delay between requests
        return stats
