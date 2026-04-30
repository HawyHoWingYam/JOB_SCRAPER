"""
JobsDB Scraper Package

Scraping strategies:
1. Primary: REST API client - direct API calls (no auth required)
2. Fallback: Playwright DOM scraper - browser automation
"""

from app.scraper.rest_client import JobsDBRestClient, RateLimitError, AuthError
from app.scraper.playwright_client import PlaywrightScraperClient

__all__ = [
    "JobsDBRestClient",
    "PlaywrightScraperClient",
    "RateLimitError",
    "AuthError",
]
