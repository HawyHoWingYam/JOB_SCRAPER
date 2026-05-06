from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.messaging.topics import STREAM_CRAWL_COMMANDS
from app.models.crawl_job import CrawlJob
from app.models.schedule import ScrapeSchedule, ScheduleExecution
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.services.progress_store import get_progress_store
from app.utils.time import utc_now


@dataclass(frozen=True)
class CrawlJobDispatchResult:
    crawl_job: CrawlJob
    schedule_execution: ScheduleExecution | None


class CrawlJobDispatchService:
    """Create durable crawl jobs, events, and outbox records in one transaction."""

    def __init__(
        self,
        *,
        crawl_job_repository: CrawlJobRepository | None = None,
        event_outbox_repository: EventOutboxRepository | None = None,
        schedule_repository: ScheduleRepository | None = None,
    ):
        self.crawl_job_repository = crawl_job_repository or CrawlJobRepository()
        self.event_outbox_repository = event_outbox_repository or EventOutboxRepository()
        self.schedule_repository = schedule_repository or ScheduleRepository()
        self.progress_store = get_progress_store()

    def dispatch_manual_crawl_job(
        self,
        db: Session,
        *,
        source_site: str,
        category_ids: list[int | str],
        max_pages: int,
        skip_existing: bool = False,
        requested_by: str | None = None,
    ) -> CrawlJobDispatchResult:
        return self.dispatch_crawl_job(
            db,
            source_site=source_site,
            trigger_type="manual",
            request_payload={
                "source_site": source_site,
                "category_ids": category_ids,
                "max_pages": max_pages,
                "skip_existing": skip_existing,
            },
            requested_by=requested_by,
        )

    def dispatch_schedule_crawl_job(
        self,
        db: Session,
        *,
        schedule: ScrapeSchedule,
        requested_by: str = "scheduler-worker",
        trigger_type: str = "schedule",
    ) -> CrawlJobDispatchResult:
        request_payload = {
            "source_site": schedule.source_site,
            "category_ids": list(schedule.category_ids or []),
            "keywords": schedule.keywords,
            "location": schedule.location,
            "max_pages": schedule.max_pages or 3,
            "skip_existing": True,
        }
        return self.dispatch_crawl_job(
            db,
            source_site=schedule.source_site,
            trigger_type=trigger_type,
            request_payload=request_payload,
            requested_by=requested_by,
            schedule_id=schedule.id,
        )

    def dispatch_crawl_job(
        self,
        db: Session,
        *,
        source_site: str,
        trigger_type: str,
        request_payload: dict[str, Any],
        requested_by: str | None = None,
        schedule_id=None,
        schedule_execution: ScheduleExecution | None = None,
    ) -> CrawlJobDispatchResult:
        payload = dict(request_payload)
        if schedule_id is not None:
            payload.setdefault("schedule_id", str(schedule_id))

        execution = schedule_execution
        if schedule_id is not None and execution is None:
            execution = self.schedule_repository.create_execution(
                db,
                schedule_id=schedule_id,
                status="pending",
                auto_commit=False,
            )

        crawl_job = self.crawl_job_repository.create_crawl_job(
            db,
            source_site=source_site,
            trigger_type=trigger_type,
            request_payload=payload,
            requested_by=requested_by,
            schedule_id=schedule_id,
            status="queued",
            auto_commit=False,
        )

        event_payload = self._build_requested_event_payload(crawl_job)
        self.crawl_job_repository.append_event(
            db,
            crawl_job_id=crawl_job.id,
            event_type="crawl.requested",
            payload=event_payload,
            emitted_by=requested_by or trigger_type,
            auto_commit=False,
        )
        self.event_outbox_repository.enqueue(
            db,
            topic=STREAM_CRAWL_COMMANDS,
            aggregate_type="crawl_job",
            aggregate_id=str(crawl_job.id),
            event_type="crawl.requested",
            payload=event_payload,
            auto_commit=False,
        )

        if execution is not None:
            execution.crawl_job_id = crawl_job.id

        db.commit()
        db.refresh(crawl_job)
        if execution is not None:
            db.refresh(execution)

        self.progress_store.update(str(crawl_job.id), self._build_progress_snapshot(crawl_job))
        return CrawlJobDispatchResult(crawl_job=crawl_job, schedule_execution=execution)

    def cancel_crawl_job(
        self,
        db: Session,
        *,
        crawl_job_id,
        requested_by: str | None = None,
        reason: str = "Cancelled by API request.",
    ) -> CrawlJob:
        crawl_job = self.crawl_job_repository.get_crawl_job_by_id(db, crawl_job_id)
        if crawl_job is None:
            raise ValueError(f"Crawl job not found: {crawl_job_id}")

        if crawl_job.status in {"completed", "failed", "cancelled"}:
            raise RuntimeError(f"Crawl job cannot be cancelled from status '{crawl_job.status}'")

        crawl_job.status = "cancelled"
        crawl_job.completed_at = utc_now()
        crawl_job.error_message = reason

        event_payload = {
            "crawl_job_id": str(crawl_job.id),
            "source_site": crawl_job.source_site,
            "schedule_id": str(crawl_job.schedule_id) if crawl_job.schedule_id else None,
            "reason": reason,
            "requested_by": requested_by,
            "status": crawl_job.status,
        }
        self.crawl_job_repository.append_event(
            db,
            crawl_job_id=crawl_job.id,
            event_type="crawl.cancelled",
            payload=event_payload,
            emitted_by=requested_by or "api",
            auto_commit=False,
        )
        self.event_outbox_repository.enqueue(
            db,
            topic=STREAM_CRAWL_COMMANDS,
            aggregate_type="crawl_job",
            aggregate_id=str(crawl_job.id),
            event_type="crawl.cancelled",
            payload=event_payload,
            auto_commit=False,
        )

        db.commit()
        db.refresh(crawl_job)
        self.progress_store.update(
            str(crawl_job.id),
            {
                **self._build_progress_snapshot(crawl_job),
                "status": "cancelled",
                "completed_at": crawl_job.completed_at.isoformat() if crawl_job.completed_at else None,
                "error": reason,
            },
        )
        return crawl_job

    def _build_requested_event_payload(self, crawl_job: CrawlJob) -> dict[str, Any]:
        return {
            "crawl_job_id": str(crawl_job.id),
            "source_site": crawl_job.source_site,
            "trigger_type": crawl_job.trigger_type,
            "schedule_id": str(crawl_job.schedule_id) if crawl_job.schedule_id else None,
            "requested_by": crawl_job.requested_by,
            "request_payload": crawl_job.request_payload,
            "status": crawl_job.status,
            "queued_at": crawl_job.queued_at.isoformat() if crawl_job.queued_at else None,
        }

    def _build_progress_snapshot(self, crawl_job: CrawlJob) -> dict[str, Any]:
        request_payload = crawl_job.request_payload or {}
        category_ids = list(request_payload.get("category_ids") or [])
        category_label = ", ".join(str(category_id) for category_id in category_ids[:3])
        if len(category_ids) > 3:
            category_label = f"{category_label}, +{len(category_ids) - 3}"
        if not category_label:
            category_label = f"{crawl_job.source_site} crawl"

        return {
            "crawl_job_id": str(crawl_job.id),
            "status": crawl_job.status,
            "phase": 0,
            "source_site": crawl_job.source_site,
            "trigger_type": crawl_job.trigger_type,
            "schedule_id": str(crawl_job.schedule_id) if crawl_job.schedule_id else None,
            "category_name": category_label,
            "category_ids": category_ids,
            "request_payload": request_payload,
            "queued_at": crawl_job.queued_at.isoformat() if crawl_job.queued_at else None,
            "updated_at": crawl_job.updated_at.isoformat() if crawl_job.updated_at else None,
            "elapsed_seconds": 0,
            "phase_rate": 0,
        }
