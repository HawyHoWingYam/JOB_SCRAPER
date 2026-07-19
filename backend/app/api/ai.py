"""
AI Enrichment API Endpoints
"""

import asyncio
import logging
from datetime import date
from typing import List, Literal, Optional, TypedDict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel, Field, field_validator, model_validator
from app.database import SessionLocal, get_db
from app.messaging.outbox_publisher import OutboxPublisher
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.job_category import JobCategory
from app.models.job import Job
from app.models.job_skill_mention import JobSkillMention
from app.models.job_subcategory import JobSubcategory
from app.models.skill import Skill
from app.models.skill_technology import SkillTechnology
from app.schemas import JobDetailSchema
from app.services.enrichment_run_service import (
    ActiveEnrichmentRunError,
    EnrichmentRunService,
    PendingJobFilters,
)
from app.services.ai_runtime_settings_service import (
    ensure_profile_runtime_ready,
    ProfileRuntimeNotReadyError,
)
from app.services.source_catalog import list_supported_source_sites

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ai", tags=["ai"])
ACTIVE_AI_RUN_STATUSES = {"pending", "running", "stopping"}
MAX_PENDING_RUN_LIMIT = 5000


class ExcludedDetail(TypedDict):
    source_classification_id: str | None
    source_classification_name: str | None
    count: int
    reason: str
    job_ids: list[str]


class EnrichRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=MAX_PENDING_RUN_LIMIT)
    all_pending_acknowledged: bool = False

    @model_validator(mode="after")
    def require_acknowledgement(self):
        if not self.all_pending_acknowledged:
            raise ValueError("all_pending_acknowledged must be true")
        return self


class PendingFiltersRequest(BaseModel):
    source_sites: List[str] = Field(default_factory=list)
    source_classification_names: List[str] = Field(default_factory=list)
    source_subclassification_names: List[str] = Field(default_factory=list)
    posted_date_from: Optional[date] = None
    posted_date_to: Optional[date] = None

    @field_validator(
        "source_sites",
        "source_classification_names",
        "source_subclassification_names",
        mode="before",
    )
    @classmethod
    def normalize_values(cls, value):
        values = value if isinstance(value, list) else []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in values:
            text_value = str(item or "").strip().lower()
            if text_value and text_value not in seen:
                seen.add(text_value)
                normalized.append(text_value)
        return normalized

    @field_validator("source_sites")
    @classmethod
    def validate_sources(cls, value: List[str]) -> List[str]:
        supported = set(list_supported_source_sites())
        unsupported = [source for source in value if source not in supported]
        if unsupported:
            raise ValueError(f"Unsupported source site(s): {', '.join(unsupported)}")
        return value

    @model_validator(mode="after")
    def validate_dates(self):
        if (
            self.posted_date_from is not None
            and self.posted_date_to is not None
            and self.posted_date_from > self.posted_date_to
        ):
            raise ValueError("posted_date_from must be on or before posted_date_to")
        return self

    def to_service_filters(self) -> PendingJobFilters:
        return PendingJobFilters(
            source_sites=tuple(self.source_sites),
            source_classification_names=tuple(self.source_classification_names),
            source_subclassification_names=tuple(self.source_subclassification_names),
            posted_date_from=self.posted_date_from,
            posted_date_to=self.posted_date_to,
        )


class PendingSelectionRequest(BaseModel):
    filters: PendingFiltersRequest = Field(default_factory=PendingFiltersRequest)
    limit: int = Field(default=100, ge=1, le=MAX_PENDING_RUN_LIMIT)
    all_pending_acknowledged: bool = False

    @model_validator(mode="after")
    def validate_scope(self):
        service_filters = self.filters.to_service_filters()
        if not service_filters.has_constraints and not self.all_pending_acknowledged:
            raise ValueError(
                "Select at least one filter or acknowledge running all pending jobs"
            )
        return self


class QueryRunRequest(BaseModel):
    review_candidate_names: Optional[List[str]] = None
    polluted_skill_names: Optional[List[str]] = None
    source_subclassification_names: Optional[List[str]] = None
    scope: Literal["all", "enriched_only"] = "all"


