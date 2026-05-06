from __future__ import annotations

import asyncio
import inspect
import logging
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings
from app.database import SessionLocal
from app.logging_config import configure_logging
from app.messaging.event_envelope import build_event_envelope
from app.messaging.redis_stream_bus import RedisStreamBus, StreamMessage
from app.messaging.topics import STREAM_CRAWL_COMMANDS, STREAM_CRAWL_PROGRESS, STREAM_JOB_INGEST
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.utils.time import utc_now

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)
_UNSET = object()

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
        runner_registry: dict[str, Any] | None = None,
        crawl_job_repository: CrawlJobRepository | None = None,
        session_factory: Any | None = None,
    ):
        self.bus = bus or RedisStreamBus()
        self.group_name = group_name
        self.consumer_name = consumer_name
        self.runner_registry = runner_registry or _default_runner_registry()
        self.crawl_job_repository = crawl_job_repository or CrawlJobRepository()
        self.session_factory = session_factory or SessionLocal
        self.bus.ensure_group(STREAM_CRAWL_COMMANDS, self.group_name)

    async def run_once(self) -> int:
        messages = self.bus.consume_group(
            STREAM_CRAWL_COMMANDS,
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
            self.bus.ack(STREAM_CRAWL_COMMANDS, self.group_name, message.message_id)
            return

        payload = dict(event.payload or {})
        crawl_job_id = str(payload.get("crawl_job_id") or event.aggregate_id)
        source_site = str(payload.get("source_site") or "").strip().lower()
        request_payload = dict(payload.get("request_payload") or {})
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
            self.bus.ack(STREAM_CRAWL_COMMANDS, self.group_name, message.message_id)
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
            self._publish_item(
                crawl_job_id=crawl_job_id,
                source_site=source_site,
                payload=item_payload,
            )

        try:
            result = runner.crawl(
                crawl_job_id=crawl_job_id,
                request_payload=request_payload,
                emit_page_processed=emit_page_processed,
                emit_item_emitted=emit_item_emitted,
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
            self.bus.ack(STREAM_CRAWL_COMMANDS, self.group_name, message.message_id)

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
        envelope = build_event_envelope(
            event_type="crawl.item_emitted",
            aggregate_type="crawl_job",
            aggregate_id=crawl_job_id,
            payload={
                "crawl_job_id": crawl_job_id,
                "source_site": source_site,
                "job": payload,
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
