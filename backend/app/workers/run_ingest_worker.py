from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.config import settings
from app.database import SessionLocal
from app.logging_config import configure_logging
from app.job_intelligence.source_attributes import (
    SourceCatalogRevisionRef,
    SourceJobAttributeEvidence,
    SourceJobAttributes,
)
from app.crawl_control.dispatch_plan_service import DispatchPlanService
from app.job_intelligence.company_industry import (
    project_company_industry as project_company_industry_evidence,
)
from app.messaging.event_envelope import build_event_envelope
from app.messaging.outbox_publisher import OutboxPublisher
from app.messaging.redis_stream_bus import RedisStreamBus, StreamMessage
from app.messaging.topics import STREAM_JOB_INGEST, STREAM_JOB_INGEST_DEAD_LETTER, STREAM_JOB_LIFECYCLE
from app.repositories.crawl_job_listing_repository import CrawlJobListingRepository
from app.repositories.company_repository import CompanyRepository
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.repositories.job_repository import JobRepository
from app.scraper.log_events import build_scrape_log_event
from app.utils.data_mapper import parse_listing_date, parse_salary_range
from app.utils.source_identity import (
    build_compat_company_id,
    build_compat_job_id,
    derive_source_company_id_from_raw_data,
    normalize_source_site,
)

from app.workers.event_types import INGEST_ITEM_SETTLED_EVENT_TYPE

configure_logging(settings.log_level, settings.scraper_log_level)
logger = logging.getLogger(__name__)
_STALE_PENDING_RECLAIM_IDLE_MS = 60_000


@dataclass(frozen=True)
class IngestActionResult:
    action: str
    job_id: str
    company_id: str
    crawl_job_id: str | None
    listing_id: str | None
    source_site: str
    source_job_id: str


class InvalidIngestPayloadError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _build_ingest_result_log_message(result: IngestActionResult) -> str:
    return build_scrape_log_event(
        "SCRAPE_INGEST_RESULT",
        source=result.source_site,
        crawl_job_id=result.crawl_job_id,
        listing_id=result.listing_id,
        source_job_id=result.source_job_id,
        action=result.action,
        job_id=result.job_id,
        company_id=result.company_id,
    )


