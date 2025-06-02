"""Job scraper module with class-based API."""

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
from typing import List, Optional, Dict, Any, Union, Literal
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from enum import Enum

# Import existing components
from .db.connector import DatabaseConnector
from .scrapers.jobsdb import JobsdbScraper
from .scrapers.linkedin import LinkedInScraper
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from .models.job import Company, Job

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


class ScrapingMethod(str, Enum):
    """Supported scraping methods."""

    SELENIUM = "selenium"
    SCRAPY = "scrapy"

    @classmethod
    def get_default(cls) -> "ScrapingMethod":
        """Get the default scraping method."""
        return cls.SELENIUM


class FilterType(str, Enum):
    """Supported filter types."""

    NA = "N/A"
    ALL = "all"
    NEW = "new"

    @classmethod
    def get_default(cls) -> "FilterType":
        """Get the default filter type."""
        return cls.NEW


@dataclass
class JobScraperConfig:
    """Configuration for the job scraper."""

    # Common parameters
    source_platform: str = "all"
    job_class: Optional[str] = None
    method: ScrapingMethod = ScrapingMethod.SELENIUM
    save: bool = False
    workers: int = 1

    # Type 1 specific parameters (quantity-based)
    quantity: Optional[int] = None
    filter: FilterType = FilterType.NEW

    # Type 2 specific parameters (page-based)
    start_page: Optional[int] = None
    end_page: Optional[int] = None

    # Internal state
    _db: Optional[DatabaseConnector] = field(default=None, repr=False)
    _config_type: Optional[int] = field(default=None, repr=False)

    def __post_init__(self):
        """Validate and normalize the configuration after initialization."""
        # Determine the configuration type
        if self.quantity is not None:
            self._config_type = 1
        elif self.start_page is not None or self.end_page is not None:
            self._config_type = 2
        else:
            # Default to Type 1 with minimum quantity
            self._config_type = 1
            self.quantity = 1

        # # Validation will happen when validate() is called
        # self._validate_config()

    def _validate_config(self):
        """Validate and normalize the configuration."""
        # Validate common parameters
        self._validate_source_platform()

        # Continue with other validations
        self._validate_method()
        self._validate_workers()

        # Validate type-specific parameters
        if self._config_type == 1:
            self._validate_type1_params()
        else:
            self._validate_type2_params()

    def validate(self):
        """Validate and normalize the configuration."""
        # First validate the source platform to get the platform name
        self._validate_source_platform()

        # Continue with other validations
        self._validate_method()
        self._validate_workers()

        # Validate type-specific parameters
        if self._config_type == 1:
            self._validate_type1_params()
        else:
            self._validate_type2_params()

    def _validate_source_platform(self):
        """Validate and normalize the source platform."""
        # Check if DB is available
        if not self._db:
            logger.error("Database not available for source platform validation")
            raise ValueError(
                "Database connection required for source platform validation"
            )

        try:
            valid_platforms = self._db.get_all_source_platforms()
            if not valid_platforms:
                logger.error("No source platforms found in database")
                raise ValueError("No source platforms found in database")
            valid_platform_ids = [int(platform.id) for platform in valid_platforms]
            platform_id_to_name = {int(p.id): p.name for p in valid_platforms}

            # Store both ID and name
            self.source_platform_id = None
            self.source_platform_name = None

            try:
                # Check if source_platform is a valid ID
                platform_id = int(self.source_platform)
                logger.info(f"Validating source platform ID 2: {platform_id}")
                if platform_id in valid_platform_ids:
                    self.source_platform_id = platform_id
                    self.source_platform_name = platform_id_to_name[platform_id]
                    logger.info(
                        f"Using source platform: {self.source_platform_name} (ID: {self.source_platform_id})"
                    )
                else:
                    # Don't default to "all", raise an error instead
                    raise ValueError(f"Invalid source platform ID: {platform_id}")
            except (ValueError, TypeError):
                # Check if source_platform is a name
                platform_name = str(self.source_platform).lower()
                for p in valid_platforms:
                    if p.name.lower() == platform_name:
                        self.source_platform_id = int(p.id)
                        self.source_platform_name = p.name
                        logger.info(
                            f"Using source platform: {self.source_platform_name} (ID: {self.source_platform_id})"
                        )
                        break
                    else:
                        # Don't default to "all", raise an error instead
                        raise ValueError(
                            f"Invalid source platform: {self.source_platform}"
                        )

            # Keep original field updated for compatibility
            self.source_platform = self.source_platform_name
        except Exception as e:
            logger.error(f"Error validating source platform: {e}")
            raise ValueError(f"Failed to validate source platform: {e}")

    def _validate_method(self):
        """Validate and normalize the scraping method."""
        if not isinstance(self.method, ScrapingMethod):
            try:
                self.method = ScrapingMethod(self.method)
            except ValueError:
                logger.warning(
                    f"Invalid method value: {self.method}. Using default: selenium"
                )
                self.method = ScrapingMethod.SELENIUM

    def _validate_workers(self):
        """Validate and normalize the number of workers."""
        if not isinstance(self.workers, int) or self.workers < 1:
            logger.warning(f"Invalid workers value: {self.workers}. Using default: 1")
            self.workers = 1

    def _validate_type1_params(self):
        """Validate Type 1 specific parameters (quantity-based)."""
        # Validate quantity
        if not isinstance(self.quantity, int) or self.quantity < 1:
            logger.warning(
                f"Invalid quantity value: {self.quantity}. Setting to minimum value: 1"
            )
            self.quantity = 1

        # Validate filter
        if not isinstance(self.filter, FilterType):
            try:
                self.filter = FilterType(self.filter)
            except ValueError:
                logger.warning(
                    f"Invalid filter value: {self.filter}. Using default: new"
                )
                self.filter = FilterType.NEW

        # Clear Type 2 params
        self.start_page = None
        self.end_page = None

    def _validate_type2_params(self):
        """Validate Type 2 specific parameters (page-based)."""
        # Validate start_page
        if not isinstance(self.start_page, int) or self.start_page < 1:
            logger.warning(
                f"Invalid start_page value: {self.start_page}. Using default: 1"
            )
            self.start_page = 1

        # Validate end_page
        if not isinstance(self.end_page, int) or self.end_page < self.start_page:
            logger.warning(
                f"Invalid end_page value: {self.end_page}. Using default: {self.start_page}"
            )
            self.end_page = self.start_page

        # Clear Type 1 params
        self.quantity = None
        self.filter = FilterType.NEW  # Still set a default even though it's not used

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "JobScraperConfig":
        """Create a configuration from a dictionary."""
        # Convert string enum values
        if "method" in config_dict and isinstance(config_dict["method"], str):
            try:
                config_dict["method"] = ScrapingMethod(config_dict["method"])
            except ValueError:
                config_dict["method"] = ScrapingMethod.SELENIUM

        if "filter" in config_dict and isinstance(config_dict["filter"], str):
            try:
                config_dict["filter"] = FilterType(config_dict["filter"])
            except ValueError:
                config_dict["filter"] = FilterType.NEW

        # Convert numeric values
        for key in ["quantity", "start_page", "end_page", "workers"]:
            if key in config_dict and config_dict[key] is not None:
                try:
                    config_dict[key] = int(config_dict[key])
                except (ValueError, TypeError):
                    # Remove invalid values, defaults will be used
                    config_dict.pop(key)

        # Convert boolean values
        if "save" in config_dict:
            if isinstance(config_dict["save"], str):
                config_dict["save"] = config_dict["save"].lower() == "true"

        return cls(**config_dict)

    @classmethod
    def from_args(cls, args_list: List[str]) -> "JobScraperConfig":
        """Create a configuration from command-line arguments."""
        # Parse command-line arguments in "key=value" format
        config_dict = {}
        # Join args with spaces and split by comma
        cmd_str = " ".join(args_list)
        parts = [part.strip() for part in cmd_str.split(",")]

        for part in parts:
            if "=" in part:
                key, value = part.split("=", 1)
                config_dict[key.strip()] = value.strip()

        return cls.from_dict(config_dict)

    def get_config_type(self) -> int:
        """Get the configuration type (1 or 2)."""
        return self._config_type


