"""
Schedule API Routes - CRUD endpoints for scheduled scraping tasks.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.crawl_jobs import _build_crawl_request_created_log_message
from app.crawl_control.errors import CrawlControlError
from app.crawl_phases import resolve_crawl_phase
from app.database import get_db
from app.repositories.schedule_repository import ScheduleRepository
from app.schemas.crawl_job import CrawlJobSchema
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService
from app.schemas.schedule import (
    ScheduleSchema,
    ScheduleCreateSchema,
    ScheduleUpdateSchema,
    ScheduleListResponse,
    ExecutionListResponse,
    ScheduleToggleResponse,
    ImmediateScrapeRequest,
)
from app.services.crawl_request_validation import (
    normalize_source_site,
    validate_published_category_ids,
)
from app.source_catalog.errors import SourceCatalogError
from app.services.headed_crawl_runtime import HeadedCrawlWorkerUnavailableError
from app.services.source_catalog import is_supported_source_site, resolve_default_max_pages

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedules", tags=["schedules"])
repository = ScheduleRepository()
crawl_job_dispatch_service = CrawlJobDispatchService()


def _crawl_control_http_error(exc: CrawlControlError) -> HTTPException:
    status_code = {
        "AUTOMATION_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "DISPATCH_PLAN_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "SCOPE_RULE_INVALID": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "WORKLOAD_CAP_EXCEEDED": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "BACKLOG_SAFETY_CAP_EXCEEDED": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "AUTOMATION_REVISION_CONFLICT": status.HTTP_409_CONFLICT,
        "AUTOMATION_TRANSITION_INVALID": status.HTTP_409_CONFLICT,
        "DETAIL_RUN_CONFLICT": status.HTTP_409_CONFLICT,
        "DISPATCH_PLAN_REVIEW_REQUIRED": status.HTTP_409_CONFLICT,
        "DISPATCH_PLAN_EXPIRED": status.HTTP_409_CONFLICT,
        "DISPATCH_PLAN_STALE": status.HTTP_409_CONFLICT,
        "DISPATCH_PLAN_ALREADY_CONSUMED": status.HTTP_409_CONFLICT,
    }.get(exc.code, status.HTTP_422_UNPROCESSABLE_ENTITY)
    return HTTPException(status_code=status_code, detail=exc.to_detail())


async def _validate_effective_category_ids(
    source_site: str | None,
    category_ids: list[int | str] | None,
    db: Session,
) -> None:
    """Validate source-aware category ids against the published revision."""
    try:
        validate_published_category_ids(db, source_site, category_ids)
    except SourceCatalogError as exc:
        raise HTTPException(
            status_code=(
                404
                if exc.code in {"CATALOG_NOT_PUBLISHED", "SOURCE_CLASSIFICATION_UNKNOWN"}
                else 422
            ),
            detail=exc.to_detail(),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=ScheduleListResponse)
async def list_schedules(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get all schedules."""
    schedules = repository.get_all_schedules(db, skip, limit)
    if len(schedules) < limit:
        total = skip + len(schedules)
    else:
        total = repository.count_schedules(db)
    return ScheduleListResponse(schedules=schedules, total=total)


