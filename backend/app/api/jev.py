from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.jev import JevRun, JevRunItem
from app.services.jev_evaluator_factory import build_jev_evaluator
from app.services.jev_run_service import (
    JevRunConfigurationError,
    JevRunService,
)


router = APIRouter(prefix="/jev", tags=["jev"])


class JevRunItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str = Field(min_length=1, max_length=255)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    payload: dict[str, Any]


class JevRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: str = Field(min_length=1, max_length=64)
    rubric_version: str = Field(min_length=1, max_length=128)
    items: list[JevRunItemRequest] = Field(min_length=1, max_length=10_000)


def _serialize_item(item: JevRunItem) -> dict[str, object]:
    return {
        "id": item.id,
        "subject_id": item.subject_id,
        "position": item.position,
        "evidence_refs": item.evidence_refs,
        "payload": item.payload,
        "status": item.status,
        "attempt_count": item.attempt_count,
        "error_code": item.error_code,
        "error_message": item.error_message,
        "result": item.result,
    }


def _serialize_run(run: JevRun) -> dict[str, object]:
    return {
        "id": run.id,
        "purpose": run.purpose,
        "rubric_version": run.rubric_version,
        "status": run.status,
        "settings_snapshot": run.settings_snapshot,
        "total_items": run.total_items,
        "pending_items": run.pending_items,
        "running_items": run.running_items,
        "completed_items": run.completed_items,
        "failed_items": run.failed_items,
        "cancelled_items": run.cancelled_items,
        "items": [_serialize_item(item) for item in run.items],
    }


@router.post("/runs", status_code=201)
def create_jev_run(
    request: JevRunCreateRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = JevRunService(db)
    try:
        run = service.start(
            purpose=request.purpose,
            rubric_version=request.rubric_version,
            items=[item.model_dump() for item in request.items],
        )
        db.commit()
        db.refresh(run)
        return _serialize_run(run)
    except JevRunConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs")
def list_jev_runs(
    limit: int = 20,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    bounded_limit = max(1, min(limit, 100))
    runs = list(
        db.scalars(
            select(JevRun)
            .order_by(JevRun.created_at.desc(), JevRun.id.desc())
            .limit(bounded_limit)
        )
    )
    return {"runs": [_serialize_run(run) for run in runs]}


@router.get("/runs/{run_id}")
def get_jev_run(
    run_id: str,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        return _serialize_run(JevRunService(db).get(run_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Jev run not found") from exc


@router.post("/runs/{run_id}/stop")
def stop_jev_run(
    run_id: str,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        run = JevRunService(db).request_stop(run_id)
        db.commit()
        db.refresh(run)
        return _serialize_run(run)
    except KeyError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Jev run not found") from exc


@router.post("/runs/{run_id}/resume")
def resume_jev_run(
    run_id: str,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        run = JevRunService(db).resume(run_id)
        db.commit()
        db.refresh(run)
        return _serialize_run(run)
    except KeyError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Jev run not found") from exc
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/runs/{run_id}/retry-failed")
def retry_failed_jev_run(
    run_id: str,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        run = JevRunService(db).retry_failed(run_id)
        db.commit()
        db.refresh(run)
        return _serialize_run(run)
    except KeyError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Jev run not found") from exc
    except (ValueError, JevRunConfigurationError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/runs/{run_id}/execute-next")
async def execute_next_jev_run_item(
    run_id: str,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = JevRunService(db)
    evaluator = None
    try:
        run = service.get(run_id)
        evaluator = build_jev_evaluator(db, run)
        await service.execute_next(run.id, evaluator=evaluator)
        db.commit()
        run = service.get(run.id)
        return _serialize_run(run)
    except KeyError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Jev run not found") from exc
    except JevRunConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        close = getattr(evaluator, "aclose", None)
        if close is not None:
            await close()


__all__ = ["router"]
