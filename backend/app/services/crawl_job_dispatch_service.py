from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.crawl_cancellation import (
    ACTIVE_MANUAL_DETAIL_STATUSES,
    can_request_cancellation,
)
from app.crawl_phases import resolve_crawl_phase
from app.crawl_modes import normalize_source_site, resolve_crawl_mode
from app.crawl_control.dispatch_plan_contracts import (
    DispatchPlanSnapshotV1,
    ExecutionAuthorityV1,
    ExecutionResumeContextV1,
    OneOffRunV1,
    SavedAutomationRunV1,
)
from app.crawl_control.contracts import (
    AuthoredCrawlScopeV1,
    CrawlScopeBacklogScopeV1,
    DetailSettingsV1,
    ListingBatchBacklogScopeV1,
    ListingSettingsV1,
    SourceBacklogScopeV1,
    StopAfterDetailLimitV1,
)
from app.crawl_control.dispatch_plan_service import DispatchPlanService
from app.crawl_control.errors import (
    DispatchPlanExpiredError,
    DispatchPlanReviewRequiredError,
)
from app.messaging.outbox_publisher import OutboxPublisher
from app.messaging.topics import STREAM_CRAWL_COMMANDS, STREAM_CRAWL_COMMANDS_HEADED
from app.models.crawl_job import CrawlJob
from app.models.schedule import ScrapeSchedule, ScheduleExecution
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.repositories.crawl_job_execution_repository import CrawlJobExecutionRepository
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.services.crawl_job_execution_launcher import CrawlJobExecutionLauncher
from app.services.headed_crawl_runtime import ensure_headed_crawl_worker_available
from app.services.source_sites import resolve_default_max_pages
from app.services.scraper_pacing_settings_service import ScraperPacingSettingsService
from app.scraper.manual_action import (
    DEFAULT_RESUME_STRATEGY,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
    ResumeStrategy,
    SUPPORTED_RESUME_STRATEGIES,
    normalize_manual_action_payload,
)
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

class ActiveManualDetailCrawlConflict(RuntimeError):
    pass


def resolve_resume_detail_statuses(classification: str | None) -> list[str]:
    if str(classification or "").strip().lower() == "content_anomaly":
        return ["failed", "manual_action_required", "pending"]
    return ["manual_action_required", "pending"]


@dataclass(frozen=True)
class CrawlJobDispatchResult:
    crawl_job: CrawlJob
    schedule_execution: ScheduleExecution | None
    dispatch_plan: DispatchPlanSnapshotV1 | None = None