@router.post(
    "/run-now",
    response_model=CrawlJobSchema,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_immediate_scrape(
    request: ImmediateScrapeRequest,
    db: Session = Depends(get_db)
):
    """Run scraping immediately without creating a schedule."""
    effective_source_site = normalize_source_site(request.source_site)
    if not is_supported_source_site(effective_source_site):
        raise HTTPException(
            status_code=400,
            detail="Unsupported source_site for execution",
        )

    if request.category_ids:
        await _validate_effective_category_ids(
            effective_source_site, request.category_ids, db
        )

    try:
        dispatch_result = crawl_job_dispatch_service.dispatch_manual_crawl_job(
            db,
            source_site=effective_source_site,
            crawl_phase=request.crawl_phase,
            crawl_mode=request.crawl_mode,
            category_ids=list(request.category_ids or []),
            max_pages=request.max_pages,
            source_listing_crawl_job_id=request.source_listing_crawl_job_id,
            detail_limit=request.detail_limit,
            skip_existing=request.skip_existing,
            requested_by="api",
        )
    except HeadedCrawlWorkerUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except CrawlControlError as exc:
        raise _crawl_control_http_error(exc) from exc
    return dispatch_result.crawl_job


@router.get("/{schedule_id}", response_model=ScheduleSchema)
async def get_schedule(
    schedule_id: UUID,
    db: Session = Depends(get_db)
):
    """Get a schedule by ID."""
    schedule = repository.get_schedule_by_id(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


@router.post("", response_model=ScheduleSchema)
async def create_schedule(
    data: ScheduleCreateSchema,
    db: Session = Depends(get_db)
):
    """Create a new schedule."""
    await _validate_effective_category_ids(data.source_site, data.category_ids, db)
    return repository.create_schedule(db, data.model_dump())


@router.put("/{schedule_id}", response_model=ScheduleSchema)
async def update_schedule(
    schedule_id: UUID,
    data: ScheduleUpdateSchema,
    db: Session = Depends(get_db)
):
    """Update a schedule."""
    current_schedule = repository.get_schedule_by_id(db, schedule_id)
    if not current_schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    update_data = data.model_dump(exclude_unset=True)
    effective_source_site = update_data.get(
        "source_site",
        normalize_source_site(getattr(current_schedule, "source_site", "jobsdb")),
    )
    if effective_source_site is None:
        effective_source_site = normalize_source_site(getattr(current_schedule, "source_site", "jobsdb"))
    if "category_ids" in update_data:
        effective_category_ids = update_data["category_ids"]
    else:
        effective_category_ids = getattr(current_schedule, "category_ids", None)

    await _validate_effective_category_ids(
        effective_source_site, effective_category_ids, db
    )

    schedule = repository.update_schedule(db, schedule_id, update_data)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: UUID,
    db: Session = Depends(get_db)
):
    """Delete a schedule."""
    deleted = repository.delete_schedule(db, schedule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"message": "Schedule deleted"}


@router.post("/{schedule_id}/toggle", response_model=ScheduleToggleResponse)
async def toggle_schedule(
    schedule_id: UUID,
    db: Session = Depends(get_db)
):
    """Toggle schedule active status."""
    current_schedule = repository.get_schedule_by_id(db, schedule_id)
    if not current_schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    if (
        normalize_source_site(getattr(current_schedule, "source_site", "jobsdb")) == "ctgoodjobs"
        and not bool(getattr(current_schedule, "is_active", False))
    ):
        try:
            await _validate_effective_category_ids(
                getattr(current_schedule, "source_site", "jobsdb"),
                getattr(current_schedule, "category_ids", None),
                db,
            )
        except HTTPException as exc:
            if exc.status_code != 422:
                raise

            schedule = repository.update_schedule(db, schedule_id, {"is_active": False})
            return ScheduleToggleResponse(
                id=schedule.id,
                is_active=schedule.is_active,
                next_run_at=schedule.next_run_at,
            )

    schedule = repository.toggle_schedule(db, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    return ScheduleToggleResponse(
        id=schedule.id,
        is_active=schedule.is_active,
        next_run_at=schedule.next_run_at
    )


@router.post(
    "/{schedule_id}/run",
    response_model=CrawlJobSchema,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_schedule_now(
    schedule_id: UUID,
    request: Request,
    db: Session = Depends(get_db)
):
    """Run a schedule immediately."""
    schedule = repository.get_schedule_by_id(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    effective_source_site = normalize_source_site(getattr(schedule, "source_site", "jobsdb"))
    if not is_supported_source_site(effective_source_site):
        raise HTTPException(
            status_code=400,
            detail="Unsupported source_site for execution",
        )

    await _validate_effective_category_ids(
        effective_source_site,
        getattr(schedule, "category_ids", None),
        db,
    )

    try:
        dispatch_result = crawl_job_dispatch_service.dispatch_schedule_crawl_job(
            db,
            schedule=schedule,
            requested_by="api",
            trigger_type="manual",
        )
    except HeadedCrawlWorkerUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except CrawlControlError as exc:
        raise _crawl_control_http_error(exc) from exc
    request_id = getattr(getattr(request, "state", None), "request_id", None)
    resolved_request_payload = dict(getattr(dispatch_result.crawl_job, "request_payload", {}) or {})
    logger.info(
        _build_crawl_request_created_log_message(
            request_id=request_id,
            source_site=effective_source_site,
            crawl_job_id=str(dispatch_result.crawl_job.id),
            crawl_phase=resolve_crawl_phase(resolved_request_payload.get("crawl_phase")),
            crawl_mode=resolved_request_payload.get("crawl_mode") or "default",
            max_pages=resolved_request_payload.get("max_pages")
            if resolved_request_payload.get("max_pages") is not None
            else resolve_default_max_pages(effective_source_site),
            category_count=len(
                resolved_request_payload.get("category_ids")
                or getattr(schedule, "category_ids", None)
                or []
            ),
            source_listing_crawl_job_id=str(
                resolved_request_payload.get("source_listing_crawl_job_id") or ""
            ) or None,
            trigger="schedule",
            schedule_id=str(schedule.id),
        )
    )
    return dispatch_result.crawl_job


@router.get("/{schedule_id}/history", response_model=ExecutionListResponse)
async def get_schedule_history(
    schedule_id: UUID,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """Get execution history for a schedule."""
    schedule = repository.get_schedule_by_id(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    executions = repository.get_executions(db, schedule_id, limit)
    if len(executions) < limit:
        total = len(executions)
    else:
        total = repository.count_executions(db, schedule_id)
    return ExecutionListResponse(executions=executions, total=total)
