"""
Playwright Scraper Client - Primary Scraper

JobsDB uses Server-Side Rendering (SSR), so job data is embedded in HTML.
This client uses browser automation to:
1. Navigate to search pages
2. Extract job data from DOM elements
3. Handle pagination

This is the PRIMARY scraping approach (not a fallback).
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Playwright is optional - only import when needed
try:
    from playwright.async_api import async_playwright, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not installed. Plan B fallback unavailable.")


class PlaywrightScraperClient:
    """
    Primary scraper using Playwright browser automation.

    Strategy:
    1. Launch headless browser with stealth settings
    2. Navigate to JobsDB search page
    3. Extract job data from DOM (SSR content)
    4. Handle pagination for multiple pages
    """

    def __init__(self):
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright not installed")
        self._playwright = None
        self._browser = None

    async def __aenter__(self):
        """Async context manager entry."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def search_jobs(
        self,
        keyword: str,
        page_num: int = 1,
    ) -> Dict[str, Any]:
        """
        Search jobs by extracting data from DOM.

        Args:
            keyword: Search keyword
            page_num: Page number (1-indexed)

        Returns:
            Dict with jobs list and metadata
        """
        page = await self._browser.new_page()

        try:
            # Build URL with pagination
            url = f"https://hk.jobsdb.com/jobs?q={keyword}"
            if page_num > 1:
                url += f"&page={page_num}"

            logger.info(f"Navigating to: {url}")
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            # Extract jobs from DOM
            jobs = await self._extract_jobs_from_dom(page)

            return {
                "jobs": jobs,
                "page": page_num,
                "keyword": keyword,
            }

        finally:
            await page.close()

    async def _extract_jobs_from_dom(self, page) -> List[Dict[str, Any]]:
        """Extract job data from DOM elements."""
        return await page.evaluate("""
            () => {
                const articles = document.querySelectorAll('article');
                return Array.from(articles).map(article => {
                    const titleLink = article.querySelector('h3 a');
                    const companyLink = article.querySelector('a[href*="-jobs"]');
                    const locationLink = article.querySelector('a[href*="/jobs/in-"]');
                    const listItems = article.querySelectorAll('li');

                    // Extract job ID from URL
                    const url = titleLink?.href || '';
                    const jobIdMatch = url.match(/job\\/(\\d+)/);

                    return {
                        id: jobIdMatch ? jobIdMatch[1] : null,
                        title: titleLink?.textContent?.trim() || null,
                        url: url,
                        company: companyLink?.textContent?.trim() || null,
                        location: locationLink?.textContent?.trim() || null,
                        highlights: Array.from(listItems).map(
                            li => li.textContent?.trim()
                        ).filter(Boolean)
                    };
                }).filter(job => job.title);
            }
        """)
