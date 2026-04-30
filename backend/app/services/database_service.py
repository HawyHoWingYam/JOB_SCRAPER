"""
Database Service - Orchestrates job and company persistence.

Coordinates repository operations, manages caching, and handles data transformation.
"""

import logging
from contextlib import nullcontext
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.repositories import CompanyRepository, JobRepository
from app.utils.data_mapper import (
    map_scraped_company_to_db,
    map_scraped_job_to_db,
    map_source_scraped_company_to_db,
    map_source_scraped_job_to_db,
)

logger = logging.getLogger(__name__)


class DatabaseService:
    """Service for persisting scraped jobs and companies to database."""

    def __init__(self):
        """Initialize repositories."""
        self.company_repo = CompanyRepository()
        self.job_repo = JobRepository()
        self._company_cache: Dict[str, Any] = {}  # In-memory cache for batch operations

    async def save_scraped_jobs(
        self, scraped_jobs: List[Dict[str, Any]], db: Session, skip_existing: bool = False, on_progress: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Save scraped jobs to database.

        Handles company creation/lookup and job upsert operations.
        Uses in-memory cache to avoid N+1 queries.

        Args:
            scraped_jobs: List of transformed job dicts from REST API
            db: SQLAlchemy session

        Returns:
            Statistics dict: {
                'jobs_created': int,
                'jobs_updated': int,
                'jobs_skipped': int,
                'companies_created': int,
                'companies_reused': int,
                'failed': int,
                'affected_job_ids': List[str],  # internal DB UUIDs for created/updated rows
            }
        """
        stats = {
            "jobs_created": 0,
            "jobs_updated": 0,
            "jobs_skipped": 0,
            "companies_created": 0,
            "companies_reused": 0,
            "failed": 0,
            "affected_job_ids": [],
        }

        self.clear_cache()
        try:
            for scraped_job in scraped_jobs:
                try:
                    nested_tx = db.begin_nested() if hasattr(db, "begin_nested") else nullcontext()
                    with nested_tx:
                        # Extract and get/create company
                        if scraped_job.get("source_site"):
                            company_data = map_source_scraped_company_to_db(scraped_job)
                        else:
                            company_data = map_scraped_company_to_db(scraped_job)
                        company, company_created = self._get_or_create_company_cached(
                            db,
                            company_data,
                            auto_commit=False,
                        )

                        if company_created:
                            stats["companies_created"] += 1
                        else:
                            stats["companies_reused"] += 1

                        # Transform and save job
                        if scraped_job.get("source_site"):
                            job_data = map_source_scraped_job_to_db(scraped_job, company.id)
                        else:
                            job_data = map_scraped_job_to_db(scraped_job, company.id)
                        job, action = self.job_repo.upsert_job(
                            db,
                            job_data,
                            skip_existing,
                            auto_commit=False,
                        )

                    if action == "created":
                        stats["jobs_created"] += 1
                        if getattr(job, "id", None):
                            stats["affected_job_ids"].append(str(job.id))
                    elif action == "updated":
                        stats["jobs_updated"] += 1
                        if getattr(job, "id", None):
                            stats["affected_job_ids"].append(str(job.id))
                    elif action == "skipped":
                        stats["jobs_skipped"] += 1

                    if on_progress:
                        on_progress(stats["jobs_created"] + stats["jobs_updated"] + stats["jobs_skipped"])

                except IntegrityError as e:
                    self.clear_cache()
                    logger.warning(
                        f"Integrity error saving job {scraped_job.get('external_id')}: {e}"
                    )
                    stats["failed"] += 1
                except Exception as e:
                    self.clear_cache()
                    logger.error(
                        f"Error saving job {scraped_job.get('external_id')}: {e}",
                        exc_info=True,
                    )
                    stats["failed"] += 1
        finally:
            self.clear_cache()

        logger.info(
            f"Batch save completed: "
            f"Created {stats['jobs_created']} jobs, "
            f"Updated {stats['jobs_updated']} jobs, "
            f"Skipped {stats['jobs_skipped']} jobs, "
            f"Created {stats['companies_created']} companies, "
            f"Reused {stats['companies_reused']} companies, "
            f"Failed {stats['failed']}"
        )

        return stats

    def _get_or_create_company_cached(
        self, db: Session, company_data: Dict[str, Any], auto_commit: bool = True
    ) -> tuple[Any, bool]:
        """
        Get or create company with in-memory caching.

        Avoids repeated database queries for the same company during batch processing.

        Args:
            db: SQLAlchemy session
            company_data: Company data dict

        Returns:
            (Company, created: bool) - Company instance and whether it was created
        """
        # Create cache key from company_id or name
        cache_key = company_data.get("company_id") or company_data.get("name")

        if not cache_key:
            # No cache key available, go directly to repository
            return self.company_repo.get_or_create_company(
                db,
                company_data,
                auto_commit=auto_commit,
            )

        # Check cache
        if cache_key in self._company_cache:
            logger.debug(f"Company cache hit: {cache_key}")
            return self._company_cache[cache_key], False

        # Not in cache, get from repository
        company, created = self.company_repo.get_or_create_company(
            db,
            company_data,
            auto_commit=auto_commit,
        )

        # Store in cache
        self._company_cache[cache_key] = company
        logger.debug(f"Company cache miss, stored: {cache_key}")

        return company, created

    def clear_cache(self) -> None:
        """Clear the company cache."""
        self._company_cache.clear()
        logger.debug("Company cache cleared")

    def filter_existing_job_ids(self, db: Session, job_ids: List[str]) -> tuple[List[str], List[str]]:
        """
        Split job_ids into new and existing.

        Returns:
            (new_job_ids, existing_job_ids)
        """
        existing = self.job_repo.get_existing_job_ids(db, job_ids)
        new_ids = [jid for jid in job_ids if jid not in existing]
        existing_ids = [jid for jid in job_ids if jid in existing]
        logger.info(f"Pre-scrape filter: {len(new_ids)} new, {len(existing_ids)} existing")
        return new_ids, existing_ids

    def deduplicate_jobs(self, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Remove duplicate jobs by job_id, keeping first occurrence.

        Args:
            jobs: List of job dicts

        Returns:
            Deduplicated job list
        """
        seen = set()
        unique_jobs = []
        duplicates = 0

        for job in jobs:
            job_id = job.get("job_id") or job.get("external_id") or job.get("jobsdb_id")
            if not job_id:
                unique_jobs.append(job)
                continue

            if job_id not in seen:
                seen.add(job_id)
                unique_jobs.append(job)
            else:
                duplicates += 1

        if duplicates > 0:
            logger.info(f"Removed {duplicates} duplicate jobs from scrape results")

        return unique_jobs
