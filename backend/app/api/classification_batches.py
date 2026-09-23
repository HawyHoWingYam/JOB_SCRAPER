from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.services.classification_batch_runtime import (
    ActiveClassificationBatchError,
    ClassificationBatchError,
    ClassificationBatchRuntime,
    ClassificationDomainAdapter,
)
from app.services.classification_domain_adapters import (
    SkillClassificationAdapter,
)


router = APIRouter(
    prefix="/job-intelligence/classification-batches",
    tags=["classification-batches"],
)


class ClassificationBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filters: dict[str, object] = Field(default_factory=dict)
    limit: int = Field(default=100, ge=1, le=5000)


def _runtime(db: Session) -> ClassificationBatchRuntime:
    adapters: tuple[ClassificationDomainAdapter, ...] = (SkillClassificationAdapter(),)
    return ClassificationBatchRuntime(
        db,
        {adapter.domain: adapter for adapter in adapters},
    )


def _serialize_candidate(candidate) -> dict[str, object]:
    return {
        "subject_id": candidate.subject_id,
        "subject_label": candidate.subject_label,
        "payload": dict(candidate.payload or {}),
    }


def _serialize_run(run) -> dict[str, object]:
    return {
        "id": run.id,
        "domain": run.domain,
        "status": run.status,
        "filters": dict(run.filters or {}),
        "requested_limit": run.requested_limit,
        "total_items": run.total_items,
        "pending_items": run.pending_items,
        "completed_items": run.completed_items,
        "failed_items": run.failed_items,
        "cancelled_items": run.cancelled_items,
        "retry_of_run_id": run.retry_of_run_id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "stop_requested_at": (
            run.stop_requested_at.isoformat() if run.stop_requested_at else None
        ),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "items": [
            {
                "id": item.id,
                "subject_id": item.subject_id,
                "subject_label": item.subject_label,
                "position": item.position,
                "status": item.status,
                "attempt_count": item.attempt_count,
                "error_code": item.error_code,
                "error_message": item.error_message,
            }
            for item in run.items
        ],
    }


def _raise_http(exc: ClassificationBatchError) -> None:
    if isinstance(exc, ActiveClassificationBatchError):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "active_classification_batch_exists",
                "domain": exc.domain,
                "run_id": exc.run_id,
            },
        ) from exc
    status_code = 404 if "not found" in str(exc).casefold() else 400
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


async def _execute_run(run_id: str) -> None:
    db = SessionLocal()
    try:
        await _runtime(db).execute(run_id)
    finally:
        db.close()


@router.post("/{domain}/preview")
def preview_classification_batch(
    domain: str,
    request: ClassificationBatchRequest,
    db: Session = Depends(get_db),
):
    try:
        preview = _runtime(db).preview(
            domain,
            filters=request.filters,
            limit=request.limit,
        )
    except ClassificationBatchError as exc:
        _raise_http(exc)
    payload = {
        "domain": preview.domain,
        "selected_item_count": preview.selected_item_count,
        "items": [_serialize_candidate(item) for item in preview.items],
    }
    if preview.mapped_item_count is not None:
        payload.update(
            {
                "mapped_item_count": preview.mapped_item_count,
                "unmapped_item_count": preview.unmapped_item_count,
                "excluded_item_count": preview.excluded_item_count,
            }
        )
    return payload


@router.post("/{domain}/runs")
def start_classification_batch(
    domain: str,
    request: ClassificationBatchRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        run = _runtime(db).start(
            domain,
            filters=request.filters,
            limit=request.limit,
        )
    except ClassificationBatchError as exc:
        _raise_http(exc)
    if run.status == "pending":
        background_tasks.add_task(_execute_run, run.id)
    return _serialize_run(run)


@router.get("/runs")
def list_classification_batches(
    domain: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        runs = _runtime(db).list_runs(domain=domain, limit=limit)
    except ClassificationBatchError as exc:
        _raise_http(exc)
    return {"items": [_serialize_run(run) for run in runs]}


@router.get("/runs/{run_id}")
def get_classification_batch(
    run_id: str,
    db: Session = Depends(get_db),
):
    run = _runtime(db).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Classification batch was not found")
    return _serialize_run(run)


@router.post("/runs/{run_id}/stop")
def stop_classification_batch(
    run_id: str,
    db: Session = Depends(get_db),
):
    try:
        run = _runtime(db).request_stop(run_id)
    except ClassificationBatchError as exc:
        _raise_http(exc)
    return _serialize_run(run)


@router.post("/runs/{run_id}/retry-failed")
def retry_failed_classification_items(
    run_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        run = _runtime(db).retry_failed(run_id)
    except ClassificationBatchError as exc:
        _raise_http(exc)
    background_tasks.add_task(_execute_run, run.id)
    return _serialize_run(run)


__all__ = ["router"]
