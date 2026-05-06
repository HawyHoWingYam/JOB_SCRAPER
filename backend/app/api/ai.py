"""
AI Enrichment API Endpoints
"""

import asyncio
import logging
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel

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
from app.services.enrichment_run_service import EnrichmentRunService
from app.services.ai_runtime_settings_service import ensure_profile_runtime_ready, ProfileRuntimeNotReadyError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ai", tags=["ai"])
ACTIVE_AI_RUN_STATUSES = {"pending", "running"}


class EnrichRequest(BaseModel):
    limit: int = 100


class QueryRunRequest(BaseModel):
    review_candidate_names: Optional[List[str]] = None
    polluted_skill_names: Optional[List[str]] = None
    source_subclassification_names: Optional[List[str]] = None
    scope: Literal["all", "enriched_only"] = "all"


class CreateRunRequest(BaseModel):
    mode: Literal["pending", "batch", "query"] = "pending"
    limit: Optional[int] = None
    job_ids: Optional[List[UUID]] = None
    query: Optional[QueryRunRequest] = None


def _job_id_param(db: Session, job_id: UUID):
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        return job_id.hex
    return job_id


def _fetch_job_title(db: Session, job_id: UUID) -> Optional[str]:
    row = db.execute(
        text("SELECT title FROM jobs WHERE id = :job_id"),
        {"job_id": _job_id_param(db, job_id)},
    ).first()
    return row[0] if row else None


def _derive_last_failed_job_title(db: Session, run_id: str) -> Optional[str]:
    failed_item = (
        db.query(EnrichmentRunItem)
        .filter(
            EnrichmentRunItem.run_id == run_id,
            EnrichmentRunItem.status == "failed",
        )
        .order_by(
            EnrichmentRunItem.completed_at.desc(),
            EnrichmentRunItem.position.desc(),
            EnrichmentRunItem.id.desc(),
        )
        .first()
    )
    if failed_item is None:
        return None
    return _fetch_job_title(db, failed_item.job_id)


def _serialize_run(run: EnrichmentRun, db: Optional[Session] = None) -> dict:
    in_progress_items = max(
        int(run.total_items or 0)
        - int(run.pending_items or 0)
        - int(run.completed_items or 0)
        - int(run.failed_items or 0),
        0,
    ) if str(run.status or "").lower() in {"pending", "running"} else 0
    return {
        "id": run.id,
        "source_type": run.source_type,
        "trigger_crawl_job_id": str(run.trigger_crawl_job_id) if getattr(run, "trigger_crawl_job_id", None) else None,
        "status": run.status,
        "job_ids": list(run.job_ids or []),
        "total_items": run.total_items,
        "pending_items": run.pending_items,
        "completed_items": run.completed_items,
        "failed_items": run.failed_items,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "current_job_title": getattr(run, "current_job_title", None),
        "latest_started_job_title": getattr(run, "current_job_title", None),
        "in_progress_items": in_progress_items,
        "last_failed_job_title": _derive_last_failed_job_title(db, run.id) if db is not None else None,
        "error_message": run.error_message,
    }


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
) -> None:
    service.request_run_execution(run_id, source_service=source_service)
    db.commit()
    OutboxPublisher().publish_pending_batch(db, limit=100)


async def _wait_for_terminal_run(run_id: str) -> EnrichmentRun:
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

    run = EnrichmentRunService(db).create_manual_pending_run(limit=request.limit)
    if run is None:
        return {"task_id": None, "run_id": None, "status": "no_jobs"}

    _publish_run_request(db, service=EnrichmentRunService(db), run_id=run.id)
    return {"task_id": run.id, "run_id": run.id, "status": "queued"}


