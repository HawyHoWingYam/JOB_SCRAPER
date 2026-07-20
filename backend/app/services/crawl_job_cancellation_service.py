from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.crawl_phases import resolve_crawl_phase
from app.database import SessionLocal
from app.models.crawl_dispatch_plan import (
    CrawlDispatchPlanTarget,
    CrawlDispatchPlanTargetRow,
)
from app.models.crawl_job_listing import CrawlJobListing
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.utils.time import utc_now


logger = logging.getLogger(__name__)


class CrawlJobCancellationService:
    """Acknowledge cancellation only after execution shutdown is confirmed."""

    def __init__(
        self,
        *,
        session_factory=SessionLocal,
        crawl_job_repository: CrawlJobRepository | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.crawl_job_repository = crawl_job_repository or CrawlJobRepository()

    def acknowledge_cancelled(
        self,
        *,
        crawl_job_id,
        execution_generation: str | None = None,
        reason: str = "Cancelled by operator request.",
        emitted_by: str = "crawl-execution-supervisor",
    ) -> bool:
        db = self.session_factory()
        try:
            crawl_job = self.crawl_job_repository.get_crawl_job_by_id_for_update(
                db, crawl_job_id
            )
            if crawl_job is None:
                return False
            if crawl_job.status == "cancelled":
                return True
            if crawl_job.status != "cancelling":
                return False

            timestamp = utc_now()
            recovered_records = self._release_running_detail_rows(
                db,
                crawl_job_id=crawl_job.id,
                dispatch_plan_id=getattr(crawl_job, "dispatch_plan_id", None),
                timestamp=timestamp,
            )
            metrics = dict(crawl_job.metrics or {})
            crawl_phase = resolve_crawl_phase(
                (crawl_job.request_payload or {}).get("crawl_phase")
            )
            if crawl_phase == "listing":
                metrics["listing_completed"] = False
                metrics["listing_partial"] = True
            crawl_job.metrics = metrics
            crawl_job.status = "cancelled"
            crawl_job.completed_at = timestamp
            crawl_job.error_message = reason

            payload: dict[str, Any] = {
                "crawl_job_id": str(crawl_job.id),
                "source_site": crawl_job.source_site,
                "crawl_phase": crawl_phase,
                "status": "cancelled",
                "reason": reason,
                "execution_generation": execution_generation,
                "released_detail_rows": len(recovered_records),
            }
            self.crawl_job_repository.append_event(
                db,
                crawl_job_id=crawl_job.id,
                event_type="crawl.cancelled",
                payload=payload,
                emitted_by=emitted_by,
                auto_commit=False,
            )
            if recovered_records:
                self.crawl_job_repository.append_event(
                    db,
                    crawl_job_id=crawl_job.id,
                    event_type="crawl.detail_cancelled_recovered",
                    payload={"records": recovered_records},
                    emitted_by=emitted_by,
                    auto_commit=False,
                )
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _release_running_detail_rows(
        db,
        *,
        crawl_job_id,
        dispatch_plan_id,
        timestamp,
    ) -> list[dict]:
        query = db.query(CrawlJobListing).filter(
            CrawlJobListing.last_detail_crawl_job_id == crawl_job_id,
            CrawlJobListing.detail_status == "running",
        )
        if dispatch_plan_id is not None:
            frozen_membership = (
                select(CrawlDispatchPlanTargetRow.crawl_job_listing_id)
                .join(
                    CrawlDispatchPlanTarget,
                    CrawlDispatchPlanTarget.id
                    == CrawlDispatchPlanTargetRow.plan_target_id,
                )
                .where(CrawlDispatchPlanTarget.plan_id == dispatch_plan_id)
            )
            query = query.filter(CrawlJobListing.id.in_(frozen_membership))
        rows = query.order_by(
            CrawlJobListing.created_at.asc(),
            CrawlJobListing.id.asc(),
        ).all()
        records: list[dict] = []
        for row in rows:
            row.detail_status = "pending"
            row.detail_error_message = None
            row.detail_started_at = None
            row.detail_completed_at = None
            records.append(
                {
                    "listing_id": str(row.id),
                    "source_site": row.source_site,
                    "source_job_id": row.source_job_id,
                    "before_status": "running",
                    "after_status": "pending",
                    "outcome": "cancelled_retryable",
                }
            )
        return records
