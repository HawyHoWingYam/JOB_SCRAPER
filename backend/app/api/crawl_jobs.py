from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.crawl_phases import resolve_crawl_phase
from app.database import get_db
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.repositories.crawl_job_listing_repository import CrawlJobListingRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.scraper.manual_action import ResumeStrategy
from app.schemas.crawl_job import (
    CrawlJobCreateRequest,
    CrawlJobEventsResponse,
    CrawlJobEventSchema,
    CrawlJobSchema,
)
from app.services.crawl_request_validation import normalize_source_site, validate_category_ids_for_source_site
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService
from app.services.headed_crawl_runtime import HeadedCrawlWorkerUnavailableError
from app.services.source_category_registry import get_source_category_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/crawl-jobs", tags=["crawl-jobs"])

crawl_job_repository = CrawlJobRepository()
crawl_job_listing_repository = CrawlJobListingRepository()
schedule_repository = ScheduleRepository()
dispatch_service = CrawlJobDispatchService()
SUPPORTED_SOURCE_SITES = {"jobsdb", "ctgoodjobs", "offertoday"}


class ResumeCrawlJobRequest(BaseModel):
    strategy: ResumeStrategy | None = None


async def _validate_ctgoodjobs_category_ids_exist(category_ids: list[str] | None) -> None:
    try:
        registry = get_source_category_registry()
        categories = await run_in_threadpool(registry.list_categories, source_site="ctgoodjobs")
    except Exception as exc:
        logger.error("CTgoodjobs registry unavailable during crawl job validation: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown CTgoodjobs category_ids: {', '.join(unknown_ids)}",
        )


async def _validate_effective_category_ids(
    source_site: str | None,
    category_ids: list[int | str] | None,
) -> None:
    try:
        validate_category_ids_for_source_site(source_site, category_ids)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if normalize_source_site(source_site) == "offertoday":
        pass
    elif normalize_source_site(source_site) == "ctgoodjobs":
        await _validate_ctgoodjobs_category_ids_exist(category_ids)


@router.post("", response_model=CrawlJobSchema, status_code=status.HTTP_202_ACCEPTED)
async def create_crawl_job(
    request: CrawlJobCreateRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    if request.schedule_id is not None:
        schedule = schedule_repository.get_schedule_by_id(db, request.schedule_id)
        if schedule is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")

        effective_source_site = normalize_source_site(getattr(schedule, "source_site", "jobsdb"))
        if effective_source_site not in SUPPORTED_SOURCE_SITES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported source_site for execution",
            )

        await _validate_effective_category_ids(
            effective_source_site,
            getattr(schedule, "category_ids", None),
        )
        try:
            dispatch_result = dispatch_service.dispatch_schedule_crawl_job(
                db,
                schedule=schedule,
                requested_by=request.requested_by or "api",
                trigger_type="manual",
            )
        except HeadedCrawlWorkerUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
        response.headers["X-Crawl-Job-Id"] = str(dispatch_result.crawl_job.id)
        return dispatch_result.crawl_job

    effective_source_site = normalize_source_site(request.source_site)
    if effective_source_site not in SUPPORTED_SOURCE_SITES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported source_site for execution",
        )

    if request.category_ids:
        await _validate_effective_category_ids(effective_source_site, request.category_ids)

    try:
        dispatch_result = dispatch_service.dispatch_manual_crawl_job(
            db,
            source_site=effective_source_site,
            crawl_phase=resolve_crawl_phase(request.crawl_phase),
            crawl_mode=request.crawl_mode,
            category_ids=list(request.category_ids or []),
            keywords=request.keywords,
            max_pages=request.max_pages,
            source_listing_crawl_job_id=request.source_listing_crawl_job_id,
            detail_limit=request.detail_limit,
            detail_statuses=request.detail_statuses,
            skip_existing=request.skip_existing,
            requested_by=request.requested_by or "api",
        )
    except HeadedCrawlWorkerUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    response.headers["X-Crawl-Job-Id"] = str(dispatch_result.crawl_job.id)

    # Queue OfferToday crawl via subprocess (reliable, no asyncio GC issues)
    if effective_source_site == "offertoday" and request.crawl_phase in (None, "listing"):
        _cat_ids = ",".join(str(c) for c in (request.category_ids or []))
        _max_p = str(request.max_pages or 100)
        _keywords = str(request.keywords or "").strip()
        _cj_id = str(dispatch_result.crawl_job.id)
        _script = "/app/scripts/offertoday_standalone_crawl.py"
        import subprocess as _sp
        _args = ["python", _script, "--category-ids", _cat_ids]
        if _keywords:
            _args.extend(["--keywords", _keywords])
        _args.extend(["--max-pages", _max_p, "--crawl-job-id", _cj_id])
        _sp.Popen(_args, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)

    return dispatch_result.crawl_job


@router.get("/listing-batches")
async def list_listing_batches(
    source_site: str | None = None,
    category_id: str | None = None,
    detail_status: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    effective_source_site = normalize_source_site(source_site) if source_site else None
    if effective_source_site is not None and effective_source_site not in SUPPORTED_SOURCE_SITES:
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


@router.get("/{crawl_job_id}", response_model=CrawlJobSchema)
async def get_crawl_job(crawl_job_id: UUID, db: Session = Depends(get_db)):
    crawl_job = crawl_job_repository.get_crawl_job_by_id(db, crawl_job_id)
    if crawl_job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crawl job not found")
    return crawl_job


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
