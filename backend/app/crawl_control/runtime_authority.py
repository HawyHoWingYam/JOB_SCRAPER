from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.crawl_control.dispatch_plan_service import DispatchPlanService
from app.repositories.crawl_job_repository import CrawlJobRepository


@dataclass(frozen=True)
class LegacyWorkerStartupInput:
    request_payload: dict[str, Any]
    source_site: str


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
