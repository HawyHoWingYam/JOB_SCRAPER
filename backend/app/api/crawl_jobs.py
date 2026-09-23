from __future__ import annotations

import logging
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.crawl_control.task_control_board_contracts import (
    CrawlTaskDetailProjectionV1,
    DismissFailedAttentionRequestV1,
    DismissFailedAttentionResponseV1,
)
from app.crawl_control.errors import CrawlControlError
from app.crawl_control.failed_run_attention import FailedRunAttentionService
from app.crawl_control.task_control_board_service import (
    build_crawl_task_detail_projection,
)
from app.database import get_db
from app.models.jev import JevIncidentTriageEvaluation
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.repositories.crawl_job_listing_repository import CrawlJobListingRepository
from app.scraper.manual_action import ResumeStrategy, normalize_manual_action_payload
from app.scraper.browser_profile_recovery import (
    PROFILE_SCOPE_FIXED,
    PROFILE_SCOPE_FRESH,
    fresh_profile_path,
    is_task_owned_profile,
    reset_profile,
)
from app.schemas.crawl_job import (
    CrawlJobEventsResponse,
    CrawlJobSchema,
    CrawlTaskListResponse,
)
from app.services.crawl_request_validation import normalize_source_site
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService
from app.services.crawl_task_snapshot_service import (
    PROGRESS_CONTEXT_EVENT_TYPES,
    build_crawl_task_snapshot,
)
from app.services.source_sites import is_supported_source_site
from app.services.jev_budget import JevBudgetExhaustedError
from app.services.jev_crawl_quality_product import JevCrawlQualityProductService
from app.services.jev_incident_triage_product import JevIncidentTriageProductService
from app.services.jev_evaluator_factory import build_jev_evaluator
from app.services.jev_run_service import JevRunConfigurationError, JevRunService
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/crawl-jobs", tags=["crawl-jobs"])

crawl_job_repository = CrawlJobRepository()
crawl_job_listing_repository = CrawlJobListingRepository()
dispatch_service = CrawlJobDispatchService()
failed_run_attention_service = FailedRunAttentionService()


class ResumeCrawlJobRequest(BaseModel):
    strategy: ResumeStrategy | None = None


class CrawlQualityLimitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(ge=1, le=100)


class IncidentTriagePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_limit: int = Field(ge=1, le=1_000)


def _resolve_time_range_start(time_range: str):
    normalized = str(time_range or "all").strip().lower()
    now = utc_now()
    if normalized == "all":
        return None
    if normalized == "24h":
        return now - timedelta(hours=24)
    if normalized == "7d":
        return now - timedelta(days=7)
    if normalized == "30d":
        return now - timedelta(days=30)
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Unsupported time_range",
    )


def _raise_action_http_error(exc: Exception) -> None:
    if isinstance(exc, CrawlControlError):
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
                if exc.code == "CRAWL_TASK_NOT_FOUND"
                else status.HTTP_409_CONFLICT
            ),
            detail=exc.to_detail(),
        ) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    raise exc


@router.get("/listing-batches")
async def list_listing_batches(
    source_site: str | None = None,
    category_id: str | None = None,
    detail_status: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    effective_source_site = normalize_source_site(source_site) if source_site else None
    if effective_source_site is not None and not is_supported_source_site(effective_source_site):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported source_site",
        )
    return {
        "batches": crawl_job_listing_repository.list_listing_batches(
            db,
            source_site=effective_source_site,
            category_id=category_id,
            detail_status=detail_status,
            limit=limit,
        )
    }


@router.get("/tasks", response_model=CrawlTaskListResponse)
async def list_crawl_tasks(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    status: str | None = None,
    source_site: str | None = None,
    crawl_mode: str | None = None,
    time_range: str = Query(default="all"),
    db: Session = Depends(get_db),
):
    updated_since = _resolve_time_range_start(time_range)
    normalized_source_site = normalize_source_site(source_site) if source_site else None
    rows, total = crawl_job_repository.list_crawl_task_page(
        db,
        page=page,
        page_size=page_size,
        status=status,
        source_site=normalized_source_site,
        crawl_mode=crawl_mode,
        updated_since=updated_since,
    )
    crawl_job_ids = [row.id for row in rows]
    latest_events_by_job = crawl_job_repository.list_latest_events_for_jobs(
        db,
        crawl_job_ids=crawl_job_ids,
    )
    events_by_job = crawl_job_repository.list_events_by_job_ids(
        db,
        crawl_job_ids=crawl_job_ids,
        event_types=PROGRESS_CONTEXT_EVENT_TYPES,
    )
    now = utc_now()
    category_lookup_cache: dict[str, dict[str, str]] = {}
    items = [
        build_crawl_task_snapshot(
            row,
            latest_event=latest_events_by_job.get(row.id),
            now=now,
            events=events_by_job.get(row.id, []),
            category_lookup_cache=category_lookup_cache,
        )
        for row in rows
    ]
    return CrawlTaskListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        status=status,
        source_site=normalized_source_site,
        crawl_mode=crawl_mode,
        time_range=str(time_range or "all").strip().lower() or "all",
        refreshed_at=now.isoformat(),
    )


