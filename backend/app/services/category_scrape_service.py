"""
Category Scrape Service (Orchestrator)

Coordinates the two-phase scraping process:
1. List scraping - collect job IDs by category
2. Detail scraping - fetch full job details

Supports incremental and batch scraping with progress tracking.
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum

from app.scraper.categories import JOBSDB_CATEGORIES, get_category_name
from app.scraper.category_scraper import CategoryListScraper
from app.scraper.job_detail_scraper import JobDetailScraper
from app.services.progress_store import get_progress_store
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


class ScrapeStatus(str, Enum):
    PENDING = "pending"
    COLLECTING_IDS = "collecting_ids"
    SCRAPING_DETAILS = "scraping_details"
    AI_CLASSIFYING = "ai_classifying"
    SAVING_TO_DB = "saving_to_db"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class CategoryScrapeService:
    """Orchestrates category-based job scraping."""

    def __init__(self, db_session=None, redis_client=None):
        self.list_scraper = CategoryListScraper()
        self.detail_scraper = JobDetailScraper()
        self.db = db_session
        self.redis = redis_client
        self._progress_store = get_progress_store()

    def get_progress(self, classification_id: int) -> Optional[Dict]:
        """Get current scraping progress for a category."""
        return self._progress_store.get(classification_id)

    def get_all_progress(self) -> Dict[int, Dict]:
        """Get progress for all categories."""
        return self._progress_store.get_all()

    def _calculate_rates(self, classification_id: int) -> Dict[str, Any]:
        """Calculate elapsed time and processing rates."""
        progress = self._progress_store.get(classification_id)
        if not progress:
            return {}

        started_at_raw = progress.get("started_at")
        if not isinstance(started_at_raw, str) or not started_at_raw:
            return {}

        phase_started_at_raw = progress.get("phase_started_at", started_at_raw)
        if not isinstance(phase_started_at_raw, str) or not phase_started_at_raw:
            phase_started_at_raw = started_at_raw

        try:
            started_at = datetime.fromisoformat(started_at_raw)
            phase_started_at = datetime.fromisoformat(phase_started_at_raw)
        except ValueError:
            return {}

        now = utc_now()
        elapsed = (now - started_at).total_seconds()
        phase_elapsed = (now - phase_started_at).total_seconds()

        overall_rate = 0
        phase_rate = 0

        jobs_scraped = progress.get("jobs_scraped", 0)
        if elapsed > 0 and jobs_scraped > 0:
            overall_rate = jobs_scraped / elapsed

        phase = progress.get("phase", 1)
        if phase == 1:
            ids_collected = progress.get("job_ids_collected", 0)
            if phase_elapsed > 0:
                phase_rate = ids_collected / phase_elapsed
        elif phase == 2:
            if phase_elapsed > 0:
                phase_rate = jobs_scraped / phase_elapsed

        return {
            "elapsed_seconds": int(elapsed),
            "phase_elapsed_seconds": int(phase_elapsed),
            "overall_rate": round(overall_rate, 2),
            "phase_rate": round(phase_rate, 2)
        }

    async def scrape_category(
        self,
        classification_id: int,
        max_pages: Optional[int] = None,
        batch_size: int = 50,
        skip_existing: bool = True,
    ) -> Dict[str, Any]:
        """
        Scrape all jobs from a single category.

        Args:
            classification_id: Category ID to scrape
            max_pages: Optional limit on list pages
            batch_size: Number of job details to fetch per batch
            skip_existing: If True, pre-filter existing job IDs before detail scraping
        """
        category_name = get_category_name(classification_id) or f"Category {classification_id}"

        # Initialize progress
        self._progress_store.update(classification_id, {
            "status": ScrapeStatus.COLLECTING_IDS,
            "category_name": category_name,
            "phase": 1,
            "job_ids_collected": 0,
            "jobs_scraped": 0,
            "total_jobs": 0,
            "started_at": utc_now().isoformat(),
            "phase_started_at": utc_now().isoformat(),
        })

        try:
            # Phase 1: Collect job IDs
            def on_list_progress(page, total_pages, jobs_found):
                update_data = {
                    "current_page": page,
                    "total_pages": total_pages,
                    "job_ids_collected": jobs_found,
                }
                update_data.update(self._calculate_rates(classification_id))
                self._progress_store.update(classification_id, update_data)

            list_result = await self.list_scraper.scrape_category(
                classification_id,
                max_pages=max_pages,
                on_progress=on_list_progress,
            )

            job_ids = list_result["job_ids"]

            if skip_existing:
                # Pre-scrape deduplication: filter out existing job_ids
                from app.database import SessionLocal
                from app.services.database_service import DatabaseService
                db_service = DatabaseService()

                db = SessionLocal()
                try:
                    new_ids, _existing_ids = db_service.filter_existing_job_ids(db, job_ids)
                    job_ids = new_ids
                finally:
                    db.close()

            total_jobs = len(job_ids)

            self._progress_store.update(classification_id, {
                "status": ScrapeStatus.SCRAPING_DETAILS,
                "phase": 2,
                "total_jobs": total_jobs,
                "phase_started_at": utc_now().isoformat(),
            })

            # Phase 2: Fetch job details in batches
            all_details = []
            for i in range(0, total_jobs, batch_size):
                batch_ids = job_ids[i:i + batch_size]

                def on_detail_progress(current, total, success, job_data=None):
                    update_data = {
                        "jobs_scraped": i + current,
                        "jobs_success": len(all_details) + success,
                    }
                    if job_data:
                        update_data["current_job_id"] = job_data.get("jobsdb_id")
                        update_data["current_job_title"] = job_data.get("title")
                    update_data.update(self._calculate_rates(classification_id))
                    self._progress_store.update(classification_id, update_data)

                batch_details = await self.detail_scraper.fetch_multiple_jobs(
                    batch_ids,
                    on_progress=on_detail_progress,
                )
                all_details.extend(batch_details)

            # Mark completed
            self._progress_store.update(classification_id, {
                "status": ScrapeStatus.COMPLETED,
                "jobs_scraped": total_jobs,
                "jobs_success": len(all_details),
                "completed_at": utc_now().isoformat(),
            })

            return {
                "classification_id": classification_id,
                "category_name": category_name,
                "total_jobs": total_jobs,
                "jobs_scraped": len(all_details),
                "details": all_details,
            }

        except Exception as e:
            self._progress_store.update(classification_id, {
                "status": ScrapeStatus.FAILED,
                "error": str(e),
            })
            raise

    async def scrape_categories(
        self,
        category_ids: List[int],
        max_pages: int = 3,
        skip_existing: bool = True,
    ) -> Dict[str, Any]:
        """
        Scrape multiple categories and save to database.

        Args:
            category_ids: List of category IDs to scrape
            max_pages: Maximum pages per category
            skip_existing: If True, skip jobs that already exist in database
        """
        from app.database import SessionLocal
        from app.services.database_service import DatabaseService
        from app.services.enrichment_run_service import EnrichmentRunService

        db_service = DatabaseService()
        total_stats = {
            "jobs_created": 0,
            "jobs_updated": 0,
            "jobs_skipped": 0,
            "failed": 0,
            "categories_processed": 0,
            "affected_job_ids": [],
        }

        for category_id in category_ids:
            try:
                # Scrape category
                result = await self.scrape_category(
                    classification_id=category_id,
                    max_pages=max_pages,
                    skip_existing=skip_existing,
                )

                # Deduplicate results
                if result.get("details"):
                    result["details"] = db_service.deduplicate_jobs(result["details"])

                # Phase 3 skipped: AI Classification now happens asynchronously after saving.
                
                # Phase 4: Saving to Database
                if result.get("details"):
                    self._progress_store.update(category_id, {
                        "status": ScrapeStatus.SAVING_TO_DB,
                        "phase": 4,
                        "jobs_saved": 0,
                        "save_total": len(result["details"]),
                        "phase_started_at": utc_now().isoformat(),
                    })

                    db = SessionLocal()
                    try:
                        def on_save_progress(saved_count):
                            self._progress_store.update(category_id, {
                                "jobs_saved": saved_count,
                                **self._calculate_rates(category_id)
                            })

                        stats = await db_service.save_scraped_jobs(
                            result["details"],
                            db,
                            skip_existing=skip_existing,
                            on_progress=on_save_progress,
                        )
                        affected_job_ids = stats["affected_job_ids"]
                        EnrichmentRunService(db).create_post_scrape_run_for_batch(affected_job_ids)
                        db.commit()

                        total_stats["affected_job_ids"].extend(affected_job_ids)
                        total_stats["jobs_created"] += stats["jobs_created"]
                        total_stats["jobs_updated"] += stats["jobs_updated"]
                        total_stats["jobs_skipped"] += stats["jobs_skipped"]
                        total_stats["failed"] += stats["failed"]
                    except Exception:
                        db.rollback()
                        raise
                    finally:
                        db.close()

                self._progress_store.update(category_id, {
                    "status": ScrapeStatus.COMPLETED,
                    "completed_at": utc_now().isoformat(),
                })

                total_stats["categories_processed"] += 1

            except Exception:
                logger.exception("Error scraping category %s", category_id)
                total_stats["failed"] += 1

        return total_stats
