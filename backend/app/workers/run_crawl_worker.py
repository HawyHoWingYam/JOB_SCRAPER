from __future__ import annotations

import asyncio
import inspect
import logging
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.crawl_phases import resolve_crawl_phase
from app.config import settings
from app.database import SessionLocal
from app.logging_config import configure_logging
from app.messaging.event_envelope import build_event_envelope
from app.messaging.redis_stream_bus import RedisStreamBus, StreamMessage
from app.messaging.topics import (
    STREAM_CRAWL_COMMANDS,
    STREAM_CRAWL_PROGRESS,
    STREAM_JOB_INGEST,
)
from app.repositories.crawl_job_listing_repository import CrawlJobListingRepository
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.scraper.manual_action import ManualActionRequiredError
from app.utils.time import utc_now

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)
_UNSET = object()
DETAIL_STATUS_METRIC_KEYS = {
    "pending": "detail_pending",
    "running": "detail_running",
    "completed": "detail_completed",
    "failed": "detail_failed",
    "manual_action_required": "detail_manual_action_required",
}

CRAWLER_ROOT = Path(__file__).resolve().parents[2] / "crawler"
BACKEND_ROOT = CRAWLER_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@dataclass(frozen=True)
class CrawlExecutionResult:
    pages_processed: int = 0
    items_emitted: int = 0


def _default_runner_registry() -> dict[str, Any]:
    from crawler.job_crawler.spiders.ctgoodjobs_spider import CTGoodJobsSpider
    from crawler.job_crawler.spiders.jobsdb_spider import JobsDBSpider

    return {
        "jobsdb": JobsDBSpider(),
        "ctgoodjobs": CTGoodJobsSpider(),
    }


