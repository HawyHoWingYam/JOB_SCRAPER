"""Command-line interface for running job scrapers."""

import argparse
import logging
import sys
from typing import List

from .db.connector import DatabaseConnector

# from .scrapers.indeed import IndeedScraper
from .scrapers.jobsdb import JobsdbScraper
import os
import tempfile
import json
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from .scrapers.jobsdb_spider import JobsDBSpider
from .models.job import Company, Job
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


def run_jobsdb_spider(job_category=None, job_type=None, sortmode="listed_date", page=1):
    """Run JobsDB spider and return the results as Job objects.

    Args:
        job_category: Category to search in (e.g., "software")
        job_type: Type of job (default: None)
        sortmode: Sorting method (default: "listed_date")
        page: Page number (default: 1)

    Returns:
        List of Job objects
    """
    # Create a temporary file to store the results
    output_file = tempfile.mktemp(suffix=".json")

    # Configure Scrapy settings
    settings = get_project_settings()
    settings.update(
        {
            "FEED_FORMAT": "json",
            "FEED_URI": f"file://{output_file}",
            "LOG_LEVEL": "INFO",
        }
    )

    # Initialize the Scrapy process
    process = CrawlerProcess(settings)

    # Start the spider
    process.crawl(
        JobsDBSpider,
        job_category=job_category,
        job_type=job_type,
        sortmode=sortmode,
        page=page,
    )

    # Run the spider and wait for it to finish
    process.start()

    # Read the results from the temporary file
    jobs = []
    if os.path.exists(output_file):
        with open(output_file, "r") as f:
            items = json.load(f)

        # Convert spider output to Job objects
        for item in items:
            job = Job(
                id=item["id"],
                name=item["title"],
                description="",  # Empty description for search results
                company_name=Company(name=item["company"]["name"]),
                location=item["location"],
                source="Jobsdb",
                date_scraped=datetime.fromisoformat(item["date_scraped"]),
                # date_posted=item["date_posted"],
                # work_type=item["work_type"],
                salary_description=item["salary_description"],
                job_class=item["job_class"],
                # job_class_id=item["job_class_id"],
                # job_subclass=item["job_subclass"],
                # job_subclass_id=item["job_subclass_id"],
                # other=item["other"],
                # remark=item["remark"]
            )
            jobs.append(job)

        # Clean up the temporary file
        os.remove(output_file)

    return jobs


def main():
    """Run the CLI application."""
    parser = argparse.ArgumentParser(description="Job Scraper CLI")

    parser.add_argument(
        "--source",
        choices=["jobsdb", "all"],
        default="all",
        help="Job source to scrape (default: all)",
    )

    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Job search query (e.g., 'software engineer')",
    )

    parser.add_argument(
        "--location",
        type=str,
        default=None,
        help="Job location (e.g., 'New York, NY')",
    )

    parser.add_argument(
        "--start_page",
        type=int,
        default=1,
        help="Page number to scrape (default: 1)",
    )

    parser.add_argument(
        "--end_page",
        type=int,
        default=None,
        help="End page number to scrape (default: same as page)",
    )

    parser.add_argument(
        "--sortmode",
        choices=["listed_date", "relevance"],
        default="listed_date",
        help="Sorting mode (default: listed_date)",
    )

    parser.add_argument(
        "--job_type",
        choices=["full_time", "part_time", "contract", "casual"],
        default=None,
        help="Job type to filter by (default: None)",
    )

    parser.add_argument(
        "--job_category",
        choices=["software", "finance"],
        default=None,
        help="Job category to filter by (default: None)",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Maximum number of jobs to scrape per source (default: 25)",
    )

    parser.add_argument(
        "--save", action="store_true", help="Save scraped jobs to database"
    )

    # Add a new argument for the scraping method
    parser.add_argument(
        "--method",
        choices=["selenium", "scrapy"],
        default="selenium",
        help="Scraping method to use (default: selenium)",
    )

    args = parser.parse_args()

    # Initialize database connector if saving is enabled
    db = None
    if args.save:
        db = DatabaseConnector()

    # Set end_page to page if not specified
    if args.end_page is None:
        args.end_page = args.page

    # Run appropriate scrapers
    if args.source == "all" or args.source == "jobsdb":
        total_jobs = 0

        # Loop through pages from start to end
        for current_page in range(args.start_page, args.end_page + 1):
            logger.info(f"Scraping page {current_page} of {args.end_page}")

            if args.method == "scrapy":
                # Use Scrapy spider
                jobsdb_jobs = run_jobsdb_spider(
                    job_category=args.job_category,
                    job_type=args.job_type,
                    sortmode=args.sortmode,
                    page=current_page,
                )
            else:
                # Use Selenium-based scraper
                jobsdb_scraper = JobsdbScraper()
                jobsdb_jobs = jobsdb_scraper.search_jobs(
                    job_category=args.job_category,
                    job_type=args.job_type,
                    sortmode=args.sortmode,
                    page=current_page,
                )

            logger.info(
                f"Found {len(jobsdb_jobs)} jobs on Jobsdb (page {current_page})"
            )
            total_jobs += len(jobsdb_jobs)

            # Save to database if enabled
            if args.save and db and jobsdb_jobs:
                logger.info(
                    f"Saving {len(jobsdb_jobs)} jobs from page {current_page} to database"
                )
                saved_count = db.save_jobs(jobsdb_jobs)
                logger.info(
                    f"Saved {saved_count} jobs from page {current_page} to database"
                )

        logger.info(
            f"Total jobs found across pages {args.start_page} to {args.end_page}: {total_jobs}"
        )

        # Print job titles
        # for i, job in enumerate(jobsdb_jobs, 1):
        #     print(f"{i}. {job}")


if __name__ == "__main__":
    main()