class CrawlJobDispatchService:
    """Create durable crawl jobs, events, and outbox records in one transaction."""

    def __init__(
        self,
        *,
        crawl_job_repository: CrawlJobRepository | None = None,
        event_outbox_repository: EventOutboxRepository | None = None,
        outbox_publisher: OutboxPublisher | None = None,
        schedule_repository: ScheduleRepository | None = None,
        execution_launcher: CrawlJobExecutionLauncher | None = None,
        dispatch_plan_service_factory: (
            Callable[[Session], DispatchPlanService] | None
        ) = None,
    ):
        self.crawl_job_repository = crawl_job_repository or CrawlJobRepository()
        self.event_outbox_repository = event_outbox_repository or EventOutboxRepository()
        self.outbox_publisher = outbox_publisher or OutboxPublisher()
        self.schedule_repository = schedule_repository or ScheduleRepository()
        self.execution_launcher = execution_launcher or CrawlJobExecutionLauncher()
        self.execution_repository = CrawlJobExecutionRepository()
        self._dispatch_plan_service_factory = (
            dispatch_plan_service_factory or DispatchPlanService
        )

    def dispatch_manual_crawl_job(
        self,
        db: Session,
        *,
        source_site: str,
        crawl_phase: str | None = None,
        crawl_mode: str | None = None,
        category_ids: list[int | str],
        max_pages: int | None,
        source_listing_crawl_job_id=None,
        detail_limit: int = 100,
        requested_by: str | None = None,
    ) -> CrawlJobDispatchResult:
        plan_request = self._build_manual_plan_request(
            source_site=source_site,
            crawl_phase=crawl_phase,
            crawl_mode=crawl_mode,
            category_ids=category_ids,
            max_pages=max_pages,
            source_listing_crawl_job_id=source_listing_crawl_job_id,
            detail_limit=detail_limit,
        )
        if plan_request.detail_settings is not None:
            normalized_source = normalize_source_site(source_site)
            ScraperPacingSettingsService(db).resolve(
                normalized_source,
                for_update=True,
            )
            conflicts = self.crawl_job_repository.list_active_manual_detail_jobs_for_update(
                db,
                source_site=normalized_source,
                statuses=ACTIVE_MANUAL_DETAIL_STATUSES,
            )
            if conflicts:
                raise ActiveManualDetailCrawlConflict(
                    "An active manual Job Detail task already exists for "
                    f"{normalized_source}: {conflicts[0].id}"
                )
        plan_service = self._dispatch_plan_service_factory(db)
        try:
            preparation = plan_service.prepare_run(
                plan_request,
                prepared_by=requested_by or "api",
                auto_commit=False,
            )
        except Exception:
            db.rollback()
            raise
        return self.dispatch_prepared_plan(
            db,
            plan_id=preparation.plan.plan_id,
            confirmation_token=preparation.confirmation_token,
            expected_plan_fingerprint=preparation.plan.plan_fingerprint,
            requested_by=requested_by,
        )

    @staticmethod
    def _build_manual_plan_request(
        *,
        source_site: str,
        crawl_phase: str | None,
        crawl_mode: str | None,
        category_ids: list[int | str],
        max_pages: int | None,
        source_listing_crawl_job_id,
        detail_limit: int,
    ) -> OneOffRunV1:
        source_site = normalize_source_site(source_site)
        classification_ids = tuple(
            str(value)
            if str(value).startswith(f"{source_site}:")
            else f"{source_site}:{value}"
            for value in category_ids
        )
        scope = AuthoredCrawlScopeV1(
            source_site=source_site,
            mode="selected" if classification_ids else "all",
            classification_ids=classification_ids,
        )
        crawl_mode = resolve_crawl_mode(
            source_site,
            crawl_mode,
        )
        if resolve_crawl_phase(crawl_phase) == "listing":
            page_depth = int(
                max_pages
                if max_pages is not None
                else resolve_default_max_pages(source_site)
            )
            return OneOffRunV1(
                scope=scope,
                listing_settings=ListingSettingsV1(
                    crawl_mode=crawl_mode,
                    page_depth=page_depth,
                    run_page_cap=(
                        3600 if source_site == "offertoday" else 1_000_000_000
                    ),
                ),
            )

        if source_listing_crawl_job_id:
            backlog_scope = ListingBatchBacklogScopeV1(
                source_listing_crawl_job_id=source_listing_crawl_job_id,
            )
        elif classification_ids:
            backlog_scope = CrawlScopeBacklogScopeV1(scope=scope)
        else:
            backlog_scope = SourceBacklogScopeV1()
        return OneOffRunV1(
            scope=scope,
            detail_settings=DetailSettingsV1(
                crawl_mode=crawl_mode,
                backlog_scope=backlog_scope,
                limit=StopAfterDetailLimitV1(
                    detail_run_cap=int(detail_limit),
                ),
            ),
        )

    def dispatch_schedule_crawl_job(
        self,
        db: Session,
        *,
        schedule: ScrapeSchedule,
        requested_by: str = "scheduler-worker",
        trigger_type: str = "schedule",
    ) -> CrawlJobDispatchResult:
        if schedule.scope_contract is None or trigger_type != "schedule":
            raise DispatchPlanReviewRequiredError(
                automation_id=schedule.id,
            )
        plan_service = self._dispatch_plan_service_factory(db)
        try:
            preparation = plan_service.prepare_run(
                SavedAutomationRunV1(
                    automation_id=schedule.id,
                ),
                prepared_by=requested_by,
                trigger_kind="scheduled_automation",
                auto_commit=False,
                automation=schedule,
            )
        except Exception:
            db.rollback()
            raise
        return self.dispatch_prepared_plan(
            db,
            plan_id=preparation.plan.plan_id,
            confirmation_token=None,
            requested_by=requested_by,
            automation=schedule,
        )

    def dispatch_prepared_plan(
        self,
        db: Session,
        *,
        plan_id,
        confirmation_token: str | None,
        requested_by: str | None = None,
        expected_plan_fingerprint: str | None = None,
        automation: ScrapeSchedule | None = None,
    ) -> CrawlJobDispatchResult:
        """Consume a reviewed plan and create every durable run artifact once."""

        plan_service = self._dispatch_plan_service_factory(db)
        command_row = None
        try:
            plan, prepared_snapshot = plan_service.lock_prepared_for_dispatch(
                plan_id,
                confirmation_token=confirmation_token,
                expected_plan_fingerprint=expected_plan_fingerprint,
            )
            locked_automation, automation_snapshot = (
                plan_service.lock_current_automation(
                    prepared_snapshot,
                    automation=automation,
                )
            )
            plan_service.revalidate_runtime_readiness(prepared_snapshot)

            request_payload = self._build_plan_request_payload(
                prepared_snapshot
            )
            schedule_id = (
                locked_automation.id if locked_automation is not None else None
            )
            trigger_type = (
                "schedule"
                if prepared_snapshot.content.trigger_kind
                == "scheduled_automation"
                else "manual"
            )
            crawl_job = self.crawl_job_repository.create_crawl_job(
                db,
                source_site=prepared_snapshot.content.source_site,
                trigger_type=trigger_type,
                request_payload=request_payload,
                requested_by=requested_by,
                schedule_id=schedule_id,
                dispatch_plan_id=prepared_snapshot.plan_id,
                dispatch_plan_fingerprint=(
                    prepared_snapshot.plan_fingerprint
                ),
                status="queued",
                auto_commit=False,
            )
            execution = None
            if locked_automation is not None:
                assert automation_snapshot is not None
                execution = self.schedule_repository.create_execution(
                    db,
                    schedule_id=locked_automation.id,
                    status="pending",
                    crawl_job_id=crawl_job.id,
                    automation_id_snapshot=locked_automation.id,
                    automation_snapshot=automation_snapshot,
                    dispatch_plan_id=prepared_snapshot.plan_id,
                    dispatch_plan_fingerprint=(
                        prepared_snapshot.plan_fingerprint
                    ),
                    auto_commit=False,
                )
                execution.request_payload_snapshot = dict(request_payload)

            plan_service.claim_detail_membership(
                prepared_snapshot,
                crawl_job_id=crawl_job.id,
            )
            consumed_snapshot = plan_service.mark_consumed_in_transaction(
                plan,
                prepared_snapshot,
                crawl_job=crawl_job,
            )
            if locked_automation is not None:
                assert consumed_snapshot.consumed_at is not None
                locked_automation.last_run_at = consumed_snapshot.consumed_at
            authority = ExecutionAuthorityV1(
                crawl_job_id=crawl_job.id,
                dispatch_plan=consumed_snapshot,
            )
            event_payload = self._build_requested_event_payload(
                crawl_job,
                execution_authority=authority,
            )
            self.crawl_job_repository.append_event(
                db,
                crawl_job_id=crawl_job.id,
                event_type="crawl.requested",
                payload=event_payload,
                emitted_by=requested_by or trigger_type,
                auto_commit=False,
            )
            if self._should_enqueue_command(
                source_site=crawl_job.source_site,
                payload=request_payload,
            ):
                command_row = self.event_outbox_repository.enqueue(
                    db,
                    topic=self._resolve_command_topic(
                        source_site=crawl_job.source_site,
                        crawl_mode=request_payload.get("crawl_mode"),
                    ),
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
        except DispatchPlanExpiredError:
            plan_service.persist_expired_plan_after_rollback(plan_id)
            raise
        except Exception:
            db.rollback()
            raise

        launch_result = self.execution_launcher.launch(crawl_job)
        if command_row is not None:
            self.outbox_publisher.publish_row(db, row=command_row)
            self.outbox_publisher.publish_pending_batch(db, limit=100)
        logger.info(
            "SCRAPE_DISPATCHED source=%s crawl_job_id=%s phase=%s mode=%s "
            "trigger=%s dispatch_plan_id=%s launched=%s command=%s",
            crawl_job.source_site,
            crawl_job.id,
            prepared_snapshot.content.crawl_phase,
            request_payload.get("crawl_mode"),
            trigger_type,
            consumed_snapshot.plan_id,
            launch_result.launched,
            " ".join(launch_result.command or []),
        )
        return CrawlJobDispatchResult(
            crawl_job=crawl_job,
            schedule_execution=execution,
            dispatch_plan=consumed_snapshot,
        )

    def cancel_crawl_job(
        self,
        db: Session,
        *,
        crawl_job_id,
        requested_by: str | None = None,
        reason: str = "Cancelled by API request.",
    ) -> CrawlJob:
        crawl_job = self.crawl_job_repository.get_crawl_job_by_id_for_update(
            db, crawl_job_id
        )
        if crawl_job is None:
            raise ValueError(f"Crawl job not found: {crawl_job_id}")

        if crawl_job.status == "cancelled":
            return crawl_job
        if crawl_job.status == "cancelling":
            db.commit()
            has_execution = self.execution_launcher.request_cancel(
                crawl_job_id=crawl_job.id
            )
            if not has_execution:
                self.execution_launcher.acknowledge_without_execution(
                    crawl_job_id=crawl_job.id,
                    reason=crawl_job.error_message or reason,
                )
                db.expire_all()
                crawl_job = self.crawl_job_repository.get_crawl_job_by_id(
                    db, crawl_job.id
                )
                if crawl_job is None:
                    raise RuntimeError(
                        "Crawl job disappeared during cancellation acknowledgement"
                    )
            else:
                db.refresh(crawl_job)
            return crawl_job
        if not can_request_cancellation(
            trigger_type=crawl_job.trigger_type,
            status=crawl_job.status,
            schedule_id=crawl_job.schedule_id,
        ):
            raise RuntimeError(f"Crawl job cannot be cancelled from status '{crawl_job.status}'")

        crawl_job.status = "cancelling"
        crawl_job.completed_at = None
        crawl_job.error_message = reason
        execution = self.execution_repository.get_latest_active_for_job(
            db,
            crawl_job.id,
            for_update=True,
        )
        if execution is not None:
            self.execution_repository.request_stop(execution)

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
            "status": "cancelling",
            "execution_generation": (
                str(execution.generation) if execution is not None else None
            ),
        }
        self.crawl_job_repository.append_event(
            db,
            crawl_job_id=crawl_job.id,
            event_type="crawl.cancel_requested",
            payload=event_payload,
            emitted_by=requested_by or "api",
            auto_commit=False,
        )
        db.commit()
        db.refresh(crawl_job)
        if execution is not None:
            self.execution_launcher.request_cancel(crawl_job_id=crawl_job.id)
        else:
            self.execution_launcher.acknowledge_without_execution(
                crawl_job_id=crawl_job.id,
                reason=reason,
            )
            db.expire_all()
            crawl_job = self.crawl_job_repository.get_crawl_job_by_id(
                db, crawl_job.id
            )
            if crawl_job is None:
                raise RuntimeError(
                    "Crawl job disappeared during cancellation acknowledgement"
                )
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
        execution_authority = DispatchPlanService(db).load_execution_authority(
            crawl_job.id
        )
        DispatchPlanService.require_worker_runtime_supported(
            execution_authority,
            supported_phases=("detail",),
        )

        if crawl_job.status != "manual_action_required":
            raise RuntimeError(f"Crawl job cannot be resumed from status '{crawl_job.status}'")

        latest_event = self.crawl_job_repository.get_latest_manual_action_event(db, crawl_job_id)
        if latest_event is None:
            raise RuntimeError("Crawl job is not resumable from its latest event")

        latest_event_payload = dict(latest_event.payload or {})
        manual_action = normalize_manual_action_payload(
            latest_event_payload.get("manual_action"),
            source_site=crawl_job.source_site,
            request_payload=(
                latest_event_payload.get("request_payload")
                or crawl_job.request_payload
                or {}
            ),
            default_browser_channel=settings.jobsdb_headed_browser_channel,
            default_browser_profile_path=settings.jobsdb_headed_browser_user_data_dir,
        )
        if not manual_action.get("resume_supported"):
            raise RuntimeError("Crawl job manual action does not support resume")

        selected_strategy = DEFAULT_RESUME_STRATEGY if strategy is None else strategy
        if selected_strategy not in SUPPORTED_RESUME_STRATEGIES:
            raise RuntimeError(f"Unsupported resume strategy: {selected_strategy}")
        if (
            selected_strategy == RESUME_STRATEGY_REUSE_OPEN_BROWSER
            and not manual_action.get("reuse_open_browser_supported")
        ):
            raise RuntimeError(
                "Crawl job manual action does not support reuse-open-browser resume"
            )
        request_payload = dict(crawl_job.request_payload or {})
        plan = execution_authority.dispatch_plan
        settings_contract = (
            plan.content.listing_settings or plan.content.detail_settings
        )
        assert settings_contract is not None
        effective_crawl_mode = settings_contract.crawl_mode
        browser_channel = None
        browser_profile_path = None
        if selected_strategy == RESUME_STRATEGY_REUSE_OPEN_BROWSER:
            browser_channel = str(manual_action.get("browser_channel") or "")
            browser_profile_path = str(
                manual_action.get("browser_profile_path") or ""
            )
        crawl_job.resume_context = ExecutionResumeContextV1(
            manual_action_event_sequence=latest_event.sequence_no,
            requested_at=utc_now(),
            resume_strategy=selected_strategy,
            manual_action_classification=(
                str(manual_action.get("classification") or "") or None
            ),
            detail_statuses=tuple(
                resolve_resume_detail_statuses(
                    manual_action.get("classification")
                )
            ),
            browser_channel=browser_channel,
            browser_profile_path=browser_profile_path,
        ).model_dump(mode="json")
        ensure_headed_crawl_worker_available(
            crawl_mode=effective_crawl_mode,
            source_site=crawl_job.source_site,
        )

        crawl_job.status = "dispatching"
        crawl_job.completed_at = None
        crawl_job.error_message = None
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

        requested_payload = self._build_requested_event_payload(
            crawl_job,
            execution_authority=execution_authority,
        )
        self.crawl_job_repository.append_event(
            db,
            crawl_job_id=crawl_job.id,
            event_type="crawl.requested",
            payload=requested_payload,
            emitted_by=requested_by or "api",
            auto_commit=False,
        )
        command_row = None
        command_payload = {
            **request_payload,
            "crawl_mode": effective_crawl_mode,
        }
        if self._should_enqueue_command(
            source_site=crawl_job.source_site,
            payload=command_payload,
        ):
            command_row = self.event_outbox_repository.enqueue(
                db,
                topic=self._resolve_command_topic(
                    source_site=crawl_job.source_site,
                    crawl_mode=effective_crawl_mode,
                ),
                aggregate_type="crawl_job",
                aggregate_id=str(crawl_job.id),
                event_type="crawl.requested",
                payload=requested_payload,
                auto_commit=False,
            )

        db.commit()
        db.refresh(crawl_job)
        launch_result = self.execution_launcher.launch(crawl_job)
        if command_row is not None:
            self.outbox_publisher.publish_row(db, row=command_row)
            self.outbox_publisher.publish_pending_batch(db, limit=100)
        logger.info(
            "SCRAPE_RESUMED source=%s crawl_job_id=%s mode=%s launched=%s command=%s",
            crawl_job.source_site,
            crawl_job.id,
            effective_crawl_mode,
            launch_result.launched,
            " ".join(launch_result.command or []),
        )
        return crawl_job

    def _build_requested_event_payload(
        self,
        crawl_job: CrawlJob,
        *,
        execution_authority: ExecutionAuthorityV1,
    ) -> dict[str, Any]:
        request_payload = dict(crawl_job.request_payload or {})
        crawl_phase = resolve_crawl_phase(request_payload.get("crawl_phase"))
        crawl_mode = resolve_crawl_mode(
            crawl_job.source_site,
            request_payload.get("crawl_mode"),
        )
        content = execution_authority.dispatch_plan.content
        settings_contract = content.listing_settings or content.detail_settings
        assert settings_contract is not None
        crawl_phase = content.crawl_phase
        crawl_mode = settings_contract.crawl_mode
        return {
            "crawl_job_id": str(crawl_job.id),
            "source_site": crawl_job.source_site,
            "crawl_phase": crawl_phase,
            "crawl_mode": crawl_mode,
            "trigger_type": crawl_job.trigger_type,
            "schedule_id": str(crawl_job.schedule_id) if crawl_job.schedule_id else None,
            "requested_by": crawl_job.requested_by,
            "request_payload": request_payload,
            "dispatch_plan_id": (
                str(getattr(crawl_job, "dispatch_plan_id", None))
                if getattr(crawl_job, "dispatch_plan_id", None) is not None
                else None
            ),
            "dispatch_plan_fingerprint": getattr(
                crawl_job,
                "dispatch_plan_fingerprint",
                None,
            ),
            "resume_context": getattr(crawl_job, "resume_context", None),
            "status": crawl_job.status,
            "queued_at": crawl_job.queued_at.isoformat() if crawl_job.queued_at else None,
        }

    @staticmethod
    def _build_plan_request_payload(
        snapshot: DispatchPlanSnapshotV1,
    ) -> dict[str, Any]:
        content = snapshot.content
        settings_contract = content.listing_settings or content.detail_settings
        assert settings_contract is not None
        payload: dict[str, Any] = {
            "source_site": content.source_site,
            "crawl_phase": content.crawl_phase,
            "crawl_mode": settings_contract.crawl_mode,
            "dispatch_plan_id": str(snapshot.plan_id),
            "dispatch_plan_fingerprint": snapshot.plan_fingerprint,
            "category_ids": [
                selected.classification_id
                for selected in content.resolved_scope.selected_classifications
            ],
            "skip_existing": False,
        }
        if content.listing_settings is not None:
            payload.update(
                {
                    "max_pages": content.listing_settings.page_depth,
                    "page_depth": content.listing_settings.page_depth,
                    "run_page_cap": content.listing_settings.run_page_cap,
                }
            )
            return payload

        detail_settings = content.detail_settings
        assert detail_settings is not None
        backlog_scope = detail_settings.backlog_scope
        detail_scope = backlog_scope.kind
        if detail_scope == "source_backlog":
            detail_scope = "global"
        payload.update(
            {
                "detail_scope": detail_scope,
                "detail_limit": snapshot.detail_target_count,
                "detail_statuses": list(
                    dict.fromkeys(
                        target.eligibility_status for target in snapshot.targets
                    )
                ),
            }
        )
        if backlog_scope.kind == "listing_batch":
            payload["source_listing_crawl_job_id"] = str(
                backlog_scope.source_listing_crawl_job_id
            )
        pacing = DispatchPlanService.detail_pacing_payload(snapshot)
        if pacing is not None:
            payload["detail_pacing"] = pacing
        return payload

    def _resolve_command_topic(self, *, source_site: str, crawl_mode: str | None) -> str:
        effective_mode = resolve_crawl_mode(source_site, crawl_mode)
        if effective_mode == "headed":
            # OfferToday runs headed mode inside the same Docker container —
            # no separate host-side worker needed.
            if normalize_source_site(source_site) == "offertoday":
                return STREAM_CRAWL_COMMANDS
            return STREAM_CRAWL_COMMANDS_HEADED
        return STREAM_CRAWL_COMMANDS

    def _should_enqueue_command(self, *, source_site: str, payload: dict[str, Any]) -> bool:
        crawl_job = type(
            "_LaunchCandidate",
            (),
            {
                "id": payload.get("crawl_job_id") or "",
                "source_site": source_site,
                "request_payload": payload,
            },
        )()
        return not self.execution_launcher.should_launch_locally(crawl_job)
