from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, exists, select, update
from sqlalchemy.orm import Session, noload

from app.models.crawl_job import CrawlJob
from app.models.crawl_job_listing import CrawlJobListing
from app.models.crawl_dispatch_plan import (
    CrawlDispatchPlan,
    CrawlDispatchPlanTarget,
    CrawlDispatchPlanTargetRow,
)
from app.models.job import Job
from app.models.schedule import ScheduleExecution
from app.crawl_control.task_control_board_contracts import (
    REMOVED_DISPATCH_PLAN_REASON_HISTORICAL_LISTING_DEDUPLICATION,
)


APPROVED_CRAWL_JOB_SOURCES = {
    UUID("720df33d-bcca-4ec0-b6e0-0da1f9c01a4f"): "ctgoodjobs",
    UUID("06e326b2-c4bf-440c-b196-b1a04fc8d6a5"): "jobsdb",
}

APPROVED_JOBSDB_DISPATCH_PLANS = {
    UUID("0c4418c9-2327-4c75-8268-f71f62369cd2"): (
        "consumed",
        UUID("bd343e54-a79d-4547-9fd5-57a7f49f5510"),
    ),
    UUID("ba27b116-21f1-4440-b163-1d899ee3fe43"): ("prepared", None),
}
APPROVED_REMOVED_DETAIL_CRAWL_JOB_ID = UUID("bd343e54-a79d-4547-9fd5-57a7f49f5510")


@dataclass(frozen=True)
class CrawlListingDeduplicationPreview:
    crawl_job_id: UUID
    source_site: str
    matched_rows: int
    retained_rows: int
    retained_source_job_ids: int
    replacement_metrics: dict[str, int]
    dispatch_plan_ids: tuple[UUID, ...] = ()
    dispatch_plan_target_rows: int = 0
    detached_crawl_job_ids: tuple[UUID, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "crawl_job_id": str(self.crawl_job_id),
            "source_site": self.source_site,
            "matched_rows": self.matched_rows,
            "retained_rows": self.retained_rows,
            "retained_source_job_ids": self.retained_source_job_ids,
            "replacement_metrics": dict(self.replacement_metrics),
            "dispatch_plan_ids": [str(plan_id) for plan_id in self.dispatch_plan_ids],
            "dispatch_plan_target_rows": self.dispatch_plan_target_rows,
            "detached_crawl_job_ids": [
                str(crawl_job_id) for crawl_job_id in self.detached_crawl_job_ids
            ],
        }


def _replacement_metrics(rows: list[CrawlJobListing]) -> dict[str, int]:
    status_counts = Counter(str(row.detail_status or "") for row in rows)
    distinct_source_job_ids = len(
        {
            str(row.source_job_id).strip()
            for row in rows
            if str(row.source_job_id).strip()
        }
    )
    return {
        "jobs_saved": 0,
        "detail_failed": int(status_counts.get("failed", 0)),
        "items_emitted": 0,
        "detail_pending": int(status_counts.get("pending", 0)),
        "detail_running": int(status_counts.get("running", 0)),
        "listings_staged": len(rows),
        "detail_completed": int(status_counts.get("completed", 0)),
        "job_ids_collected": distinct_source_job_ids,
        "detail_target_rows": 0,
        "detail_selected_rows": 0,
        "jobs_skipped_existing": 0,
        "raw_job_ids_collected": distinct_source_job_ids,
        "detail_identity_conflict": int(status_counts.get("identity_conflict", 0)),
        "detail_terminal_unavailable": int(
            status_counts.get("terminal_unavailable", 0)
        ),
        "detail_skipped_existing_rows": 0,
        "detail_manual_action_required": int(
            status_counts.get("manual_action_required", 0)
        ),
    }


def _published_job_exists() -> object:
    return exists(
        select(Job.id).where(
            Job.source_site == CrawlJobListing.source_site,
            Job.source_job_id == CrawlJobListing.source_job_id,
            Job.is_deleted.is_(False),
        )
    )