@router.get("/status/{task_id}")
async def get_enrichment_status(task_id: str, db: Session = Depends(get_db)):
    """Get status of an enrichment task."""
    run = EnrichmentRunService(db).get_run(task_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Task not found")
    payload = _serialize_run(run, db)
    payload["progress"] = run.completed_items + run.failed_items
    payload["total"] = run.total_items
    return payload


@router.get("/overview")
async def get_ai_overview(db: Session = Depends(get_db)):
    """Get AI enrichment overview and run summary."""
    overview = EnrichmentRunService(db).get_overview()
    return {
        "total_jobs": overview["total_jobs"],
        "enriched_jobs": overview["enriched_jobs"],
        "pending_jobs": overview["pending_jobs"],
        "running_runs": overview["running_runs"],
        "active_runs": overview["active_runs"],
        "failed_jobs": overview["failed_jobs"],
        "failed_items": overview["failed_items"],
        "last_completed_run": (
            _serialize_run(overview["last_completed_run"], db)
            if overview["last_completed_run"] is not None
            else None
        ),
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

    if request.mode == "pending":
        run = service.create_manual_pending_run(limit=request.limit)
    elif request.mode == "batch":
        if not request.job_ids:
            raise HTTPException(status_code=400, detail="job_ids are required for batch mode")
        run = service.create_manual_batch_run([str(job_id) for job_id in request.job_ids])
    elif request.mode == "query":
        if request.query is None:
            raise HTTPException(status_code=400, detail="query is required for query mode")
        try:
            run = service.create_manual_query_run(
                review_candidate_names=request.query.review_candidate_names,
                polluted_skill_names=request.query.polluted_skill_names,
                source_subclassification_names=request.query.source_subclassification_names,
                scope=request.query.scope,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        raise HTTPException(status_code=400, detail="Unsupported run mode")

    if run is None:
        return {"status": "empty", "run": None}

    _publish_run_request(db, service=service, run_id=run.id)
    db.refresh(run)
    return _serialize_run(run, db)


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
    return {"runs": [_serialize_run(run, db) for run in runs]}


@router.get("/runs/{run_id}")
async def get_enrichment_run(run_id: str, db: Session = Depends(get_db)):
    """Get a persisted enrichment run by ID."""
    run = EnrichmentRunService(db).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _serialize_run(run, db)


@router.get("/runs/{run_id}/items")
async def get_enrichment_run_items(
    run_id: str,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get items for a persisted enrichment run."""
    service = EnrichmentRunService(db)
    if service.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    items = service.list_run_items(run_id, status=status)
    return {"items": [_serialize_item(item) for item in items]}


@router.post("/runs/{run_id}/retry-failed")
async def retry_failed_enrichment_run(
    run_id: str,
    db: Session = Depends(get_db),
):
    """Create a retry run from the failed items of a previous run."""
    service = EnrichmentRunService(db)
    if service.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        run = service.create_retry_run_from_failed_items(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _publish_run_request(db, service=service, run_id=run.id)
    db.refresh(run)
    return _serialize_run(run, db)


@router.post("/enrich-job/{job_id}")
async def enrich_single_job(job_id: UUID, db: Session = Depends(get_db)):
    """Enrich a single job through the worker-owned run pipeline."""
    try:
        ensure_profile_runtime_ready("jobs")
    except ProfileRuntimeNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    service = EnrichmentRunService(db)
    run = service.create_manual_single_job_run(str(job_id))
    _publish_run_request(db, service=service, run_id=run.id)
    terminal_run = await _wait_for_terminal_run(run.id)
    return {
        "run": _serialize_run(terminal_run),
        "job": _load_job_snapshot(job_id),
    }


@router.get("/stats")
async def get_ai_stats(db: Session = Depends(get_db)):
    """Get AI enrichment statistics in the legacy shape."""
    overview = EnrichmentRunService(db).get_overview()
    total = overview["total_jobs"]
    enriched = overview["enriched_jobs"]
    return {
        "total_jobs": total,
        "enriched_jobs": enriched,
        "pending_jobs": total - enriched,
        "enrichment_rate": round(enriched / total * 100, 1) if total > 0 else 0
    }
