"""JobsDB Scrapy spider implementation."""

import logging
from datetime import datetime

import scrapy
from scrapy.http import Response

from job_scraper.models.job import Job  # Import your updated Job model


class JobsDBSpider(scrapy.Spider):
    """Scrapy spider for JobsDB job listings."""
    
    name = "jobsdb"
    allowed_domains = ["jobsdb.com"]
    
    def __init__(self, query=None, location=None, *args, **kwargs):
        """Initialize the spider with search parameters.
        
        Args:
            query: Job search query (e.g., "software engineer")
            location: Job location (e.g., "Hong Kong")
        """
        super(JobsDBSpider, self).__init__(*args, **kwargs)
        self.query = query
        self.location = location
        
        # Build start URL
        self.start_urls = [
            f"https://hk.jobsdb.com/hk/search-jobs/{query}/{location}"
        ]
    
    def parse(self, response):
        """Parse the search results page.
        
        Args:
            response: Scrapy response object
        
        Yields:
            Request objects for job detail pages
        """
        # Update these selectors based on actual JobsDB HTML structure
        job_links = response.css("a.job-card-link::attr(href)").getall()
        
        for link in job_links:
            # Follow the link to the job detail page
            yield response.follow(link, callback=self.parse_job)
        
        # Follow pagination if needed
        next_page = response.css("a.pagination-next::attr(href)").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)
    
    def parse_job(self, response):
        """Parse a job detail page.
        
        Args:
            response: Scrapy response object
        
        Yields:
            Job item with details
        """
        # Update these selectors based on actual JobsDB HTML structure
        job_title = self.clean_text(response.css(".job-title::text").get())
        company_name = self.clean_text(response.css(".company-name::text").get())
        location = self.clean_text(response.css(".job-location::text").get())
        
        # Get the full description
        description = " ".join([
            self.clean_text(text)
            for text in response.css(".job-description ::text").getall()
        ])
        
        # Extract work type if available
        work_type = self.clean_text(response.css(".job-type::text").get())
        
        # Extract salary if available
        salary_description = self.clean_text(response.css(".salary::text").get())
        
        # Extract posting date if available
        date_posted = self.clean_text(response.css(".posted-date::text").get())

        # current HK date and time in timestamp format
        current_time = datetime.now(datetime.timezone.utc).timestamp()
        # if date_posted contains "d ago", then calculate the timestamp
        if "d ago" in date_posted:
            date_posted = current_time - int(date_posted.split("d ago")[0]) * 24 * 60 * 60
        elif "h ago" in date_posted:
            date_posted = current_time - int(date_posted.split("h ago")[0]) * 60 * 60
        elif "m ago" in date_posted:
            date_posted = current_time - int(date_posted.split("m ago")[0]) * 60
        else:
            date_posted = current_time
        
        # Create a Job object with the updated schema
        job = Job(
            name=job_title,  # Changed from title to name
            description=description,
            company_name=company_name,  # Changed from nested company object
            location=location,
            work_type=work_type,
            salary_description=salary_description,  # Changed from salary_min/max to salary_description
            date_posted=datetime.fromtimestamp(date_posted).strftime("%Y-%m-%d"),
            date_scraped=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            source="JobsDB",
            # Fields added to match the schema
            other=None,
            remark=None,
            job_class=None,
            job_subclass=None
        )
        
        # Yield the job for pipeline processing
        yield job.dict()
    
    def clean_text(self, text):
        """Clean and normalize text.
        
        Args:
            text: Text to clean
            
        Returns:
            Cleaned text
        """
        if not text:
            return None
            
        # Remove extra whitespace
        return " ".join(text.strip().split())