@router.get(
    "/tasks/{crawl_job_id}",
    response_model=CrawlTaskDetailProjectionV1,
)
async def get_crawl_task_detail(
    crawl_job_id: UUID,
    db: Session = Depends(get_db),
) -> CrawlTaskDetailProjectionV1:
    crawl_job = crawl_job_repository.get_crawl_job_by_id(db, crawl_job_id)
    if crawl_job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CRAWL_TASK_NOT_FOUND",
                "message": "Crawl task not found",
                "context": {"crawl_job_id": str(crawl_job_id)},
            },
        )
    latest_event = crawl_job_repository.list_latest_events_for_jobs(
        db,
        crawl_job_ids=[crawl_job.id],
    ).get(crawl_job.id)
    events = crawl_job_repository.list_events_by_job_ids(
        db,
        crawl_job_ids=[crawl_job.id],
        event_types=PROGRESS_CONTEXT_EVENT_TYPES,
    ).get(crawl_job.id, [])
    normalized = build_crawl_task_snapshot(
        crawl_job,
        latest_event=latest_event,
        now=utc_now(),
        events=events,
        category_lookup_cache={},
    )
    return build_crawl_task_detail_projection(
        crawl_job,
        normalized=normalized,
    )


@router.get("/tasks/{crawl_job_id}/quality")
def get_crawl_quality(
    crawl_job_id: UUID,
    db: Session = Depends(get_db),
):
    if crawl_job_repository.get_crawl_job_by_id(db, crawl_job_id) is None:
        raise HTTPException(status_code=404, detail="Crawl task not found")
    settings_row = JevRuntimeSettingsService(db).get_or_create()
    return {
        "enabled": bool(settings_row.crawl_quality_enabled),
        "maximum_limit": settings_row.crawl_quality_batch_limit,
        "latest": JevCrawlQualityProductService(db).latest(crawl_job_id),
    }


@router.post("/tasks/{crawl_job_id}/quality/preview")
def preview_crawl_quality(
    crawl_job_id: UUID,
    request: CrawlQualityLimitRequest,
    db: Session = Depends(get_db),
):
    try:
        preview = JevCrawlQualityProductService(db).preview(
            crawl_job_id,
            limit=request.limit,
        )
        return {
            "crawl_job_id": str(preview.crawl_job_id),
            "eligible_count": preview.eligible_count,
            "selected_count": preview.selected_count,
            "deterministic_excluded_count": preview.deterministic_excluded_count,
            "insufficient_excluded_count": preview.insufficient_excluded_count,
            "input_fingerprint": preview.input_fingerprint,
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Crawl task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/tasks/{crawl_job_id}/quality/evaluations")
async def evaluate_crawl_quality(
    crawl_job_id: UUID,
    request: CrawlQualityLimitRequest,
    db: Session = Depends(get_db),
):
    settings_row = JevRuntimeSettingsService(db).get_or_create()
    if not settings_row.crawl_quality_enabled:
        raise HTTPException(status_code=409, detail="Jev crawl quality is disabled")
    if request.limit > settings_row.crawl_quality_batch_limit:
        raise HTTPException(
            status_code=422,
            detail="limit exceeds the saved crawl-quality batch limit",
        )
    service = JevCrawlQualityProductService(db)
    evaluator = None
    try:
        evaluation = service.start(crawl_job_id, limit=request.limit)
        if evaluation.status not in {"completed", "completed_with_failures"}:
            run = JevRunService(db).get(evaluation.jev_run_id)
            evaluator = build_jev_evaluator(db, run)
            await service.execute(evaluation.id, evaluator=evaluator)
        db.commit()
        return service.serialize(evaluation)
    except KeyError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Crawl task not found") from exc
    except JevBudgetExhaustedError as exc:
        db.commit()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "jev_allowance_exhausted",
                "remaining_microdollars": exc.remaining_microdollars,
            },
        ) from exc
    except JevRunConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        close = getattr(evaluator, "aclose", None)
        if close is not None:
            await close()


