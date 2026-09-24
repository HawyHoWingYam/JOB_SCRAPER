from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.jev import JevOperationBatch, JevOperationBatchItem
from app.services.jev_operation_batch import (
    JevOperationBatchService,
    execute_jev_operation_batch,
)


router = APIRouter(prefix="/jev/operations", tags=["jev-operations"])


class JevOperationSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_sites: list[str] = Field(default_factory=list, max_length=10)
    keyword: str | None = Field(default=None, max_length=500)
    job_ids: list[UUID] = Field(default_factory=list)
    posted_date_from: date | None = None
    posted_date_to: date | None = None
    processing_status: Literal["all", "eligible", "successful", "failed"] = "all"
    job_offset: int = Field(default=0, ge=0)
    max_jobs: int | None = Field(default=100, ge=1)
    execution_batch_size: int = Field(default=500, ge=1)
    start_execution_batch: int = Field(default=1, ge=1)
    operations: list[Literal["skills", "duplicate", "related_jobs"]] = Field(
        min_length=1,
        max_length=3,
    )
    force_reevaluation: bool = False

    @model_validator(mode="after")
    def validate_scope(self):
        if (
            self.posted_date_from is not None
            and self.posted_date_to is not None
            and self.posted_date_from > self.posted_date_to
        ):
            raise ValueError("posted_date_from must be on or before posted_date_to")
        if (
            self.max_jobs is not None
            and (self.start_execution_batch - 1) * self.execution_batch_size
            >= self.max_jobs
        ):
            raise ValueError(
                "start_execution_batch must fall within the maximum matching Jobs"
            )
        return self


class JevOperationStartRequest(JevOperationSelectionRequest):
    preview_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)


def _serialize_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"items", "selected_job_ids"}
    }


def _serialize_batch(
    batch: JevOperationBatch,
    *,
    include_items: bool = False,
    db: Session | None = None,
) -> dict[str, object]:
    selection = batch.selection_snapshot or {}
    execution_batch_size = max(
        int(selection.get("execution_batch_size") or len(batch.selected_job_ids or []) or 1),
        1,
    )
    start_execution_batch = max(int(selection.get("start_execution_batch") or 1), 1)
    selected_job_count = len(batch.selected_job_ids or [])
    selected_execution_batches = (
        (selected_job_count + execution_batch_size - 1) // execution_batch_size
        if selected_job_count
        else 0
    )
    final_execution_batch = (
        start_execution_batch + selected_execution_batches - 1
        if selected_execution_batches
        else start_execution_batch - 1
    )
    if include_items or db is None:
        unfinished_position = min(
            (
                item.position
                for item in batch.items
                if item.status in {"pending", "running", "stopped"}
            ),
            default=None,
        )
    else:
        unfinished_position = db.scalar(
            select(func.min(JevOperationBatchItem.position)).where(
                JevOperationBatchItem.batch_id == batch.id,
                JevOperationBatchItem.status.in_(("pending", "running", "stopped")),
            )
        )
    operations_per_job = max(len(batch.operations or []), 1)
    if unfinished_position is None:
        completed_execution_batches = final_execution_batch
        current_execution_batch = final_execution_batch
    else:
        current_job_index = unfinished_position // operations_per_job
        completed_execution_batches = (
            start_execution_batch - 1 + current_job_index // execution_batch_size
        )
        current_execution_batch = min(
            completed_execution_batches + 1, final_execution_batch
        )
    payload = {
        "id": batch.id,
        "status": batch.status,
        "preview_fingerprint": batch.preview_fingerprint,
        "selection": batch.selection_snapshot,
        "selected_job_count": selected_job_count,
        "operations": batch.operations,
        "force_reevaluation": bool(batch.force_reevaluation),
        "execution_batch_size": execution_batch_size,
        "start_execution_batch": start_execution_batch,
        "total_execution_batches": final_execution_batch,
        "current_execution_batch": current_execution_batch,
        "completed_execution_batches": completed_execution_batches,
        "total_items": batch.total_items,
        "pending_items": batch.pending_items,
        "running_items": batch.running_items,
        "completed_items": batch.completed_items,
        "failed_items": batch.failed_items,
        "skipped_items": batch.skipped_items,
        "stop_requested_at": batch.stop_requested_at,
        "started_at": batch.started_at,
        "completed_at": batch.completed_at,
        "created_at": batch.created_at,
        "item_details_included": include_items,
    }
    if include_items:
        payload["selected_job_ids"] = batch.selected_job_ids
        payload["items"] = [
            {
                "id": item.id,
                "job_id": str(item.job_id),
                "operation": item.operation,
                "position": item.position,
                "status": item.status,
                "eligibility_reason": item.eligibility_reason,
                "input_fingerprint": item.input_fingerprint,
                "attempt_count": item.attempt_count,
                "result": item.result,
                "error_code": item.error_code,
                "error_message": item.error_message,
            }
            for item in batch.items
        ]
    return payload


@router.post("/preview")
def preview_jev_operations(
    request: JevOperationSelectionRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        return _serialize_preview(JevOperationBatchService(db).preview(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/batches", status_code=201)
def start_jev_operation_batch(
    request: JevOperationStartRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = JevOperationBatchService(db)
    try:
        batch = service.start(
            request,
            preview_fingerprint=request.preview_fingerprint,
            idempotency_key=idempotency_key,
        )
        db.commit()
        db.refresh(batch)
        if batch.status == "pending":
            background_tasks.add_task(execute_jev_operation_batch, batch.id)
        return _serialize_batch(batch, db=db)
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/batches")
def list_jev_operation_batches(
    limit: int = 20,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return {
        "batches": [
            _serialize_batch(batch, db=db)
            for batch in JevOperationBatchService(db).list(limit=limit)
        ]
    }


@router.get("/batches/{batch_id}")
def get_jev_operation_batch(
    batch_id: str,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        return _serialize_batch(
            JevOperationBatchService(db).get(batch_id), include_items=True, db=db
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Jev operation batch not found") from exc


def _manual_dispatch(
    batch_id: str,
    *,
    action: Literal["resume", "retry"],
    background_tasks: BackgroundTasks,
    db: Session,
) -> dict[str, object]:
    service = JevOperationBatchService(db)
    try:
        batch = service.resume(batch_id) if action == "resume" else service.retry_failed(batch_id)
        db.commit()
        db.refresh(batch)
        background_tasks.add_task(execute_jev_operation_batch, batch.id)
        return _serialize_batch(batch, db=db)
    except KeyError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Jev operation batch not found") from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/batches/{batch_id}/stop")
def stop_jev_operation_batch(
    batch_id: str,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        batch = JevOperationBatchService(db).request_stop(batch_id)
        db.commit()
        db.refresh(batch)
        return _serialize_batch(batch, db=db)
    except KeyError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Jev operation batch not found") from exc


@router.post("/batches/{batch_id}/resume")
def resume_jev_operation_batch(
    batch_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return _manual_dispatch(
        batch_id,
        action="resume",
        background_tasks=background_tasks,
        db=db,
    )


@router.post("/batches/{batch_id}/retry-failed")
def retry_failed_jev_operation_batch(
    batch_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return _manual_dispatch(
        batch_id,
        action="retry",
        background_tasks=background_tasks,
        db=db,
    )


__all__ = ["router"]
