"""
Job Detail Scraper

Fetches complete job details from JobsDB job pages.
Phase 2 of the two-phase scraping approach.

Extracts job data from window.SEEK_REDUX_DATA embedded in HTML.
"""

import re
import json
import asyncio
import random
import logging
from typing import Dict, Any, Optional, List
from html import unescape

import httpx

from app.config import settings
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


class JobDetailScraper:
    """Scrapes detailed job information from JobsDB job pages."""

    BASE_URL = "https://hk.jobsdb.com/job"

    # Rotate User-Agents to avoid detection
    USER_AGENTS = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]

    def __init__(self):
        self.min_delay = getattr(settings, 'scrape_min_delay', 3.0)
        self.max_delay = getattr(settings, 'scrape_max_delay', 6.0)

    def _get_headers(self, referer: str = None) -> Dict[str, str]:
        """Get randomized browser-like headers."""
        return {
            "User-Agent": random.choice(self.USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-HK,en;q=0.9,zh-HK;q=0.8,zh;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": referer or "https://hk.jobsdb.com/",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
        }

    def _extract_redux_data(self, html: str) -> Optional[Dict[str, Any]]:
        """Extract SEEK_REDUX_DATA from HTML page."""
        # Find the start of the Redux data
        marker = 'window.SEEK_REDUX_DATA'
        start_idx = html.find(marker)
        if start_idx == -1:
            logger.warning("Redux data marker not found in HTML")
            return None

        # Find the opening brace
        brace_start = html.find('{', start_idx)
        if brace_start == -1:
            logger.warning("Opening brace not found after Redux marker")
            return None

        # Count braces to find the matching closing brace
        depth = 0
        in_string = False
        escape_next = False
        end_idx = brace_start

        for i, char in enumerate(html[brace_start:], brace_start):
            if escape_next:
                escape_next = False
                continue

            if char == '\\' and in_string:
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if not in_string:
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        end_idx = i + 1
                        break

        if depth != 0:
            logger.warning(f"Unbalanced braces in Redux data (depth={depth})")
            return None

        json_str = html[brace_start:end_idx]

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Redux JSON: {e}")
            return None

    def _parse_job_details(self, redux_data: Dict, job_id: str) -> Optional[Dict[str, Any]]:
        """Parse job details from Redux data structure."""
        try:
            # JobsDB structure: jobdetails.result.job
            job_details_container = redux_data.get("jobdetails", {})
            result = job_details_container.get("result", {})

            # The actual job data is under 'result.job'
            job = result.get("job", {})

            if not job or not isinstance(job, dict):
                logger.warning(f"Job not found in jobdetails.result for {job_id}")
                return None

            # Extract tracking info for classification
            tracking = job.get("tracking", {})
            classification_info = tracking.get("classificationInfo", {})

            # Extract content (HTML description) - it's a direct string now
            content_html = job.get("content", "")

            # Extract listing date
            listed_at = job.get("listedAt", {})
            listing_date = listed_at.get("dateTimeUtc") if isinstance(listed_at, dict) else None

            # Extract expiry date
            expires_at = job.get("expiresAt", {})
            expiry_date = expires_at.get("dateTimeUtc") if isinstance(expires_at, dict) else None

            # Extract work types - simple label access
            work_types = job.get("workTypes", {})
            work_type = work_types.get("label", "") if isinstance(work_types, dict) else ""

            # Extract location - simple label access
            location = job.get("location", {})
            location_label = location.get("label", "") if isinstance(location, dict) else ""

            # Extract advertiser info
            advertiser = job.get("advertiser", {})
            advertiser_id = advertiser.get("id", "") if isinstance(advertiser, dict) else ""
            advertiser_name = advertiser.get("name", "") if isinstance(advertiser, dict) else ""

            return {
                "jobsdb_id": job_id,
                "title": job.get("title", ""),
                "abstract": job.get("abstract", ""),
                "description_html": unescape(content_html) if content_html else "",
                "classification_id": classification_info.get("classificationId"),
                "classification": classification_info.get("classification"),
                "subclassification_id": classification_info.get("subClassificationId"),
                "subclassification": classification_info.get("subClassification"),
                "location": location_label,
                "work_type": work_type,
                "salary": job.get("salary"),
                "listing_date": listing_date,
                "expiry_date": expiry_date,
                "is_expired": job.get("isExpired", False),
                "advertiser_id": advertiser_id,
                "advertiser_name": advertiser_name,
                "status": job.get("status", ""),
                "scraped_at": utc_now().isoformat(),
            }

        except (KeyError, TypeError) as e:
            return None

    async def fetch_job_detail(
        self,
        job_id: str,
        client: Optional[httpx.AsyncClient] = None
    ) -> Optional[Dict[str, Any]]:
        """Fetch and parse job details for a single job ID."""
        url = f"{self.BASE_URL}/{job_id}"
        referer = f"https://hk.jobsdb.com/jobs?classification={job_id[:4]}"

        should_close = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=30.0)

        try:
            headers = self._get_headers(referer)
            response = await client.get(url, headers=headers, follow_redirects=True)
            response.raise_for_status()

            html = response.text
            redux_data = self._extract_redux_data(html)

            if not redux_data:
                return None

            return self._parse_job_details(redux_data, job_id)

        except httpx.HTTPError:
            return None
        finally:
            if should_close:
                await client.aclose()

    async def fetch_multiple_jobs(
        self,
        job_ids: List[str],
        on_progress: Optional[callable] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch details for multiple jobs with rate limiting."""
        results = []
        total = len(job_ids)

        async with httpx.AsyncClient(timeout=30.0) as client:
            for i, job_id in enumerate(job_ids):
                detail = await self.fetch_job_detail(job_id, client)

                if detail:
                    results.append(detail)

                if on_progress:
                    on_progress(i + 1, total, len(results), detail)

                # Rate limiting between requests
                if i < total - 1:
                    delay = random.uniform(self.min_delay, self.max_delay)
                    await asyncio.sleep(delay)

        return results
