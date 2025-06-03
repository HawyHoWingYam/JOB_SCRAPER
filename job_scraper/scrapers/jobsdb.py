"""Jobsdb job scraper implementation."""

import logging, re, random, pytz, os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
import google.generativeai as genai
from dotenv import load_dotenv

from ..base.scraper import BaseScraper
from ..models.job import Company, Job

logger = logging.getLogger(__name__)
load_dotenv()
api_key = "AIzaSyDnUHmWDSsrh3X6wImAH4UOgRV1kLUA41E"
genai.configure(api_key=api_key)


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

    def __init__(self, headless=True, db=None):
        """Initialize the Jobsdb scraper.

        Args:
            headless (bool): Whether to run browser in headless mode. Defaults to True.
            db: Database connector instance
        """
        super().__init__(
            name="Jobsdb", base_url="https://hk.jobsdb.com/", headless=headless
        )
        self.db = db

    def save_soup_to_html(self, soup: BeautifulSoup, filename_prefix: str):
        """Save BeautifulSoup object to an HTML file in the raw_data folder.

        Args:
            soup: BeautifulSoup object to save
            filename_prefix: Prefix for the filename (e.g. 'search', 'job_123')
        """
        # Create raw_data directory if it doesn't exist
        raw_data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "raw_data"
        )
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
        # Available categories
        job_categories = {
            "software": "information-communication-technology",
            "finance": "accounting-finance",
        }
        # Use ListedDate as the default sorting method
        return (job_categories[job_category],)

    def search_jobs(self, **kwargs) -> List[Job]:
        page = kwargs.get("page", 1)
        search_url = f"{self.base_url}jobs-in-{kwargs.get('job_class')}"
        params = {"sortmode": "ListedDate", "page": page}
        
        try:
            existing_ids = []
            if self.db:  # Make sure db connection exists
                existing_ids = self.db.get_existing_job_ids()
            else:
                logger.warning(
                    "No database connection available, skipping duplicate check"
                )
            logger.info(f"{search_url} - Searching for jobs in {kwargs.get('job_class')}")
            soup = self.get_soup(search_url, params=params)
            # filename_prefix = f"jobsdb_{job_class}_page{page}"
            # self.save_soup_to_html(soup, filename_prefix)
            job_listings = []
            job_cards = soup.select("article[data-job-id]")

            for card in job_cards:
                try:
                    job = self._parse_job_card(card)
                    if job:
                        if str(job.id) in existing_ids:
                            continue
                        job_listings.append(job)
                except Exception as e:
                    logger.error(f"Error parsing job card: {e}")

            self.log_scraping_stats(
                jobs_found=len(job_listings),
                search_params={
                    # "job_class": job_class,
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
            job_class = "N/A"
            job_class_element = soup.select_one(
                'span[data-automation="job-detail-classifications"] a'
            )
            if job_class_element:
                full_text = job_class_element.get_text(strip=True)
                match = re.search(r"\((.*?)\)", full_text)
                if match:
                    job_class = match.group(1)
                else:
                    job_class = full_text

            # Try multiple possible selectors
            description_element = None
            selectors = [
                "[data-automation='jobAdDetails']",  # More general selector
                "div[data-automation='jobAdDetails'] > div",  # Child of jobAdDetails
            ]
            for selector in selectors:
                description_element = soup.select_one(selector)
                if description_element:
                    break

            description = description_element.get_text() if description_element else ""
            # description_html = self.format_job_description_with_gemini(description)
            # Create job object with ID and description
            return Job(id=str(job_id), description=description, job_class=job_class)

        except Exception as e:
            logger.error(f"Error getting job details for {job_id}: {e}")
            return None

    def read_job_description_prompt(self):
        prompt_path = "job_scraper/prompt/job_description.txt"
        try:
            with open(prompt_path, "r", encoding="utf-8") as file:
                prompt = file.read()
            return prompt
        except FileNotFoundError:
            print(f"Error: Could not find the prompt file at {prompt_path}")
            return None
        except Exception as e:
            print(f"Error reading prompt file: {str(e)}")
            return None

    def format_job_description_with_gemini(self, text):
        """Format job description as HTML using Gemini API"""
        if not text or not text.strip():
            return "<p>No description available</p>"

        try:
            # Initialize the model
            model = genai.GenerativeModel("gemini-2.0-flash")

            # Create the prompt
            prompt = self.read_job_description_prompt()

            # Generate the HTML response
            response = model.generate_content(prompt)

            # Extract and sanitize the HTML
            html_content = response.text.strip()

            # If the response has markdown code blocks, extract just the HTML
            if "```html" in html_content:
                html_content = html_content.split("```html")[1].split("```")[0].strip()
            elif "```" in html_content:
                html_content = html_content.split("```")[1].strip()

            # Wrap in a container if not already wrapped
            if not html_content.startswith("<div"):
                html_content = f'<div class="job-description">{html_content}</div>'

            return html_content

        except Exception as e:
            print(f"Error calling Gemini API: {str(e)}")
            # Fallback to simple formatting if API call fails
            return f"<div class='job-description'><p>{text}</p></div>"

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
                    # logger.info(f"Posting date text: {posting_date_text}")
                    # current HK date and time in timestamp format
                    current_time = datetime.now(
                        pytz.timezone("Asia/Hong_Kong")
                    ).timestamp()
                    # if date_posted contains "d ago", then calculate the timestamp
                    if "d ago" in posting_date_text:
                        date_posted = (
                            current_time
                            - int(posting_date_text.split("d ago")[0]) * 24 * 60 * 60
                        )
                    elif "h ago" in posting_date_text:
                        date_posted = (
                            current_time
                            - int(posting_date_text.split("h ago")[0]) * 60 * 60
                        )
                    elif "m ago" in posting_date_text:
                        date_posted = (
                            current_time - int(posting_date_text.split("m ago")[0]) * 60
                        )
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
                id=str(job_id),
                name=title,
                company_name=company_name,
                location=location,
                salary_description=salary,
                source="JobsDB",
                date_scraped=datetime.now(pytz.timezone("Asia/Hong_Kong")).strftime(
                    "%Y-%m-%d"
                ),
                date_posted=datetime.fromtimestamp(date_posted).strftime("%Y-%m-%d"),
                # job_class=job_class,
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
