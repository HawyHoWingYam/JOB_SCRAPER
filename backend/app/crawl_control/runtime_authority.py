from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.crawl_control.dispatch_plan_contracts import ExecutionAuthorityV1
from app.crawl_control.dispatch_plan_service import DispatchPlanService
from app.crawl_control.errors import DispatchPlanStaleError
from app.crawl_control.listing_runtime import (
    ListingRuntimePlan,
    build_listing_runtime_plan,
)
from app.repositories.crawl_job_repository import CrawlJobRepository


@dataclass(frozen=True)
class LegacyWorkerStartupInput:
    request_payload: dict[str, Any]
    source_site: str


@dataclass(frozen=True)
class WorkerStartupInput:
    request_payload: dict[str, Any]
    source_site: str
    execution_authority: ExecutionAuthorityV1 | None = None
    listing_runtime_plan: ListingRuntimePlan | None = None

    @property
    def is_versioned(self) -> bool:
        return self.execution_authority is not None


def load_legacy_worker_startup_input(
    db: Session,
    *,
    crawl_job_id,
    default_source_site: str,
) -> LegacyWorkerStartupInput:
    """Load legacy payloads while fail-closing versioned jobs at one boundary."""

    crawl_job = CrawlJobRepository().get_crawl_job_by_id(db, crawl_job_id)
    if crawl_job is None:
        return LegacyWorkerStartupInput(
            request_payload={},
            source_site=default_source_site,
        )
    if (
        crawl_job.dispatch_plan_id is not None
        or crawl_job.dispatch_plan_fingerprint is not None
    ):
        plan_service = DispatchPlanService(db)
        authority = plan_service.load_execution_authority(crawl_job.id)
        plan_service.require_worker_runtime_supported(authority)
        raise AssertionError("Versioned worker authority gate unexpectedly returned")
    return LegacyWorkerStartupInput(
        request_payload=dict(crawl_job.request_payload or {}),
        source_site=str(crawl_job.source_site or default_source_site),
    )


def load_worker_startup_input(
    db: Session,
    *,
    crawl_job_id,
    default_source_site: str,
    allow_missing: bool = False,
) -> WorkerStartupInput:
    """Load legacy input or validated listing authority at the worker boundary."""

    crawl_job = CrawlJobRepository().get_crawl_job_by_id(db, crawl_job_id)
    if crawl_job is None:
        if allow_missing:
            return WorkerStartupInput(
                request_payload={},
                source_site=default_source_site,
            )
        raise DispatchPlanStaleError(
            "Crawl Job no longer exists at worker startup",
            reason="crawl_job_missing",
        )
    if (
        crawl_job.dispatch_plan_id is None
        and crawl_job.dispatch_plan_fingerprint is None
    ):
        return WorkerStartupInput(
            request_payload=dict(crawl_job.request_payload or {}),
            source_site=str(crawl_job.source_site or default_source_site),
        )

    plan_service = DispatchPlanService(db)
    authority = plan_service.load_execution_authority(crawl_job.id)
    assert authority is not None
    plan_service.require_worker_runtime_supported(
        authority,
        supported_phases=("listing",),
    )
    listing_runtime_plan = build_listing_runtime_plan(
        authority,
        expected_source_site=default_source_site,
    )
    return WorkerStartupInput(
        request_payload={},
        source_site=listing_runtime_plan.source_site,
        execution_authority=authority,
        listing_runtime_plan=listing_runtime_plan,
    )


def load_listing_runtime_plan_for_worker(
    crawl_job_id,
    *,
    expected_source_site: str,
) -> ListingRuntimePlan | None:
    """Reload listing authority by Crawl Job ID inside a retained worker."""

    if not str(crawl_job_id or "").strip():
        return None
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return load_worker_startup_input(
            db,
            crawl_job_id=crawl_job_id,
            default_source_site=expected_source_site,
        ).listing_runtime_plan
    finally:
        db.close()
