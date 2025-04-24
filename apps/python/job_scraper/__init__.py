"""Command-line interface for running job scrapers."""

import argparse
import logging
import sys
import time
import random
import threading
from .db.connector import DatabaseConnector
from .scrapers.jobsdb import JobsdbScraper
import os
import tempfile
import json
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from .scrapers.jobsdb_spider import JobsDBSpider
from .models.job import Company, Job
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)
logging.getLogger("WDM").setLevel(logging.WARNING)


def _worker_scrape(job_id: int, save: bool) -> bool:
    """Scrape details for one job and optionally save; return True on success."""
    thread_id = threading.get_ident()  # Get current thread ID
    log_prefix = f"[Thread-{thread_id} Job-{job_id}]"  # Create a log prefix

    db = (
        DatabaseConnector()
    )  # Consider if DB connection pooling is needed for many workers
    scraper = JobsdbScraper()  # Instantiated per call, might be okay
    try:
        # --- Add random delay ---
        delay = random.uniform(1.0, 3.0)
        logger.debug(f"{log_prefix} Sleeping for {delay:.2f} seconds")
        time.sleep(delay)
        # --- End delay ---

        logger.debug(f"{log_prefix} Requesting details")
        details = scraper.get_job_details(job_id)

        if details and details.description and details.description != "N/A":
            logger.debug(f"{log_prefix} Found description.")
            if save:
                logger.debug(f"{log_prefix} Attempting to save description.")
                success = db.update_job_description(job_id, details.description)
                if success:
                    logger.debug(f"{log_prefix} Save successful.")
                    return True
                else:
                    logger.error(f"{log_prefix} Failed to save description to DB.")
                    return False
            else:
                logger.debug(
                    f"{log_prefix} Preview mode, description found but not saving."
                )
                return True  # Preview successful if description found

        elif details:  # Description was None or "N/A"
            logger.warning(f"{log_prefix} Scraped empty/NA description.")
            if save:
                logger.debug(f"{log_prefix} Saving 'N/A' as description.")
                db.update_job_description(job_id, "N/A")  # Save N/A placeholder
            return False  # Indicate failure as no valid description was found/saved
        else:  # details was None (scraping failed)
            ## logger.warning(f"{log_prefix} scraper.get_job_details returned None.")
            if save:
                logger.debug(
                    f"{log_prefix} Saving 'Error: Scrape Failed' as description."
                )
                db.update_job_description(
                    job_id, "Error: Scrape Failed"
                )  # Indicate scrape error
            return False  # Indicate failure

    except Exception as e:
        logger.error(
            f"{log_prefix} Unexpected error: {e}", exc_info=True
        )  # Log exception details
        # Optionally, update DB with error status if saving
        if save:
            try:  # Nested try/except for DB update during error handling
                db.update_job_description(job_id, f"Error: {type(e).__name__}")
                logger.debug(f"{log_prefix} Saved error status to DB.")
            except Exception as db_err:
                logger.error(
                    f"{log_prefix} Failed to save error status to DB: {db_err}"
                )
        return False


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
            # Ensure company is handled correctly
            company_data = item.get("company", {})
            company_name_str = (
                company_data.get("name", "Unknown Company")
                if isinstance(company_data, dict)
                else str(company_data)
            )

            # Convert date string if it exists
            date_scraped_obj = None
            if item.get("date_scraped"):
                try:
                    date_scraped_obj = datetime.fromisoformat(item["date_scraped"])
                except ValueError:
                    logger.warning(
                        f"Could not parse date_scraped: {item['date_scraped']}"
                    )
                    date_scraped_obj = datetime.utcnow()  # Fallback

            job = Job(
                id=item.get("id"),
                name=item.get("title", "Unknown Title"),
                description="",  # Empty description for search results
                company_name=company_name_str,  # Use extracted string
                location=item.get("location", "Unknown Location"),
                source="Jobsdb",
                date_scraped=date_scraped_obj,
                # date_posted=item.get("date_posted"), # Uncomment if available
                # work_type=item.get("work_type"), # Uncomment if available
                salary_description=item.get("salary_description", "N/A"),
                job_class=item.get("job_class", "N/A"),
                # job_class_id=item.get("job_class_id"), # Uncomment if available
                # job_subclass=item.get("job_subclass"), # Uncomment if available
                # job_subclass_id=item.get("job_subclass_id"), # Uncomment if available
                # other=item.get("other"), # Uncomment if available
                # remark=item.get("remark") # Uncomment if available
            )
            # Validate essential fields before appending
            if job.id and job.name:
                jobs.append(job)
            else:
                logger.warning(f"Skipping job item due to missing ID or Title: {item}")

        # Clean up the temporary file
        os.remove(output_file)

    return jobs