class IngestWorkerService:
    def __init__(
        self,
        *,
        bus: RedisStreamBus | Any | None = None,
        outbox_publisher: OutboxPublisher | None = None,
        group_name: str = "ingest-workers",
        consumer_name: str = "ingest-worker",
        crawl_job_listing_repository: CrawlJobListingRepository | None = None,
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
        self.crawl_job_listing_repository = crawl_job_listing_repository or CrawlJobListingRepository()
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
            reclaim_idle_ms=_STALE_PENDING_RECLAIM_IDLE_MS,
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
            logger.info(_build_ingest_result_log_message(result))
        except InvalidIngestPayloadError as exc:
            db.rollback()
            self._record_ingest_failure(db, event, exc)
            db.commit()
            self._publish_dead_letter(message, exc)
            logger.warning(
                "ingest worker dead-lettered event_id=%s reason=%s",
                getattr(event, "event_id", None),
                exc.reason,
            )
        except Exception:
            db.rollback()
            logger.exception("ingest worker failed for event_id=%s", getattr(event, "event_id", None))
            raise
        finally:
            db.close()

        self.bus.ack(STREAM_JOB_INGEST, self.group_name, message.message_id)

    def _persist_event(self, db, event) -> IngestActionResult:
        canonical_job, crawl_job_id, listing_id = self._extract_canonical_job(event)
        self._validate_canonical_job(canonical_job)
        source_site = normalize_source_site(canonical_job["source_site"])
        source_job_id = str(canonical_job["source_job_id"]).strip()
        skip_existing = self._resolve_skip_existing(db, crawl_job_id=crawl_job_id)
        source_catalog_revision = self._resolve_source_catalog_revision(
            db,
            crawl_job_id=crawl_job_id,
            source_site=source_site,
        )

        company_data = self._build_company_data(canonical_job)
        company, _company_action = self.company_repository.upsert_company(
            db,
            company_data,
            auto_commit=False,
        )
        self.project_company_industry(db, company, canonical_job)

        job_data = self._build_job_data(canonical_job, company.id)
        job, job_action = self.job_repository.upsert_source_job(
            db,
            job_data,
            skip_existing=skip_existing,
            auto_commit=False,
        )
        self.project_source_attributes(
            db,
            job,
            canonical_job,
            source_catalog_revision=source_catalog_revision,
        )
        if listing_id is not None:
            self.crawl_job_listing_repository.attach_published_job(
                db,
                listing_id=uuid.UUID(listing_id),
                published_job_id=job.id,
                auto_commit=False,
            )
            logger.debug(
                build_scrape_log_event(
                    "SCRAPE_INGEST_ATTACH_LISTING",
                    source=source_site,
                    crawl_job_id=crawl_job_id,
                    listing_id=listing_id,
                    source_job_id=source_job_id,
                    job_id=str(job.id),
                )
            )

        if crawl_job_id is not None:
            metrics_delta = {
                "ingest_items_seen": 1,
                "ingest_items_settled": 1,
            }
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
            self.crawl_job_repository.append_event(
                db,
                crawl_job_id=uuid.UUID(crawl_job_id),
                event_type=INGEST_ITEM_SETTLED_EVENT_TYPE,
                payload={
                    "source_site": source_site,
                    "source_job_id": source_job_id,
                    "job_id": str(job.id),
                    "action": job_action,
                },
                emitted_by="ingest-worker",
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
            listing_id=listing_id,
            source_site=source_site,
            source_job_id=source_job_id,
        )

    def project_source_attributes(
        self,
        db,
        job,
        canonical_job: dict[str, Any],
        *,
        source_catalog_revision: SourceCatalogRevisionRef | None = None,
    ):
        source_attribute_payload = canonical_job.get("source_attribute_evidence")
        if source_attribute_payload is None:
            raise InvalidIngestPayloadError(
                "missing_source_attribute_evidence",
                "Canonical collected Job has no Source Job Attribute evidence",
            )
        try:
            source_attribute_evidence = SourceJobAttributeEvidence.from_payload(
                source_attribute_payload
            )
            return SourceJobAttributes(
                db,
                outbox_repository=self.event_outbox_repository,
            ).project(
                job.id,
                source_attribute_evidence,
                source_catalog_revision=source_catalog_revision,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidIngestPayloadError(
                "invalid_source_attribute_evidence",
                f"Invalid Source Job Attribute evidence: {exc}",
            ) from exc

    def _resolve_source_catalog_revision(
        self,
        db,
        *,
        crawl_job_id: str | None,
        source_site: str,
    ) -> SourceCatalogRevisionRef | None:
        """Resolve only immutable Dispatch Plan authority; never active defaults."""

        if not crawl_job_id:
            return None
        try:
            crawl_job_uuid = uuid.UUID(str(crawl_job_id))
        except (TypeError, ValueError, AttributeError):
            return None

        crawl_job = self.crawl_job_repository.get_crawl_job_by_id(
            db,
            crawl_job_uuid,
        )
        if crawl_job is None:
            return None
        has_plan_fields = (
            crawl_job.dispatch_plan_id is not None
            or crawl_job.dispatch_plan_fingerprint is not None
        )
        if not has_plan_fields:
            return None

        try:
            authority = DispatchPlanService(db).load_execution_authority(
                crawl_job.id
            )
        except Exception as exc:
            raise InvalidIngestPayloadError(
                "source_catalog_authority_invalid",
                f"Unable to load versioned source catalog authority: {exc}",
            ) from exc
        if authority is None:
            raise InvalidIngestPayloadError(
                "source_catalog_authority_missing",
                "Versioned Crawl Job has no Dispatch Plan authority",
            )

        content = authority.dispatch_plan.content
        if content.source_site != source_site:
            raise InvalidIngestPayloadError(
                "source_catalog_authority_source_mismatch",
                "Dispatch Plan source does not match collected Job source",
            )
        return SourceCatalogRevisionRef(
            source_site=content.source_site,
            revision_id=content.catalog_revision_id,
            fingerprint=content.resolved_scope.catalog_revision_fingerprint,
        )

    def project_company_industry(self, db, company, canonical_job: dict[str, Any]):
        try:
            return project_company_industry_evidence(
                db,
                company.id,
                canonical_job,
                outbox_repository=self.event_outbox_repository,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidIngestPayloadError(
                "invalid_company_industry_evidence",
                f"Invalid Company Industry evidence: {exc}",
            ) from exc

    def _resolve_skip_existing(self, db, *, crawl_job_id: str | None) -> bool:
        if not crawl_job_id:
            return False

        try:
            crawl_job = self.crawl_job_repository.get_crawl_job_by_id(db, uuid.UUID(str(crawl_job_id)))
        except ValueError:
            return False

        if crawl_job is None:
            return False

        request_payload = crawl_job.request_payload if isinstance(crawl_job.request_payload, dict) else {}
        return bool(request_payload.get("skip_existing"))

    def _extract_canonical_job(self, event) -> tuple[dict[str, Any], str | None, str | None]:
        payload = dict(event.payload or {})
        if isinstance(payload.get("job"), dict):
            canonical_job = dict(payload["job"])
            crawl_job_id = payload.get("crawl_job_id")
        else:
            canonical_job = payload
            crawl_job_id = payload.get("crawl_job_id")
        listing_id = payload.get("listing_id")

        if not canonical_job.get("source_site") and payload.get("source_site"):
            canonical_job["source_site"] = payload["source_site"]

        return (
            canonical_job,
            str(crawl_job_id) if crawl_job_id else None,
            str(listing_id) if listing_id else None,
        )

    def _validate_canonical_job(self, canonical_job: dict[str, Any]) -> None:
        source_site = normalize_source_site(canonical_job.get("source_site"))
        source_job_id = str(canonical_job.get("source_job_id") or "").strip()
        if not source_site:
            raise InvalidIngestPayloadError("missing_source_site", "Missing source_site")
        if not source_job_id:
            raise InvalidIngestPayloadError("missing_source_job_id", "Missing source_job_id")

        raw_data = canonical_job.get("raw_data")
        raw_errors = raw_data.get("errors") if isinstance(raw_data, dict) else []
        normalized_errors = {str(error).strip() for error in (raw_errors or []) if str(error).strip()}
        title = str(canonical_job.get("title") or "").strip()
        description = str(canonical_job.get("description") or "").strip()
        if "missing_job_content" in normalized_errors or (not title and not description):
            raise InvalidIngestPayloadError(
                "missing_job_content",
                f"Missing job content for source_site={source_site} source_job_id={source_job_id}",
            )

    def _build_company_data(self, canonical_job: dict[str, Any]) -> dict[str, Any]:
        source_site = normalize_source_site(canonical_job.get("source_site"))
        source_company_id = derive_source_company_id_from_raw_data(
            source_site,
            canonical_job.get("raw_data"),
        )
        company_name = str(canonical_job.get("company_name") or "").strip()
        if not source_company_id:
            if not company_name:
                raise InvalidIngestPayloadError(
                    "missing_company_identity",
                    f"Missing source company id and company name for source_site={source_site}",
                )
            source_company_id = self._derive_fallback_source_company_id(
                source_site=source_site,
                company_name=company_name,
            )

        return {
            "source_site": source_site,
            "source_company_id": source_company_id,
            "company_id": build_compat_company_id(source_site, source_company_id),
            "name": company_name,
            "location": canonical_job.get("location"),
            "extra_data": {
                "source_url": canonical_job.get("source_url"),
                "raw_data": canonical_job.get("raw_data"),
                "source_identity": "fallback_company_name"
                if str(source_company_id).startswith("fallback:name:")
                else "source_company_id",
            },
        }

    def _derive_fallback_source_company_id(self, *, source_site: str, company_name: str) -> str:
        normalized_company_name = " ".join(str(company_name or "").strip().lower().split())
        digest = hashlib.sha1(f"{source_site}:{normalized_company_name}".encode("utf-8")).hexdigest()[:16]
        return f"fallback:name:{digest}"

    def _record_ingest_failure(self, db, event, exc: InvalidIngestPayloadError) -> None:
        payload = dict(event.payload or {})
        crawl_job_id = payload.get("crawl_job_id") or getattr(event, "aggregate_id", None)
        if not crawl_job_id:
            return

        safe_reason = "".join(ch if ch.isalnum() else "_" for ch in exc.reason).strip("_") or "unknown"
        try:
            self.crawl_job_repository.increment_metrics(
                db,
                crawl_job_id=uuid.UUID(str(crawl_job_id)),
                metrics_delta={
                    "ingest_items_failed": 1,
                    "ingest_items_settled": 1,
                    "ingest_dead_lettered": 1,
                    f"ingest_failure_{safe_reason}": 1,
                },
                auto_commit=False,
            )
            self.crawl_job_repository.append_event(
                db,
                crawl_job_id=uuid.UUID(str(crawl_job_id)),
                event_type=INGEST_ITEM_SETTLED_EVENT_TYPE,
                payload={
                    "source_site": payload.get("source_site"),
                    "source_job_id": (payload.get("job") or {}).get("source_job_id")
                    if isinstance(payload.get("job"), dict)
                    else payload.get("source_job_id"),
                    "action": "dead_lettered",
                    "reason": exc.reason,
                },
                emitted_by="ingest-worker",
                auto_commit=False,
            )
        except ValueError:
            logger.warning("could not attach ingest failure to missing crawl_job_id=%s", crawl_job_id)

    def _publish_dead_letter(self, message: StreamMessage | Any, exc: InvalidIngestPayloadError) -> None:
        event = message.event
        original_event = event.to_dict() if hasattr(event, "to_dict") else {
            "event_id": getattr(event, "event_id", None),
            "event_type": getattr(event, "event_type", None),
            "payload": getattr(event, "payload", None),
        }
        payload = dict(getattr(event, "payload", None) or {})
        envelope = build_event_envelope(
            event_type="ingest.message_dead_lettered",
            aggregate_type=getattr(event, "aggregate_type", "crawl_job"),
            aggregate_id=str(getattr(event, "aggregate_id", payload.get("crawl_job_id") or "")),
            source_service="ingest-worker",
            payload={
                "reason": exc.reason,
                "error": str(exc),
                "original_message_id": getattr(message, "message_id", None),
                "original_event_id": getattr(event, "event_id", None),
                "crawl_job_id": payload.get("crawl_job_id"),
                "source_site": payload.get("source_site"),
                "source_job_id": (payload.get("job") or {}).get("source_job_id")
                if isinstance(payload.get("job"), dict)
                else payload.get("source_job_id"),
                "original_event": original_event,
            },
        )
        self.bus.publish(STREAM_JOB_INGEST_DEAD_LETTER, envelope)

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
