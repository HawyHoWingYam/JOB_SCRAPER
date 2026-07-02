"""Repository for CrawlRun persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.crawl_run import CrawlRun


class CrawlRunRepository:
    """Data access layer for CrawlRun records."""

    def create(self, db: Session, *, crawl_run: CrawlRun) -> CrawlRun:
        db.add(crawl_run)
        db.flush()
        return crawl_run

    def get_by_id(self, db: Session, run_id: UUID) -> CrawlRun | None:
        return db.query(CrawlRun).filter(CrawlRun.id == run_id).first()

    def get_by_scrapyd_job_id(self, db: Session, scrapyd_job_id: str) -> CrawlRun | None:
        return (
            db.query(CrawlRun)
            .filter(CrawlRun.scrapyd_job_id == scrapyd_job_id)
            .first()
        )

    def get_by_crawl_job_id(self, db: Session, crawl_job_id: UUID) -> list[CrawlRun]:
        return (
            db.query(CrawlRun)
            .filter(CrawlRun.crawl_job_id == crawl_job_id)
            .order_by(CrawlRun.created_at.desc())
            .all()
        )

    def list_by_source(self, db: Session, source_site: str, limit: int = 20) -> list[CrawlRun]:
        return (
            db.query(CrawlRun)
            .filter(CrawlRun.source_site == source_site)
            .order_by(CrawlRun.created_at.desc())
            .limit(limit)
            .all()
        )

    def update_status(
        self,
        db: Session,
        run_id: UUID,
        *,
        status: str,
    ) -> CrawlRun | None:
        run = self.get_by_id(db, run_id)
        if run is None:
            return None
        run.status = status
        db.flush()
        return run

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
        run = self.get_by_id(db, run_id)
        if run is None:
            return None
        if pages_processed is not None:
            run.pages_processed = pages_processed
        if listings_staged is not None:
            run.listings_staged = listings_staged
        if details_completed is not None:
            run.details_completed = details_completed
        if details_failed is not None:
            run.details_failed = details_failed
        db.flush()
        return run

    def delete(self, db: Session, run_id: UUID) -> bool:
        run = self.get_by_id(db, run_id)
        if run is None:
            return False
        db.delete(run)
        db.flush()
        return True
