from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import desc, func
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.models.crawl_job import CrawlJob, CrawlJobEvent
from app.models.schedule import ScheduleExecution
from app.utils.time import utc_now

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
        self._sync_linked_schedule_execution(
            db,
            crawl_job=crawl_job,
            event_type=event_type,
            payload=payload,
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
        self._sync_linked_schedule_execution(db, crawl_job=crawl_job)

        if auto_commit:
            db.commit()
            db.refresh(crawl_job)
        else:
            db.flush()
        return crawl_job

    def list_events(
        self,
        db: Session,
        crawl_job_id,
        event_types: set[str] | list[str] | None = None,
    ) -> list[CrawlJobEvent]:
        query = db.query(CrawlJobEvent).filter(CrawlJobEvent.crawl_job_id == crawl_job_id)
        if event_types:
            query = query.filter(CrawlJobEvent.event_type.in_(list(event_types)))
        return query.order_by(CrawlJobEvent.sequence_no.asc()).all()

    def get_latest_event(self, db: Session, crawl_job_id) -> CrawlJobEvent | None:
        return (
            db.query(CrawlJobEvent)
            .filter(CrawlJobEvent.crawl_job_id == crawl_job_id)
            .order_by(CrawlJobEvent.sequence_no.desc())
            .first()
        )

    def list_latest_events_for_jobs(
        self,
        db: Session,
        *,
        crawl_job_ids,
    ) -> dict[Any, CrawlJobEvent]:
        normalized_job_ids = list(dict.fromkeys(crawl_job_ids))
        if not normalized_job_ids:
            return {}

        latest_sequence_by_job = (
            db.query(
                CrawlJobEvent.crawl_job_id.label("crawl_job_id"),
                func.max(CrawlJobEvent.sequence_no).label("latest_sequence_no"),
            )
            .filter(CrawlJobEvent.crawl_job_id.in_(normalized_job_ids))
            .group_by(CrawlJobEvent.crawl_job_id)
            .subquery()
        )
        latest_events = (
            db.query(CrawlJobEvent)
            .join(
                latest_sequence_by_job,
                (CrawlJobEvent.crawl_job_id == latest_sequence_by_job.c.crawl_job_id)
                & (CrawlJobEvent.sequence_no == latest_sequence_by_job.c.latest_sequence_no),
            )
            .all()
        )
        latest_events_by_job = {event.crawl_job_id: event for event in latest_events}
        return {
            crawl_job_id: latest_events_by_job[crawl_job_id]
            for crawl_job_id in normalized_job_ids
            if crawl_job_id in latest_events_by_job
        }

    def list_events_by_job_ids(
        self,
        db: Session,
        *,
        crawl_job_ids,
        event_types: set[str] | list[str] | None = None,
    ) -> dict[Any, list[CrawlJobEvent]]:
        normalized_job_ids = list(dict.fromkeys(crawl_job_ids))
        if not normalized_job_ids:
            return {}

        query = db.query(CrawlJobEvent).filter(CrawlJobEvent.crawl_job_id.in_(normalized_job_ids))
        if event_types:
            query = query.filter(CrawlJobEvent.event_type.in_(list(event_types)))
        events = (
            query.order_by(CrawlJobEvent.crawl_job_id.asc(), CrawlJobEvent.sequence_no.asc()).all()
        )

        grouped_events: defaultdict[Any, list[CrawlJobEvent]] = defaultdict(list)
        for event in events:
            grouped_events[event.crawl_job_id].append(event)
        return dict(grouped_events)

    def get_latest_manual_action_event(self, db: Session, crawl_job_id) -> CrawlJobEvent | None:
        return (
            db.query(CrawlJobEvent)
            .filter(CrawlJobEvent.crawl_job_id == crawl_job_id)
            .filter(CrawlJobEvent.event_type == "crawl.manual_action_required")
            .order_by(CrawlJobEvent.sequence_no.desc())
            .first()
        )

    def list_recent_crawl_jobs(self, db: Session, *, limit: int = 100) -> list[CrawlJob]:
        return (
            db.query(CrawlJob)
            .order_by(desc(CrawlJob.queued_at), desc(CrawlJob.created_at))
            .limit(limit)
            .all()
        )

    def list_crawl_jobs_by_statuses(
        self,
        db: Session,
        *,
        statuses: set[str] | list[str],
    ) -> list[CrawlJob]:
        if not statuses:
            return []
        return (
            db.query(CrawlJob)
            .filter(CrawlJob.status.in_(list(statuses)))
            .order_by(desc(CrawlJob.queued_at), desc(CrawlJob.created_at))
            .all()
        )

    def _merge_metrics(self, existing_metrics, metrics_patch: dict[str, Any]) -> dict[str, Any]:
        merged = dict(existing_metrics or {})
        for key, value in (metrics_patch or {}).items():
            merged[key] = value
        return merged

    def _sync_linked_schedule_execution(
        self,
        db: Session,
        *,
        crawl_job: CrawlJob,
        event_type: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        try:
            execution = (
                db.query(ScheduleExecution)
                .filter(ScheduleExecution.crawl_job_id == crawl_job.id)
                .order_by(desc(ScheduleExecution.started_at), desc(ScheduleExecution.created_at))
                .first()
            )
        except (OperationalError, ProgrammingError):
            return
        if execution is None:
            return

        metrics = dict(crawl_job.metrics or {})
        payload = dict(payload or {})
        items_emitted = self._metric_as_int(metrics.get("items_emitted"))
        ingest_items_seen = self._metric_as_int(metrics.get("ingest_items_seen"))
        ids_collected = self._metric_as_int(metrics.get("job_ids_collected"))
        pages_processed = self._metric_as_int(metrics.get("pages_processed"))

        execution.started_at = crawl_job.started_at or execution.started_at
        execution.ids_collected = ids_collected
        execution.jobs_scraped = items_emitted
        execution.jobs_saved = ingest_items_seen

        current_page = self._metric_as_int(payload.get("current_page"))
        total_pages = self._metric_as_int(payload.get("total_pages"))
        if (total_pages > 0 and current_page >= total_pages) or (
            pages_processed > 0 and crawl_job.status in {"completed", "failed", "cancelled"}
        ):
            execution.phase1_completed = True

        if event_type in {"crawl.completed", "crawl.failed", "crawl.cancelled"}:
            execution.phase2_completed = True

        save_backlog_remaining = items_emitted > ingest_items_seen
        execution.phase4_completed = items_emitted == 0 or not save_backlog_remaining

        if crawl_job.status in {"queued", "dispatching"}:
            execution.status = "pending"
            execution.completed_at = None
            execution.duration_seconds = None
            execution.error_message = None
            return

        if crawl_job.status == "running":
            execution.status = "running"
            execution.completed_at = None
            execution.duration_seconds = None
            execution.error_message = None
            return

        if crawl_job.status == "completed" and save_backlog_remaining:
            execution.status = "running"
            execution.completed_at = None
            execution.duration_seconds = None
            execution.error_message = None
            return

        terminal_status = "failed" if crawl_job.status == "cancelled" else crawl_job.status
        execution.status = terminal_status
        execution.error_message = crawl_job.error_message if terminal_status == "failed" else None
        execution.completed_at = crawl_job.completed_at or execution.completed_at or utc_now()
        if execution.started_at is not None and execution.completed_at is not None:
            started_at = execution.started_at
            completed_at = execution.completed_at
            if started_at.tzinfo is not None and completed_at.tzinfo is None:
                completed_at = completed_at.replace(tzinfo=started_at.tzinfo)
            elif started_at.tzinfo is None and completed_at.tzinfo is not None:
                started_at = started_at.replace(tzinfo=completed_at.tzinfo)
            try:
                execution.duration_seconds = max(
                    0,
                    int((completed_at - started_at).total_seconds()),
                )
            except TypeError:
                execution.duration_seconds = None

    def _metric_as_int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
