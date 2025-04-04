"""Indeed job scraper implementation."""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from base.scraper import BaseScraper
from models.job import Company, Job

logger = logging.getLogger(__name__)


class IndeedScraper(BaseScraper):
    """Scraper for Indeed job listings."""
    
    def __init__(self):
        """Initialize the Indeed scraper."""
        super().__init__(name="Indeed", base_url="https://www.indeed.com")
    
    def search_jobs(self, query: str, location: str, **kwargs) -> List[Job]:
        """Search for jobs on Indeed.
        
        Args:
            query: Job search query (e.g., "software engineer")
            location: Job location (e.g., "New York, NY")
            **kwargs: Additional search parameters
                - limit: Maximum number of jobs to return (default: 25)
                - radius: Search radius in miles (default: 25)
                - sort: Sort order (default: "relevance")
            
        Returns:
            List of Job objects
        """
        limit = kwargs.get("limit", 25)
        radius = kwargs.get("radius", 25)
        sort = kwargs.get("sort", "relevance")
        
        # Indeed search URL parameters
        params = {
            "q": query,
            "l": location,
            "radius": radius,
            "sort": sort,
            "limit": limit,
        }
        
        search_url = f"{self.base_url}/jobs"
        
        try:
            soup = self.get_soup(search_url, params=params)
            job_listings = []
            
            # Find and parse job cards
            job_cards = soup.select(".jobsearch-ResultsList .result")
            
            for card in job_cards[:limit]:
                try:
                    job = self._parse_job_card(card)
                    if job:
                        job_listings.append(job)
                except Exception as e:
                    logger.error(f"Error parsing job card: {e}")
            
            self.log_scraping_stats(
                jobs_found=len(job_listings),
                search_params={"query": query, "location": location}
            )
            
            return job_listings
        
        except Exception as e:
            logger.error(f"Error searching jobs on Indeed: {e}")
            return []
    
    def get_job_details(self, job_id: str) -> Optional[Job]:
        """Get detailed information for a specific job.
        
        Args:
            job_id: Indeed job ID
            
        Returns:
            Job object with detailed information or None if not found
        """
        job_url = f"{self.base_url}/viewjob?jk={job_id}"
        
        try:
            soup = self.get_soup(job_url)
            
            # Extract full job description
            description_element = soup.select_one("#jobDescriptionText")
            full_description = description_element.get_text() if description_element else ""
            
            # Parse other job details (company, location, salary, etc.)
            # This would require more detailed parsing logic for Indeed
            
            # For now, create a minimal job object
            company_name = self._extract_company_name(soup)
            
            return Job(
                id=job_id,
                title=self._extract_job_title(soup),
                description=full_description,
                url=job_url,
                company=Company(name=company_name),
                location=self._extract_location(soup),
                source="Indeed",
                source_id=job_id,
                date_scraped=datetime.utcnow()
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
            # Extract job ID
            job_id_element = card.select_one("[data-jk]")
            job_id = job_id_element.get("data-jk") if job_id_element else None
            
            if not job_id:
                return None
            
            # Extract job title
            title_element = card.select_one(".jobTitle span")
            title = self.clean_text(title_element.get_text()) if title_element else "Unknown Title"
            
            # Extract company name
            company_element = card.select_one(".companyName")
            company_name = self.clean_text(company_element.get_text()) if company_element else "Unknown Company"
            
            # Extract location
            location_element = card.select_one(".companyLocation")
            location = self.clean_text(location_element.get_text()) if location_element else "Unknown Location"
            
            # Extract job URL
            job_url = f"{self.base_url}/viewjob?jk={job_id}"
            
            # Create job object
            return Job(
                id=job_id,
                title=title,
                description="",  # Empty description for search results
                url=job_url,
                company=Company(name=company_name),
                location=location,
                source="Indeed",
                source_id=job_id,
                date_scraped=datetime.utcnow()
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
        return self.clean_text(title_element.get_text()) if title_element else "Unknown Title"
    
    def _extract_company_name(self, soup: BeautifulSoup) -> str:
        """Extract company name from job details page.
        
        Args:
            soup: BeautifulSoup object for job details page
            
        Returns:
            Company name or default text if not found
        """
        company_element = soup.select_one(".jobsearch-InlineCompanyName")
        return self.clean_text(company_element.get_text()) if company_element else "Unknown Company"
    
    def _extract_location(self, soup: BeautifulSoup) -> str:
        """Extract job location from job details page.
        
        Args:
            soup: BeautifulSoup object for job details page
            
        Returns:
            Job location or default text if not found
        """
        location_element = soup.select_one(".jobsearch-JobInfoHeader-subtitle .jobsearch-JobInfoHeader-locationText")
        return self.clean_text(location_element.get_text()) if location_element else "Unknown Location"