@router.get("/incident-triage")
def get_incident_triage(db: Session = Depends(get_db)):
    settings_row = JevRuntimeSettingsService(db).get_or_create()
    return {
        "enabled": bool(settings_row.incident_triage_enabled),
        "maximum_event_limit": settings_row.incident_triage_event_limit,
        "latest": JevIncidentTriageProductService(db).latest(),
    }


@router.post("/incident-triage/preview")
def preview_incident_triage(
    request: IncidentTriagePreviewRequest,
    db: Session = Depends(get_db),
):
    settings_row = JevRuntimeSettingsService(db).get_or_create()
    if request.event_limit > settings_row.incident_triage_event_limit:
        raise HTTPException(
            status_code=422,
            detail="event_limit exceeds the saved incident-triage event limit",
        )
    service = JevIncidentTriageProductService(db)
    try:
        evaluation = service.preview(event_limit=request.event_limit)
        db.commit()
        return service.serialize(evaluation)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/incident-triage/evaluations/{evaluation_id}")
async def evaluate_incident_triage(
    evaluation_id: str,
    db: Session = Depends(get_db),
):
    settings_row = JevRuntimeSettingsService(db).get_or_create()
    if not settings_row.incident_triage_enabled:
        raise HTTPException(status_code=409, detail="Jev incident triage is disabled")
    service = JevIncidentTriageProductService(db)
    evaluator = None
    try:
        evaluation = service.start(evaluation_id)
        if evaluation.jev_run_id is not None and evaluation.status not in {
            "completed",
            "completed_with_failures",
        }:
            run = JevRunService(db).get(evaluation.jev_run_id)
            evaluator = build_jev_evaluator(db, run)
            evaluation = await service.execute(evaluation.id, evaluator=evaluator)
        db.commit()
        return service.serialize(evaluation)
    except KeyError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Incident triage preview not found") from exc
    except JevBudgetExhaustedError:
        db.commit()
        evaluation = db.get(JevIncidentTriageEvaluation, evaluation_id)
        return service.serialize(evaluation)
    except JevRunConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        close = getattr(evaluator, "aclose", None)
        if close is not None:
            await close()


@router.get("/{crawl_job_id}", response_model=CrawlJobSchema)
async def get_crawl_job(crawl_job_id: UUID, db: Session = Depends(get_db)):
    crawl_job = crawl_job_repository.get_crawl_job_by_id(db, crawl_job_id)
    if crawl_job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crawl job not found")
    return crawl_job


@router.post("/{crawl_job_id}/resume", response_model=CrawlJobSchema)
async def resume_crawl_job(
    crawl_job_id: UUID,
    request: ResumeCrawlJobRequest,
    db: Session = Depends(get_db),
):
    try:
        return dispatch_service.resume_crawl_job(
            db,
            crawl_job_id=crawl_job_id,
            requested_by="api",
            strategy=request.strategy,
        )
    except Exception as exc:
        _raise_action_http_error(exc)


@router.post(
    "/{crawl_job_id}/dismiss-failed-attention",
    response_model=DismissFailedAttentionResponseV1,
)
async def dismiss_failed_attention(
    crawl_job_id: UUID,
    request: DismissFailedAttentionRequestV1,
    db: Session = Depends(get_db),
) -> DismissFailedAttentionResponseV1:
    try:
        return failed_run_attention_service.dismiss(
            db,
            crawl_job_id=crawl_job_id,
            expected_failure_event_sequence=request.expected_failure_event_sequence,
        )
    except Exception as exc:
        _raise_action_http_error(exc)