class CreateRunRequest(BaseModel):
    mode: Literal["pending", "query"] = "pending"
    filters: PendingFiltersRequest = Field(default_factory=PendingFiltersRequest)
    limit: int = Field(default=100, ge=1, le=MAX_PENDING_RUN_LIMIT)
    all_pending_acknowledged: bool = False
    query: Optional[QueryRunRequest] = None

    @model_validator(mode="after")
    def validate_mode_payload(self):
        if self.mode == "pending":
            PendingSelectionRequest(
                filters=self.filters,
                limit=self.limit,
                all_pending_acknowledged=self.all_pending_acknowledged,
            )
        elif self.query is None:
            raise ValueError("query is required for query mode")
        return self


def _derive_last_failed_job_titles(
    db: Session, run_ids: list[str]
) -> dict[str, Optional[str]]:
    if not run_ids:
        return {}

    latest_failed_items = (
        db.query(
            EnrichmentRunItem.run_id.label("run_id"),
            Job.title.label("job_title"),
            func.row_number()
            .over(
                partition_by=EnrichmentRunItem.run_id,
                order_by=(
                    EnrichmentRunItem.completed_at.desc(),
                    EnrichmentRunItem.position.desc(),
                    EnrichmentRunItem.id.desc(),
                ),
            )
            .label("row_number"),
        )
        .join(Job, Job.id == EnrichmentRunItem.job_id)
        .filter(
            EnrichmentRunItem.run_id.in_(run_ids),
            EnrichmentRunItem.status == "failed",
        )
        .subquery()
    )
    rows = (
        db.query(
            latest_failed_items.c.run_id,
            latest_failed_items.c.job_title,
        )
        .filter(latest_failed_items.c.row_number == 1)
        .all()
    )
    return {str(run_id): job_title for run_id, job_title in rows}


def _derive_last_failed_job_title(db: Session, run_id: str) -> Optional[str]:
    return _derive_last_failed_job_titles(db, [run_id]).get(run_id)


def _derive_excluded_details(
    db: Session,
    run_ids: list[str],
) -> dict[str, list[ExcludedDetail]]:
    """Group excluded items by source category and preflight reason."""
    if not run_ids:
        return {}

    grouped: dict[tuple[str, str | None, str | None, str], ExcludedDetail] = {}
    rows = (
        db.query(
            EnrichmentRunItem.run_id,
            EnrichmentRunItem.job_id,
            Job.source_classification_id,
            Job.source_classification_name,
            EnrichmentRunItem.error_message,
        )
        .join(Job, Job.id == EnrichmentRunItem.job_id)
        .filter(
            EnrichmentRunItem.run_id.in_(run_ids),
            EnrichmentRunItem.status == "excluded",
        )
        .order_by(EnrichmentRunItem.run_id.asc(), EnrichmentRunItem.position.asc())
        .all()
    )
    for run_id, job_id, source_id, source_name, error_message in rows:
        normalized_source_id = (
            str(source_id).strip() if source_id is not None else None
        ) or None
        normalized_source_name = (
            str(source_name).strip() if source_name is not None else None
        ) or None
        reason = str(error_message or "canonical_taxonomy_preflight_blocked")
        key = (str(run_id), normalized_source_id, normalized_source_name, reason)
        group = grouped.setdefault(
            key,
            {
                "source_classification_id": normalized_source_id,
                "source_classification_name": normalized_source_name,
                "count": 0,
                "reason": reason,
                "job_ids": [],
            },
        )
        group["count"] = int(group["count"]) + 1
        group["job_ids"].append(str(job_id))

    details: dict[str, list[ExcludedDetail]] = {}
    for (run_id, _source_id, _source_name, _reason), detail in grouped.items():
        details.setdefault(run_id, []).append(detail)
    return details


