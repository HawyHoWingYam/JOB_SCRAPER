"""Projection service — synchronises crawl-run state visible to the frontend.

Keeps PostgreSQL CrawlRun records updated as the Scrapy spider progresses.
This service is called by Scrapy pipelines and the FastAPI facade.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models.crawl_run import CrawlRun
from app.repositories.crawl_run_repository import CrawlRunRepository

logger = logging.getLogger(__name__)


class CrawlRunProjectionService:
    """Maintains the product-facing crawl-run projection."""

    def __init__(self, repository: CrawlRunRepository | None = None):
        self._repository = repository or CrawlRunRepository()

    def create_run(
        self,
        db: Session,
        *,
        crawl_job_id: UUID,
        source_site: str,
        scrapyd_spider: str,
        scrapyd_project: str = "job_scraper_spiders",
        scrapyd_job_id: str | None = None,
        request_payload: dict | None = None,
    ) -> CrawlRun:
        run = CrawlRun(
            id=uuid4(),
            crawl_job_id=crawl_job_id,
            source_site=source_site,
            scrapyd_project=scrapyd_project,
            scrapyd_spider=scrapyd_spider,
            scrapyd_job_id=scrapyd_job_id,
            status="pending",
            request_payload=json.dumps(request_payload) if request_payload else None,
            created_at=datetime.utcnow(),
        )
        return self._repository.create(db, crawl_run=run)

    def mark_started(self, db: Session, run_id: UUID) -> CrawlRun | None:
        run = self._repository.update_status(db, run_id, status="running")
        if run:
            run.started_at = datetime.utcnow()
            db.flush()
        return run

    def mark_completed(self, db: Session, run_id: UUID) -> CrawlRun | None:
        run = self._repository.update_status(db, run_id, status="completed")
        if run:
            run.completed_at = datetime.utcnow()
            db.flush()
        return run

    def mark_failed(self, db: Session, run_id: UUID) -> CrawlRun | None:
        run = self._repository.update_status(db, run_id, status="failed")
        if run:
            run.completed_at = datetime.utcnow()
            db.flush()
        return run

    def mark_cancelled(self, db: Session, run_id: UUID) -> CrawlRun | None:
        return self._repository.update_status(db, run_id, status="cancelled")

    def update_progress(
        self,
        db: Session,
        run_id: UUID,
        *,
        pages_processed: int | None = None,
        listings_staged: int | None = None,
        details_completed: int | None = None,
        details_failed: int | None = None,
    ) -> CrawlRun | None:
        return self._repository.update_progress(
            db,
            run_id,
            pages_processed=pages_processed,
            listings_staged=listings_staged,
            details_completed=details_completed,
            details_failed=details_failed,
        )
