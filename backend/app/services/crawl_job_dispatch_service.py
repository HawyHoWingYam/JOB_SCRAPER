from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.crawl_phases import resolve_crawl_phase, resolve_detail_statuses
from app.crawl_modes import normalize_source_site, resolve_crawl_mode
from app.messaging.outbox_publisher import OutboxPublisher
from app.messaging.topics import STREAM_CRAWL_COMMANDS, STREAM_CRAWL_COMMANDS_HEADED
from app.models.crawl_job import CrawlJob
from app.models.schedule import ScrapeSchedule, ScheduleExecution
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.services.headed_crawl_runtime import ensure_headed_crawl_worker_available
from app.services.source_catalog import resolve_default_max_pages
from app.scraper.manual_action import (
    LEGACY_RESUME_STRATEGY_DEFAULT,
    ResumeStrategy,
    SUPPORTED_RESUME_STRATEGIES,
)
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

RESUME_CONTEXT_EVENT_TYPES = {
    "crawl.manual_action_required",
    "crawl.requested",
}


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
        outbox_publisher: OutboxPublisher | None = None,
        schedule_repository: ScheduleRepository | None = None,
    ):
        self.crawl_job_repository = crawl_job_repository or CrawlJobRepository()
        self.event_outbox_repository = event_outbox_repository or EventOutboxRepository()
        self.outbox_publisher = outbox_publisher or OutboxPublisher()
        self.schedule_repository = schedule_repository or ScheduleRepository()

    def build_manual_request_payload(
        self,
        *,
        source_site: str,
        crawl_phase: str | None = None,
        crawl_mode: str | None = None,
        category_ids: list[int | str],
        keywords: str | None = None,
        max_pages: int | None,
        source_listing_crawl_job_id=None,
        detail_limit: int = 100,
        detail_statuses: list[str] | None = None,
        skip_existing: bool = False,
    ) -> dict[str, Any]:
        resolved_phase = resolve_crawl_phase(crawl_phase)
        return {
            "source_site": source_site,
            "crawl_phase": resolved_phase,
            "crawl_mode": resolve_crawl_mode(source_site, crawl_mode),
            "category_ids": list(category_ids),
            "keywords": keywords,
            "max_pages": int(max_pages) if max_pages is not None else resolve_default_max_pages(source_site),
            "source_listing_crawl_job_id": str(source_listing_crawl_job_id)
            if source_listing_crawl_job_id is not None
            else None,
            "detail_limit": int(detail_limit),
            "detail_statuses": resolve_detail_statuses(
                crawl_phase=resolved_phase,
                detail_statuses=detail_statuses,
            ),
            "skip_existing": skip_existing,
        }

    def build_schedule_request_payload(self, *, schedule: ScrapeSchedule) -> dict[str, Any]:
        resolved_phase = resolve_crawl_phase(getattr(schedule, "crawl_phase", None))
        payload = {
            "source_site": schedule.source_site,
            "crawl_phase": resolved_phase,
            "crawl_mode": resolve_crawl_mode(schedule.source_site, getattr(schedule, "crawl_mode", None)),
            "category_ids": list(schedule.category_ids or []),
            "keywords": schedule.keywords,
            "max_pages": schedule.max_pages or 3,
            "detail_limit": int(getattr(schedule, "detail_limit", 100) or 100),
            "detail_statuses": resolve_detail_statuses(
                crawl_phase=resolved_phase,
                detail_statuses=None,
            ),
            "skip_existing": True,
        }
        if getattr(schedule, "location", None):
            payload["location"] = schedule.location
        return payload

    def dispatch_manual_crawl_job(
        self,
        db: Session,
        *,
        source_site: str,
        crawl_phase: str | None = None,
        crawl_mode: str | None = None,
        category_ids: list[int | str],
        keywords: str | None = None,
        max_pages: int | None,
        source_listing_crawl_job_id=None,
        detail_limit: int = 100,
        detail_statuses: list[str] | None = None,
        skip_existing: bool = False,
        requested_by: str | None = None,
    ) -> CrawlJobDispatchResult:
        return self.dispatch_crawl_job(
            db,
            source_site=source_site,
            trigger_type="manual",
            request_payload=self.build_manual_request_payload(
                source_site=source_site,
                crawl_phase=crawl_phase,
                crawl_mode=crawl_mode,
                category_ids=category_ids,
                keywords=keywords,
                max_pages=max_pages,
                source_listing_crawl_job_id=source_listing_crawl_job_id,
                detail_limit=detail_limit,
                detail_statuses=detail_statuses,
                skip_existing=skip_existing,
            ),
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
        schedule.last_run_at = utc_now()
        return self.dispatch_crawl_job(
            db,
            source_site=schedule.source_site,
            trigger_type=trigger_type,
            request_payload=self.build_schedule_request_payload(schedule=schedule),
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
        payload["crawl_phase"] = resolve_crawl_phase(payload.get("crawl_phase"))
        payload["crawl_mode"] = resolve_crawl_mode(source_site, payload.get("crawl_mode"))
        ensure_headed_crawl_worker_available(crawl_mode=payload.get("crawl_mode"), source_site=source_site)
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

        if execution is not None:
            execution.crawl_job_id = crawl_job.id
            execution.request_payload_snapshot = dict(payload)

        event_payload = self._build_requested_event_payload(crawl_job)
        self.crawl_job_repository.append_event(
            db,
            crawl_job_id=crawl_job.id,
            event_type="crawl.requested",
            payload=event_payload,
            emitted_by=requested_by or trigger_type,
            auto_commit=False,
        )
        command_row = self.event_outbox_repository.enqueue(
            db,
            topic=self._resolve_command_topic(source_site=source_site, crawl_mode=payload.get("crawl_mode")),
            aggregate_type="crawl_job",
            aggregate_id=str(crawl_job.id),
            event_type="crawl.requested",
            payload=event_payload,
            auto_commit=False,
        )

        db.commit()
        db.refresh(crawl_job)
        if execution is not None:
            db.refresh(execution)
        self.outbox_publisher.publish_row(db, row=command_row)
        self.outbox_publisher.publish_pending_batch(db, limit=100)

        logger.info(
            "SCRAPE_DISPATCHED source=%s crawl_job_id=%s phase=%s mode=%s trigger=%s topic=%s",
            source_site,
            crawl_job.id,
            payload.get("crawl_phase"),
            payload.get("crawl_mode"),
            trigger_type,
            self._resolve_command_topic(source_site=source_site, crawl_mode=payload.get("crawl_mode")),
        )
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
            "crawl_phase": resolve_crawl_phase((crawl_job.request_payload or {}).get("crawl_phase")),
            "crawl_mode": resolve_crawl_mode(
                crawl_job.source_site,
                (crawl_job.request_payload or {}).get("crawl_mode"),
            ),
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
        command_row = self.event_outbox_repository.enqueue(
            db,
            topic=self._resolve_command_topic(
                source_site=crawl_job.source_site,
                crawl_mode=(crawl_job.request_payload or {}).get("crawl_mode"),
            ),
            aggregate_type="crawl_job",
            aggregate_id=str(crawl_job.id),
            event_type="crawl.cancelled",
            payload=event_payload,
            auto_commit=False,
        )

        db.commit()
        db.refresh(crawl_job)
        self.outbox_publisher.publish_row(db, row=command_row)
        self.outbox_publisher.publish_pending_batch(db, limit=100)
        return crawl_job

    def resume_crawl_job(
        self,
        db: Session,
        *,
        crawl_job_id,
        requested_by: str | None = None,
        strategy: ResumeStrategy | None = None,
    ) -> CrawlJob:
        crawl_job = self.crawl_job_repository.get_crawl_job_by_id(db, crawl_job_id)
        if crawl_job is None:
            raise ValueError(f"Crawl job not found: {crawl_job_id}")

        if crawl_job.status != "manual_action_required":
            raise RuntimeError(f"Crawl job cannot be resumed from status '{crawl_job.status}'")

        latest_event = self.crawl_job_repository.get_latest_manual_action_event(db, crawl_job_id)
        if latest_event is None:
            raise RuntimeError("Crawl job is not resumable from its latest event")

        manual_action = dict((latest_event.payload or {}).get("manual_action") or {})
        if not manual_action.get("resume_supported"):
            raise RuntimeError("Crawl job manual action does not support resume")

        selected_strategy = LEGACY_RESUME_STRATEGY_DEFAULT if strategy is None else strategy
        if selected_strategy not in SUPPORTED_RESUME_STRATEGIES:
            raise RuntimeError(f"Unsupported resume strategy: {selected_strategy}")

        resume_context = dict(manual_action.get("resume_context") or {})
        if not resume_context:
            resume_context = self._recover_previous_resume_context(db, crawl_job_id=crawl_job_id)
        request_payload = dict(crawl_job.request_payload or {})
        request_payload["is_resume"] = True
        request_payload["resume_context"] = resume_context
        request_payload["resume_strategy"] = selected_strategy
        if resume_context.get("crawl_phase") == "detail":
            source_listing_crawl_job_id = resume_context.get("source_listing_crawl_job_id")
            if source_listing_crawl_job_id and not request_payload.get("source_listing_crawl_job_id"):
                request_payload["source_listing_crawl_job_id"] = source_listing_crawl_job_id
            request_payload["detail_statuses"] = ["manual_action_required", "pending"]
        ensure_headed_crawl_worker_available(
            crawl_mode=request_payload.get("crawl_mode"),
            source_site=crawl_job.source_site,
        )

        crawl_job.status = "dispatching"
        crawl_job.completed_at = None
        crawl_job.error_message = None
        crawl_job.request_payload = request_payload

        resume_requested_payload = {
            "crawl_job_id": str(crawl_job.id),
            "source_site": crawl_job.source_site,
            "requested_by": requested_by,
            "status": crawl_job.status,
            "strategy": selected_strategy,
            "manual_action": manual_action,
        }
        self.crawl_job_repository.append_event(
            db,
            crawl_job_id=crawl_job.id,
            event_type="crawl.resume_requested",
            payload=resume_requested_payload,
            emitted_by=requested_by or "api",
            auto_commit=False,
        )

        requested_payload = self._build_requested_event_payload(crawl_job)
        self.crawl_job_repository.append_event(
            db,
            crawl_job_id=crawl_job.id,
            event_type="crawl.requested",
            payload=requested_payload,
            emitted_by=requested_by or "api",
            auto_commit=False,
        )
        command_row = self.event_outbox_repository.enqueue(
            db,
            topic=self._resolve_command_topic(
                source_site=crawl_job.source_site,
                crawl_mode=request_payload.get("crawl_mode"),
            ),
            aggregate_type="crawl_job",
            aggregate_id=str(crawl_job.id),
            event_type="crawl.requested",
            payload=requested_payload,
            auto_commit=False,
        )

        db.commit()
        db.refresh(crawl_job)
        self.outbox_publisher.publish_row(db, row=command_row)
        self.outbox_publisher.publish_pending_batch(db, limit=100)
        return crawl_job

    def _build_requested_event_payload(self, crawl_job: CrawlJob) -> dict[str, Any]:
        return {
            "crawl_job_id": str(crawl_job.id),
            "source_site": crawl_job.source_site,
            "crawl_phase": resolve_crawl_phase((crawl_job.request_payload or {}).get("crawl_phase")),
            "crawl_mode": resolve_crawl_mode(
                crawl_job.source_site,
                (crawl_job.request_payload or {}).get("crawl_mode"),
            ),
            "trigger_type": crawl_job.trigger_type,
            "schedule_id": str(crawl_job.schedule_id) if crawl_job.schedule_id else None,
            "requested_by": crawl_job.requested_by,
            "request_payload": crawl_job.request_payload,
            "status": crawl_job.status,
            "queued_at": crawl_job.queued_at.isoformat() if crawl_job.queued_at else None,
        }

    def _resolve_command_topic(self, *, source_site: str, crawl_mode: str | None) -> str:
        effective_mode = resolve_crawl_mode(source_site, crawl_mode)
        if effective_mode == "headed":
            # OfferToday runs headed mode inside the same Docker container —
            # no separate host-side worker needed.
            if normalize_source_site(source_site) == "offertoday":
                return STREAM_CRAWL_COMMANDS
            return STREAM_CRAWL_COMMANDS_HEADED
        return STREAM_CRAWL_COMMANDS

    def _recover_previous_resume_context(self, db: Session, *, crawl_job_id) -> dict[str, Any]:
        for event in reversed(
            self.crawl_job_repository.list_events(
                db,
                crawl_job_id,
                event_types=RESUME_CONTEXT_EVENT_TYPES,
            )
        ):
            payload = dict(event.payload or {})
            manual_action = dict(payload.get("manual_action") or {})
            manual_resume_context = dict(manual_action.get("resume_context") or {})
            if manual_resume_context:
                return manual_resume_context

            request_payload = dict(payload.get("request_payload") or {})
            request_resume_context = dict(request_payload.get("resume_context") or {})
            if request_resume_context:
                return request_resume_context

        return {}