def _serialize_run(
    run: EnrichmentRun,
    db: Optional[Session] = None,
    *,
    last_failed_job_titles: Optional[dict[str, Optional[str]]] = None,
    pending_gate: Optional[dict[str, object]] = None,
    excluded_details: Optional[list[ExcludedDetail]] = None,
) -> dict:
    in_progress_items = (
        max(
            int(run.total_items or 0)
            - int(run.pending_items or 0)
            - int(run.completed_items or 0)
            - int(run.failed_items or 0)
            - int(getattr(run, "cancelled_items", 0) or 0)
            - int(getattr(run, "excluded_items", 0) or 0),
            0,
        )
        if str(run.status or "").lower() in ACTIVE_AI_RUN_STATUSES
        else 0
    )
    failed_items = int(run.failed_items or 0)
    resolved_failed_title = None
    if failed_items > 0:
        if last_failed_job_titles is not None:
            resolved_failed_title = last_failed_job_titles.get(run.id)
        elif db is not None:
            resolved_failed_title = _derive_last_failed_job_title(db, run.id)
    return {
        "id": run.id,
        "source_type": run.source_type,
        "trigger_crawl_job_id": str(run.trigger_crawl_job_id)
        if getattr(run, "trigger_crawl_job_id", None)
        else None,
        "status": run.status,
        "job_ids": list(run.job_ids or []),
        "total_items": run.total_items,
        "pending_items": run.pending_items,
        "completed_items": run.completed_items,
        "failed_items": run.failed_items,
        "cancelled_items": int(getattr(run, "cancelled_items", 0) or 0),
        "excluded_items": int(getattr(run, "excluded_items", 0) or 0),
        "excluded_details": excluded_details or [],
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "stop_requested_at": (
            run.stop_requested_at.isoformat()
            if getattr(run, "stop_requested_at", None)
            else None
        ),
        "current_job_title": getattr(run, "current_job_title", None),
        "latest_started_job_title": getattr(run, "current_job_title", None),
        "in_progress_items": in_progress_items,
        "last_failed_job_title": resolved_failed_title,
        "pending_gate_reason": (pending_gate or {}).get("reason"),
        "pending_gate_progress": (
            {
                "emitted_items": pending_gate["emitted_items"],
                "settled_items": pending_gate["settled_items"],
            }
            if pending_gate
            and "emitted_items" in pending_gate
            and "settled_items" in pending_gate
            else None
        ),
        "pending_gate_crawl_job_status": (pending_gate or {}).get("crawl_job_status"),
        "error_message": run.error_message,
    }


def _serialize_runs(
    runs: list[EnrichmentRun], db: Optional[Session] = None
) -> list[dict]:
    failed_title_map: Optional[dict[str, Optional[str]]] = None
    excluded_details_map: dict[str, list[ExcludedDetail]] = {}
    pending_gate_map: dict[str, dict[str, object] | None] = {}
    if db is not None:
        failed_run_ids = [
            run.id for run in runs if int(getattr(run, "failed_items", 0) or 0) > 0
        ]
        failed_title_map = _derive_last_failed_job_titles(db, failed_run_ids)
        excluded_details_map = _derive_excluded_details(db, [run.id for run in runs])
        service = EnrichmentRunService(db)
        pending_gate_map = {
            run.id: service.describe_pending_gate(run)
            for run in runs
            if str(getattr(run, "status", "") or "").lower() in {"waiting", "pending"}
        }
    return [
        _serialize_run(
            run,
            db,
            last_failed_job_titles=failed_title_map,
            pending_gate=pending_gate_map.get(run.id),
            excluded_details=excluded_details_map.get(run.id),
        )
        for run in runs
    ]


def _serialize_single_run(run: EnrichmentRun, db: Optional[Session] = None) -> dict:
    return _serialize_runs([run], db)[0]


def _serialize_item(item: EnrichmentRunItem) -> dict:
    return {
        "id": item.id,
        "run_id": item.run_id,
        "job_id": str(item.job_id),
        "position": item.position,
        "status": item.status,
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "error_message": item.error_message,
    }


def _publish_run_request(
    db: Session,
    *,
    service: EnrichmentRunService,
    run_id: str,
    source_service: str = "ai-api",
) -> bool:
    requested = service.request_run_execution(run_id, source_service=source_service)
    db.commit()
    if requested:
        OutboxPublisher().publish_pending_batch(db, limit=100)
    return requested


def _run_execution_result(run: EnrichmentRun, requested: bool) -> str:
    if requested:
        return "queued"
    if int(run.total_items or 0) > 0 and int(
        getattr(run, "excluded_items", 0) or 0
    ) == int(run.total_items or 0):
        return "no_supported_items"
    return "not_dispatched"


async def _wait_for_terminal_run(run_id: str) -> EnrichmentRun:
    """Wait for internal synchronous workflows such as manual job creation."""
    while True:
        wait_db = SessionLocal()
        try:
            run = EnrichmentRunService(wait_db).get_run(run_id)
            if run is None:
                raise HTTPException(status_code=404, detail="Run not found")
            if str(run.status or "").lower() not in ACTIVE_AI_RUN_STATUSES:
                return run
        finally:
            wait_db.close()
        await asyncio.sleep(0.1)


