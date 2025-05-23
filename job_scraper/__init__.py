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
from .scrapers.jobsdb_spider import JobsDBSpider
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
        # Initialize database connector for validation
        self._db = DatabaseConnector()

        # Determine the configuration type
        if self.quantity is not None:
            self._config_type = 1
        elif self.start_page is not None or self.end_page is not None:
            self._config_type = 2
        else:
            # Default to Type 1 with minimum quantity
            self._config_type = 1
            self.quantity = 1

        # Validate according to type
        self._validate_config()

    def _validate_config(self):
        """Validate and normalize the configuration."""
        # Validate common parameters
        self._validate_source_platform()
        self._validate_job_class()
        self._validate_method()
        self._validate_workers()

        # Validate type-specific parameters
        if self._config_type == 1:
            self._validate_type1_params()
        else:
            self._validate_type2_params()

    def _validate_source_platform(self):
        """Validate and normalize the source platform."""
        try:
            valid_platforms = self._db.get_all_source_platforms()
            valid_platform_ids = [int(platform.id) for platform in valid_platforms]

            # Create mapping from ID to platform name
            platform_id_to_name = {int(p.id): p.name for p in valid_platforms}

            # Store both ID and name
            self.source_platform_id = None
            self.source_platform_name = None

            # Check if source_platform is a valid ID
            platform_id = int(self.source_platform)
            if platform_id in valid_platform_ids:
                self.source_platform_id = platform_id
                self.source_platform = self.source_platform_name = platform_id_to_name[
                    platform_id
                ]
                logger.info(
                    f"Using source platform: {self.source_platform_name} (ID: {self.source_platform_id})"
                )
            else:
                raise ValueError(f"Invalid source ID: {platform_id}")
        except Exception as e:
            logger.error(f"Error validating source platform: {e}")
            raise e

    def _validate_job_class(self):
        try:
            valid_job_classes = self._db.get_all_job_classes()
            valid_job_class_ids = [int(job_class.id) for job_class in valid_job_classes]

            # Create mapping from ID to job class name
            job_class_id_to_name = {int(jc.id): jc.name for jc in valid_job_classes}

            # Store both ID and name
            self.job_class_id = None
            self.job_class_name = None

            # Check if job_class is a valid ID
            job_class_id = int(self.job_class)
            if job_class_id in valid_job_class_ids:
                self.job_class_id = job_class_id
                self.job_class = self.job_class_name = job_class_id_to_name[
                    job_class_id
                ]
                logger.info(
                    f"Using job class: {self.job_class_name} (ID: {self.job_class_id})"
                )
            else:
                raise ValueError(f"Invalid job class ID: {job_class_id}")
        except Exception as e:
            logger.error(f"Error validating job class: {e}")
            raise e

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
                    config_dict.pop(key)  # Remove invalid values, defaults will be used

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

    def __init__(self, config: JobScraperConfig):
        """Initialize with a configuration."""
        self.config = config
        # self.db = DatabaseConnector()

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
        """Run the job scraper with the current configuration.

        Returns:
            Dict: Results of the scraping operation
        """
        if self.config.get_config_type() == 1:
            return self._run_quantity_based()
        else:
            return self._run_page_based()

    def _run_quantity_based(self) -> Dict[str, Any]:
        """Run Type 1 (quantity-based) scraping."""
        logger.info(f"Running quantity-based scraping with {self.config.quantity} jobs")

        if self.config.source_platform == "jobsdb":
            return self._run_jobsdb_quantity()
        elif self.config.source_platform == "linkedin":
            return self._run_linkedin_quantity()
        else:
            # Default to running all sources
            return self._run_all_sources_quantity()

    def _run_page_based(self) -> Dict[str, Any]:
        """Run Type 2 (page-based) scraping."""
        logger.info(
            f"Running page-based scraping from page {self.config.start_page} to {self.config.end_page}"
        )

        if self.config.source_platform == 1:
            return self._run_jobsdb_pages()
        elif self.config.source_platform == 4:
            return self._run_linkedin_pages()
        else:
            # Default to running all sources
            return self._run_all_sources_pages()

    def _run_jobsdb_quantity(self) -> Dict[str, Any]:
        """Run quantity-based JobsDB scraping."""
        # Implementation for JobsDB scraping by quantity
        job_ids = self.db.get_jobs_with_null_description(limit=self.config.quantity)

        if not job_ids:
            logger.warning("No job IDs found with null descriptions to scrape.")
            return {"success": False, "message": "No jobs found", "jobs_scraped": 0}

        return self._scrape_job_details(job_ids)

    def _run_linkedin_quantity(self) -> Dict[str, Any]:
        """Run quantity-based LinkedIn scraping."""
        # Implementation for LinkedIn scraping by quantity
        # This would be similar to the JobsDB implementation
        return {
            "success": True,
            "message": "LinkedIn quantity scraping not implemented yet",
            "jobs_scraped": 0,
        }

    def _run_all_sources_quantity(self) -> Dict[str, Any]:
        """Run quantity-based scraping for all sources."""
        # Implementation for all sources by quantity
        results = {}
        results.update(self._run_jobsdb_quantity())
        results.update(self._run_linkedin_quantity())
        return results

    def _run_jobsdb_pages(self) -> Dict[str, Any]:
        """Run page-based JobsDB scraping."""
        total_jobs = 0
        jobs = []
        for current_page in range(self.config.start_page, self.config.end_page + 1):
            logger.info(f"Scraping page {current_page} of {self.config.end_page}")

            if self.config.method == ScrapingMethod.SELENIUM:
                # Use Selenium-based scraper
                jobsdb_scraper = JobsdbScraper()

                # Only pass the parameters specified by the user
                search_params = {
                    "job_class": self.config.job_class,
                    "page": current_page,
                    "source_platform": self.config.source_platform,
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
        # Similar implementation as JobsDB but for LinkedIn
        return {
            "success": True,
            "message": "LinkedIn page-based scraping not implemented yet",
            "jobs_scraped": 0,
        }

    def _run_all_sources_pages(self) -> Dict[str, Any]:
        """Run page-based scraping for all sources."""
        # Implementation for all sources by page range
        results = {}
        results.update(self._run_jobsdb_pages())
        results.update(self._run_linkedin_pages())
        return results

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


# Keep existing functions for compatibility
def run_jobsdb_spider(job_category=None, job_type=None, sortmode="listed_date", page=1):
    """Run JobsDB spider and return the results as Job objects."""
    # Your existing implementation
    # ...


def process_job_batch(job_batch, worker_id, total_workers, save=False):
    """Process a batch of jobs with a dedicated worker."""
    # Your existing implementation
    # ...


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