class JobScraperManager:
    """Manager class for job scraping operations."""

    def __init__(
        self, config: JobScraperConfig, db_connector: Optional[DatabaseConnector] = None
    ):
        """Initialize with a configuration and optional database connector."""
        self.config = config

        # Initialize database connector - now required
        self.db = db_connector
        if self.db is None:
            try:
                self.db = DatabaseConnector()
                logger.info("Database connection established")
            except Exception as e:
                logger.error(f"Failed to connect to database: {e}")
                raise ValueError(f"Database connection required but failed: {e}")

        # Inject the same DB connection into the config
        self.config._db = self.db

        # Now validate config with DB connection
        try:
            self.config.validate()
        except ValueError as e:
            logger.error(f"Configuration validation failed: {e}")
            raise

    def needs_db_validation(self):
        """Check if this configuration needs database validation."""
        # If we need to validate source_platform or job_class, we need DB
        return self.config.source_platform != "all" or self.config.job_class is not None

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "JobScraperManager":
        """Create a manager from a dictionary configuration."""
        config = JobScraperConfig.from_dict(config_dict)
        return cls(config)

    @classmethod
    def from_args(cls, args_list: List[str]) -> "JobScraperManager":
        """Create a manager from command-line arguments."""
        config = JobScraperConfig.from_args(args_list)
        return cls(config)

    def run(self) -> Dict[str, Any]:
        if self.config.get_config_type() == 1:
            return self._run_quantity_based()
        else:
            return self._run_page_based()

    def _run_quantity_based(self) -> Dict[str, Any]:
        """Run Type 1 (quantity-based) scraping."""
        logger.info(f"Running quantity-based scraping with {self.config.quantity} jobs")

        # Convert source platform name to method name
        platform_name = str(self.config.source_platform_name).lower()
        platform_method = platform_name.replace(" ", "_").replace("-", "_")
        method_name = f"_run_{platform_method}_quantity"

        # Check if the method exists
        if hasattr(self, method_name):
            # Dynamically call the appropriate method
            method = getattr(self, method_name)
            return method()
        else:
            # Fallback if no specific method exists
            logger.warning(
                f"No scraping method found for platform: {self.config.source_platform_name}"
            )
            return {
                "success": False,
                "message": f"Unsupported platform: {self.config.source_platform_name}",
            }

    def _run_page_based(self) -> Dict[str, Any]:
        """Run Type 2 (page-based) scraping."""
        logger.info(
            f"Running page-based scraping from page {self.config.start_page} to {self.config.end_page}"
        )

        # Convert source platform name to method name
        platform_name = str(self.config.source_platform_name).lower()
        platform_method = platform_name.replace(" ", "_").replace("-", "_")
        method_name = f"_run_{platform_method}_pages"

        # Check if the method exists
        if hasattr(self, method_name):
            # Dynamically call the appropriate method
            method = getattr(self, method_name)
            return method()
        else:
            # Fallback if no specific method exists
            logger.warning(
                f"No scraping method found for platform: {self.config.source_platform_name}"
            )
            return {
                "success": False,
                "message": f"Unsupported platform: {self.config.source_platform_name}",
            }

    def _run_jobsdb_quantity(self) -> Dict[str, Any]:
        """Run quantity-based JobsDB scraping."""
        job_ids = self.db.get_jobs_with_filters(
            limit=self.config.quantity,
            filter_type=self.config.filter.value,
            job_class=self.config.job_class,
            source=self.config.source_platform_name,
        )

        if not job_ids:
            logger.warning(
                f"No job IDs found with filter '{self.config.filter.value}'."
            )
            return {"success": False, "message": "No jobs found", "jobs_scraped": 0}

        return self._scrape_job_details(job_ids)

    def _run_linkedin_quantity(self) -> Dict[str, Any]:
        """Run quantity-based LinkedIn scraping."""
        job_ids = self.db.get_jobs_with_filters(
            limit=self.config.quantity,
            filter_type=self.config.filter.value,
            job_class=self.config.job_class,
            source=self.config.source_platform_name,
        )

        if not job_ids:
            logger.warning(
                f"No job IDs found with filter '{self.config.filter.value}'."
            )
            return {"success": False, "message": "No jobs found", "jobs_scraped": 0}

        return self._scrape_job_details(job_ids)

    def _run_jobsdb_pages(self) -> Dict[str, Any]:
        """Run page-based JobsDB scraping."""
        total_jobs = 0
        jobs = []
        job_classes = [
            # s"accounting",
            "administration-office-support",
            # "advertising-arts-media",
            "banking-financial-services",
            # "call-centre-customer-service",
            # "ceo-general-management",
            # "community-services-development",
            # "construction",
            # "consulting-strategy",
            # "design-architecture",
            # "education-training",
            # "engineering",
            # "farming-animals-conservation",
            # "government-defence",
            # "healthcare-medical",
            # "hospitality-tourism",
            # "human-resources-recruitment",
            "information-communication-technology",
            # "insurance-superannuation",
            # "mining-resources-energy",
            # "real-estate-property",
            # "retail-consumer-products",
            # "sales",
            # "science-technology",
            # "sport-recreation",
            # "trades-services",
        ]
    
        for current_page in range(self.config.start_page, self.config.end_page + 1):
            logger.info(f"Scraping page {current_page} of {self.config.end_page}")

            for job_class in job_classes:
                if self.config.method == ScrapingMethod.SELENIUM:
                    # Use Selenium-based scraper
                    jobsdb_scraper = JobsdbScraper(headless=True, db=self.db)

                # Only pass the parameters specified by the user
                search_params = {
                    "page": current_page,
                    "job_class": job_class,
                }

                jobs = jobsdb_scraper.search_jobs(**search_params)

                # Use the save parameter to determine if we should save to database
                if self.config.save and self.db and jobs:
                    saved_count = self.db.save_jobs(jobs)
                    logger.info(
                        f"Saved {saved_count} jobs from page {current_page} to database"
                        )
                total_jobs += len(jobs)
                jobs = []

        logger.info(
            f"Total jobs found across pages {self.config.start_page} to {self.config.end_page}: {total_jobs}"
        )

        return {
            "success": True,
            "jobs_scraped": total_jobs,
            "pages_scraped": self.config.end_page - self.config.start_page + 1,
            "job_class": self.config.job_class,
            "save": self.config.save,
            "source_platform": self.config.source_platform,
        }

    def _run_linkedin_pages(self) -> Dict[str, Any]:
        """Run page-based LinkedIn scraping."""
        total_jobs = 0
        jobs = []

        if self.config.method == ScrapingMethod.SELENIUM:
            linkedin_scraper = LinkedInScraper(db=self.db, headless=False)
            linkedin_scraper.login()

        for current_page in range(self.config.start_page, self.config.end_page + 1):
            logger.info(f"Scraping page {current_page} of {self.config.end_page}")

            # Only pass the parameters specified by the user
            search_params = {
                "job_class": self.config.job_class,
                "page": current_page,
            }

            jobs = linkedin_scraper.search_jobs(
                **search_params
            )  # Reuse scraper instance

            # Use the save parameter to determine if we should save to database
            if self.config.save and self.db and jobs:
                saved_count = self.db.save_jobs(jobs)
                logger.info(
                    f"Saved {saved_count} jobs from page {current_page} to database"
                )

            total_jobs += len(jobs)
            jobs = []

        logger.info(
            f"Total jobs found across pages {self.config.start_page} to {self.config.end_page}: {total_jobs}"
        )

        return {
            "success": True,
            "jobs_scraped": total_jobs,
            "pages_scraped": self.config.end_page - self.config.start_page + 1,
            "job_class": self.config.job_class,
            "save": self.config.save,
            "source_platform": self.config.source_platform,
        }

    def _scrape_job_details(self, job_ids: List[str]) -> Dict[str, Any]:
        """Scrape details for the given job IDs."""
        max_workers = min(self.config.workers, len(job_ids))

        # Calculate batch size (with ceiling division to ensure all jobs are covered)
        batch_size = math.ceil(len(job_ids) / max_workers)

        # Split jobs into equal-sized batches (last batch may be smaller)
        job_batches = [
            job_ids[i : i + batch_size] for i in range(0, len(job_ids), batch_size)
        ]

        logger.info(
            f"Starting detail scraping with {max_workers} workers. Each worker will process ~{batch_size} jobs."
        )
        logger.info(f"Total jobs: {len(job_ids)}, Save mode: {self.config.save}")

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
                    save=self.config.save,
                    source=self.config.source_platform_name,
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
            f"Final Stats -> Success: {total_success}, Failure: {total_failure}"
        )

        return {
            "success": True,
            "jobs_processed": total_success + total_failure,
            "success_count": total_success,
            "failure_count": total_failure,
        }


