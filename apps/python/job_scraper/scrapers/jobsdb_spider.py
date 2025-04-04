"""JobsDB Scrapy spider."""

import logging
import scrapy
from scrapy import Request
from ..models.job import Company, Job
from datetime import datetime

logger = logging.getLogger(__name__)

class JobsDBSpider(scrapy.Spider):
    name = "jobsdb"
    allowed_domains = ["hk.jobsdb.com"]
    
    def __init__(self, job_category="software", sortmode="listed_date", job_type=None, page=1, *args, **kwargs):
        super(JobsDBSpider, self).__init__(*args, **kwargs)
        self.job_category = job_category
        self.sortmode = sortmode
        self.job_type = job_type
        self.page = page
        
        # Map parameters to URL format
        categories = {
            "software": "information-communication-technology",
            "finance": "accounting-finance",
        }
        
        sortmodes = {"listed_date": "ListedDate", "relevance": "KeywordRelevance"}
        
        job_types = {
            "full_time": "full-time",
            "part_time": "part-time",
            "contract": "contract-temp",
            "casual": "casual-vacation",
        }
        
        # Build the start URL
        self.category_path = categories.get(job_category, "information-communication-technology")
        self.sortmode_value = sortmodes.get(sortmode, "ListedDate")
        
        base_url = "https://hk.jobsdb.com/"
        url_path = f"jobs-in-{self.category_path}"
        
        if job_type and job_type in job_types:
            url_path += f"/{job_types[job_type]}"
        
        self.start_urls = [f"{base_url}{url_path}?sortmode={self.sortmode_value}&page={page}"]
        
    def parse(self, response):
        # Parse job listings
        job_cards = response.css(".jobsearch-ResultsList .result")
        
        for card in job_cards:
            job_id = card.css("[data-jk]::attr(data-jk)").get()
            
            if not job_id:
                continue
                
            title = self.clean_text(card.css(".jobTitle span::text").get() or "Unknown Title")
            company_name = self.clean_text(card.css(".companyName::text").get() or "Unknown Company")
            location = self.clean_text(card.css(".companyLocation::text").get() or "Unknown Location")
            job_url = f"https://hk.jobsdb.com/viewjob?jk={job_id}"
            
            yield {
                "id": job_id,
                "title": title,
                "company": {"name": company_name},
                "location": location,
                "url": job_url,
                "source": "Jobsdb",
                "source_id": job_id,
                "date_scraped": datetime.utcnow().isoformat()
            }
            
        # Follow pagination if needed
        next_page = response.css("a.next-page::attr(href)").get()
        if next_page:
            yield Request(response.urljoin(next_page), callback=self.parse)
    
    def clean_text(self, text):
        """Clean and normalize text."""
        if not text:
            return ""
        
        # Remove extra whitespace
        return " ".join(text.strip().split())