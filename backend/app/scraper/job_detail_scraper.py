"""
Job Detail Scraper

Fetches complete job details from JobsDB job pages.
Phase 2 of the two-phase scraping approach.

Extracts job data from window.SEEK_REDUX_DATA embedded in HTML.
"""

import asyncio
import random
import logging
from typing import Dict, Any, Optional, List

import httpx

from app.config import settings
from app.scraper.access_block import classify_public_access_evidence
from app.scraper.log_events import build_scrape_log_event
from app.scraper.manual_action import (
    ManualActionRequiredError,
    build_session_recovery_manual_action,
)
from app.sources.jobsdb.parsers import parse_detail_page as parse_jobsdb_detail_page

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

    async def fetch_job_detail(
        self,
        job_id: str,
        client: Optional[httpx.AsyncClient] = None
    ) -> Optional[Dict[str, Any]]:
        """Fetch and parse job details for a single job ID."""
        url = f"{self.BASE_URL}/{job_id}"
        referer = f"https://hk.jobsdb.com/jobs?classification={job_id[:4]}"
        logger.debug(
            build_scrape_log_event(
                "SCRAPE_DETAIL_START",
                source="jobsdb",
                source_job_id=job_id,
                url=url,
            )
        )

        should_close = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=30.0)

        try:
            headers = self._get_headers(referer)
            response = await client.get(url, headers=headers, follow_redirects=True)
            access_evidence = classify_public_access_evidence(
                status_code=response.status_code,
                final_url=str(response.url),
                text=(
                    response.text
                    if len(response.text) <= 65536
                    else response.text[:4096]
                ),
            )
            if access_evidence is not None:
                logger.warning(
                    build_scrape_log_event(
                        "SCRAPE_DETAIL_MANUAL_ACTION",
                        source="jobsdb",
                        source_job_id=job_id,
                        classification=access_evidence.classification,
                        status_code=access_evidence.status_code,
                        reason=access_evidence.reason,
                    )
                )
                raise build_session_recovery_manual_action(
                    source_site="jobsdb",
                    stage="detail_page",
                    blocked_url=access_evidence.final_url or url,
                    referer=referer,
                    classification=access_evidence.classification,
                    evidence=access_evidence.to_payload(),
                )
            response.raise_for_status()

            html = response.text
            detail = parse_jobsdb_detail_page(html, job_id=job_id)
            logger.debug(
                build_scrape_log_event(
                    "SCRAPE_DETAIL_OK",
                    source="jobsdb",
                    source_job_id=job_id,
                    url=url,
                )
            )
            return detail

        except ManualActionRequiredError:
            raise
        except httpx.HTTPError as exc:
            logger.warning(
                build_scrape_log_event(
                    "SCRAPE_DETAIL_FAIL",
                    source="jobsdb",
                    source_job_id=job_id,
                    url=url,
                    error=type(exc).__name__,
                )
            )
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
        logger.info(
            build_scrape_log_event(
                "SCRAPE_DETAIL_BATCH_START",
                source="jobsdb",
                jobs=total,
            )
        )

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

        logger.info(
            build_scrape_log_event(
                "SCRAPE_DETAIL_BATCH_OK",
                source="jobsdb",
                jobs=total,
                completed=len(results),
            )
        )
        return results