def process_job_batch(job_batch, worker_id, total_workers, save=False, source=None):

    thread_id = threading.get_ident()
    log_prefix = f"[Worker-{worker_id}/{total_workers} Thread-{thread_id}]"

    logger.info(f"{log_prefix} Starting batch processing of {len(job_batch)} jobs")

    db = DatabaseConnector()
    if source.lower() == "jobsdb":
        scraper = JobsdbScraper(headless=True, db=db)
    elif source.lower() == "linkedin":
        scraper = LinkedInScraper(db=db)
    else:
        raise ValueError(f"Unsupported source: {source}")

    success_count = 0
    failure_count = 0
    failure_job_ids = []
    for idx, job_id in enumerate(job_batch):
        try:
            # Add random delay to avoid rate limiting
            delay = random.uniform(1.0, 3.0)
            logger.debug(f"{log_prefix} Job {job_id} sleeping for {delay:.2f} seconds")
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
                    logger.info(f"Saving job {job_id} to database")
                    success = db.update_job_description(job_id, job_details.description)
                    if source.lower() == "linkedin":
                        db.update_job_title(job_id, job_details.name)
                        db.update_job_company(job_id, job_details.company_name)
                    elif source.lower() == "jobsdb":
                        db.update_job_class(job_id, job_details.job_class)
                    if success:
                        success_count += 1
                    else:
                        failure_count += 1
                        failure_job_ids.append(job_id)  # Add to failure list
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
                failure_job_ids.append(job_id)  # Add to failure list

        except Exception as e:
            failure_count += 1
            failure_job_ids.append(job_id)  # Add to failure list
            logger.error(
                f"{log_prefix} ({idx+1}/{len(job_batch)}) Job {job_id} failed: {e}"
            )
            if save:
                try:
                    db.update_job_description(job_id, f"Error: {type(e).__name__}")
                except Exception:
                    pass

    logger.info(
        f"{log_prefix} Completed batch. Success: {success_count}, Failure: {failure_count}, Failed IDs: {failure_job_ids}"
    )
    return success_count, failure_count


# Main function for command-line use
def main():
    """Run the CLI application."""
    # Create a scraper from command-line arguments
    manager = JobScraperManager.from_args(sys.argv[1:])
    results = manager.run()

    # # Print a summary of results
    # print(f"\nScraping completed!")
    # for key, value in results.items():
    #     if key != "jobs":  # Don't print the full job list
    #         print(f"{key}: {value}")


# API functions for external use
def create_scraper(config_dict: Dict[str, Any]) -> JobScraperManager:
    """Create a scraper from a configuration dictionary."""
    return JobScraperManager.from_dict(config_dict)


def run_scraper(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Run a scraper with the given configuration."""
    manager = create_scraper(config_dict)
    return manager.run()


if __name__ == "__main__":
    main()