def scrape_job_details(
    job_ids: Optional[List[int]] = None,
    start_id: Optional[int] = None,
    end_id: Optional[int] = None,
    quantity: Optional[int] = None,
    save: bool = False,
    max_workers: int = 5,
):
    """Parallel scrape with ThreadPoolExecutor."""
    db = DatabaseConnector()
    # Determine job_ids if not provided
    if not job_ids:
        if start_id is not None and end_id is not None:
            # Fetch IDs by internal_id range if start/end IDs are provided
            job_ids = db.get_jobs_by_internal_id_range(start_id, end_id)
            logger.info(
                f"Found {len(job_ids)} job IDs in range {start_id}-{end_id} to scrape."
            )
        elif quantity is not None:
            # Fetch IDs with null description if quantity is provided
            job_ids = db.get_jobs_with_null_description(limit=quantity)
            logger.info(f"Found {len(job_ids)} jobs with null descriptions to scrape.")
        else:
            # Default: fetch jobs with null descriptions (limit to a reasonable number if quantity not set)
            default_quantity = 100  # Example default
            job_ids = db.get_jobs_with_null_description(
                limit=quantity if quantity is not None else default_quantity
            )
            logger.info(
                f"Found {len(job_ids)} jobs with null descriptions (default limit: {default_quantity if quantity is None else quantity})"
            )

    if not job_ids:
        logger.warning("No job IDs found matching the criteria to scrape details for.")
        return

    logger.info(
        f"Starting detail scraping for {len(job_ids)} job IDs with {max_workers} workers (Save mode: {save})."
    )

    success = failure = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Create futures mapping back to job IDs
        futures = {executor.submit(_worker_scrape, jid, save): jid for jid in job_ids}

        # Process completed futures
        for fut in as_completed(futures):
            jid = futures[fut]
            processed_count = success + failure + 1  # Current job being processed
            try:
                ok = fut.result()  # Get result (True/False) from worker future
                if ok:
                    success += 1
                    # Optional: Log success less frequently to reduce noise
                    # if success % 10 == 0:
                    #    logger.debug(f"Job {jid} succeeded.")
                else:
                    failure += 1
                    # Log failure clearly, indicating which job failed
                    # logger.error(
                    #     f"Progress: [{processed_count}/{len(job_ids)}] Job {jid} - Worker reported failure or no description found."
                    # )
            except Exception as exc:
                # Catch exceptions *propagated* from the worker (if not caught inside _worker_scrape)
                failure += 1
                logger.error(
                    f"Progress: [{processed_count}/{len(job_ids)}] Job {jid} - Worker raised an unhandled exception: {exc}",
                    exc_info=True,  # Include traceback for unexpected errors
                )

            # Log overall progress periodically
            if processed_count % 50 == 0 or processed_count == len(
                job_ids
            ):  # Log every 50 jobs or at the end
                logger.info(
                    f"Progress: {processed_count}/{len(job_ids)} processed. Current Stats -> Success: {success}, Failure: {failure}"
                )

    logger.info(
        f"Scraping complete. Total processed: {success + failure}. Final Stats -> Success: {success}, Failure: {failure}"
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
    thread_id = threading.get_ident()  # Get current thread ID
    log_prefix = f"[Thread-{thread_id} Job-{job_id}]"  # Create a log prefix for single updates too

    try:
        # If description not provided, scrape it
        if description is None:
            logger.info(f"{log_prefix} Scraping description")
            # --- Add random delay ---
            delay = random.uniform(1.0, 3.0)
            logger.debug(f"{log_prefix} Sleeping for {delay:.2f} seconds")
            time.sleep(delay)
            # --- End delay ---
            job_details = jobsdb_scraper.get_job_details(job_id)
            if (
                job_details
                and job_details.description
                and job_details.description != "N/A"
            ):
                description = job_details.description
                logger.debug(f"{log_prefix} Scraped description successfully.")
            elif job_details:  # Scraped but got N/A or empty
                logger.warning(
                    f"{log_prefix} Scraped empty/NA description, cannot update."
                )
                return False
            else:  # Scraping failed
                logger.error(f"{log_prefix} Could not scrape description.")
                return False

        # Update the description in the database
        logger.debug(f"{log_prefix} Attempting to save description to DB.")
        success = db.update_job_description(job_id, description)
        if success:
            logger.info(f"{log_prefix} Successfully updated description.")
            return True
        else:
            logger.error(f"{log_prefix} Failed to update description in DB.")
            return False

    except Exception as e:
        logger.error(f"{log_prefix} Error updating job description: {e}", exc_info=True)
        return False


def main():
    """Run the CLI application."""
    parser = argparse.ArgumentParser(description="Job Scraper CLI")

    # --- Scraper Selection ---
    parser.add_argument(
        "--source",
        choices=["jobsdb", "all"],  # Add other sources if needed
        default="jobsdb",  # Default to jobsdb if 'all' isn't meaningful yet
        help="Job source to scrape (default: jobsdb)",
    )
    parser.add_argument(
        "--method",
        choices=["selenium", "scrapy"],
        default="selenium",  # Or 'scrapy' if preferred
        help="Scraping method for searching jobs (default: selenium)",
    )

    # --- Job Search Arguments ---
    search_group = parser.add_argument_group("Job Search Options (Scrapes listings)")
    search_group.add_argument(
        "--search",
        action="store_true",
        help="Perform a job search (scrape listings).",
    )
    search_group.add_argument(
        "--query",
        type=str,
        default=None,
        help="Job search query (e.g., 'software engineer')",
    )
    search_group.add_argument(
        "--location",
        type=str,
        default=None,  # Let the scraper handle default location if applicable
        help="Job location (e.g., 'Hong Kong')",
    )
    search_group.add_argument(
        "--start_page",
        type=int,
        default=1,
        help="Start page number for search results (default: 1)",
    )
    search_group.add_argument(
        "--end_page",
        type=int,
        default=1,  # Default to scraping only the start_page
        help="End page number for search results (inclusive, default: same as --start_page)",
    )
    search_group.add_argument(
        "--sortmode",
        choices=["listed_date", "relevance"],
        default="listed_date",
        help="Sorting mode for search results (default: listed_date)",
    )
    search_group.add_argument(
        "--job_type",
        choices=["full_time", "part_time", "contract", "casual"],
        default=None,
        help="Filter search results by job type (default: all)",
    )
    search_group.add_argument(
        "--job_category",
        choices=["software", "finance"],  # Add more as needed
        default="software",  # Default to a common category or None
        help="Filter search results by job category (default: software)",
    )
    # search_group.add_argument(
    #     "--limit", # Limit per page is often fixed by the site, overall limit might be better
    #     type=int,
    #     default=1000, # High default if limiting total jobs across pages
    #     help="Maximum total jobs to scrape across all pages (approximate)",
    # )

    # --- Job Detail Scraping Arguments ---
    details_group = parser.add_argument_group(
        "Job Detail Options (Scrapes descriptions)"
    )
    details_group.add_argument(
        "--details",
        action="store_true",
        help="Scrape job details for jobs missing descriptions.",
    )
    details_group.add_argument(
        "--quantity",
        type=int,
        default=100,  # Default number of descriptions to fetch
        help="Max number of jobs with missing descriptions to scrape details for (default: 100).",
    )
    details_group.add_argument(
        "--scrape_details_range",  # Alternative way to select jobs for details
        action="store_true",
        help="Scrape job details for a range of internal DB IDs (overrides --quantity).",
    )
    details_group.add_argument(
        "--start_id",
        type=int,
        help="Starting internal DB ID for --scrape_details_range",
    )
    details_group.add_argument(
        "--end_id", type=int, help="Ending internal DB ID for --scrape_details_range"
    )
    details_group.add_argument(
        "--max_workers",
        type=int,
        default=5,  # Keep default reasonable
        help="Number of parallel workers for scraping details (default: 5).",
    )

    # --- Direct Update Argument ---
    update_group = parser.add_argument_group("Direct Update Options")
    update_group.add_argument(
        "--update_description",
        metavar="JOB_ID",
        type=str,
        help="Scrape and update description for a single specific job ID.",
    )

    # --- General Arguments ---
    parser.add_argument(
        "--save", action="store_true", help="Save scraped jobs/details to database."
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging."
    )

    args = parser.parse_args()

    # Adjust log level if verbose
    if args.verbose:
        # Set root logger level
        logging.getLogger().setLevel(logging.DEBUG)
        # Set level for specific loggers if needed (e.g., suppress noisy libraries)
        logging.getLogger("WDM").setLevel(logging.INFO)  # Or WARNING
        logging.getLogger("urllib3").setLevel(logging.INFO)  # Often noisy
        logger.debug("Verbose logging enabled.")
    else:
        # Ensure default level is INFO if not verbose
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger("WDM").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)

    # Determine action based on arguments
    action_taken = False

    # --- Action: Update Single Description ---
    if args.update_description:
        logger.info(
            f"Attempting to update description for job ID: {args.update_description}"
        )
        # Force save=True for single update is implied
        update_job_description(args.update_description)
        action_taken = True

    # --- Action: Scrape Details ---
    # Prioritize range over quantity if both flags are somehow set
    elif (
        args.scrape_details_range
        and args.start_id is not None
        and args.end_id is not None
    ):
        logger.info(
            f"Starting detail scraping for internal ID range: {args.start_id} - {args.end_id}"
        )
        scrape_job_details(
            start_id=args.start_id,
            end_id=args.end_id,
            save=args.save,
            max_workers=args.max_workers,
        )
        action_taken = True
    elif args.details:
        logger.info(
            f"Starting detail scraping for up to {args.quantity} jobs missing descriptions."
        )
        scrape_job_details(
            quantity=args.quantity, save=args.save, max_workers=args.max_workers
        )
        action_taken = True

    # --- Action: Search for Job Listings ---
    elif args.search:
        logger.info(f"Starting job search on {args.source} using {args.method} method.")
        db = None  # Initialize db only if saving
        if args.save:
            db = DatabaseConnector()

        if args.source == "all" or args.source == "jobsdb":
            # Set end_page to start_page if end_page is less than start_page or None
            if args.end_page is None or args.end_page < args.start_page:
                args.end_page = args.start_page
            total_jobs_found_all_pages = 0

            # Loop through pages from start to end
            for current_page in range(args.start_page, args.end_page + 1):
                logger.info(f"Scraping page {current_page} of {args.end_page}...")
                jobs_on_page = []

                try:
                    if args.method == "scrapy":
                        # Use Scrapy spider
                        jobs_on_page = run_jobsdb_spider(
                            job_category=args.job_category,
                            job_type=args.job_type,
                            sortmode=args.sortmode,
                            page=current_page,
                        )
                    else:  # Default to selenium
                        # Use Selenium-based scraper
                        # Need to ensure JobsdbScraper is instantiated correctly
                        jobsdb_scraper = (
                            JobsdbScraper()
                        )  # Instantiate here or make it global? Careful with state.
                        jobs_on_page = jobsdb_scraper.search_jobs(
                            job_category=args.job_category,
                            job_type=args.job_type,
                            sortmode=args.sortmode,
                            page=current_page,
                            # query=args.query # Pass query if needed by search_jobs
                            # location=args.location # Pass location if needed
                        )
                    logger.info(
                        f"Found {len(jobs_on_page)} jobs on Jobsdb (page {current_page})"
                    )
                    total_jobs_found_all_pages += len(jobs_on_page)

                    # Save to database if enabled
                    if args.save and db and jobs_on_page:
                        logger.info(
                            f"Saving {len(jobs_on_page)} jobs from page {current_page}..."
                        )
                        saved_count = db.save_jobs(
                            jobs_on_page
                        )  # Assuming save_jobs handles duplicates/updates
                        logger.info(
                            f"Attempted to save {len(jobs_on_page)} jobs. Result count (may differ due to updates/skips): {saved_count}."
                        )

                except Exception as e:
                    logger.error(
                        f"Error scraping page {current_page}: {e}",
                        exc_info=args.verbose,
                    )  # Show traceback if verbose
                    # Decide whether to continue to next page or stop
                    # break # Example: stop on error

            logger.info(
                f"Total jobs found across pages {args.start_page} to {args.end_page}: {total_jobs_found_all_pages}"
            )
        action_taken = True

    # --- No Action ---
    if not action_taken:
        logger.warning(
            "No action specified. Use --search, --details, --scrape_details_range, or --update_description."
        )
        parser.print_help()


if __name__ == "__main__":
    main()
