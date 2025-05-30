"""Glassdoor job scraper implementation."""

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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from ..base.scraper import BaseScraper
from ..models.job import Company, Job
from selenium import webdriver

logger = logging.getLogger(__name__)
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)

# User agents list for randomization
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
]


class GlassdoorScraper(BaseScraper):
    """Scraper for Glassdoor job listings."""

    def __init__(self, headless=False, db=None, use_profile=True):
        """Initialize the Glassdoor scraper with option to use existing profile.
        
        Args:
            headless (bool): Whether to run browser in headless mode
            db: Database connector instance
            use_profile (bool): Whether to use a persistent Chrome profile
        """
        self.name = "Glassdoor"
        self.base_url = "https://www.glassdoor.com/"
        self.db = db
        self.is_logged_in = False
        self.driver = None
        self._setup_driver(headless, use_profile)

    def _setup_driver(self, headless=False, use_profile=True):
        """Set up the Selenium WebDriver with optional user profile."""
        chrome_options = webdriver.ChromeOptions()
        
        if headless:
            chrome_options.add_argument('--headless')
        
        if use_profile:
            # Create a profile directory if it doesn't exist
            profile_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "user_data", "glassdoor_profile"
            )
            os.makedirs(profile_dir, exist_ok=True)
            
            # Use this directory as the user profile
            chrome_options.add_argument(f'--user-data-dir={profile_dir}')
            
            # Use a specific profile
            chrome_options.add_argument('--profile-directory=Default')
            
            logger.info(f"Using Chrome profile at: {profile_dir}")
        
        # Other necessary options
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--window-size=1920,1080')
        
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
        except Exception as e:
            logger.error(f"Failed to initialize Chrome driver: {e}")
            raise

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
        """Search for jobs on Glassdoor."""
        # Check if logged in if login is required
        if not self.is_logged_in and kwargs.get("require_login", False):
            logger.warning("Not logged in. Please call login() first")
            return []

        page = kwargs.get("page", 1)
        location = kwargs.get("location", "Hong Kong")
        job_title = kwargs.get("job_title", "")
        
        # Construct search URL
        search_url = f"{self.base_url}Job/jobs.htm"
        
        # Base parameters for search
        params = {
            "sc.keyword": job_title,
            "locT": "C",
            "locId": "2308631", # Hong Kong ID, can be parameterized
            "jobType": "",
            "fromAge": "7", # Last 7 days
            "minSalary": "",
            "includeNoSalaryJobs": "true",
            "pgc": f"{page}",
        }

        try:
            # Get the page content
            soup = self.get_soup(search_url, params=params)
            
            # For debugging
            # filename_prefix = f"glassdoor_search_page_{page}"
            # self.save_soup_to_html(soup, filename_prefix)
            
            # Find job listings - adjust selectors based on Glassdoor's HTML structure
            job_cards = soup.select("li.react-job-listing")
            
            # Extract job IDs from the cards
            job_ids = []
            for card in job_cards:
                job_id = card.get("data-id")
                if job_id:
                    job_ids.append(job_id)
            
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
                    continue

                # Create a Job object for new jobs only
                job = Job(
                    id=str(job_id),
                    name="N/A",
                    description="",
                    company_name="N/A",
                    location="N/A",
                    source="Glassdoor",
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
            logger.error(f"Error searching jobs on Glassdoor: {e}")
            return []

    def login(self):
        """Handle login process for Glassdoor using profile."""
        if self.is_logged_in:
            logger.info("Already logged in via profile, skipping login")
            return True
        
        # Check if already logged in via profile
        try:
            self.driver.get(self.base_url)
            time.sleep(3)
            
            # Look for elements that indicate logged-in state
            if "isLoggedIn" in self.driver.page_source or "member_home" in self.driver.current_url:
                logger.info("Already logged in via saved profile")
                self.is_logged_in = True
                return True
        except Exception as e:
            logger.warning(f"Error checking login status: {e}")
        
        # If not logged in, prompt for manual login
        logger.info("Manual login required...")
        self.driver.get(f"{self.base_url}profile/login_input.htm")
        
        print("\n=== MANUAL LOGIN REQUIRED ===")
        print("1. Please log into your Glassdoor account in the browser")
        print("2. Your login will be saved for future sessions")
        print("3. After logging in, return to this console")
        input("Press Enter once you've logged in to continue...")
        
        # Verify login was successful
        try:
            if "isLoggedIn" in self.driver.page_source or "member_home" in self.driver.current_url:
                logger.info("Manual login successful")
                self.is_logged_in = True
                return True
            else:
                logger.warning("Could not confirm successful login")
                return False
        except:
            logger.warning("Could not verify login state")
            return False

    def close_modals(self):
        """Find and close any modal popups that might interfere with scraping."""
        try:
            # Look for common Glassdoor modals
            # Email capture modal
            email_modal_close = self.driver.find_elements(
                By.CSS_SELECTOR, "button[alt='Close'], .modal_closeIcon"
            )
            
            # General modal close buttons
            modal_close_buttons = self.driver.find_elements(
                By.CSS_SELECTOR, ".modal_closeIcon, button.close, button[aria-label='Close']"
            )
            
            # Combine all close buttons
            close_buttons = email_modal_close + modal_close_buttons
            
            if close_buttons:
                logger.info(f"Found {len(close_buttons)} modal(s) to close")
                
                # Try to click each button
                for button in close_buttons:
                    try:
                        button.click()
                        time.sleep(1)  # Brief pause to let modal close
                    except Exception as e:
                        continue
                        
        except Exception as e:
            logger.warning(f"Error while closing modals: {e}")

    def click_show_more_buttons(self):
        """Find and click 'Show more' buttons to expand all content"""
        try:
            # Find all "Show more" buttons - adjust selectors for Glassdoor
            show_more_buttons = self.driver.find_elements(
                By.CSS_SELECTOR,
                "button.css-1r0x7ej, .showMore, .more"
            )

            if show_more_buttons:
                for button in show_more_buttons:
                    try:
                        button.click()
                        time.sleep(1)  # Wait for content to expand
                    except Exception as e:
                        logger.warning(f"Failed to click 'Show more' button: {e}")
        except Exception as e:
            logger.warning(f"Error handling 'Show more' buttons: {e}")

    def get_job_details(self, job_id: str) -> Optional[Job]:
        """Get detailed job information from Glassdoor."""
        job_url = f"{self.base_url}job-listing/job.htm?jl={job_id}"
        
        try:
            # Navigate to job page
            self.driver.get(job_url)
            time.sleep(3)  # Wait for page to load
            
            # Close any modals that might appear
            self.close_modals()
            
            # Expand job description if needed
            self.click_show_more_buttons()
            
            # Get page content
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            
            # Extract job details
            job_title_elem = soup.select_one(".css-1vg6q84, .jobTitle")
            company_elem = soup.select_one(".css-87uc0g, .employerName")
            location_elem = soup.select_one(".css-56kyx5, .location")
            salary_elem = soup.select_one(".css-1xe2xww, .salary")
            description_elem = soup.select_one(".jobDescriptionContent, .desc")
            
            # Extract text from elements
            job_title = job_title_elem.text.strip() if job_title_elem else "N/A"
            company_name = company_elem.text.strip() if company_elem else "N/A"
            location = location_elem.text.strip() if location_elem else "N/A"
            salary = salary_elem.text.strip() if salary_elem else "N/A"
            description = description_elem.get_text("\n").strip() if description_elem else ""
            
            # Format the description with Gemini if available
            if description and api_key:
                description = self.format_job_description_with_gemini(description)
            
            # Create and return Job object
            job = Job(
                id=str(job_id),
                name=job_title,
                description=description,
                company_name=company_name,
                location=location,
                source="Glassdoor",
                date_scraped=datetime.now(pytz.timezone("Asia/Hong_Kong")).strftime(
                    "%Y-%m-%d"
                ),
                salary_description=salary,
                job_class="N/A",  # Can be enhanced with classification logic
            )
            
            return job
            
        except Exception as e:
            logger.error(f"Error getting job details from Glassdoor: {e}")
            return None

    def read_job_description_prompt(self):
        """Read the prompt template for job description formatting."""
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "prompts",
            "job_description.txt",
        )
        
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading prompt template: {e}")
            return "Format the following job description in a clean, structured way:"

    def format_job_description_with_gemini(self, text):
        """Format job description using Google's Gemini API."""
        try:
            # Get prompt template
            prompt_template = self.read_job_description_prompt()
            
            # Create the full prompt with the job description
            prompt = f"{prompt_template}\n\n{text}"
            
            # Call Gemini API
            model = genai.GenerativeModel('gemini-1.0-pro')
            response = model.generate_content(prompt)
            
            # Extract and return the formatted text
            if response and hasattr(response, "text"):
                return response.text
            else:
                logger.warning("Received empty response from Gemini API")
                return text
                
        except Exception as e:
            logger.error(f"Error formatting job description with Gemini: {e}")
            return text  # Return original text if formatting fails

    def _parse_job_card(
        self, card: BeautifulSoup, job_function: str = None, job_type: str = None
    ) -> Optional[Job]:
        """Parse a job card element to extract basic job information.
        
        Args:
            card: BeautifulSoup object representing a job card
            job_function: Optional job function category
            job_type: Optional job type (e.g., full-time, contract)
            
        Returns:
            Job object with basic information or None if parsing fails
        """
        try:
            # Extract job ID
            job_id = card.get("data-id")
            if not job_id:
                return None
                
            # Extract job title
            title_elem = card.select_one(".jobTitle")
            job_title = title_elem.text.strip() if title_elem else "N/A"
            
            # Extract company name
            company_elem = card.select_one(".employer")
            company_name = company_elem.text.strip() if company_elem else "N/A"
            
            # Extract location
            location_elem = card.select_one(".location")
            location = location_elem.text.strip() if location_elem else "N/A"
            
            # Extract salary if available
            salary_elem = card.select_one(".salary")
            salary = salary_elem.text.strip() if salary_elem else "N/A"
            
            # Create Job object
            job = Job(
                id=str(job_id),
                name=job_title,
                company_name=company_name,
                location=location,
                source="Glassdoor",
                date_scraped=datetime.now(pytz.timezone("Asia/Hong_Kong")).strftime(
                    "%Y-%m-%d"
                ),
                salary_description=salary,
                job_class=job_function if job_function else "N/A",
                work_type=job_type if job_type else "N/A",
            )
            
            return job
            
        except Exception as e:
            logger.error(f"Error parsing job card: {e}")
            return None