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


# def scrape_job_details_by_internal_id_range(
#     start_id: int, end_id: int, save: bool = False
# ):
#     """Scrape job details for jobs within an internal ID range."""
#     # Initialize database connector
#     db = DatabaseConnector()

#     # Get job IDs from database
#     job_ids = db.get_jobs_by_internal_id_range(start_id, end_id)
#     logger.info(f"Found {len(job_ids)} jobs to scrape details for")

#     # Initialize scraper
#     jobsdb_scraper = JobsdbScraper()

#     # Scrape details for each job
#     for job_id in job_ids:
#         try:
#             logger.info(f"Scraping details for job ID: {job_id}")
#             job_details = jobsdb_scraper.get_job_details(job_id)

#             if job_details and job_details.description:
#                 # Show preview of the description
#                 preview = (
#                     job_details.description[:200] + "..."
#                     if len(job_details.description) > 200
#                     else job_details.description
#                 )
#                 # print(f"\nJob ID: {job_id}")
#                 # print(f"Description preview: {preview}")

#                 if save:
#                     # Ask for confirmation before saving
#                     save_choice = input("\nSave this job description? (y/n): ").lower()
#                     if save_choice == "y":
#                         # Update only the description field
#                         success = db.update_job_description(
#                             job_id, job_details.description
#                         )
#                         if success:
#                             logger.info(f"Saved description for job ID: {job_id}")
#                         else:
#                             logger.error(
#                                 f"Failed to save description for job ID: {job_id}"
#                             )
#                     else:
#                         logger.info(f"Skipped saving description for job ID: {job_id}")
#             else:
#                 logger.warning(f"No description found for job ID: {job_id}")

#         except Exception as e:
#             logger.error(f"Error processing job ID {job_id}: {e}")


def scrape_job_details(
    job_ids: List[int] = None,
    start_id: int = None,
    end_id: int = None,
    quantity: int = None,
    save: bool = False,
):
    """Scrape job details for specified jobs.

    Args:
        job_ids: Specific job IDs to scrape (prioritized if provided)
        start_id: Starting internal ID for range-based scraping
        end_id: Ending internal ID for range-based scraping
        quantity: Number of jobs with null descriptions to scrape
        save: Whether to save the scraped descriptions
    """
    # Initialize database connector
    db = DatabaseConnector()

    # Determine which jobs to scrape
    if job_ids is None:
        if start_id is not None and end_id is not None:
            # Get jobs by internal ID range
            job_ids = db.get_jobs_by_internal_id_range(start_id, end_id)
            logger.info(f"Found {len(job_ids)} jobs in ID range {start_id}-{end_id}")

        elif quantity is not None:
            # Get jobs with null descriptions
            job_ids = db.get_jobs_with_null_description(limit=quantity)
            logger.info(f"Found {len(job_ids)} jobs with null descriptions")

        else:
            logger.error("No job selection criteria provided")
            return

    if not job_ids:
        logger.warning("No jobs found to scrape")
        return

    # Initialize scraper
    jobsdb_scraper = JobsdbScraper()

    # Track success/failure counts
    success_count = 0
    failure_count = 0

    # Scrape details for each job
    for job_id in job_ids:
        try:
            logger.info(f"Scraping details for job ID: {job_id}")
            job_details = jobsdb_scraper.get_job_details(job_id)

            if job_details and job_details.description:
                # Show preview of the description
                preview = (
                    job_details.description[:200] + "..."
                    if len(job_details.description) > 200
                    else job_details.description
                )
                # print(f"\nJob ID: {job_id}")
                # print(f"Description preview: {preview}")

                if save:
                    # Ask for confirmation before saving
                    success = db.update_job_description(job_id, job_details.description)
                    if success:
                        success_count += 1
                        logger.info(f"Saved description {success_count}/{len(job_ids)} for job ID: {job_id}")
                        
                    else:
                        failure_count += 1
                        logger.error(f"Failed to save description {failure_count} for job ID: {job_id}")
                        
                else:
                    # If no save flag, just show the preview
                    logger.info(f"Preview only mode (use --save to update database)")
            else:
                logger.warning(f"No description found for job ID: {job_id}")
                db.update_job_description(job_id, "N/A")
                failure_count += 1

        except Exception as e:
            logger.error(f"Error processing job ID {job_id}: {e}")
            failure_count += 1

    # Log summary
    logger.info(
        f"Scraping complete. Success: {success_count}, Failure: {failure_count}"
    )


def update_job_description(job_id: str, description: str = None):
    """Update job description for a specific job.

    Args:
        job_id: Job ID to update
        description: Optional description text. If None, will scrape it.
    """
    # Initialize database connector and scraper
    db = DatabaseConnector()
    jobsdb_scraper = JobsdbScraper()

    try:
        # If description not provided, scrape it
        if description is None:
            logger.info(f"Scraping description for job ID: {job_id}")
            job_details = jobsdb_scraper.get_job_details(job_id)
            if job_details and job_details.description:
                description = job_details.description
            else:
                logger.error(f"Could not scrape description for job ID: {job_id}")
                return False

        # Update the description in the database
        success = db.update_job_description(job_id, description)
        if success:
            logger.info(f"Successfully updated description for job ID: {job_id}")
            return True
        else:
            logger.error(f"Failed to update description for job ID: {job_id}")
            return False

    except Exception as e:
        logger.error(f"Error updating job description: {e}")
        return False


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

    parser.add_argument(
        "--details",
        action="store_true",
        help="Scrape job details (default: False)",
    )

    parser.add_argument(
        "--quantity",
        type=int,
        default=None,
        help="Number of jobs with NULL descriptions to scrape",
    )

    # Add new arguments for job details scraping
    parser.add_argument(
        "--scrape_details_range",
        action="store_true",
        help="Scrape job details for a range of internal IDs",
    )

    parser.add_argument(
        "--start_id", type=int, help="Starting internal ID for scraping details"
    )

    parser.add_argument(
        "--end_id", type=int, help="Ending internal ID for scraping details"
    )

    # In main() function, add:
    parser.add_argument(
        "--update_description",
        type=str,
        help="Update description for a specific job ID",
    )

    args = parser.parse_args()

    # Initialize database connector if saving is enabled
    db = None
    if args.save:
        db = DatabaseConnector()

    # Then in the main logic:
    if args.update_description:
        update_job_description(args.update_description)
        return

    # Add new condition to handle job details scraping
    # In main() function
    if args.scrape_details_range:
        # Case 1: Range of internal IDs
        if args.start_id is not None and args.end_id is not None:
            scrape_job_details(
                start_id=args.start_id, end_id=args.end_id, save=args.save
            )

        # Case 2: Quantity of jobs with null descriptions
        elif args.quantity is not None:
            scrape_job_details(quantity=args.quantity, save=args.save)

        # Error case: Invalid parameters
        else:
            logger.error(
                "Either provide both --start_id and --end_id OR provide --quantity"
            )

        return

    elif args.source == "all" or args.source == "jobsdb":
        # Set end_page to page if not specified
        if args.end_page is None:
            args.end_page = args.page
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
