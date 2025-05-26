"""LinkedIn job scraper implementation."""

import logging
import re
import random
import pytz
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
import google.generativeai as genai
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
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


class LinkedInScraper(BaseScraper):
    """Scraper for LinkedIn job listings."""

    def __init__(self, db=None, headless=True):
        """Initialize the LinkedIn scraper with optional credentials."""
        # Call parent init but don't set up driver yet
        self.name = "LinkedIn"
        self.base_url = "https://www.linkedin.com/"
        self.driver = None
        self.is_logged_in = False
        self.db = db

        # Set up driver with visible browser (not headless)
        self._setup_driver(headless=headless)

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

    def search_jobs(self, **kwargs) -> List[Job]:
        """Search for jobs on LinkedIn using a manual login session."""
        # Login check only - no login process here
        if not self.is_logged_in:
            logger.warning("Not logged in. Please call login() first")
            return []

        page = kwargs.get("page", 1)
        base_url = f"{self.base_url}jobs/search/"

        # Base parameters
        params = {
            # "currentJobId": 4222208398,
            "geoId": 103291313,
            # "origin": "JOB_SEARCH_PAGE_SEARCH_BUTTON",
            "f_TPR": "r172800",
            "sortBy": "DD",
            "start": (page - 1) * 25,
        }

        try:
            # Get the page content
            soup = self.get_soup(base_url, params=params)

            # Save the soup to HTML for debugging
            # filename_prefix = f"linkedin_search_page_{page}"
            # self.save_soup_to_html(soup, filename_prefix)
            job_cards = soup.select("li[data-occludable-job-id]")
            job_ids = [card.get("data-occludable-job-id") for card in job_cards]

            # Get list of existing job IDs from database
            existing_ids = []
            if self.db:  # Make sure db connection exists
                existing_ids = self.db.get_existing_job_ids()
            else:
                logger.warning(
                    "No database connection available, skipping duplicate check"
                )

            job_listings = []
            for job_id in job_ids:
                # Skip if already exists in database
                if str(job_id) in existing_ids:
                    # logger.info(
                    #     f"Skipping job ID {job_id} - already exists in database"
                    # )
                    continue

                # Create a Job object for new jobs only
                job = Job(
                    id=str(job_id),
                    name="N/A",
                    description="",
                    company_name="N/A",
                    location="N/A",
                    source="LinkedIn",
                    date_scraped=datetime.now(pytz.timezone("Asia/Hong_Kong")).strftime(
                        "%Y-%m-%d"
                    ),
                    salary_description="N/A",
                    job_class="N/A",
                )
                job_listings.append(job)

            logger.info(
                f"Found {len(job_listings)} new jobs out of {len(job_ids)} total listings"
            )
            return job_listings

        except Exception as e:
            logger.error(f"Error searching jobs on LinkedIn: {e}")
            return []

    def login(self):
        """Handle manual login process"""
        if self.is_logged_in:
            logger.info("Already logged in, skipping login")
            return True

        logger.info("Using manual login approach...")

        # Open LinkedIn and wait for manual login
        self.driver.get("https://www.linkedin.com/login")

        # Display instructions to the user
        print("\n=== MANUAL LOGIN REQUIRED ===")
        print("1. A browser window has opened")
        print("2. Please log into your LinkedIn account manually")
        print("3. After successful login, return to this console")
        input("Press Enter once you've logged in to continue...")

        # Check if login was successful
        try:
            if (
                "/feed" in self.driver.current_url
                or "global-nav" in self.driver.page_source
            ):
                logger.info("Manual login successful")
                self.is_logged_in = True
                return True
            else:
                logger.warning(
                    "Could not confirm successful login. Continuing anyway..."
                )
                return False
        except:
            logger.warning("Could not verify login state. Continuing anyway...")
            return False

    def close_modals(self):
        """Find and close any modal popups that might interfere with scraping."""
        try:
            # Look for modal sections
            modals = self.driver.find_elements(
                By.CSS_SELECTOR, "section[aria-modal='true']"
            )

            if modals:
                logger.info(f"Found {len(modals)} modal(s) to close")

                # First try to find close buttons by SVG icon
                close_buttons = self.driver.find_elements(
                    By.CSS_SELECTOR, "svg.artdeco-icon"
                )

                # If no specific SVG close buttons, look for any button within the modal
                if not close_buttons:
                    for modal in modals:
                        buttons = modal.find_elements(By.TAG_NAME, "button")
                        close_buttons.extend(buttons)

                # Try to click each button
                for button in close_buttons:
                    try:
                        # logger.info("Clicking close button on modal")
                        button.click()
                        time.sleep(1)  # Brief pause to let modal close
                    except Exception as e:
                       #logger.warning(f"Failed to click a close button: {e}")
                       continue

                # Check if we still have modals
                remaining = self.driver.find_elements(
                    By.CSS_SELECTOR, "section[aria-modal='true']"
                )
                if remaining:
                    logger.warning(
                        f"Still have {len(remaining)} modal(s) after attempting to close"
                    )

        except Exception as e:
            logger.warning(f"Error while closing modals: {e}")

    def click_show_more_buttons(self):
        """Find and click 'Show more' buttons to expand all content"""
        try:
            # Find all "Show more" buttons
            show_more_buttons = self.driver.find_elements(
                By.CSS_SELECTOR,
                "button.show-more-less-html__button[aria-label='Show more'], "
                "button.show-more-less-button[aria-expanded='false']",
            )

            if show_more_buttons:
                #logger.info(f"Found {len(show_more_buttons)} 'Show more' buttons")
                for button in show_more_buttons:
                    try:
                        #logger.info("Clicking 'Show more' button")
                        button.click()
                        time.sleep(1)  # Wait for content to expand
                    except Exception as e:
                        logger.warning(f"Failed to click 'Show more' button: {e}")
        except Exception as e:
            logger.warning(f"Error handling 'Show more' buttons: {e}")

    def get_job_details(self, job_id: str) -> Optional[Job]:
        job_url = f"{self.base_url}jobs/view/{job_id}/"

        try:
            # Select random user agent
            user_agent = random.choice(USER_AGENTS)
            headers = {"User-Agent": user_agent}

            # Get the page content
            self.driver.get(job_url)
            time.sleep(3)

            # Close any modals
            self.close_modals()

            # Click show more buttons
            self.click_show_more_buttons()

            # Get updated page content after expanding
            soup = BeautifulSoup(self.driver.page_source, "html.parser")

            # Extract job title - multiple possible selectors
            job_title = "N/A"
            title_selectors = [
                "h1.top-card-layout__title",
                "h1.topcard__title",
                "h1.t-24.t-bold.inline",
            ]
            for selector in title_selectors:
                title_element = soup.select_one(selector)
                if title_element:
                    job_title = title_element.get_text(strip=True)
                    break

            # Extract company name
            company_name = "N/A"
            company_selectors = [
                "span.topcard__flavor a",
                "a.topcard__org-name-link",
                "a[data-tracking-control-name='public_jobs_topcard-org-name']",
            ]
            for selector in company_selectors:
                company_element = soup.select_one(selector)
                if company_element:
                    company_name = company_element.get_text(strip=True)
                    break

            # Extract job description
            description = "N/A"
            description_selectors = [
                "div.show-more-less-html__markup",
                "div.jobs-description__content",
                "div.jobs-box__html-content",
            ]
            for selector in description_selectors:
                description_element = soup.select_one(selector)
                if description_element:
                    description = description_element.get_text(
                        separator="\n", strip=True
                    )
                    break

            logger.info(f"Job ID: {str(job_id)}")
            logger.info(f"Company Name: {company_name}")
            logger.info(f"Job Title: {job_title}")

            return Job(
                id=str(job_id),
                internal_id=job_id,
                company_name=company_name,
                name=job_title,
                description=description,
                source="LinkedIn",
            )

        except Exception as e:
            logger.error(f"Error getting job details for {job_id}: {e}")
            return None

    def read_job_description_prompt(self):
        """Read job description prompt from file."""
        prompt_path = "job_scraper/prompt/job_description.txt"
        try:
            with open(prompt_path, "r", encoding="utf-8") as file:
                prompt = file.read()
            return prompt
        except FileNotFoundError:
            logger.error(f"Error: Could not find the prompt file at {prompt_path}")
            return None
        except Exception as e:
            logger.error(f"Error reading prompt file: {str(e)}")
            return None

    def format_job_description_with_gemini(self, text):
        """Format job description as HTML using Gemini API."""
        if not text or not text.strip():
            return "<p>No description available</p>"

        try:
            # Initialize the model
            model = genai.GenerativeModel("gemini-2.0-flash")

            # Create the prompt
            prompt = self.read_job_description_prompt()
            if not prompt:
                return f"<div class='job-description'><p>{text}</p></div>"

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
            logger.error(f"Error calling Gemini API: {str(e)}")
            # Fallback to simple formatting if API call fails
            return f"<div class='job-description'><p>{text}</p></div>"

    def _parse_job_card(
        self, card: BeautifulSoup, job_function: str = None, job_type: str = None
    ) -> Optional[Job]:
        """Parse job information from a job card.

        Args:
            card: BeautifulSoup object for a job card
            job_function: Job function category
            job_type: Job type

        Returns:
            Job object or None if parsing fails
        """
        try:
            # Extract job ID - usually in data attributes or URLs
            job_id = None

            # Try to get job ID from data attribute
            job_id_attr = card.get("data-job-id") or card.get("data-entity-urn")

            if job_id_attr:
                # Extract numeric ID from the attribute value
                job_id_match = re.search(r"(\d+)", job_id_attr)
                job_id = job_id_match.group(1) if job_id_match else None

            # If not found in attribute, try finding it in the URL of the job link
            if not job_id:
                job_link = card.select_one(
                    "a.job-card-container__link"
                ) or card.select_one("a.job-search-card__link")
                if job_link:
                    href = job_link.get("href", "")
                    job_id_match = re.search(r"/jobs/view/(\d+)/", href)
                    job_id = job_id_match.group(1) if job_id_match else None

            if not job_id:
                # As a last resort, try to find any numeric pattern that looks like a job ID
                html_str = str(card)
                job_id_match = re.search(r'jobId[=":]+(\d+)', html_str)
                job_id = job_id_match.group(1) if job_id_match else None

            if not job_id:
                return None

            # Extract job title
            title = "N/A"
            try:
                # Look for various possible title selectors
                title_selectors = [
                    "h3.job-card-list__title",
                    "h3.base-search-card__title",
                    ".job-card-container__link",
                    ".job-search-card__title",
                ]

                for selector in title_selectors:
                    title_element = card.select_one(selector)
                    if title_element:
                        title = self.clean_text(title_element.get_text())
                        break

                if title == "N/A":
                    # Try a broader h3 search if specific selectors failed
                    h3_element = card.find("h3")
                    if h3_element:
                        title = self.clean_text(h3_element.get_text())
            except Exception as e:
                logger.error(f"Error extracting title: {e}")

            # Extract company name
            company_name = "N/A"
            try:
                company_selectors = [
                    ".job-card-container__primary-description",
                    ".base-search-card__subtitle",
                    ".job-search-card__subtitle",
                    "[data-job-hook='company-name']",
                ]

                for selector in company_selectors:
                    company_element = card.select_one(selector)
                    if company_element:
                        company_name = self.clean_text(company_element.get_text())
                        break
            except Exception as e:
                logger.error(f"Error extracting company name: {e}")

            # Extract location
            location = "N/A"
            try:
                location_selectors = [
                    ".job-card-container__metadata-item",
                    ".job-search-card__location",
                    ".base-search-card__metadata",
                ]

                for selector in location_selectors:
                    location_element = card.select_one(selector)
                    if location_element:
                        location = self.clean_text(location_element.get_text())
                        break
            except Exception as e:
                logger.error(f"Error extracting location: {e}")

            # Extract salary information if available
            salary = "N/A"
            try:
                salary_selectors = [
                    ".job-search-card__salary-info",
                    ".base-search-card__metadata-salary",
                    "[data-job-hook='salary-info']",
                ]

                for selector in salary_selectors:
                    salary_element = card.select_one(selector)
                    if salary_element:
                        salary = self.clean_text(salary_element.get_text())
                        break
            except Exception as e:
                logger.error(f"Error extracting salary: {e}")

            # Extract job posting date
            posting_date_text = "N/A"
            date_posted = "N/A"
            try:
                date_selectors = [
                    ".job-search-card__listdate",
                    "time.job-search-card__listdate",
                    ".base-search-card__metadata time",
                    "[data-job-hook='posting-date']",
                ]

                for selector in date_selectors:
                    date_element = card.select_one(selector)
                    if date_element:
                        posting_date_text = self.clean_text(date_element.get_text())

                        # Try to get the datetime attribute
                        datetime_attr = date_element.get("datetime")
                        if datetime_attr:
                            try:
                                date_posted = datetime.fromisoformat(
                                    datetime_attr
                                ).strftime("%Y-%m-%d")
                                break
                            except ValueError:
                                pass

                # If we couldn't get the datetime attribute, try to parse the text
                if date_posted == "N/A" and posting_date_text != "N/A":
                    current_time = datetime.now(pytz.timezone("UTC")).timestamp()

                    # Parse relative date strings
                    if (
                        "day ago" in posting_date_text
                        or "days ago" in posting_date_text
                    ):
                        days = int(re.search(r"(\d+)", posting_date_text).group(1))
                        date_posted = datetime.fromtimestamp(
                            current_time - days * 24 * 60 * 60
                        ).strftime("%Y-%m-%d")
                    elif (
                        "hour ago" in posting_date_text
                        or "hours ago" in posting_date_text
                    ):
                        hours = int(re.search(r"(\d+)", posting_date_text).group(1))
                        date_posted = datetime.fromtimestamp(
                            current_time - hours * 60 * 60
                        ).strftime("%Y-%m-%d")
                    elif (
                        "week ago" in posting_date_text
                        or "weeks ago" in posting_date_text
                    ):
                        weeks = int(re.search(r"(\d+)", posting_date_text).group(1))
                        date_posted = datetime.fromtimestamp(
                            current_time - weeks * 7 * 24 * 60 * 60
                        ).strftime("%Y-%m-%d")
                    elif (
                        "month ago" in posting_date_text
                        or "months ago" in posting_date_text
                    ):
                        months = int(re.search(r"(\d+)", posting_date_text).group(1))
                        date_posted = datetime.fromtimestamp(
                            current_time - months * 30 * 24 * 60 * 60
                        ).strftime("%Y-%m-%d")
                    else:
                        # Try to parse absolute date
                        try:
                            date_posted = datetime.strptime(
                                posting_date_text, "%b %d, %Y"
                            ).strftime("%Y-%m-%d")
                        except ValueError:
                            date_posted = datetime.now(pytz.timezone("UTC")).strftime(
                                "%Y-%m-%d"
                            )
            except Exception as e:
                logger.error(f"Error extracting posting date: {e}")
                date_posted = datetime.now(pytz.timezone("UTC")).strftime("%Y-%m-%d")

            # Create job object
            return Job(
                internal_id=job_id,
                id=job_id,
                name=title,
                company_name=company_name,
                location=location,
                salary_description=salary,
                source="LinkedIn",
                date_scraped=datetime.now(pytz.timezone("UTC")).strftime("%Y-%m-%d"),
                date_posted=date_posted,
                job_class=job_function,
                work_type=job_type,
            )

        except Exception as e:
            logger.error(f"Error parsing job card: {e}")
            return None
