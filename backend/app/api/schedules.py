"""
Schedule API Routes - CRUD endpoints for scheduled scraping tasks.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from typing import List
from uuid import UUID

logger = logging.getLogger(__name__)

from app.database import get_db
from app.repositories.schedule_repository import ScheduleRepository
from app.schemas.crawl_job import CrawlJobSchema
from app.services.source_category_registry import get_source_category_registry
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
    validate_category_ids_for_source_site,
)

router = APIRouter(prefix="/schedules", tags=["schedules"])
repository = ScheduleRepository()
crawl_job_dispatch_service = CrawlJobDispatchService()
SUPPORTED_SOURCE_SITES = {"jobsdb", "ctgoodjobs"}


async def _validate_ctgoodjobs_category_ids_exist(category_ids: list[str] | None) -> None:
    """Validate CTgoodjobs category ids against the current registry."""
    try:
        registry = get_source_category_registry()
        categories = await run_in_threadpool(registry.list_categories, source_site="ctgoodjobs")
    except Exception as exc:
        logger.error("CTgoodjobs registry unavailable during category validation: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="CTgoodjobs category registry unavailable",
        ) from exc

    supported_ids = {str(category["id"]) for category in categories}
    unknown_ids = sorted(
        {
            str(category_id)
            for category_id in (category_ids or [])
            if str(category_id) not in supported_ids
        }
    )
    if unknown_ids:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown CTgoodjobs category_ids: {', '.join(unknown_ids)}",
        )


async def _validate_effective_category_ids(source_site: str | None, category_ids: list[int | str] | None) -> None:
    """Validate source-aware category ids and registry-backed CTgoodjobs existence."""
    try:
        validate_category_ids_for_source_site(source_site, category_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if normalize_source_site(source_site) == "ctgoodjobs":
        await _validate_ctgoodjobs_category_ids_exist(category_ids)


@router.get("", response_model=ScheduleListResponse)
async def list_schedules(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get all schedules."""
    schedules = repository.get_all_schedules(db, skip, limit)
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
    if request.source_site not in SUPPORTED_SOURCE_SITES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported source_site for execution",
        )

    dispatch_result = crawl_job_dispatch_service.dispatch_manual_crawl_job(
        db,
        source_site=request.source_site,
        crawl_phase=request.crawl_phase,
        crawl_mode=request.crawl_mode,
        category_ids=list(request.category_ids or []),
        max_pages=request.max_pages,
        source_listing_crawl_job_id=request.source_listing_crawl_job_id,
        detail_limit=request.detail_limit,
        skip_existing=request.skip_existing,
        requested_by="api",
    )
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
    await _validate_effective_category_ids(data.source_site, data.category_ids)
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

    await _validate_effective_category_ids(effective_source_site, effective_category_ids)

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
    db: Session = Depends(get_db)
):
    """Run a schedule immediately."""
    schedule = repository.get_schedule_by_id(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    effective_source_site = normalize_source_site(getattr(schedule, "source_site", "jobsdb"))
    if effective_source_site not in SUPPORTED_SOURCE_SITES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported source_site for execution",
        )

    await _validate_effective_category_ids(
        effective_source_site,
        getattr(schedule, "category_ids", None),
    )

    dispatch_result = crawl_job_dispatch_service.dispatch_schedule_crawl_job(
        db,
        schedule=schedule,
        requested_by="api",
        trigger_type="manual",
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
    return ExecutionListResponse(executions=executions, total=len(executions))
