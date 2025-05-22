"""Command-line interface for running job scrapers."""

import argparse
import logging
import sys
import math
import os
import tempfile
import json
import random
import time
import threading
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor
from .db.connector import DatabaseConnector
from .scrapers.jobsdb import JobsdbScraper
from .scrapers.linkedin import LinkedinScraper
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


def process_job_batch(job_batch, worker_id, total_workers, save=False):
    """Process a batch of jobs with a dedicated worker.

    Args:
        job_batch: List of job IDs to process
        worker_id: ID of this worker (for logging)
        total_workers: Total number of workers running
        save: Whether to save results to database

    Returns:
        Tuple of (success_count, failure_count)
    """
    thread_id = threading.get_ident()
    log_prefix = f"[Worker-{worker_id}/{total_workers} Thread-{thread_id}]"

    logger.info(
        f"{log_prefix} Starting batch processing of {len(job_batch)} jobs")

    db = DatabaseConnector()
    scraper = JobsdbScraper()

    success_count = 0
    failure_count = 0

    for idx, job_id in enumerate(job_batch):
        try:
            # Add random delay to avoid rate limiting
            delay = random.uniform(1.0, 3.0)
            logger.debug(
                f"{log_prefix} Job {job_id} sleeping for {delay:.2f} seconds")
            time.sleep(delay)

            # Replace the existing logging line (around line 128) with this:
            if (idx + 1) % 50 == 0 or idx == 0 or idx == len(job_batch) - 1:
                logger.info(
                    f"{log_prefix} Processing job {idx+1}/{len(job_batch)}:{job_id} (Success: {success_count}, Failure: {failure_count})"
                )
            job_details = scraper.get_job_details(job_id)

            if (
                job_details
                and job_details.description
                and job_details.description != "N/A"
            ):
                if save:
                    success = db.update_job_description(
                        job_id, job_details.description)
                    if success:
                        success_count += 1
                    else:
                        failure_count += 1
                else:
                    # Preview mode
                    success_count += 1
                    logger.info(
                        f"{log_prefix} ({idx+1}/{len(job_batch)}) Job {job_id} description found (preview mode)"
                    )
            else:
                logger.warning(
                    f"{log_prefix} ({idx+1}/{len(job_batch)}) Job {job_id} no valid description found"
                )
                if save:
                    db.update_job_description(job_id, "N/A")
                failure_count += 1

        except Exception as e:
            failure_count += 1
            logger.error(
                f"{log_prefix} ({idx+1}/{len(job_batch)}) Job {job_id} failed: {e}"
            )
            if save:
                try:
                    db.update_job_description(
                        job_id, f"Error: {type(e).__name__}")
                except Exception:
                    pass

    logger.info(
        f"{log_prefix} Completed batch. Success: {success_count}, Failure: {failure_count}"
    )
    return success_count, failure_count


def scrape_job_details(
    job_ids: Optional[List[int]] = None,
    start_id: Optional[int] = None,
    end_id: Optional[int] = None,
    quantity: Optional[int] = None,
    save: bool = False,
    max_workers: int = 5,
):
    """Parallel scrape with evenly distributed workload per worker."""
    db = DatabaseConnector()

    # Determine job_ids if not provided
    if not job_ids:
        if start_id is not None and end_id is not None:
            job_ids = db.get_jobs_by_internal_id_range(start_id, end_id)
            logger.info(
                f"Found {len(job_ids)} job IDs in range {start_id}-{end_id} to scrape."
            )
        elif quantity is not None:
            job_ids = db.get_jobs_with_null_description(limit=quantity)
            logger.info(
                f"Found {len(job_ids)} jobs with null descriptions to scrape.")
        else:
            default_quantity = 100
            job_ids = db.get_jobs_with_null_description(limit=default_quantity)
            logger.info(
                f"Found {len(job_ids)} jobs with null descriptions (default limit: {default_quantity})."
            )

    if not job_ids:
        logger.warning(
            "No job IDs found matching the criteria to scrape details for.")
        return

    # Adjust worker count if fewer jobs than workers
    max_workers = min(max_workers, len(job_ids))

    # Calculate batch size (with ceiling division to ensure all jobs are covered)
    batch_size = math.ceil(len(job_ids) / max_workers)

    # Split jobs into equal-sized batches (last batch may be smaller)
    job_batches = [
        job_ids[i: i + batch_size] for i in range(0, len(job_ids), batch_size)
    ]

    logger.info(
        f"Starting detail scraping with {max_workers} workers. Each worker will process ~{batch_size} jobs."
    )
    logger.info(f"Total jobs: {len(job_ids)}, Save mode: {save}")

    # Create and start workers
    total_success = 0
    total_failure = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Create a future for each batch with its worker ID
        futures = []
        for worker_id, batch in enumerate(job_batches, 1):
            future = executor.submit(
                process_job_batch,
                job_batch=batch,
                worker_id=worker_id,
                total_workers=len(job_batches),
                save=save,
            )
            futures.append(future)

        # Collect results as they complete
        for future in futures:
            success, failure = future.result()
            total_success += success
            total_failure += failure

    # Log final summary
    logger.info(
        f"All workers completed. Total processed: {total_success + total_failure}."
    )
    logger.info(
        f"Final Stats -> Success: {total_success}, Failure: {total_failure}")


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
        # Update the description in the database
        success = db.update_job_description(job_id, description)
        if success:
            logger.info(
                f"Successfully updated description for job ID: {job_id}")
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
    elif args.source == "linkedin":
        # Set end_page to page if not specified
        if args.end_page is None:
            args.end_page = args.page
        total_jobs = 0

        # Loop through pages from start to end
        for current_page in range(args.start_page, args.end_page + 1):
            logger.info(f"Scraping page {current_page} of {args.end_page}")

            # Use Selenium-based scraper
            linkedin_scraper = LinkedinScraper()
            linkedin_jobs = linkedin_scraper.search_jobs(
                page=current_page,
            )

            logger.info(
                f"Found {len(linkedin_jobs)} jobs on Jobsdb (page {current_page})"
            )
            total_jobs += len(linkedin_jobs)

            # Save to database if enabled
            if args.save and db and linkedin_jobs:
                logger.info(
                    f"Saving {len(linkedin_jobs)} jobs from page {current_page} to database"
                )
                saved_count = db.save_jobs(linkedin_jobs)
                logger.info(
                    f"Saved {saved_count} jobs from page {current_page} to database"
                )

        logger.info(
            f"Total jobs found across pages {args.start_page} to {args.end_page}: {total_jobs}"
        )

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
