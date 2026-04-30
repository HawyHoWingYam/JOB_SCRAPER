"""
Anti-detection utilities for stealth web scraping.

This module provides tools to mimic real browser behavior and avoid bot detection.
Strategy: Stealth-first, then reliability.
"""

import random
import asyncio
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

# User-Agent pool - rotate between these to avoid fingerprinting
USER_AGENTS = [
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]


def get_random_user_agent() -> str:
    """Return a random user agent from the pool."""
    return random.choice(USER_AGENTS)


def get_stealth_headers(user_agent: Optional[str] = None) -> Dict[str, str]:
    """
    Generate headers that mimic a real browser making XHR requests.

    These headers are critical for bypassing bot detection on JobsDB.
    They mimic what a React frontend would send when making GraphQL requests.
    """
    ua = user_agent or get_random_user_agent()

    # Determine browser type from user agent for sec-ch-ua
    if "Chrome" in ua and "Edg" not in ua:
        sec_ch_ua = '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"'
    elif "Edg" in ua:
        sec_ch_ua = '"Not_A Brand";v="8", "Chromium";v="120", "Microsoft Edge";v="120"'
    elif "Firefox" in ua:
        sec_ch_ua = ""  # Firefox doesn't send sec-ch-ua
    else:
        sec_ch_ua = '"Not_A Brand";v="8", "Chromium";v="120"'

    headers = {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-HK,en;q=0.9,zh-HK;q=0.8,zh;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Content-Type": "application/json",
        "Origin": "https://hk.jobsdb.com",
        "Referer": "https://hk.jobsdb.com/",
        "Connection": "keep-alive",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }

    # Add Chrome-specific headers
    if sec_ch_ua:
        headers["sec-ch-ua"] = sec_ch_ua
        headers["sec-ch-ua-mobile"] = "?0"
        headers["sec-ch-ua-platform"] = '"macOS"' if "Mac" in ua else '"Windows"'

    return headers


async def random_delay(min_seconds: float = 2.0, max_seconds: float = 5.0) -> None:
    """
    Async sleep with random jitter to avoid request pattern detection.

    Human browsing has natural variance - we mimic this with random delays.
    """
    delay = random.uniform(min_seconds, max_seconds)
    logger.debug(f"Stealth delay: {delay:.2f}s")
    await asyncio.sleep(delay)


class ExponentialBackoff:
    """
    Exponential backoff with jitter for retry logic.

    Usage:
        backoff = ExponentialBackoff(max_retries=3)
        for attempt in range(backoff.max_retries):
            try:
                result = await make_request()
                break
            except RateLimitError:
                await backoff.wait(attempt)
    """

    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        max_retries: int = 3,
        jitter: float = 0.5,
    ):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self.jitter = jitter

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number (0-indexed)."""
        delay = self.base_delay * (2 ** attempt)
        delay = min(delay, self.max_delay)
        # Add jitter to prevent thundering herd
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)
        return max(0, delay)

    async def wait(self, attempt: int) -> None:
        """Wait with exponential backoff."""
        delay = self.get_delay(attempt)
        logger.info(f"Backoff: attempt {attempt + 1}, waiting {delay:.2f}s")
        await asyncio.sleep(delay)