@router.post("/{crawl_job_id}/reset-browser-profile")
async def reset_browser_profile(
    crawl_job_id: UUID,
    db: Session = Depends(get_db),
):
    crawl_job = crawl_job_repository.get_crawl_job_by_id(db, crawl_job_id)
    if crawl_job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CRAWL_TASK_NOT_FOUND",
                "message": "Crawl task not found",
                "context": {"crawl_job_id": str(crawl_job_id)},
            },
        )
    if crawl_job.status != "manual_action_required":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Crawl task must be manual_action_required before its browser profile can be reset",
        )

    latest_event = crawl_job_repository.get_latest_manual_action_event(db, crawl_job_id)
    if latest_event is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Crawl task has no manual-action profile to reset",
        )
    latest_payload = dict(latest_event.payload or {})
    manual_action = normalize_manual_action_payload(
        latest_payload.get("manual_action"),
        source_site=crawl_job.source_site,
        request_payload=(
            latest_payload.get("request_payload")
            or crawl_job.request_payload
            or {}
        ),
        default_browser_channel=settings.jobsdb_headed_browser_channel,
        default_browser_profile_path=settings.jobsdb_headed_browser_user_data_dir,
    )
    stage = str(manual_action.get("stage") or "").strip().lower()
    if crawl_job.source_site not in {"jobsdb", "ctgoodjobs"} or stage not in {
        "browser_profile_in_use",
        "profile_lock",
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The latest manual action does not expose a resettable browser profile",
        )

    profile_path = str(manual_action.get("browser_profile_path") or "").strip()
    if not profile_path:
        profile_path = str(
            fresh_profile_path(
                str(crawl_job_id),
                configured_path=settings.jobsdb_headed_browser_user_data_dir,
                browser_channel=settings.jobsdb_headed_browser_channel,
            )
        )
    profile_scope = str(manual_action.get("profile_scope") or "").strip()
    if profile_scope not in {PROFILE_SCOPE_FIXED, PROFILE_SCOPE_FRESH}:
        profile_scope = (
            PROFILE_SCOPE_FRESH
            if is_task_owned_profile(
                profile_path,
                configured_path=settings.jobsdb_headed_browser_user_data_dir,
                browser_channel=settings.jobsdb_headed_browser_channel,
            )
            else PROFILE_SCOPE_FIXED
        )

    reset_result = reset_profile(
        profile_path,
        profile_scope=profile_scope,
        browser_channel=(
            str(manual_action.get("browser_channel") or "").strip()
            or settings.jobsdb_headed_browser_channel
        ),
        configured_path=settings.jobsdb_headed_browser_user_data_dir,
    )
    if not reset_result.available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "BROWSER_PROFILE_RESET_UNAVAILABLE",
                "message": "Browser profile reset is disabled until the worker confirms no active browser session remains.",
                "reason": reset_result.reason,
                "liveness": reset_result.liveness.state,
                "profile_scope": reset_result.profile_scope,
            },
        )

    crawl_job_repository.append_event(
        db,
        crawl_job_id=crawl_job_id,
        event_type="crawl.browser_profile_reset",
        payload={
            "crawl_job_id": str(crawl_job_id),
            "source_site": crawl_job.source_site,
            "profile_scope": reset_result.profile_scope,
            "liveness": reset_result.liveness.state,
            "removed_lock_markers": list(reset_result.removed_lock_markers),
            "recreated": reset_result.recreated,
            "profile_path": reset_result.profile_path,
        },
        emitted_by="api",
    )
    return {
        "status": "reset",
        "crawl_job_id": str(crawl_job_id),
        "profile_scope": reset_result.profile_scope,
        "liveness": reset_result.liveness.state,
        "removed_lock_markers": list(reset_result.removed_lock_markers),
        "recreated": reset_result.recreated,
    }


@router.post("/{crawl_job_id}/cancel", response_model=CrawlJobSchema)
async def cancel_crawl_job(crawl_job_id: UUID, db: Session = Depends(get_db)):
    try:
        return dispatch_service.cancel_crawl_job(
            db,
            crawl_job_id=crawl_job_id,
            requested_by="api",
        )
    except Exception as exc:
        _raise_action_http_error(exc)


@router.get("/{crawl_job_id}/events", response_model=CrawlJobEventsResponse)
async def list_crawl_job_events(
    crawl_job_id: UUID,
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    crawl_job = crawl_job_repository.get_crawl_job_by_id(db, crawl_job_id)
    if crawl_job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crawl job not found")

    total = crawl_job_repository.count_events(db, crawl_job_id)
    events = crawl_job_repository.list_events(db, crawl_job_id, limit=limit, tail=True)
    return CrawlJobEventsResponse(events=events, total=total)
