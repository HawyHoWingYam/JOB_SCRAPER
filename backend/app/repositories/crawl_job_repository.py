from __future__ import annotations

from typing import Any

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models.crawl_job import CrawlJob, CrawlJobEvent

_UNSET = object()


class CrawlJobRepository:
    """Repository for durable crawl jobs and their ordered event history."""

    def create_crawl_job(
        self,
        db: Session,
        *,
        source_site: str,
        trigger_type: str,
        request_payload: dict[str, Any],
        requested_by: str | None = None,
        schedule_id=None,
        status: str = "queued",
        auto_commit: bool = True,
    ) -> CrawlJob:
        crawl_job = CrawlJob(
            source_site=source_site,
            trigger_type=trigger_type,
            schedule_id=schedule_id,
            status=status,
            request_payload=request_payload,
            requested_by=requested_by,
        )
        db.add(crawl_job)
        if auto_commit:
            db.commit()
            db.refresh(crawl_job)
        else:
            db.flush()
        return crawl_job

    def append_event(
        self,
        db: Session,
        *,
        crawl_job_id,
        event_type: str,
        payload: dict[str, Any],
        emitted_by: str | None = None,
        auto_commit: bool = True,
    ) -> CrawlJobEvent:
        crawl_job = (
            db.query(CrawlJob)
            .filter(CrawlJob.id == crawl_job_id)
            .with_for_update()
            .one_or_none()
        )
        if crawl_job is None:
            raise ValueError(f"Crawl job not found: {crawl_job_id}")

        next_sequence_no = (
            db.query(func.coalesce(func.max(CrawlJobEvent.sequence_no), 0))
            .filter(CrawlJobEvent.crawl_job_id == crawl_job_id)
            .scalar()
            + 1
        )
        event = CrawlJobEvent(
            crawl_job_id=crawl_job_id,
            sequence_no=int(next_sequence_no),
            event_type=event_type,
            payload=payload,
            emitted_by=emitted_by,
        )
        db.add(event)
        if auto_commit:
            db.commit()
            db.refresh(event)
        else:
            db.flush()
        return event

    def get_crawl_job_by_id(self, db: Session, crawl_job_id) -> CrawlJob | None:
        return db.query(CrawlJob).filter(CrawlJob.id == crawl_job_id).first()

    def record_runtime_event(
        self,
        db: Session,
        *,
        crawl_job_id,
        status: str,
        event_type: str,
        payload: dict[str, Any],
        emitted_by: str = "crawl-worker",
        started_at=_UNSET,
        completed_at=_UNSET,
        error_message=_UNSET,
        metrics: dict[str, Any] | None = None,
        auto_commit: bool = True,
    ) -> CrawlJob:
        crawl_job = (
            db.query(CrawlJob)
            .filter(CrawlJob.id == crawl_job_id)
            .with_for_update()
            .one_or_none()
        )
        if crawl_job is None:
            raise ValueError(f"Crawl job not found: {crawl_job_id}")

        crawl_job.status = status
        if started_at is not _UNSET:
            crawl_job.started_at = started_at
        if completed_at is not _UNSET:
            crawl_job.completed_at = completed_at
        if error_message is not _UNSET:
            crawl_job.error_message = error_message
        if metrics is not None:
            crawl_job.metrics = self._merge_metrics(crawl_job.metrics, metrics)

        self.append_event(
            db,
            crawl_job_id=crawl_job_id,
            event_type=event_type,
            payload=payload,
            emitted_by=emitted_by,
            auto_commit=False,
        )

        if auto_commit:
            db.commit()
            db.refresh(crawl_job)
        else:
            db.flush()
        return crawl_job

    def increment_metrics(
        self,
        db: Session,
        *,
        crawl_job_id,
        metrics_delta: dict[str, Any],
        auto_commit: bool = True,
    ) -> CrawlJob:
        crawl_job = (
            db.query(CrawlJob)
            .filter(CrawlJob.id == crawl_job_id)
            .with_for_update()
            .one_or_none()
        )
        if crawl_job is None:
            raise ValueError(f"Crawl job not found: {crawl_job_id}")

        merged_metrics = self._merge_metrics(crawl_job.metrics, {})
        for key, value in metrics_delta.items():
            merged_metrics[key] = int(merged_metrics.get(key) or 0) + int(value)
        crawl_job.metrics = merged_metrics

        if auto_commit:
            db.commit()
            db.refresh(crawl_job)
        else:
            db.flush()
        return crawl_job

    def list_events(self, db: Session, crawl_job_id) -> list[CrawlJobEvent]:
        return (
            db.query(CrawlJobEvent)
            .filter(CrawlJobEvent.crawl_job_id == crawl_job_id)
            .order_by(CrawlJobEvent.sequence_no.asc())
            .all()
        )

    def list_recent_crawl_jobs(self, db: Session, *, limit: int = 100) -> list[CrawlJob]:
        return (
            db.query(CrawlJob)
            .order_by(desc(CrawlJob.queued_at), desc(CrawlJob.created_at))
            .limit(limit)
            .all()
        )

    def _merge_metrics(self, existing_metrics, metrics_patch: dict[str, Any]) -> dict[str, Any]:
        merged = dict(existing_metrics or {})
        for key, value in (metrics_patch or {}).items():
            merged[key] = value
        return merged
