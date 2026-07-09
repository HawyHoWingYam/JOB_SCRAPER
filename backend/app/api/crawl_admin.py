"""FastAPI admin routes for the new Scrapyd-based crawl platform.

These routes expose a thin facade over Scrapyd job operations while keeping
the PostgreSQL CrawlRun records as the authoritative product-facing state.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

import httpx

from app.database import get_db
from app.repositories.crawl_run_repository import CrawlRunRepository
from app.services.crawl_run_projection_service import CrawlRunProjectionService
from app.services.scrapyd_client import ScrapydClient, ScrapydClientError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/crawl-admin", tags=["crawl-admin"])

# --- Dependencies ---

_scrapyd_client: ScrapydClient | None = None


def _get_scrapyd_client() -> ScrapydClient:
    global _scrapyd_client
    if _scrapyd_client is None:
        _scrapyd_client = ScrapydClient()
    return _scrapyd_client


_repo = CrawlRunRepository()
_projection = CrawlRunProjectionService(_repo)


# --- Schemas ---


class CrawlRunCreateRequest(BaseModel):
    crawl_job_id: UUID
    source_site: str
    scrapyd_spider: str
    scrapyd_project: str = "job_scraper_spiders"


class CrawlRunResponse(BaseModel):
    id: UUID
    crawl_job_id: UUID | None
    source_site: str
    scrapyd_project: str
    scrapyd_spider: str
    scrapyd_job_id: str | None
    status: str
    pages_processed: int
    listings_staged: int
    details_completed: int
    details_failed: int
    created_at: str


class ScrapydStatusResponse(BaseModel):
    scrapyd_available: bool
    scrapyd_node_name: str | None
    scrapyd_pending: int
    scrapyd_running: int
    scrapyd_finished: int


# --- Routes ---


@router.get("/status", response_model=ScrapydStatusResponse)
async def admin_status():
    """Check Scrapyd daemon health and job counts."""
    client = _get_scrapyd_client()
    try:
        status_info = await run_in_threadpool(client.daemon_status)
        return ScrapydStatusResponse(
            scrapyd_available=True,
            scrapyd_node_name=status_info.get("node_name"),
            scrapyd_pending=int(status_info.get("pending", 0)),
            scrapyd_running=int(status_info.get("running", 0)),
            scrapyd_finished=int(status_info.get("finished", 0)),
        )
    except Exception as exc:
        logger.warning("Scrapyd unavailable: %s", exc)
        return ScrapydStatusResponse(
            scrapyd_available=False,
            scrapyd_node_name=None,
            scrapyd_pending=0,
            scrapyd_running=0,
            scrapyd_finished=0,
        )


@router.post("/schedule", response_model=CrawlRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def schedule_spider(
    request: CrawlRunCreateRequest,
    db: Session = Depends(get_db),
):
    """Schedule a spider run via Scrapyd and persist the crawl run."""
    client = _get_scrapyd_client()

    try:
        scrapyd_job_id = await run_in_threadpool(
            client.schedule,
            project=request.scrapyd_project,
            spider=request.scrapyd_spider,
            crawl_run_id=str(request.crawl_job_id),
        )
    except (ScrapydClientError, httpx.HTTPError) as exc:
        logger.error("Failed to schedule spider via Scrapyd: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Scrapyd scheduling failed: {exc}",
        ) from exc

    run = _projection.create_run(
        db,
        crawl_job_id=request.crawl_job_id,
        source_site=request.source_site,
        scrapyd_spider=request.scrapyd_spider,
        scrapyd_project=request.scrapyd_project,
        scrapyd_job_id=scrapyd_job_id,
    )
    db.commit()
    return _to_response(run)


@router.post("/cancel/{run_id}", response_model=CrawlRunResponse)
async def cancel_spider_run(
    run_id: UUID,
    db: Session = Depends(get_db),
):
    """Cancel a running spider run via Scrapyd."""
    run = _repo.get_by_id(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crawl run not found")

    client = _get_scrapyd_client()
    if run.scrapyd_job_id:
        try:
            await run_in_threadpool(
                client.cancel,
                project=run.scrapyd_project,
                job_id=run.scrapyd_job_id,
            )
        except httpx.HTTPError as exc:
            logger.warning("Scrapyd cancel failed (may already be stopped): %s", exc)

    _projection.mark_cancelled(db, run_id)
    db.commit()
    updated_run = _repo.get_by_id(db, run_id)
    return _to_response(updated_run)  # type: ignore[arg-type]


@router.get("/runs", response_model=list[CrawlRunResponse])
async def list_runs(
    source_site: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List crawl runs, optionally filtered by source site."""
    if source_site:
        runs = _repo.list_by_source(db, source_site, limit=limit)
    else:
        runs = _repo.list_by_source(db, "", limit=limit)  # fallback: all
    return [_to_response(run) for run in runs]


@router.get("/runs/{run_id}", response_model=CrawlRunResponse)
async def get_run(run_id: UUID, db: Session = Depends(get_db)):
    run = _repo.get_by_id(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crawl run not found")
    return _to_response(run)


# --- Internal ---


def _to_response(run: CrawlRun) -> CrawlRunResponse:
    return CrawlRunResponse(
        id=run.id,
        crawl_job_id=run.crawl_job_id,
        source_site=run.source_site,
        scrapyd_project=run.scrapyd_project,
        scrapyd_spider=run.scrapyd_spider,
        scrapyd_job_id=run.scrapyd_job_id,
        status=run.status,
        pages_processed=run.pages_processed or 0,
        listings_staged=run.listings_staged or 0,
        details_completed=run.details_completed or 0,
        details_failed=run.details_failed or 0,
        created_at=run.created_at.isoformat() if run.created_at else "",
    )
