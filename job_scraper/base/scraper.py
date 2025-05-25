"""Base scraper class with common functionality for all job scrapers."""

import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Union

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from ..models.job import Job

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Base class for all job scrapers.

    This class provides common functionality for all job scrapers, including
    browser automation, HTML parsing, and standardized data extraction.
    """

    def __init__(self, name: str, base_url: str):
        """Initialize the scraper.

        Args:
            name: Name of the job board/source
            base_url: Base URL for the job board
        """
        self.name = name
        self.base_url = base_url
        self.driver = None
        self._setup_driver()

    def _setup_driver(self, headless=True):
        """Set up the Selenium WebDriver.

        Args:
            headless: Whether to run the browser in headless mode
        """
        options = Options()

        # Only add headless mode if requested
        if headless:
            options.add_argument("--headless")
            options.add_argument("--disable-gpu")

        # Common options regardless of headless mode
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36"
        )

        self.driver = webdriver.Chrome(
            service=Service("chromedriver/chromedriver"),
            options=options,
        )

    def __del__(self):
        """Clean up resources when the scraper is destroyed."""
        if self.driver:
            self.driver.quit()

    def get_soup(
        self, url: str, params: Optional[Dict] = None, headers: Optional[Dict] = None
    ) -> BeautifulSoup:
        """Get BeautifulSoup object from URL using Selenium.

        Args:
            url: URL to fetch
            params: Optional query parameters
            headers: Optional HTTP headers

        Returns:
            BeautifulSoup object for parsing
        """
        try:
            # Construct URL with params if provided
            if params:
                query_string = "&".join(f"{k}={v}" for k, v in params.items())
                full_url = (
                    f"{url}?{query_string}"
                    if "?" not in url
                    else f"{url}&{query_string}"
                )
            else:
                full_url = url

            # Set User-Agent if provided in headers
            if headers and "User-Agent" in headers:
                # Execute CDP (Chrome DevTools Protocol) command to set user agent
                self.driver.execute_cdp_cmd(
                    "Network.setUserAgentOverride", {"userAgent": headers["User-Agent"]}
                )
                logger.debug(f"Using User-Agent: {headers['User-Agent']}")

            logger.info(f"Fetching URL: {full_url}")
            self.driver.get(full_url)

            # Wait for page to load
            time.sleep(5)  # Basic wait - can be improved with explicit waits

            # Get page source and create BeautifulSoup object
            page_source = self.driver.page_source
            return BeautifulSoup(page_source, "html.parser")
        except Exception as e:
            logger.error(f"Error fetching URL: {url}")
            logger.error(f"Error: {e}")
            raise

    @abstractmethod
    def search_jobs(self, query: str, location: str, **kwargs) -> List[Job]:
        """Search for jobs with the given query and location.

        Args:
            query: Job search query (e.g., "software engineer")
            location: Job location (e.g., "New York, NY")
            **kwargs: Additional search parameters

        Returns:
            List of Job objects
        """
        pass

    @abstractmethod
    def get_job_details(self, job_id: str) -> Job:
        """Get detailed information for a specific job.

        Args:
            job_id: Unique identifier for the job

        Returns:
            Job object with detailed information
        """
        pass

    def clean_text(self, text: Optional[str]) -> str:
        """Clean and normalize text."""
        if not text:
            return ""

        # Remove extra whitespace
        return " ".join(text.strip().split())

    def log_scraping_stats(self, jobs_found: int, search_params: Dict) -> None:
        """Log scraping statistics."""
        logger.info(
            f"[{self.name}] Found {jobs_found} jobs for params: {search_params}"
        )
