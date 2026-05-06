from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.config import settings
from app.database import SessionLocal
from app.logging_config import configure_logging
from app.messaging.outbox_publisher import OutboxPublisher
from app.messaging.redis_stream_bus import RedisStreamBus, StreamMessage
from app.messaging.topics import STREAM_JOB_INGEST, STREAM_JOB_LIFECYCLE
from app.repositories.company_repository import CompanyRepository
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.repositories.job_repository import JobRepository
from app.utils.data_mapper import parse_listing_date, parse_salary_range
from app.utils.source_identity import (
    build_compat_company_id,
    build_compat_job_id,
    derive_source_company_id_from_raw_data,
    normalize_source_site,
)

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestActionResult:
    action: str
    job_id: str
    company_id: str
    crawl_job_id: str | None
    source_site: str
    source_job_id: str


class IngestWorkerService:
    def __init__(
        self,
        *,
        bus: RedisStreamBus | Any | None = None,
        outbox_publisher: OutboxPublisher | None = None,
        group_name: str = "ingest-workers",
        consumer_name: str = "ingest-worker",
        company_repository: CompanyRepository | None = None,
        crawl_job_repository: CrawlJobRepository | None = None,
        event_outbox_repository: EventOutboxRepository | None = None,
        job_repository: JobRepository | None = None,
        session_factory: Any | None = None,
    ):
        self.bus = bus or RedisStreamBus()
        self.outbox_publisher = outbox_publisher or OutboxPublisher(stream_bus=self.bus)
        self.group_name = group_name
        self.consumer_name = consumer_name
        self.company_repository = company_repository or CompanyRepository()
        self.crawl_job_repository = crawl_job_repository or CrawlJobRepository()
        self.event_outbox_repository = event_outbox_repository or EventOutboxRepository()
        self.job_repository = job_repository or JobRepository()
        self.session_factory = session_factory or SessionLocal
        self.bus.ensure_group(STREAM_JOB_INGEST, self.group_name)

    async def run_once(self) -> int:
        messages = self.bus.consume_group(
            STREAM_JOB_INGEST,
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
        if event.event_type != "crawl.item_emitted":
            self.bus.ack(STREAM_JOB_INGEST, self.group_name, message.message_id)
            return

        db = self.session_factory()
        try:
            result = self._persist_event(db, event)
            db.commit()
            self.outbox_publisher.publish_pending_batch(db, limit=100)
            logger.info(
                "ingest worker processed source_site=%s source_job_id=%s action=%s",
                result.source_site,
                result.source_job_id,
                result.action,
            )
        except Exception:
            db.rollback()
            logger.exception("ingest worker failed for event_id=%s", getattr(event, "event_id", None))
            raise
        finally:
            db.close()

        self.bus.ack(STREAM_JOB_INGEST, self.group_name, message.message_id)

    def _persist_event(self, db, event) -> IngestActionResult:
        canonical_job, crawl_job_id = self._extract_canonical_job(event)
        source_site = normalize_source_site(canonical_job["source_site"])
        source_job_id = str(canonical_job["source_job_id"]).strip()

        company_data = self._build_company_data(canonical_job)
        company, _company_action = self.company_repository.upsert_company(
            db,
            company_data,
            auto_commit=False,
        )

        job_data = self._build_job_data(canonical_job, company.id)
        job, job_action = self.job_repository.upsert_source_job(
            db,
            job_data,
            auto_commit=False,
        )

        if crawl_job_id is not None:
            metrics_delta = {"ingest_items_seen": 1}
            metrics_key = {
                "created": "ingest_jobs_created",
                "updated": "ingest_jobs_updated",
                "skipped": "ingest_jobs_skipped",
            }[job_action]
            metrics_delta[metrics_key] = 1
            self.crawl_job_repository.increment_metrics(
                db,
                crawl_job_id=uuid.UUID(crawl_job_id),
                metrics_delta=metrics_delta,
                auto_commit=False,
            )

        if job_action in {"created", "updated"}:
            self.event_outbox_repository.enqueue(
                db,
                topic=STREAM_JOB_LIFECYCLE,
                aggregate_type="job",
                aggregate_id=str(job.id),
                event_type="job.ingested",
                payload={
                    "crawl_job_id": crawl_job_id,
                    "job_id": str(job.id),
                    "external_job_id": job.job_id,
                    "source_site": source_site,
                    "source_job_id": source_job_id,
                    "company_id": str(company.id),
                    "action": job_action,
                },
                source_service="ingest-worker",
                auto_commit=False,
            )

        return IngestActionResult(
            action=job_action,
            job_id=str(job.id),
            company_id=str(company.id),
            crawl_job_id=crawl_job_id,
            source_site=source_site,
            source_job_id=source_job_id,
        )

    def _extract_canonical_job(self, event) -> tuple[dict[str, Any], str | None]:
        payload = dict(event.payload or {})
        if isinstance(payload.get("job"), dict):
            canonical_job = dict(payload["job"])
            crawl_job_id = payload.get("crawl_job_id")
        else:
            canonical_job = payload
            crawl_job_id = payload.get("crawl_job_id")

        if not canonical_job.get("source_site") and payload.get("source_site"):
            canonical_job["source_site"] = payload["source_site"]

        return canonical_job, str(crawl_job_id) if crawl_job_id else None

    def _build_company_data(self, canonical_job: dict[str, Any]) -> dict[str, Any]:
        source_site = normalize_source_site(canonical_job.get("source_site"))
        source_company_id = derive_source_company_id_from_raw_data(
            source_site,
            canonical_job.get("raw_data"),
        )
        if not source_company_id:
            raise ValueError(f"Missing source company id for source_site={source_site}")

        company_name = str(canonical_job.get("company_name") or "").strip() or "Unknown Company"
        return {
            "source_site": source_site,
            "source_company_id": source_company_id,
            "company_id": build_compat_company_id(source_site, source_company_id),
            "name": company_name,
            "industry": canonical_job.get("source_classification_name"),
            "location": canonical_job.get("location"),
            "extra_data": {
                "source_url": canonical_job.get("source_url"),
                "raw_data": canonical_job.get("raw_data"),
            },
        }

    def _build_job_data(self, canonical_job: dict[str, Any], company_id) -> dict[str, Any]:
        source_site = normalize_source_site(canonical_job.get("source_site"))
        source_job_id = str(canonical_job.get("source_job_id") or "").strip()
        salary_range = self._normalize_salary_range(canonical_job.get("salary_range"))
        salary_min, salary_max, salary_currency = parse_salary_range(
            salary_range if isinstance(salary_range, str) else None
        )

        return {
            "job_id": build_compat_job_id(source_site, source_job_id),
            "source_site": source_site,
            "source_job_id": source_job_id,
            "company_id": company_id,
            "title": canonical_job.get("title"),
            "description": canonical_job.get("description"),
            "salary_range": salary_range,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": salary_currency,
            "location": canonical_job.get("location"),
            "employment_type": canonical_job.get("employment_type"),
            "source_classification_id": canonical_job.get("source_classification_id"),
            "source_classification_name": canonical_job.get("source_classification_name"),
            "source_subclassification_id": canonical_job.get("source_subclassification_id"),
            "source_subclassification_name": canonical_job.get("source_subclassification_name"),
            "posted_date": self._parse_optional_datetime(canonical_job.get("posted_date")),
            "raw_data": canonical_job.get("raw_data"),
        }

    def _normalize_salary_range(self, value: Any) -> str | None:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        if isinstance(value, dict):
            for key in ("label", "display", "text"):
                label = value.get(key)
                if isinstance(label, str) and label.strip():
                    return label.strip()
        return None

    def _parse_optional_datetime(self, value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            parsed = parse_listing_date(value)
            if parsed is not None:
                return parsed
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None


async def main() -> None:
    service = IngestWorkerService()
    logger.info("Starting ingest worker")
    while True:
        processed = await service.run_once()
        if processed == 0:
            await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())
