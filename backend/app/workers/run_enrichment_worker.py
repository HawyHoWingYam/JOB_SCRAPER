from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import settings
from app.database import SessionLocal
from app.logging_config import configure_logging
from app.messaging.outbox_publisher import OutboxPublisher
from app.messaging.redis_stream_bus import RedisStreamBus, StreamMessage
from app.messaging.topics import STREAM_CRAWL_PROGRESS, STREAM_JOB_LIFECYCLE
from app.services.enrichment_run_service import EnrichmentRunService
from app.services.startup_recovery_service import StartupRecoveryService

configure_logging(settings.log_level, settings.scraper_log_level)
logger = logging.getLogger(__name__)
_STALE_PENDING_RECLAIM_IDLE_MS = 60_000


def run_worker_startup_recovery() -> dict[str, int]:
    db = SessionLocal()
    try:
        recovered_ai_runs = StartupRecoveryService(db).recover_ai_runs_only()
        queued_pending_runs = EnrichmentRunService(db).request_ready_pending_runs(
            source_service="enrichment-worker-startup",
        )
        db.commit()
        OutboxPublisher().publish_pending_batch(db, limit=100)
        return {
            "recovered_ai_runs": recovered_ai_runs,
            "queued_pending_runs": queued_pending_runs,
        }
    finally:
        db.close()


class EnrichmentWorkerService:
    def __init__(
        self,
        *,
        bus: RedisStreamBus | Any | None = None,
        outbox_publisher: OutboxPublisher | None = None,
        group_name: str = "enrichment-workers",
        consumer_name: str = "enrichment-worker",
        session_factory: Any | None = None,
        enrichment_service=None,
    ):
        self.bus = bus or RedisStreamBus()
        self.outbox_publisher = outbox_publisher or OutboxPublisher(stream_bus=self.bus)
        self.group_name = group_name
        self.consumer_name = consumer_name
        self.session_factory = session_factory or SessionLocal
        self.enrichment_service = enrichment_service
        self.bus.ensure_group(STREAM_JOB_LIFECYCLE, self.group_name)
        self.bus.ensure_group(STREAM_CRAWL_PROGRESS, self.group_name)

    async def run_once(self) -> int:
        processed = 0

        lifecycle_messages = self.bus.consume_group(
            STREAM_JOB_LIFECYCLE,
            self.group_name,
            self.consumer_name,
            count=10,
            block_ms=100,
            reclaim_idle_ms=_STALE_PENDING_RECLAIM_IDLE_MS,
        )
        for message in lifecycle_messages:
            await self._handle_lifecycle_message(message)
        processed += len(lifecycle_messages)

        progress_messages = self.bus.consume_group(
            STREAM_CRAWL_PROGRESS,
            self.group_name,
            self.consumer_name,
            count=10,
            block_ms=100,
            reclaim_idle_ms=_STALE_PENDING_RECLAIM_IDLE_MS,
        )
        for message in progress_messages:
            await self._handle_progress_message(message)
        processed += len(progress_messages)

        self._run_maintenance()
        return processed

    def _run_maintenance(self) -> None:
        """Promote retained automatic work and republish durable requests."""
        db = self.session_factory()
        try:
            EnrichmentRunService(db).request_ready_pending_runs(
                source_service="enrichment-worker-maintenance",
            )
            db.commit()
            self.outbox_publisher.publish_pending_batch(db, limit=100)
        except Exception:
            db.rollback()
            logger.exception("enrichment worker maintenance sweep failed")
        finally:
            db.close()

    async def _handle_lifecycle_message(self, message: StreamMessage | Any) -> None:
        event = message.event
        if event.event_type == "job.ingested":
            db = self.session_factory()
            try:
                payload = dict(event.payload or {})
                crawl_job_id = payload.get("crawl_job_id")
                job_id = payload.get("job_id")
                if crawl_job_id and job_id:
                    service = EnrichmentRunService(db)
                    append_result = service.append_job_to_crawl_auto_run(
                        crawl_job_id=str(crawl_job_id),
                        job_id=str(job_id),
                    )
                    if append_result.action == "skipped_terminal":
                        logger.info(
                            "skipped late job.ingested for terminal crawl_auto run_id=%s crawl_job_id=%s reason=%s",
                            append_result.run.id,
                            crawl_job_id,
                            append_result.skipped_reason,
                        )
                    else:
                        service.request_crawl_auto_run_if_ready(str(crawl_job_id))
                    db.commit()
                    self.outbox_publisher.publish_pending_batch(db, limit=100)
            except Exception:
                db.rollback()
                logger.exception("enrichment worker failed while handling job.ingested")
                raise
            finally:
                db.close()
            self.bus.ack(STREAM_JOB_LIFECYCLE, self.group_name, message.message_id)
            return

        if event.event_type == "enrichment.run.requested":
            db = self.session_factory()
            try:
                payload = dict(event.payload or {})
                run_id = str(payload.get("run_id") or event.aggregate_id)
                service = EnrichmentRunService(db)
                claimed_run = service.claim_run(run_id)
                if claimed_run is not None:
                    try:
                        await service.execute_run(
                            run_id,
                            enrichment_service=self.enrichment_service,
                            claim=False,
                        )
                    except Exception as exc:
                        db.rollback()
                        service.mark_run_failed(run_id, str(exc))
                        db.commit()
                        raise
                    self.outbox_publisher.publish_pending_batch(db, limit=100)
            except Exception:
                logger.exception("enrichment worker failed while executing run request")
                raise
            finally:
                db.close()
            self.bus.ack(STREAM_JOB_LIFECYCLE, self.group_name, message.message_id)
            return

        self.bus.ack(STREAM_JOB_LIFECYCLE, self.group_name, message.message_id)

    async def _handle_progress_message(self, message: StreamMessage | Any) -> None:
        event = message.event
        if event.event_type not in {"crawl.completed", "crawl.failed"}:
            self.bus.ack(STREAM_CRAWL_PROGRESS, self.group_name, message.message_id)
            return

        db = self.session_factory()
        try:
            payload = dict(event.payload or {})
            crawl_job_id = str(payload.get("crawl_job_id") or event.aggregate_id)
            service = EnrichmentRunService(db)
            service.request_crawl_auto_run_if_ready(crawl_job_id)
            db.commit()
            self.outbox_publisher.publish_pending_batch(db, limit=100)
        except Exception:
            db.rollback()
            logger.exception("enrichment worker failed while handling crawl progress")
            raise
        finally:
            db.close()

        self.bus.ack(STREAM_CRAWL_PROGRESS, self.group_name, message.message_id)


async def main() -> None:
    recovery_summary = run_worker_startup_recovery()
    logger.info(
        "Starting enrichment worker (recovered_ai_runs=%s queued_pending_runs=%s)",
        recovery_summary["recovered_ai_runs"],
        recovery_summary["queued_pending_runs"],
    )
    service = EnrichmentWorkerService()
    while True:
        processed = await service.run_once()
        if processed == 0:
            await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())