def _load_job_snapshot(job_id: UUID) -> dict:
    """Load the enriched job projection for the internal manual-job workflow."""
    snapshot_db = SessionLocal()
    try:
        job = (
            snapshot_db.query(Job)
            .options(
                joinedload(Job.company),
                joinedload(Job.job_skill_mentions)
                .joinedload(JobSkillMention.skill)
                .joinedload(Skill.technology)
                .joinedload(SkillTechnology.category),
                joinedload(Job.subcategory)
                .joinedload(JobSubcategory.category)
                .joinedload(JobCategory.domain),
            )
            .filter(Job.id == job_id, Job.is_deleted.is_(False))
            .first()
        )
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return JobDetailSchema.model_validate(job).model_dump(mode="json")
    finally:
        snapshot_db.close()


def _active_run_conflict(exc: ActiveEnrichmentRunError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": "active_run_exists", "run_id": exc.run_id},
    )


def _normalized_pending_payload(request: PendingSelectionRequest) -> dict:
    return request.filters.model_dump(mode="json")


@router.post("/enrich")
async def start_enrichment(
    request: EnrichRequest,
    db: Session = Depends(get_db),
):
    """Start batch AI enrichment for unenriched jobs."""
    try:
        ensure_profile_runtime_ready("jobs")
    except ProfileRuntimeNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    service = EnrichmentRunService(db)
    try:
        run = service.create_manual_pending_run(
            limit=request.limit,
            filters=PendingJobFilters(),
        )
    except ActiveEnrichmentRunError as exc:
        raise _active_run_conflict(exc) from exc
    if run is None:
        return {"task_id": None, "run_id": None, "status": "no_jobs"}

    requested = _publish_run_request(db, service=service, run_id=run.id)
    db.refresh(run)
    return {
        "task_id": run.id,
        "run_id": run.id,
        "status": _run_execution_result(run, requested),
        "run_status": run.status,
        "total_items": int(run.total_items or 0),
        "excluded_items": int(getattr(run, "excluded_items", 0) or 0),
    }


