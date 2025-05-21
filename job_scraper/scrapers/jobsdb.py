"""Jobsdb job scraper implementation."""

import logging, re, random, pytz, os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup

from ..base.scraper import BaseScraper
from ..models.job import Company, Job

logger = logging.getLogger(__name__)


# Add this list at the class level or module level
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
]


class JobsdbScraper(BaseScraper):
    """Scraper for Jobsdb job listings."""

    def __init__(self):
        """Initialize the Jobsdb scraper."""
        super().__init__(name="Jobsdb", base_url="https://hk.jobsdb.com/")
        # Example URL: "https://hk.jobsdb.com/jobs-in-information-communication-technology?sortmode=ListedDate&page=1"

    def save_soup_to_html(self, soup: BeautifulSoup, filename_prefix: str):
        """Save BeautifulSoup object to an HTML file in the raw_data folder.
        
        Args:
            soup: BeautifulSoup object to save
            filename_prefix: Prefix for the filename (e.g. 'search', 'job_123')
        """
        # Create raw_data directory if it doesn't exist
        raw_data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'raw_data')
        os.makedirs(raw_data_dir, exist_ok=True)
        
        # Generate timestamp for unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{filename_prefix}_{timestamp}.html"
        file_path = os.path.join(raw_data_dir, filename)
        
        # Write the HTML content to the file
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(str(soup))
        
        logger.info(f"Saved HTML content to {file_path}")

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
        """Search for jobs on JobsDB.

        Args:
            query: Job search query (e.g., "software engineer")
            location: Job location (e.g., "Hong Kong")
            **kwargs: Additional search parameters
                - limit: Maximum number of jobs to return (default: 25)

        Returns:
            List of Job objects
        """

        # # Get job category from kwargs if provided
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
            
            # Save the soup to HTML file
            filename_prefix = f"search_{job_category or 'all'}_{job_type or 'all'}_page{page}"
            self.save_soup_to_html(soup, filename_prefix)
            
            job_listings = []

            # Find and parse job cards (update selector based on actual JobsDB HTML)
            job_cards = soup.select("article[data-job-id]")  # Update this selector

            for card in job_cards:
                try:
                    job = self._parse_job_card(card, job_category, job_type)
                    if job:
                        job_listings.append(job)
                except Exception as e:
                    logger.error(f"Error parsing job card: {e}")

            self.log_scraping_stats(
                jobs_found=len(job_listings),
                search_params={
                    "job_category": job_category,
                    "category_path": category_path,
                    "sortmode": sortmode_value,
                    # "page": page,
                },
            )

            return job_listings

        except Exception as e:
            logger.error(f"Error searching jobs on JobsDB: {e}")
            return []

    def get_job_details(self, job_id: str) -> Optional[Job]:
        """Get detailed information for a specific job.

        Args:
            job_id: JobsDB job ID

        Returns:
            Job object with detailed information or None if not found
        """
        job_url = f"{self.base_url}job/{job_id}"
        
        try:
            # Select random user agent
            user_agent = random.choice(USER_AGENTS)
            headers = {"User-Agent": user_agent}
            
            # Pass headers to get_soup
            soup = self.get_soup(job_url, headers=headers)
            
            # Save the soup to HTML file
            # filename_prefix = f"job_details_{job_id}"
            # self.save_soup_to_html(soup, filename_prefix)
 
            # Try multiple possible selectors
            description_element = None
            selectors = [
                ".x3iy8f0._1xd6mbw0",
                ".gg45di0._1apz9us0",  # Previous selector
                "[data-automation='jobAdDetails']",  # More general selector
                "div[data-automation='jobAdDetails'] > div"  # Child of jobAdDetails
            ]
            for selector in selectors:
                description_element = soup.select_one(selector)
                if description_element:
                    break
                        
            description = description_element.get_text() if description_element else ""
            # description = str(description_element) if description_element else ""
            
            # Create job object with ID and description
            return Job(
                id=job_id, description=description  # Important: Include the job_id
            )

        except Exception as e:
            logger.error(f"Error getting job details for {job_id}: {e}")
            return None

    def _parse_job_card(
        self, card: BeautifulSoup, job_category: str, job_type: str
    ) -> Optional[Job]:
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
                html_str = str(card)
                job_id_match = re.search(r'"jobId":"(\d+)"', html_str)
                job_id = job_id_match.group(1) if job_id_match else None

            if not job_id:
                return None

            title = "N/A"
            try:
                # Extract job title from h3 element
                title_element = card.select_one("h3 a")
                title = (
                    self.clean_text(title_element.get_text())
                    if title_element
                    else "Unknown Title"
                )
            except Exception as e:
                logger.error(f"Error extracting title: {e}")
                raise

            company_name = "N/A"
            try:
                # Extract company name - update selector based on the HTML structure
                company_element = card.select_one('a[data-automation="jobCompany"]')
                company_name = (
                    self.clean_text(company_element.get_text())
                    if company_element
                    else "Unknown Company"
                )
            except Exception as e:
                logger.error(f"Error extracting company name: {e}")
                raise

            location = "N/A"
            try:
                # Extract location - update selector based on the HTML structure
                location_element = card.select_one(
                    'span[data-automation="jobLocation"]'
                )
                location = (
                    self.clean_text(location_element.get_text())
                    if location_element
                    else "Unknown Location"
                )
            except Exception as e:
                logger.error(f"Error extracting location: {e}")
                raise

            # Extract salary information
            salary = "N/A"
            try:
                salary_element = card.select_one('span[data-automation="jobSalary"]')
                if salary_element:
                    # Look for the inner span that contains the actual salary text
                    salary = self.clean_text(salary_element.get_text())

            except Exception as e:
                logger.error(f"Error extracting salary: {e}")
                raise

            # Extract job posting date
            posting_date_text = "N/A"
            date_posted = "N/A"
            try:
                date_element = card.select_one('span[data-automation="jobListingDate"]')
                if date_element:
                    # Extract text directly from the span element
                    posting_date_text = self.clean_text(date_element.get_text())

                    # current HK date and time in timestamp format
                    current_time = datetime.now(pytz.timezone('Asia/Hong_Kong')).timestamp()
                    # if date_posted contains "d ago", then calculate the timestamp
                    if "d ago" in posting_date_text:
                        date_posted = current_time - int(posting_date_text.split("d ago")[0]) * 24 * 60 * 60
                    elif "h ago" in posting_date_text:
                        date_posted = current_time - int(posting_date_text.split("h ago")[0]) * 60 * 60
                    elif "m ago" in posting_date_text:
                        date_posted = current_time - int(posting_date_text.split("m ago")[0]) * 60
                    else:
                        date_posted = current_time


            except Exception as e:
                logger.error(f"Error extracting posting date: {e}")
                raise
            # logger.info(
            #     f"Extracted jobID & title: {job_id}-{title} - {company_name} - {location} - {salary}"
            # )

            # Create job object with new schema
            return Job(
                internal_id=job_id,
                id=job_id,
                name=title,
                company_name=company_name,
                location=location,
                salary_description=salary,
                source="JobsDB",
                date_scraped=datetime.now(pytz.timezone('Asia/Hong_Kong')).strftime("%Y-%m-%d"),
                date_posted=datetime.fromtimestamp(date_posted).strftime("%Y-%m-%d"),
                job_class=job_category,
                work_type=job_type,
            )

        except Exception as e:
            logger.error(f"Error parsing job card: {e}")
            return None

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