class CrawlWorkerService:
    def __init__(
        self,
        *,
        bus: RedisStreamBus | Any | None = None,
        group_name: str = "crawl-workers",
        consumer_name: str = "crawl-worker",
        command_topic: str = STREAM_CRAWL_COMMANDS,
        runner_registry: dict[str, Any] | None = None,
        crawl_job_listing_repository: CrawlJobListingRepository | None = None,
        crawl_job_repository: CrawlJobRepository | None = None,
        session_factory: Any | None = None,
    ):
        self.bus = bus or RedisStreamBus()
        self.group_name = group_name
        self.consumer_name = consumer_name
        self.command_topic = command_topic
        self.runner_registry = runner_registry or _default_runner_registry()
        self.crawl_job_listing_repository = crawl_job_listing_repository or CrawlJobListingRepository()
        self.crawl_job_repository = crawl_job_repository or CrawlJobRepository()
        self.session_factory = session_factory or SessionLocal
        self.bus.ensure_group(self.command_topic, self.group_name)

    async def run_once(self) -> int:
        messages = self.bus.consume_group(
            self.command_topic,
            self.group_name,
            self.consumer_name,
            count=10,
            block_ms=100,
        )
        for message in messages:
            await self._handle_message(message)
        return len(messages)

    async def _handle_message(self, message: StreamMessage | Any) -> None:
        event = message.event
        if event.event_type != "crawl.requested":
            self.bus.ack(self.command_topic, self.group_name, message.message_id)
            return

        payload = dict(event.payload or {})
        crawl_job_id = str(payload.get("crawl_job_id") or event.aggregate_id)
        source_site = str(payload.get("source_site") or "").strip().lower()
        request_payload = dict(payload.get("request_payload") or {})
        crawl_phase = resolve_crawl_phase(request_payload.get("crawl_phase"))
        job_ids_collected = 0
        latest_page_payload: dict[str, Any] = {}

        started_payload = {
            "request_payload": request_payload,
            **self._build_runtime_metrics_payload(
                pages_processed=0,
                items_emitted=0,
                job_ids_collected=0,
            ),
        }

        runner = self.runner_registry.get(source_site)
        if runner is None:
            failed_payload = {
                **started_payload,
                "error": f"Unsupported source_site: {source_site}",
            }
            self._publish_progress(
                event_type="crawl.failed",
                crawl_job_id=crawl_job_id,
                source_site=source_site,
                payload=failed_payload,
            )
            self._persist_runtime_event(
                crawl_job_id=crawl_job_id,
                status="failed",
                event_type="crawl.failed",
                source_site=source_site,
                payload=failed_payload,
                started_at=utc_now(),
                completed_at=utc_now(),
                error_message=failed_payload["error"],
                metrics=self._build_runtime_metrics(
                    pages_processed=0,
                    items_emitted=0,
                    job_ids_collected=0,
                ),
            )
            self.bus.ack(self.command_topic, self.group_name, message.message_id)
            return

        self._publish_progress(
            event_type="crawl.started",
            crawl_job_id=crawl_job_id,
            source_site=source_site,
            payload=started_payload,
        )
        self._persist_runtime_event(
            crawl_job_id=crawl_job_id,
            status="running",
            event_type="crawl.started",
            source_site=source_site,
            payload=started_payload,
            started_at=utc_now(),
            completed_at=None,
            error_message=None,
            metrics=self._build_runtime_metrics(
                pages_processed=0,
                items_emitted=0,
                job_ids_collected=0,
            ),
        )

        pages_processed = 0
        items_emitted = 0

        def emit_page_processed(progress_payload: dict[str, Any]) -> None:
            nonlocal pages_processed, job_ids_collected, latest_page_payload
            pages_processed += 1
            if progress_payload.get("job_ids_collected") is not None:
                job_ids_collected = int(progress_payload["job_ids_collected"])
            latest_page_payload = dict(progress_payload)
            event_payload = {
                **progress_payload,
                **self._build_runtime_metrics_payload(
                    pages_processed=pages_processed,
                    items_emitted=items_emitted,
                    job_ids_collected=job_ids_collected,
                ),
            }
            self._publish_progress(
                event_type="crawl.page_processed",
                crawl_job_id=crawl_job_id,
                source_site=source_site,
                payload=event_payload,
            )
            self._persist_runtime_event(
                crawl_job_id=crawl_job_id,
                status="running",
                event_type="crawl.page_processed",
                source_site=source_site,
                payload=event_payload,
                metrics=self._build_runtime_metrics(
                    pages_processed=pages_processed,
                    items_emitted=items_emitted,
                    job_ids_collected=job_ids_collected,
                ),
            )

        def emit_item_emitted(item_payload: dict[str, Any]) -> None:
            nonlocal items_emitted
            items_emitted += 1
            self._increment_runtime_metrics(
                crawl_job_id=crawl_job_id,
                metrics_delta={"items_emitted": 1},
            )
            self._publish_item(
                crawl_job_id=crawl_job_id,
                source_site=source_site,
                payload=item_payload,
            )

        def emit_listing_emitted(listing_payload: dict[str, Any]) -> None:
            self._persist_listing(
                crawl_job_id=crawl_job_id,
                payload=listing_payload,
            )

        def emit_detail_progress(progress_payload: dict[str, Any]) -> None:
            event_payload = {
                **progress_payload,
                **self._build_runtime_metrics_payload(
                    pages_processed=pages_processed,
                    items_emitted=items_emitted,
                    job_ids_collected=job_ids_collected,
                ),
            }
            self._publish_progress(
                event_type="crawl.detail_progress",
                crawl_job_id=crawl_job_id,
                source_site=source_site,
                payload=event_payload,
            )
            self._persist_runtime_event(
                crawl_job_id=crawl_job_id,
                status="running",
                event_type="crawl.detail_progress",
                source_site=source_site,
                payload=event_payload,
                metrics=self._build_runtime_metrics(
                    pages_processed=pages_processed,
                    items_emitted=items_emitted,
                    job_ids_collected=job_ids_collected,
                ),
            )

        def mark_detail_running(target: dict[str, Any]) -> None:
            listing_id = target.get("listing_id")
            if not listing_id:
                return
            self._mark_detail_running(
                listing_id=listing_id,
                detail_crawl_job_id=crawl_job_id,
            )

        def mark_detail_completed(target: dict[str, Any], detail_payload: dict[str, Any]) -> None:
            listing_id = target.get("listing_id")
            if not listing_id:
                return
            self._mark_detail_completed(
                listing_id=listing_id,
                detail_crawl_job_id=crawl_job_id,
                detail_payload=detail_payload,
            )

        def mark_detail_failed(target: dict[str, Any], error_message: str) -> None:
            listing_id = target.get("listing_id")
            if not listing_id:
                return
            self._mark_detail_failed(
                listing_id=listing_id,
                detail_crawl_job_id=crawl_job_id,
                error_message=error_message,
            )

        try:
            runner_request_payload = dict(request_payload)
            runner_request_payload["crawl_phase"] = crawl_phase
            if crawl_phase == "detail":
                detail_targets = self._load_detail_targets(
                    source_site=source_site,
                    request_payload=request_payload,
                )
                runner_request_payload["detail_targets"] = detail_targets
                job_ids_collected = len(detail_targets)
            result = runner.crawl(
                crawl_job_id=crawl_job_id,
                request_payload=runner_request_payload,
                emit_page_processed=emit_page_processed,
                emit_detail_progress=emit_detail_progress,
                emit_item_emitted=emit_item_emitted,
                emit_listing_emitted=emit_listing_emitted,
                mark_detail_running=mark_detail_running,
                mark_detail_completed=mark_detail_completed,
                mark_detail_failed=mark_detail_failed,
            )
            if inspect.isawaitable(result):
                result = await result

            execution_result = self._coerce_execution_result(
                result,
                pages_processed=pages_processed,
                items_emitted=items_emitted,
            )
            final_pages_processed = execution_result.pages_processed or pages_processed
            final_items_emitted = execution_result.items_emitted or items_emitted
            completed_payload = {
                **latest_page_payload,
                "request_payload": request_payload,
                **self._build_runtime_metrics_payload(
                    pages_processed=final_pages_processed,
                    items_emitted=final_items_emitted,
                    job_ids_collected=job_ids_collected,
                ),
            }
            self._publish_progress(
                event_type="crawl.completed",
                crawl_job_id=crawl_job_id,
                source_site=source_site,
                payload=completed_payload,
            )
            self._persist_runtime_event(
                crawl_job_id=crawl_job_id,
                status="completed",
                event_type="crawl.completed",
                source_site=source_site,
                payload=completed_payload,
                completed_at=utc_now(),
                error_message=None,
                metrics=self._build_runtime_metrics(
                    pages_processed=final_pages_processed,
                    items_emitted=final_items_emitted,
                    job_ids_collected=job_ids_collected,
                ),
            )
        except ManualActionRequiredError as exc:
            manual_action_payload = exc.to_payload(
                crawl_mode=str(request_payload.get("crawl_mode") or ""),
                browser_channel=settings.jobsdb_headed_browser_channel,
                browser_profile_path=settings.jobsdb_headed_browser_user_data_dir,
            )
            action_payload = {
                **latest_page_payload,
                "request_payload": request_payload,
                "error": exc.message,
                "manual_action": manual_action_payload,
                **self._build_runtime_metrics_payload(
                    pages_processed=pages_processed,
                    items_emitted=items_emitted,
                    job_ids_collected=job_ids_collected,
                ),
            }
            detail_resume_context = manual_action_payload.get("resume_context") or {}
            listing_id = detail_resume_context.get("listing_id")
            if detail_resume_context.get("crawl_phase") == "detail" and listing_id:
                self._mark_detail_manual_action_required(
                    listing_id=str(listing_id),
                    detail_crawl_job_id=crawl_job_id,
                    error_message=exc.message,
                )
            self._publish_progress(
                event_type="crawl.manual_action_required",
                crawl_job_id=crawl_job_id,
                source_site=source_site,
                payload=action_payload,
            )
            self._persist_runtime_event(
                crawl_job_id=crawl_job_id,
                status="manual_action_required",
                event_type="crawl.manual_action_required",
                source_site=source_site,
                payload=action_payload,
                completed_at=None,
                error_message=exc.message,
                metrics=self._build_runtime_metrics(
                    pages_processed=pages_processed,
                    items_emitted=items_emitted,
                    job_ids_collected=job_ids_collected,
                ),
            )
        except Exception as exc:  # pragma: no cover - surfaced in tests when needed
            logger.exception("crawl worker failed: crawl_job_id=%s source_site=%s", crawl_job_id, source_site)
            failed_payload = {
                **latest_page_payload,
                "request_payload": request_payload,
                "error": str(exc),
                **self._build_runtime_metrics_payload(
                    pages_processed=pages_processed,
                    items_emitted=items_emitted,
                    job_ids_collected=job_ids_collected,
                ),
            }
            self._publish_progress(
                event_type="crawl.failed",
                crawl_job_id=crawl_job_id,
                source_site=source_site,
                payload=failed_payload,
            )
            self._persist_runtime_event(
                crawl_job_id=crawl_job_id,
                status="failed",
                event_type="crawl.failed",
                source_site=source_site,
                payload=failed_payload,
                completed_at=utc_now(),
                error_message=str(exc),
                metrics=self._build_runtime_metrics(
                    pages_processed=pages_processed,
                    items_emitted=items_emitted,
                    job_ids_collected=job_ids_collected,
                ),
            )
        finally:
            self.bus.ack(self.command_topic, self.group_name, message.message_id)

    def _publish_progress(
        self,
        *,
        event_type: str,
        crawl_job_id: str,
        source_site: str,
        payload: dict[str, Any],
    ) -> None:
        envelope = build_event_envelope(
            event_type=event_type,
            aggregate_type="crawl_job",
            aggregate_id=crawl_job_id,
            payload={
                "crawl_job_id": crawl_job_id,
                "source_site": source_site,
                **payload,
            },
            source_service="crawl-worker",
        )
        self.bus.publish(STREAM_CRAWL_PROGRESS, envelope)

    def _publish_item(
        self,
        *,
        crawl_job_id: str,
        source_site: str,
        payload: dict[str, Any],
    ) -> None:
        listing_id = payload.get("listing_id")
        source_listing_crawl_job_id = payload.get("source_listing_crawl_job_id")
        job_payload = payload.get("job") if isinstance(payload.get("job"), dict) else payload
        envelope = build_event_envelope(
            event_type="crawl.item_emitted",
            aggregate_type="crawl_job",
            aggregate_id=crawl_job_id,
            payload={
                "crawl_job_id": crawl_job_id,
                "source_site": source_site,
                "listing_id": listing_id,
                "source_listing_crawl_job_id": source_listing_crawl_job_id,
                "job": job_payload,
            },
            source_service="crawl-worker",
        )
        self.bus.publish(STREAM_JOB_INGEST, envelope)

    def _persist_runtime_event(
        self,
        *,
        crawl_job_id: str,
        status: str,
        event_type: str,
        source_site: str,
        payload: dict[str, Any],
        started_at: Any = _UNSET,
        completed_at: Any = _UNSET,
        error_message: Any = _UNSET,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        event_payload = {
            "crawl_job_id": crawl_job_id,
            "source_site": source_site,
            **payload,
        }
        normalized_crawl_job_id = self._normalize_crawl_job_id(crawl_job_id)
        db = self.session_factory()
        try:
            repository_kwargs = {
                "crawl_job_id": normalized_crawl_job_id,
                "status": status,
                "event_type": event_type,
                "payload": event_payload,
                "metrics": metrics,
            }
            if started_at is not _UNSET:
                repository_kwargs["started_at"] = started_at
            if completed_at is not _UNSET:
                repository_kwargs["completed_at"] = completed_at
            if error_message is not _UNSET:
                repository_kwargs["error_message"] = error_message

            self.crawl_job_repository.record_runtime_event(
                db,
                **repository_kwargs,
            )
        finally:
            db.close()

    def _increment_runtime_metrics(
        self,
        *,
        crawl_job_id: str,
        metrics_delta: dict[str, Any],
    ) -> None:
        normalized_crawl_job_id = self._normalize_crawl_job_id(crawl_job_id)
        db = self.session_factory()
        try:
            self.crawl_job_repository.increment_metrics(
                db,
                crawl_job_id=normalized_crawl_job_id,
                metrics_delta=metrics_delta,
            )
        finally:
            db.close()

    def _persist_listing(self, *, crawl_job_id: str, payload: dict[str, Any]) -> None:
        normalized_crawl_job_id = self._normalize_crawl_job_id(crawl_job_id)
        db = self.session_factory()
        try:
            self.crawl_job_listing_repository.upsert_listing(
                db,
                crawl_job_id=normalized_crawl_job_id,
                source_site=str(payload.get("source_site") or ""),
                source_job_id=str(payload.get("source_job_id") or ""),
                source_url=str(payload.get("source_url") or ""),
                source_classification_id=payload.get("source_classification_id"),
                source_classification_name=payload.get("source_classification_name"),
                listing_page=payload.get("listing_page"),
                listing_rank=payload.get("listing_rank"),
                listing_payload=dict(payload.get("listing_payload") or {}),
                auto_commit=False,
            )
            self._sync_listing_detail_status_metrics(
                db,
                source_listing_crawl_job_id=normalized_crawl_job_id,
                source_site=str(payload.get("source_site") or ""),
            )
            db.commit()
        finally:
            db.close()

    def _load_detail_targets(
        self,
        *,
        source_site: str,
        request_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        source_listing_crawl_job_id = request_payload.get("source_listing_crawl_job_id")
        detail_statuses = list(request_payload.get("detail_statuses") or ["pending"])
        category_ids = list(request_payload.get("category_ids") or [])
        detail_limit = int(request_payload.get("detail_limit") or 100)

        db = self.session_factory()
        try:
            rows = self.crawl_job_listing_repository.list_detail_candidates(
                db,
                source_site=source_site,
                source_listing_crawl_job_id=self._normalize_crawl_job_id(source_listing_crawl_job_id),
                category_ids=category_ids,
                statuses=detail_statuses,
                limit=detail_limit,
            )
            return [
                {
                    "listing_id": str(row.id),
                    "source_listing_crawl_job_id": str(row.crawl_job_id),
                    "source_site": row.source_site,
                    "source_job_id": row.source_job_id,
                    "source_url": row.source_url,
                    "source_classification_id": row.source_classification_id,
                    "source_classification_name": row.source_classification_name,
                    "listing_page": row.listing_page,
                    "listing_rank": row.listing_rank,
                    "listing_payload": dict(row.listing_payload or {}),
                }
                for row in rows
            ]
        finally:
            db.close()

    def _mark_detail_running(self, *, listing_id: str, detail_crawl_job_id: str) -> None:
        db = self.session_factory()
        try:
            listing = self.crawl_job_listing_repository.mark_detail_running(
                db,
                listing_id=self._normalize_crawl_job_id(listing_id),
                detail_crawl_job_id=self._normalize_crawl_job_id(detail_crawl_job_id),
                auto_commit=False,
            )
            self._sync_listing_detail_status_metrics(
                db,
                source_listing_crawl_job_id=listing.crawl_job_id,
                source_site=listing.source_site,
            )
            db.commit()
        finally:
            db.close()

    def _mark_detail_completed(
        self,
        *,
        listing_id: str,
        detail_crawl_job_id: str,
        detail_payload: dict[str, Any],
    ) -> None:
        db = self.session_factory()
        try:
            listing = self.crawl_job_listing_repository.mark_detail_completed(
                db,
                listing_id=self._normalize_crawl_job_id(listing_id),
                detail_crawl_job_id=self._normalize_crawl_job_id(detail_crawl_job_id),
                detail_payload=detail_payload,
                auto_commit=False,
            )
            self._sync_listing_detail_status_metrics(
                db,
                source_listing_crawl_job_id=listing.crawl_job_id,
                source_site=listing.source_site,
            )
            db.commit()
        finally:
            db.close()

    def _mark_detail_failed(
        self,
        *,
        listing_id: str,
        detail_crawl_job_id: str,
        error_message: str,
    ) -> None:
        db = self.session_factory()
        try:
            listing = self.crawl_job_listing_repository.mark_detail_failed(
                db,
                listing_id=self._normalize_crawl_job_id(listing_id),
                detail_crawl_job_id=self._normalize_crawl_job_id(detail_crawl_job_id),
                error_message=error_message,
                auto_commit=False,
            )
            self._sync_listing_detail_status_metrics(
                db,
                source_listing_crawl_job_id=listing.crawl_job_id,
                source_site=listing.source_site,
            )
            db.commit()
        finally:
            db.close()

    def _mark_detail_manual_action_required(
        self,
        *,
        listing_id: str,
        detail_crawl_job_id: str,
        error_message: str,
    ) -> None:
        db = self.session_factory()
        try:
            listing = self.crawl_job_listing_repository.mark_detail_manual_action_required(
                db,
                listing_id=self._normalize_crawl_job_id(listing_id),
                detail_crawl_job_id=self._normalize_crawl_job_id(detail_crawl_job_id),
                error_message=error_message,
                auto_commit=False,
            )
            self._sync_listing_detail_status_metrics(
                db,
                source_listing_crawl_job_id=listing.crawl_job_id,
                source_site=listing.source_site,
            )
            db.commit()
        finally:
            db.close()

    def _sync_listing_detail_status_metrics(
        self,
        db,
        *,
        source_listing_crawl_job_id,
        source_site: str | None = None,
    ) -> None:
        counts = self.crawl_job_listing_repository.count_detail_statuses(
            db,
            source_site=source_site,
            source_listing_crawl_job_id=source_listing_crawl_job_id,
        )
        exact_metrics = {
            "listings_staged": sum(int(value) for value in counts.values()),
            **{
                metric_key: int(counts.get(status, 0))
                for status, metric_key in DETAIL_STATUS_METRIC_KEYS.items()
            },
        }
        crawl_job = self.crawl_job_repository.get_crawl_job_by_id(db, source_listing_crawl_job_id)
        current_metrics = dict(crawl_job.metrics or {}) if crawl_job is not None else {}
        metrics_delta = {
            key: value - int(current_metrics.get(key) or 0)
            for key, value in exact_metrics.items()
            if key not in current_metrics or value != int(current_metrics.get(key) or 0)
        }
        if metrics_delta:
            self.crawl_job_repository.increment_metrics(
                db,
                crawl_job_id=source_listing_crawl_job_id,
                metrics_delta=metrics_delta,
                auto_commit=False,
            )

    def _build_runtime_metrics(
        self,
        *,
        pages_processed: int,
        items_emitted: int,
        job_ids_collected: int,
    ) -> dict[str, int]:
        return {
            "pages_processed": int(pages_processed),
            "items_emitted": int(items_emitted),
            "job_ids_collected": int(job_ids_collected),
        }

    def _build_runtime_metrics_payload(
        self,
        *,
        pages_processed: int,
        items_emitted: int,
        job_ids_collected: int,
    ) -> dict[str, int]:
        return self._build_runtime_metrics(
            pages_processed=pages_processed,
            items_emitted=items_emitted,
            job_ids_collected=job_ids_collected,
        )

    def _coerce_execution_result(
        self,
        result: Any,
        *,
        pages_processed: int,
        items_emitted: int,
    ) -> CrawlExecutionResult:
        if isinstance(result, CrawlExecutionResult):
            return result
        if isinstance(result, dict):
            return CrawlExecutionResult(
                pages_processed=int(result.get("pages_processed") or pages_processed),
                items_emitted=int(result.get("items_emitted") or items_emitted),
            )
        return CrawlExecutionResult(
            pages_processed=pages_processed,
            items_emitted=items_emitted,
        )

    def _normalize_crawl_job_id(self, crawl_job_id: str) -> Any:
        try:
            return uuid.UUID(str(crawl_job_id))
        except (ValueError, TypeError, AttributeError):
            return crawl_job_id


async def main() -> None:
    service = CrawlWorkerService()
    logger.info("Starting crawl worker")
    while True:
        processed = await service.run_once()
        if processed == 0:
            await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())