@router.get("/status/{task_id}")
async def get_enrichment_status(task_id: str, db: Session = Depends(get_db)):
    """Get status of an enrichment task."""
    run = EnrichmentRunService(db).get_run(task_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Task not found")
    payload = _serialize_single_run(run, db)
    payload["progress"] = (
        int(run.completed_items or 0)
        + int(run.failed_items or 0)
        + int(getattr(run, "cancelled_items", 0) or 0)
        + int(getattr(run, "excluded_items", 0) or 0)
    )
    payload["total"] = run.total_items
    return payload


@router.get("/overview")
async def get_ai_overview(db: Session = Depends(get_db)):
    """Get AI enrichment overview and run summary."""
    overview = EnrichmentRunService(db).get_overview()
    return {
        "total_jobs": overview["total_jobs"],
        "enriched_jobs": overview["enriched_jobs"],
        "eligible_enriched_jobs": overview["eligible_enriched_jobs"],
        "ai_eligible_jobs": overview["ai_eligible_jobs"],
        "ineligible_jobs": overview["ineligible_jobs"],
        "pending_jobs": overview["pending_jobs"],
        "running_runs": overview["running_runs"],
        "active_runs": overview["active_runs"],
        "failed_jobs": overview["failed_jobs"],
        "failed_items": overview["failed_items"],
        "last_completed_run": (
            _serialize_single_run(overview["last_completed_run"], db)
            if overview["last_completed_run"] is not None
            else None
        ),
    }


@router.get("/pending/filter-options")
async def get_pending_filter_options(db: Session = Depends(get_db)):
    """Return the current pending candidate hierarchy for local cascading filters."""
    rows = EnrichmentRunService(db).get_pending_filter_options()
    hierarchy: dict[str, dict[str, set[str]]] = {}
    for row in rows:
        source = str(row.get("source_site") or "").strip().lower()
        classification = str(row.get("source_classification_name") or "").strip()
        subclassification = str(row.get("source_subclassification_name") or "").strip()
        if not source:
            continue
        classifications = hierarchy.setdefault(source, {})
        subclassifications = classifications.setdefault(classification, set())
        if subclassification:
            subclassifications.add(subclassification)

    return {
        "sources": [
            {
                "source_site": source,
                "classifications": [
                    {
                        "name": classification,
                        "subclassifications": sorted(subclassifications),
                    }
                    for classification, subclassifications in classifications.items()
                    if classification
                ],
            }
            for source, classifications in hierarchy.items()
        ]
    }


@router.post("/pending/preview")
async def preview_pending_enrichment(
    request: PendingSelectionRequest,
    db: Session = Depends(get_db),
):
    """Preview the current filtered pending selection without reserving jobs."""
    filters = request.filters.to_service_filters()
    preview = EnrichmentRunService(db).preview_pending_jobs(
        filters=filters,
        limit=request.limit,
    )
    return {
        **preview,
        "filters": _normalized_pending_payload(request),
        "all_pending_acknowledgement_required": not filters.has_constraints,
    }


@router.post("/runs")
async def create_enrichment_run(
    request: CreateRunRequest,
    db: Session = Depends(get_db),
):
    """Create a persisted enrichment run."""
    try:
        ensure_profile_runtime_ready("jobs")
    except ProfileRuntimeNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    service = EnrichmentRunService(db)

    try:
        if request.mode == "pending":
            run = service.create_manual_pending_run(
                limit=request.limit,
                filters=request.filters.to_service_filters(),
            )
        else:
            query = request.query
            if query is None:
                raise HTTPException(status_code=422, detail="query is required")
            run = service.create_manual_query_run(
                review_candidate_names=query.review_candidate_names,
                polluted_skill_names=query.polluted_skill_names,
                source_subclassification_names=query.source_subclassification_names,
                scope=query.scope,
            )
    except ActiveEnrichmentRunError as exc:
        raise _active_run_conflict(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if run is None:
        return {"status": "empty", "run": None}

    requested = _publish_run_request(db, service=service, run_id=run.id)
    db.refresh(run)
    payload = _serialize_single_run(run, db)
    payload["execution_dispatched"] = requested
    payload["execution_result"] = _run_execution_result(run, requested)
    return payload


@router.get("/runs")
async def list_enrichment_runs(
    status: Optional[str] = None,
    source_type: Optional[str] = None,
    limit: Optional[int] = None,
    monitor: bool = False,
    db: Session = Depends(get_db),
):
    """List persisted enrichment runs."""
    service = EnrichmentRunService(db)
    if monitor:
        runs = service.list_runs_for_monitor()
    else:
        runs = service.list_runs(
            status=status,
            source_type=source_type,
            limit=limit,
        )
    return {"runs": _serialize_runs(runs, db)}


@router.get("/runs/{run_id}")
async def get_enrichment_run(run_id: str, db: Session = Depends(get_db)):
    """Get a persisted enrichment run by ID."""
    run = EnrichmentRunService(db).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _serialize_single_run(run, db)


@router.get("/runs/{run_id}/items")
async def get_enrichment_run_items(
    run_id: str,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get items for a persisted enrichment run."""
    service = EnrichmentRunService(db)
    items = service.list_run_items_or_none(run_id, status=status)
    if items is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"items": [_serialize_item(item) for item in items]}


@router.post("/runs/{run_id}/retry-failed")
async def retry_failed_enrichment_run(
    run_id: str,
    db: Session = Depends(get_db),
):
    """Create a retry run from the failed items of a previous run."""
    service = EnrichmentRunService(db)
    try:
        run = service.create_retry_run_from_failed_items(run_id)
    except ActiveEnrichmentRunError as exc:
        raise _active_run_conflict(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    _publish_run_request(db, service=service, run_id=run.id)
    db.refresh(run)
    return _serialize_single_run(run, db)


@router.post("/runs/{run_id}/stop")
async def stop_enrichment_run(run_id: str, db: Session = Depends(get_db)):
    """Request cooperative stop and return the updated run projection."""
    service = EnrichmentRunService(db)
    run = service.request_stop(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    db.commit()
    OutboxPublisher().publish_pending_batch(db, limit=100)
    db.refresh(run)
    return _serialize_single_run(run, db)


@router.get("/stats")
async def get_ai_stats(db: Session = Depends(get_db)):
    """Get AI enrichment statistics in the legacy shape."""
    queue_counts = EnrichmentRunService(db).get_job_queue_counts()
    total = queue_counts["total_jobs"]
    enriched = queue_counts["enriched_jobs"]
    ai_eligible_jobs = queue_counts["ai_eligible_jobs"]
    return {
        "total_jobs": total,
        "enriched_jobs": enriched,
        "eligible_enriched_jobs": queue_counts["eligible_enriched_jobs"],
        "ai_eligible_jobs": ai_eligible_jobs,
        "ineligible_jobs": queue_counts["ineligible_jobs"],
        "pending_jobs": queue_counts["pending_jobs"],
        "enrichment_rate": round(
            queue_counts["eligible_enriched_jobs"] / ai_eligible_jobs * 100, 1
        )
        if ai_eligible_jobs > 0
        else 0,
    }
