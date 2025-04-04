"""Jobsdb job scraper implementation."""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import re
from bs4 import BeautifulSoup

from ..base.scraper import BaseScraper
from ..models.job import Company, Job

logger = logging.getLogger(__name__)


class JobsdbScraper(BaseScraper):
    """Scraper for Jobsdb job listings."""

    def __init__(self):
        """Initialize the Jobsdb scraper."""
        super().__init__(name="Jobsdb", base_url="https://hk.jobsdb.com/")
        # Example URL: "https://hk.jobsdb.com/jobs-in-information-communication-technology?sortmode=ListedDate&page=1"

    def search_filters(
        self, job_category: str = None, sortmode: str = None, job_type: str = None
    ) -> Tuple[str, str]:
        """Get search filters for Jobsdb.

        Args:
            job_category: Job category to filter by (e.g., "software-engineer")

        Returns:
            Tuple of (job_category_path, sortmode)
        """
        # Available job types
        job_types = {
            "full_time": "full-time",
            "part_time": "part-time",
            "contract": "contract-temp",
            "casual": "casual-vacation",
        }

        # Available categories
        job_categories = {
            "software": "information-communication-technology",
            "finance": "accounting-finance",
        }

        # Available sort modes
        sortmodes = {"listed_date": "ListedDate", "relevance": "KeywordRelevance"}

        # Use ListedDate as the default sorting method
        return (
            job_categories[job_category],
            job_types[job_type] if job_type else None,
            sortmodes[sortmode],
        )

    def search_jobs(self, **kwargs) -> List[Job]:
        """Search for jobs on Jobsdb.

        Args:
            **kwargs: Additional search parameters
                - job_category: Category to search in (e.g., "software")
                - page: Page number (default: 1)
                - job_type: Type of job (default: None)
                - sortmode: Sorting method (default: "ListedDate")

        Returns:
            List of Job objects
        """
        # Get job category from kwargs if provided
        job_category = kwargs.get("job_category")
        sortmode = kwargs.get("sortmode", "listed_date")
        job_type = kwargs.get("job_type")

        # Get filters from search_filters method
        category_path, job_type_path, sortmode_value = self.search_filters(
            job_category, sortmode, job_type
        )

        # Get optional parameters
        page = kwargs.get("page", 1)

        # Build the URL with the correct format
        # Only add job_type to URL if it's not None
        if job_type_path:
            search_url = f"{self.base_url}jobs-in-{category_path}/{job_type_path}"
        else:
            search_url = f"{self.base_url}jobs-in-{category_path}"

        # Jobsdb search URL parameters
        params = {"sortmode": sortmode_value, "page": page}

        try:
            soup = self.get_soup(search_url, params=params)
            # logger.info(f"Searching jobs on Jobsdb: {soup}")
            # save soup to file for debugging
            with open("jobsdb_soup.html", "w", encoding="utf-8") as f:
                f.write(str(soup))

            job_listings = []

            # Find and parse job cards
            job_cards = soup.select("article[data-job-id]")
            logger.info(f"Found {len(job_cards)} job cards.")

            for card in job_cards:
                try:
                    job = self._parse_job_card(card)
                    if job:
                        job_listings.append(job)
                except Exception as e:
                    logger.error(f"Error parsing job card: {e}")

            self.log_scraping_stats(
                jobs_found=len(job_listings),
                search_params={
                    "job_category": job_category,
                    "category_path": category_path,
                    "sortmode": sortmode,
                    # "page": page,
                },
            )

            return job_listings

        except Exception as e:
            logger.error(f"Error searching jobs on Jobsdb: {e}")
            return []

    def get_job_details(self, job_id: str) -> Optional[Job]:
        """Get detailed information for a specific job.

        Args:
            job_id: Jobsdb job ID

        Returns:
            Job object with detailed information or None if not found
        """
        job_url = f"{self.base_url}/viewjob?jk={job_id}"

        try:
            soup = self.get_soup(job_url)

            # Extract full job description
            description_element = soup.select_one("#jobDescriptionText")
            full_description = (
                description_element.get_text() if description_element else ""
            )

            # Parse other job details (company, location, salary, etc.)
            # This would require more detailed parsing logic for Jobsdb

            # For now, create a minimal job object
            company_name = self._extract_company_name(soup)

            return Job(
                id=job_id,
                title=self._extract_job_title(soup),
                description=full_description,
                url=job_url,
                company=Company(name=company_name),
                location=self._extract_location(soup),
                source="Jobsdb",
                source_id=job_id,
                date_scraped=datetime.utcnow(),
            )

        except Exception as e:
            logger.error(f"Error getting job details for {job_id}: {e}")
            return None

    def _parse_job_card(self, card: BeautifulSoup) -> Optional[Job]:
        """Parse job information from a job card.

        Args:
            card: BeautifulSoup object for a job card

        Returns:
            Job object or None if parsing fails
        """
        try:
            # Extract job ID from the data-job-id attribute
            job_id = card.get("data-job-id")

            if not job_id:
                # Fallback to regex pattern if attribute extraction fails
                import re

                html_str = str(card)
                job_id_match = re.search(r'"jobId":"(\d+)"', html_str)
                job_id = job_id_match.group(1) if job_id_match else None

            if not job_id:
                return None

            # Extract job title from h3 element
            title_element = card.select_one("h3 a")
            title = (
                self.clean_text(title_element.get_text())
                if title_element
                else "Unknown Title"
            )

            # Extract company name - update selector based on the HTML structure
            company_element = card.select_one('a[data-automation="jobCompany"]')
            company_name = (
                self.clean_text(company_element.get_text())
                if company_element
                else "Unknown Company"
            )

            # Extract location - update selector based on the HTML structure
            location_element = card.select_one('span[data-automation="jobLocation"]')
            location = (
                self.clean_text(location_element.get_text())
                if location_element
                else "Unknown Location"
            )

            # Extract job URL
            job_url = f"{self.base_url}job/{job_id}"

            # Create job object
            return Job(
                id=job_id,
                title=title,
                description="",  # Empty description for search results
                url=job_url,
                company=Company(name=company_name),
                location=location,
                source="Jobsdb",
                source_id=job_id,
                date_scraped=datetime.utcnow(),
            )
        except Exception as e:
            logger.error(f"Error parsing job card: {e}")
            return None

    def _extract_job_title(self, soup: BeautifulSoup) -> str:
        """Extract job title from job details page.

        Args:
            soup: BeautifulSoup object for job details page

        Returns:
            Job title or default text if not found
        """
        title_element = soup.select_one(".jobsearch-JobInfoHeader-title")
        return (
            self.clean_text(title_element.get_text())
            if title_element
            else "Unknown Title"
        )

    def _extract_company_name(self, soup: BeautifulSoup) -> str:
        """Extract company name from job details page.

        Args:
            soup: BeautifulSoup object for job details page

        Returns:
            Company name or default text if not found
        """
        company_element = soup.select_one(".jobsearch-InlineCompanyName")
        return (
            self.clean_text(company_element.get_text())
            if company_element
            else "Unknown Company"
        )

    def _extract_location(self, soup: BeautifulSoup) -> str:
        """Extract job location from job details page.

        Args:
            soup: BeautifulSoup object for job details page

        Returns:
            Job location or default text if not found
        """
        location_element = soup.select_one(
            ".jobsearch-JobInfoHeader-subtitle .jobsearch-JobInfoHeader-locationText"
        )
        return (
            self.clean_text(location_element.get_text())
            if location_element
            else "Unknown Location"
        )
