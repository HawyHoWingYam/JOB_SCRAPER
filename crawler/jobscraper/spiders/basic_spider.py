import scrapy
from datetime import datetime

class BasicJobSpider(scrapy.Spider):
    name = 'basic_jobs'
    
    def start_requests(self):
        urls = [
            'https://example-job-site.com/jobs',  # Replace with actual job site
        ]
        for url in urls:
            yield scrapy.Request(url=url, callback=self.parse)

    def parse(self, response):
        # Basic extraction logic - adapt to your target site
        job_listings = response.css('div.job-listing')
        
        for job in job_listings:
            yield {
                'title': job.css('h2.title::text').get(),
                'company': job.css('span.company::text').get(),
                'location': job.css('span.location::text').get(),
                'description': job.css('div.description::text').get(),
                'url': job.css('a.job-link::attr(href)').get(),
                'scraped_at': datetime.now().isoformat(),
            }

        # Follow pagination if available
        next_page = response.css('a.next-page::attr(href)').get()
        if next_page:
            yield response.follow(next_page, self.parse)