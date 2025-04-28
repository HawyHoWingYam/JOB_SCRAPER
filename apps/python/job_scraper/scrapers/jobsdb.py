# apps/python/job_scraper/scrapers/jobsdb.py
"""Jobsdb job scraper implementation."""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import re
import random  # Import random
from bs4 import BeautifulSoup

from ..base.scraper import BaseScraper
from ..models.job import Company, Job

logger = logging.getLogger(__name__)

# List of common User-Agent strings
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
]


class JobsdbScraper(BaseScraper):
    """Scraper for Jobsdb job listings."""

    def __init__(self):
        """Initialize the Jobsdb scraper."""
        super().__init__(name="Jobsdb", base_url="https://hk.jobsdb.com/")
        # Example URL: "https://hk.jobsdb.com/jobs-in-information-communication-technology?sortmode=ListedDate&page=1"

    def search_filters(
        self, job_category: str = None, sortmode: str = None, job_type: str = None
    ) -> Tuple[str, str, str]:  # Return type corrected
        """Get search filters for Jobsdb.

        Args:
            job_category: Job category key (e.g., "software")
            sortmode: Sort mode key (e.g., "listed_date")
            job_type: Job type key (e.g., "full_time")

        Returns:
            Tuple of (category_path, job_type_path, sortmode_value)
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
            # Add more categories as needed
        }

        # Available sort modes
        sortmodes = {"listed_date": "ListedDate", "relevance": "KeywordRelevance"}

        # Default values
        default_category_path = (
            "information-communication-technology"  # Or handle None case
        )
        default_sortmode_value = "ListedDate"

        category_path = job_categories.get(job_category, default_category_path)
        job_type_path = job_types.get(
            job_type
        )  # Returns None if job_type is None or invalid
        sortmode_value = sortmodes.get(sortmode, default_sortmode_value)

        # Log if defaults were used due to invalid input? Optional.
        if job_category and job_category not in job_categories:
            logger.warning(
                f"Invalid job_category '{job_category}', using default '{default_category_path}'."
            )
        if sortmode and sortmode not in sortmodes:
            logger.warning(
                f"Invalid sortmode '{sortmode}', using default '{default_sortmode_value}'."
            )
        if job_type and job_type not in job_types:
            logger.warning(
                f"Invalid job_type '{job_type}', filter will not be applied."
            )

        return category_path, job_type_path, sortmode_value

    def search_jobs(self, **kwargs) -> List[Job]:
        """Search for jobs on JobsDB using the configured method (Selenium/Requests).

        Args:
            **kwargs: Search parameters including:
                - job_category (str): e.g., "software"
                - sortmode (str): e.g., "listed_date"
                - job_type (str): e.g., "full_time"
                - page (int): Page number (default: 1)
                - query (str): Optional search query keyword
                - location (str): Optional location keyword

        Returns:
            List of Job objects found on the page.
        """
        job_category = kwargs.get("job_category")
        sortmode = kwargs.get("sortmode", "listed_date")
        job_type = kwargs.get("job_type")
        page = kwargs.get("page", 1)
        # Potentially use query/location if the URL structure supports it or if using Selenium actions

        category_path, job_type_path, sortmode_value = self.search_filters(
            job_category, sortmode, job_type
        )

        # Build the URL
        if job_type_path:
            # Example: /jobs-in-cat/job-type?sortmode=X&page=Y
            search_url = f"{self.base_url}jobs-in-{category_path}/{job_type_path}"
        else:
            # Example: /jobs-in-cat?sortmode=X&page=Y
            search_url = f"{self.base_url}jobs-in-{category_path}"

        params = {"sortmode": sortmode_value, "page": page}
        # Add query/location to params if the site uses them like ?q=...&l=...
        # if kwargs.get("query"): params["q"] = kwargs["query"]
        # if kwargs.get("location"): params["l"] = kwargs["location"]

        # --- Select random User-Agent ---
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        # logger.info(
        #     f"Searching jobs on page {page} with User-Agent: {headers['User-Agent']}"
        # )

        try:
            # Assumes get_soup accepts headers and params
            # logger.info(f"Fetching URL: {search_url} with params: {params} and headers: {headers}")
            soup = self.get_soup(search_url, params=params
                                 #, headers=headers
                                 )
            if not soup:
                logger.error(
                    f"Failed to get soup object for page {page} of {category_path}"
                )
                return []

            job_listings = []
            # Find job cards (Selector needs verification against actual JobsDB HTML)
            # Common patterns: article, div with data-job-id, li elements
            job_cards = soup.select("article[data-job-id]")
            if not job_cards:
                # Try alternative selectors if the primary one fails
                job_cards = soup.select("div[data-jobid]")  # Example alternative
                if not job_cards:
                    logger.warning(
                        f"Could not find job cards on page {page} using selectors. Check HTML structure."
                    )
                    # Maybe log soup.prettify() here for debugging if needed (careful with size)

            # logger.info(f"Found {len(job_cards)} potential job cards on page {page}.")

            for card in job_cards:
                try:
                    job = self._parse_job_card(card, job_category, job_type)
                    if job:
                        # Basic validation before adding
                        if job.id and job.name and job.company_name:
                            job_listings.append(job)
                        else:
                            logger.warning(
                                f"Parsed job card missing essential info (ID/Name/Company): {job.id}, {job.name}"
                            )
                except Exception as e:
                    # Log error for specific card parsing failure but continue with others
                    logger.error(
                        f"Error parsing a job card on page {page}: {e}", exc_info=True
                    )  # Include traceback

            # Log stats for the current page
            self.log_scraping_stats(
                #page=page,  # Add page number to stats
                jobs_found=len(job_listings),
                search_params={
                    "job_category": job_category,
                    "category_path": category_path,
                    "job_type": job_type,
                    "sortmode": sortmode_value,
                },
            )

            return job_listings

        except Exception as e:
            logger.error(
                f"Error searching jobs on JobsDB page {page}: {e}", exc_info=True
            )
            return []

    def get_job_details(self, job_id: str) -> Optional[Job]:
        """Get detailed information (primarily description) for a specific job.

        Args:
            job_id: JobsDB job ID

        Returns:
            Job object with ID and description, or None if fetching/parsing fails.
        """
        if not job_id:
            logger.error("get_job_details called with empty job_id")
            return None

        job_url = f"{self.base_url}job/{job_id}"
        logger.debug(f"Fetching details for job URL: {job_url}")

        # --- Select random User-Agent ---
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        logger.debug(f"Using User-Agent for job {job_id}: {headers['User-Agent']}")

        try:
            # Pass headers to get_soup (assuming it's supported)
            soup = self.get_soup(job_url, headers=headers)
            if not soup:
                logger.error(f"Failed to get soup object for job details: {job_id}")
                return None  # Critical failure if soup is None

            # Extract job description (Selector needs verification)
            # Common selectors: div[class*="description"], div[id*="description"], section[class*="content"]
            description_element = soup.select_one(
                'div[data-automation="jobAdDetails"] ._1apz9us0'
            )  # Example selector, needs verification
            if not description_element:
                # Try alternative selectors
                description_element = soup.select_one("div.job-description")
                if not description_element:
                    logger.warning(
                        f"Could not find description element for job ID: {job_id}. Check selectors."
                    )
                    description = "N/A"  # Fallback if no description found
                else:
                    description = description_element.get_text(
                        separator="\\n", strip=True
                    )  # Get text, preserve line breaks somewhat
            else:
                description = description_element.get_text(separator="\\n", strip=True)

            # Basic cleaning (optional)
            description = self.clean_text(description) if description else "N/A"

            # Return a minimal Job object containing only the essential info updated
            return Job(
                id=str(job_id),  # Ensure ID is string if needed
                description=description,
                # Add other fields only if they are reliably parsed from the details page
            )

        except Exception as e:
            # Catch specific exceptions if possible (e.g., requests.exceptions.RequestException)
            # logger.error(
            #     f"Error getting job details for {job_id} from {job_url}: {e}",
            #     exc_info=True,
            # )
            return None  # Return None on any exception during detail fetch/parse

    def _parse_job_card(
        self, card: BeautifulSoup, job_category: str, job_type: Optional[str]
    ) -> Optional[Job]:
        """Parse job information from a job card HTML element.

        Args:
            card: BeautifulSoup object for a job card.
            job_category: The category used for the search (for logging/classification).
            job_type: The job type used for the search (for logging/classification).

        Returns:
            Job object populated with info from the card, or None if essential info is missing.
        """
        try:
            # --- Extract Job ID ---
            job_id = card.get("data-job-id")
            if not job_id:
                # Fallback: Check common alternative attributes
                job_id = card.get("data-jobid") or card.get("id")
                if job_id and job_id.startswith("job_"):  # Clean prefix if needed
                    job_id = job_id.replace("job_", "")

                # Fallback: Regex (use cautiously)
                if not job_id:
                    html_str = str(card)
                    # Make regex more specific if possible
                    job_id_match = re.search(r'"jobId":"?(\d+)"?', html_str)
                    job_id = job_id_match.group(1) if job_id_match else None

            if not job_id:
                logger.warning("Could not extract job ID from card.")
                return None  # Cannot proceed without an ID

            # --- Extract Job Title ---
            title = "Unknown Title"
            # Prioritize specific selectors, then broader ones
            title_element = (
                card.select_one('h3 a[data-automation="jobTitle"]')
                or card.select_one('div[data-automation="jobTitle"] a')
                or card.select_one('a[data-automation="jobTitle"]')
                or card.select_one("h3")
            )  # General fallback
            if title_element:
                title = self.clean_text(title_element.get_text())

            # --- Extract Company Name ---
            company_name = "Unknown Company"
            company_element = card.select_one(
                'a[data-automation="jobCompany"]'
            ) or card.select_one(
                'span[data-automation="jobCompany"]'
            )  # Alternative
            if company_element:
                company_name = self.clean_text(company_element.get_text())

            # --- Extract Location ---
            location = "Unknown Location"
            location_element = card.select_one('span[data-automation="jobLocation"]')
            if location_element:
                location = self.clean_text(location_element.get_text())

            # --- Extract Salary ---
            salary = "N/A"
            salary_element = card.select_one('span[data-automation="jobSalary"]')
            if salary_element:
                salary = self.clean_text(salary_element.get_text())

            # --- Extract Posting Date ---
            posting_date_text = "N/A"
            date_element = card.select_one('span[data-automation="jobListingDate"]')
            if date_element:
                posting_date_text = self.clean_text(date_element.get_text())
                # Optional: Try parsing date_text into a datetime object here if format is consistent

            # --- Create Job Object ---
            job = Job(
                id=str(job_id),  # Ensure ID is string
                name=title,
                company_name=company_name,  # Store as string directly
                location=location,
                salary_description=salary,
                source="JobsDB",  # Hardcoded source
                date_scraped=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),  # Use UTC time for consistency
                date_posted=posting_date_text,  # Store raw text, parse later if needed
                job_class=job_category,  # Store category used for search
                work_type=job_type,  # Store type used for search
                description=None,  # Description is fetched later
            )
            # logger.debug(f"Parsed job card: {job.id} - {job.name}")
            return job

        except Exception as e:
            # Log the error and the card's HTML (truncated) for debugging
            card_html_preview = str(card)[:200]  # Preview first 200 chars
            logger.error(
                f"Error parsing job card: {e} - Card HTML preview: {card_html_preview}",
                exc_info=True,
            )
            return None  # Return None on parsing failure

    def _extract_job_title(self, soup: BeautifulSoup) -> str:
        """Extract job title from job details page.

        Args:
            soup: BeautifulSoup object for job details page

        Returns:
            Job title or empty string if not found
        """
        # Update selector based on actual JobsDB HTML
        title_element = soup.select_one(".job-title")
        return self.clean_text(title_element.get_text()) if title_element else ""

    def _extract_company_name(self, soup: BeautifulSoup) -> str:
        """Extract company name from job details page.

        Args:
            soup: BeautifulSoup object for job details page

        Returns:
            Company name or empty string if not found
        """
        # Update selector based on actual JobsDB HTML
        company_element = soup.select_one(".company-name")
        return self.clean_text(company_element.get_text()) if company_element else ""

    def _extract_location(self, soup: BeautifulSoup) -> str:
        """Extract job location from job details page.

        Args:
            soup: BeautifulSoup object for job details page

        Returns:
            Job location or empty string if not found
        """
        # Update selector based on actual JobsDB HTML
        location_element = soup.select_one(".job-location")
        return self.clean_text(location_element.get_text()) if location_element else ""