class CrawlListingDeduplicationService:
    """Guarded one-off cleanup for the two approved listing crawl jobs."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _inspect_jobsdb_dispatch_plans(
        self,
        *,
        jobsdb_listing_ids: set[UUID],
        jobsdb_matching_ids: set[UUID],
    ) -> tuple[tuple[UUID, ...], int, tuple[UUID, ...]]:
        approved_plan_ids = set(APPROVED_JOBSDB_DISPATCH_PLANS)
        plans = (
            self.db.query(CrawlDispatchPlan)
            .filter(CrawlDispatchPlan.id.in_(tuple(approved_plan_ids)))
            .options(noload("*"))
            .with_for_update()
            .all()
        )
        plans_by_id = {plan.id: plan for plan in plans}
        if plans_by_id and set(plans_by_id) != approved_plan_ids:
            raise RuntimeError(
                "Only part of the approved JobsDB Dispatch Plan set exists"
            )

        referenced_plan_ids: set[UUID] = set()
        if jobsdb_matching_ids:
            referenced_plan_ids = {
                plan_id
                for (plan_id,) in self.db.execute(
                    select(CrawlDispatchPlanTarget.plan_id)
                    .join(
                        CrawlDispatchPlanTargetRow,
                        CrawlDispatchPlanTargetRow.plan_target_id
                        == CrawlDispatchPlanTarget.id,
                    )
                    .where(
                        CrawlDispatchPlanTargetRow.crawl_job_listing_id.in_(
                            tuple(jobsdb_matching_ids)
                        )
                    )
                    .distinct()
                )
            }
            if referenced_plan_ids != approved_plan_ids:
                raise RuntimeError(
                    "JobsDB matching listings are not referenced by exactly the "
                    "approved Dispatch Plans"
                )

        if not plans_by_id:
            if referenced_plan_ids:
                raise RuntimeError("Approved JobsDB Dispatch Plans could not be loaded")
            detached_crawl_job = (
                self.db.query(CrawlJob)
                .filter(CrawlJob.id == APPROVED_REMOVED_DETAIL_CRAWL_JOB_ID)
                .options(noload("*"))
                .with_for_update()
                .one_or_none()
            )
            if detached_crawl_job is None:
                raise RuntimeError(
                    "Approved detached JobsDB Crawl Job no longer exists"
                )
            request_payload = (
                detached_crawl_job.request_payload
                if isinstance(detached_crawl_job.request_payload, dict)
                else {}
            )
            removed_plan_id = next(
                plan_id
                for plan_id, (_state, crawl_job_id) in (
                    APPROVED_JOBSDB_DISPATCH_PLANS.items()
                )
                if crawl_job_id == APPROVED_REMOVED_DETAIL_CRAWL_JOB_ID
            )
            if (
                detached_crawl_job.status != "cancelled"
                or detached_crawl_job.dispatch_plan_id is not None
                or detached_crawl_job.dispatch_plan_fingerprint is not None
                or request_payload.get("dispatch_plan_id") != str(removed_plan_id)
                or len(str(request_payload.get("dispatch_plan_fingerprint") or ""))
                != 64
            ):
                raise RuntimeError(
                    "Approved detached JobsDB Crawl Job no longer matches its fence"
                )
            marker = request_payload.get("removed_dispatch_plan")
            if marker is not None and marker != {
                "reason": (
                    REMOVED_DISPATCH_PLAN_REASON_HISTORICAL_LISTING_DEDUPLICATION
                ),
                "plan_id": str(removed_plan_id),
                "plan_fingerprint": request_payload["dispatch_plan_fingerprint"],
            }:
                raise RuntimeError("Detached JobsDB Crawl Job tombstone is invalid")
            return (), 0, (APPROVED_REMOVED_DETAIL_CRAWL_JOB_ID,)

        for plan_id, (
            expected_state,
            expected_crawl_job_id,
        ) in APPROVED_JOBSDB_DISPATCH_PLANS.items():
            plan = plans_by_id[plan_id]
            if (
                plan.source_site != "jobsdb"
                or plan.crawl_phase != "detail"
                or plan.state != expected_state
                or plan.crawl_job_id != expected_crawl_job_id
            ):
                raise RuntimeError(
                    f"Dispatch Plan {plan_id} no longer matches the approved fence"
                )

            membership_rows = self.db.execute(
                select(CrawlDispatchPlanTargetRow.crawl_job_listing_id)
                .join(
                    CrawlDispatchPlanTarget,
                    CrawlDispatchPlanTarget.id
                    == CrawlDispatchPlanTargetRow.plan_target_id,
                )
                .where(CrawlDispatchPlanTarget.plan_id == plan_id)
            ).all()
            membership_ids = {listing_id for (listing_id,) in membership_rows}
            if membership_ids != jobsdb_listing_ids or len(membership_rows) != len(
                membership_ids
            ):
                raise RuntimeError(
                    f"Dispatch Plan {plan_id} membership no longer matches the "
                    "approved JobsDB listing batch"
                )

        schedule_execution_count = (
            self.db.query(ScheduleExecution)
            .filter(ScheduleExecution.dispatch_plan_id.in_(tuple(approved_plan_ids)))
            .count()
        )
        if schedule_execution_count:
            raise RuntimeError(
                "Approved JobsDB Dispatch Plans have an unexpected Schedule Execution reference"
            )

        linked_crawl_jobs = (
            self.db.query(CrawlJob)
            .filter(CrawlJob.dispatch_plan_id.in_(tuple(approved_plan_ids)))
            .options(noload("*"))
            .with_for_update()
            .all()
        )
        expected_linked_ids = {
            crawl_job_id
            for _state, crawl_job_id in APPROVED_JOBSDB_DISPATCH_PLANS.values()
            if crawl_job_id is not None
        }
        linked_ids = {crawl_job.id for crawl_job in linked_crawl_jobs}
        if linked_ids != expected_linked_ids or any(
            str(crawl_job.status or "").strip().lower() != "cancelled"
            for crawl_job in linked_crawl_jobs
        ):
            raise RuntimeError(
                "Approved consumed Dispatch Plan is not linked only to its expected "
                "cancelled Crawl Job"
            )

        target_row_count = (
            self.db.query(CrawlDispatchPlanTargetRow)
            .join(
                CrawlDispatchPlanTarget,
                CrawlDispatchPlanTarget.id == CrawlDispatchPlanTargetRow.plan_target_id,
            )
            .filter(CrawlDispatchPlanTarget.plan_id.in_(tuple(approved_plan_ids)))
            .count()
        )
        return (
            tuple(APPROVED_JOBSDB_DISPATCH_PLANS),
            target_row_count,
            tuple(sorted(linked_ids, key=str)),
        )

    def _delete_jobsdb_dispatch_plans(
        self,
        plan_ids: tuple[UUID, ...],
        detached_crawl_job_ids: tuple[UUID, ...],
    ) -> None:
        for crawl_job_id in detached_crawl_job_ids:
            crawl_job = (
                self.db.query(CrawlJob)
                .filter(CrawlJob.id == crawl_job_id)
                .options(noload("*"))
                .with_for_update()
                .one()
            )
            request_payload = (
                dict(crawl_job.request_payload)
                if isinstance(crawl_job.request_payload, dict)
                else {}
            )
            plan_id = request_payload.get("dispatch_plan_id") or str(
                crawl_job.dispatch_plan_id
            )
            plan_fingerprint = (
                request_payload.get("dispatch_plan_fingerprint")
                or crawl_job.dispatch_plan_fingerprint
            )
            request_payload["dispatch_plan_id"] = plan_id
            request_payload["dispatch_plan_fingerprint"] = plan_fingerprint
            request_payload["removed_dispatch_plan"] = {
                "reason": (
                    REMOVED_DISPATCH_PLAN_REASON_HISTORICAL_LISTING_DEDUPLICATION
                ),
                "plan_id": plan_id,
                "plan_fingerprint": plan_fingerprint,
            }
            self.db.execute(
                update(CrawlJob.__table__)
                .where(CrawlJob.id == crawl_job_id)
                .values(
                    dispatch_plan_id=None,
                    dispatch_plan_fingerprint=None,
                    request_payload=request_payload,
                )
            )

        if not plan_ids:
            return
        plan_id_set = tuple(plan_ids)
        target_ids = select(CrawlDispatchPlanTarget.id).where(
            CrawlDispatchPlanTarget.plan_id.in_(plan_id_set)
        )
        self.db.execute(
            delete(CrawlDispatchPlanTargetRow.__table__).where(
                CrawlDispatchPlanTargetRow.plan_target_id.in_(target_ids)
            )
        )
        self.db.execute(
            delete(CrawlDispatchPlanTarget.__table__).where(
                CrawlDispatchPlanTarget.plan_id.in_(plan_id_set)
            )
        )
        self.db.execute(
            delete(CrawlDispatchPlan.__table__).where(
                CrawlDispatchPlan.id.in_(plan_id_set)
            )
        )

    def run(
        self,
        *,
        execute: bool = False,
        expected_matched_rows: dict[UUID, int] | None = None,
    ) -> tuple[CrawlListingDeduplicationPreview, ...]:
        expected = dict(expected_matched_rows or {})
        if execute and set(expected) != set(APPROVED_CRAWL_JOB_SOURCES):
            raise ValueError(
                "Execute requires an expected matched-row count for every approved crawl job"
            )

        crawl_jobs = (
            self.db.query(CrawlJob)
            .filter(CrawlJob.id.in_(tuple(APPROVED_CRAWL_JOB_SOURCES)))
            .options(noload("*"))
            .with_for_update()
            .all()
        )
        crawl_jobs_by_id = {crawl_job.id: crawl_job for crawl_job in crawl_jobs}
        if set(crawl_jobs_by_id) != set(APPROVED_CRAWL_JOB_SOURCES):
            raise RuntimeError("One or more approved crawl jobs do not exist")

        previews: list[CrawlListingDeduplicationPreview] = []
        retained_ids_before: dict[UUID, set[UUID]] = {}
        listing_ids_before: dict[UUID, set[UUID]] = {}
        matching_ids_before: dict[UUID, set[UUID]] = {}
        for crawl_job_id, expected_source in APPROVED_CRAWL_JOB_SOURCES.items():
            crawl_job = crawl_jobs_by_id[crawl_job_id]
            source_site = str(crawl_job.source_site or "").strip().lower()
            if source_site != expected_source:
                raise RuntimeError(
                    f"Crawl job {crawl_job_id} source mismatch: "
                    f"expected {expected_source}, found {source_site}"
                )
            if str(crawl_job.status or "").strip().lower() != "completed":
                raise RuntimeError(
                    f"Crawl job {crawl_job_id} must be completed before cleanup"
                )

            rows = (
                self.db.query(CrawlJobListing)
                .filter(CrawlJobListing.crawl_job_id == crawl_job_id)
                .order_by(CrawlJobListing.id.asc())
                .all()
            )
            row_sources = {str(row.source_site or "").strip().lower() for row in rows}
            if row_sources - {expected_source}:
                raise RuntimeError(
                    f"Crawl job {crawl_job_id} contains an unexpected listing source"
                )

            matching_ids = {
                listing_id
                for (listing_id,) in (
                    self.db.query(CrawlJobListing.id)
                    .filter(
                        CrawlJobListing.crawl_job_id == crawl_job_id,
                        _published_job_exists(),
                    )
                    .all()
                )
            }
            retained_rows = [row for row in rows if row.id not in matching_ids]
            listing_ids_before[crawl_job_id] = {row.id for row in rows}
            matching_ids_before[crawl_job_id] = matching_ids
            retained_ids_before[crawl_job_id] = {row.id for row in retained_rows}
            preview = CrawlListingDeduplicationPreview(
                crawl_job_id=crawl_job_id,
                source_site=expected_source,
                matched_rows=len(matching_ids),
                retained_rows=len(retained_rows),
                retained_source_job_ids=len(
                    {str(row.source_job_id).strip() for row in retained_rows}
                ),
                replacement_metrics=_replacement_metrics(retained_rows),
            )
            if execute and expected[crawl_job_id] != preview.matched_rows:
                raise RuntimeError(
                    f"Crawl job {crawl_job_id} matched-row fence changed: "
                    f"expected {expected[crawl_job_id]}, found {preview.matched_rows}"
                )
            previews.append(preview)

        jobsdb_crawl_job_id = next(
            crawl_job_id
            for crawl_job_id, source_site in APPROVED_CRAWL_JOB_SOURCES.items()
            if source_site == "jobsdb"
        )
        (
            plan_ids,
            plan_target_rows,
            detached_crawl_job_ids,
        ) = self._inspect_jobsdb_dispatch_plans(
            jobsdb_listing_ids=listing_ids_before[jobsdb_crawl_job_id],
            jobsdb_matching_ids=matching_ids_before[jobsdb_crawl_job_id],
        )
        previews = [
            (
                CrawlListingDeduplicationPreview(
                    crawl_job_id=preview.crawl_job_id,
                    source_site=preview.source_site,
                    matched_rows=preview.matched_rows,
                    retained_rows=preview.retained_rows,
                    retained_source_job_ids=preview.retained_source_job_ids,
                    replacement_metrics=preview.replacement_metrics,
                    dispatch_plan_ids=plan_ids,
                    dispatch_plan_target_rows=plan_target_rows,
                    detached_crawl_job_ids=detached_crawl_job_ids,
                )
                if preview.crawl_job_id == jobsdb_crawl_job_id
                else preview
            )
            for preview in previews
        ]

        if not execute:
            return tuple(previews)

        self._delete_jobsdb_dispatch_plans(plan_ids, detached_crawl_job_ids)
        for preview in previews:
            self.db.execute(
                delete(CrawlJobListing).where(
                    CrawlJobListing.crawl_job_id == preview.crawl_job_id,
                    _published_job_exists(),
                )
            )
            crawl_jobs_by_id[preview.crawl_job_id].metrics = dict(
                preview.replacement_metrics
            )
        self.db.flush()

        if plan_ids:
            remaining_plans = (
                self.db.query(CrawlDispatchPlan)
                .filter(CrawlDispatchPlan.id.in_(plan_ids))
                .count()
            )
            if remaining_plans:
                raise RuntimeError("Approved JobsDB Dispatch Plan deletion failed")
            remaining_links = (
                self.db.query(CrawlJob)
                .filter(CrawlJob.dispatch_plan_id.in_(plan_ids))
                .count()
            )
            if remaining_links:
                raise RuntimeError("Approved JobsDB Crawl Job detachment failed")

        for preview in previews:
            remaining_rows = (
                self.db.query(CrawlJobListing)
                .filter(CrawlJobListing.crawl_job_id == preview.crawl_job_id)
                .all()
            )
            if {row.id for row in remaining_rows} != retained_ids_before[
                preview.crawl_job_id
            ]:
                raise RuntimeError(
                    f"Crawl job {preview.crawl_job_id} retained-row verification failed"
                )
            remaining_matches = (
                self.db.query(CrawlJobListing.id)
                .filter(
                    CrawlJobListing.crawl_job_id == preview.crawl_job_id,
                    _published_job_exists(),
                )
                .count()
            )
            if remaining_matches:
                raise RuntimeError(
                    f"Crawl job {preview.crawl_job_id} still has published-identity listings"
                )

        return tuple(previews)
