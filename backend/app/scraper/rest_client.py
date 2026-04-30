"""
JobsDB REST API Client - Primary Scraper

Discovered API endpoint (2026-02-04):
GET https://hk.jobsdb.com/api/jobsearch/v5/me/search

This is the ACTUAL API used by JobsDB's React frontend for job search.
The GraphQL endpoint is only used for banners/feature flags.
"""

import logging
from typing import Dict, Any, List, Optional

import httpx

from app.utils.anti_detection import (
    get_stealth_headers,
    random_delay,
    ExponentialBackoff,
)
from app.config import settings

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when API returns 429 Too Many Requests."""
    pass


class AuthError(Exception):
    """Raised when API returns 401/403 authentication errors."""
    pass


class JobsDBRestClient:
    """
    REST API client for JobsDB job search.

    Endpoint: GET /api/jobsearch/v5/me/search

    Strategy:
    1. Send GET requests with stealth headers
    2. Random delays between requests (2-5 seconds)
    3. Exponential backoff on failures
    4. Transform response to our schema
    """

    # Public endpoint (no auth required)
    # Note: /me/search requires OAuth, /search is public
    BASE_URL = "https://hk.jobsdb.com/api/jobsearch/v5/search"

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """Async context manager entry."""
        self._client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()

    async def search_jobs(
        self,
        keywords: str,
        page: int = 1,
        page_size: int = 32,
        classification: Optional[str] = None,
        location: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Search jobs via REST API.

        Args:
            keywords: Search keywords (e.g., "Data Analyst")
            page: Page number (1-indexed)
            page_size: Results per page (max 32)
            classification: Job category ID (e.g., "6281" for ICT)
            location: Location filter

        Returns:
            Dict with jobs list and metadata
        """
        # Build query parameters
        params = {
            "siteKey": "HK-Main",
            "sourcesystem": "houston",
            "keywords": keywords,
            "pageSize": min(page_size, 32),
            "page": page,
            "locale": "en-HK",
        }

        if classification:
            params["classification"] = classification
        if location:
            params["where"] = location

        # Get stealth headers (no Content-Type for GET)
        headers = get_stealth_headers()
        # Remove Content-Type for GET requests
        headers.pop("Content-Type", None)

        # Add delay before request
        await random_delay(
            settings.scraper_min_delay,
            settings.scraper_max_delay,
        )

        logger.info(f"Searching jobs: keywords={keywords}, page={page}")

        response = await self._client.get(
            self.BASE_URL,
            params=params,
            headers=headers,
        )

        # Handle errors
        if response.status_code == 429:
            raise RateLimitError("Rate limited by JobsDB API")
        if response.status_code in (401, 403):
            raise AuthError(f"Auth error: {response.status_code}")

        response.raise_for_status()
        data = response.json()

        return {
            "jobs": data.get("data", []),
            "total_count": data.get("totalCount", 0),
            "page": page,
            "page_size": page_size,
            "keyword": keywords,
            "suggestions": data.get("suggestions", {}),
        }

    async def search_jobs_with_retry(
        self,
        keywords: str,
        page: int = 1,
        page_size: int = 32,
        classification: Optional[str] = None,
        location: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Search jobs with exponential backoff retry."""
        backoff = ExponentialBackoff(max_retries=settings.scraper_max_retries)

        for attempt in range(backoff.max_retries):
            try:
                return await self.search_jobs(
                    keywords=keywords,
                    page=page,
                    page_size=page_size,
                    classification=classification,
                    location=location,
                )
            except RateLimitError:
                if attempt < backoff.max_retries - 1:
                    logger.warning(f"Rate limited, retrying... (attempt {attempt + 1})")
                    await backoff.wait(attempt)
                else:
                    raise

        # Should not reach here
        raise RateLimitError("Max retries exceeded")

    def transform_job(self, raw_job: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform raw API response to our schema.

        Maps JobsDB API fields to our database schema.
        """
        # Extract nested fields safely
        advertiser = raw_job.get("advertiser", {})
        locations = raw_job.get("locations", [{}])
        classifications = raw_job.get("classifications", [{}])
        work_arrangements = raw_job.get("workArrangements", {}).get("data", [])
        branding = raw_job.get("branding", {})

        return {
            "external_id": raw_job.get("id"),
            "title": raw_job.get("title"),
            "company_name": raw_job.get("companyName"),
            "advertiser_id": advertiser.get("id"),
            "advertiser_name": advertiser.get("description"),
            "bullet_points": raw_job.get("bulletPoints", []),
            "location": locations[0].get("label") if locations else None,
            "country_code": locations[0].get("countryCode") if locations else None,
            "salary_label": raw_job.get("salaryLabel"),
            "listing_date": raw_job.get("listingDate"),
            "listing_date_display": raw_job.get("listingDateDisplay"),
            "teaser": raw_job.get("teaser"),
            "work_types": raw_job.get("workTypes", []),
            "work_arrangements": [
                arr.get("label", {}).get("text")
                for arr in work_arrangements
                if arr.get("label", {}).get("text")
            ],
            "classification_id": (
                classifications[0].get("classification", {}).get("id")
                if classifications else None
            ),
            "classification_name": (
                classifications[0].get("classification", {}).get("description")
                if classifications else None
            ),
            "logo_url": branding.get("serpLogoUrl"),
        }

    def transform_jobs(self, raw_jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Transform a list of raw jobs to our schema."""
        return [self.transform_job(job) for job in raw_jobs]
