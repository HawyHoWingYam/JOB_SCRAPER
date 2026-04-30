"""Category API routes.

Task 2:
- Source-aware category listing (JobsDB + CTgoodjobs).
- CTgoodjobs category registry is cached in-memory with a TTL (see service).
"""

from typing import Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.scraper.categories import JOBSDB_CATEGORIES
from app.services.category_scrape_service import CategoryScrapeService
from app.services.source_category_registry import get_source_category_registry

# Combined router mounted under /api in backend/app/main.py.
router = APIRouter(tags=["categories"])
v1_router = APIRouter(prefix="/v1/categories", tags=["categories"])
compat_router = APIRouter(prefix="/categories", tags=["categories"])

# Service instance (in production, use dependency injection)
scrape_service = CategoryScrapeService()


class ScrapeRequest(BaseModel):
    max_pages: Optional[int] = None
    batch_size: int = 50


async def _list_categories_impl(source_site: Optional[str] = None):
    """List all available categories for a source site."""
    normalized = (source_site or "jobsdb").strip().lower()
    try:
        registry = get_source_category_registry()
        # list_categories may perform sync network I/O on CTgoodjobs cache miss.
        categories = await run_in_threadpool(registry.list_categories, source_site=normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface as a 502 for callers
        raise HTTPException(
            status_code=502,
            detail=f"Failed to load categories for source_site={normalized}",
        ) from exc

    return {
        "source_site": normalized,
        "total": len(categories),
        "categories": categories,
    }


@v1_router.get("")
async def list_categories_v1(source_site: Optional[str] = None):
    return await _list_categories_impl(source_site=source_site)


@compat_router.get("")
async def list_categories_compat(source_site: Optional[str] = None):
    # Backward compatibility: frontend still calls /api/categories.
    return await _list_categories_impl(source_site=source_site)


@v1_router.get("/{classification_id}")
async def get_category(classification_id: int):
    """Get details for a specific category."""
    if classification_id not in JOBSDB_CATEGORIES:
        raise HTTPException(status_code=404, detail="Category not found")

    cat = JOBSDB_CATEGORIES[classification_id]
    return {"id": cat.id, "name": cat.name, "slug": cat.slug, "source_site": "jobsdb"}


@v1_router.post("/{classification_id}/scrape")
async def start_category_scrape(
    classification_id: int,
    request: ScrapeRequest,
    background_tasks: BackgroundTasks,
):
    """Start scraping a specific category."""
    if classification_id not in JOBSDB_CATEGORIES:
        raise HTTPException(status_code=404, detail="Category not found")

    # Check if already scraping
    progress = scrape_service.get_progress(classification_id)
    if progress and progress.get("status") in ["collecting_ids", "scraping_details"]:
        raise HTTPException(status_code=409, detail="Scraping already in progress")

    # Start scraping in background
    background_tasks.add_task(
        scrape_service.scrape_category,
        classification_id,
        request.max_pages,
        request.batch_size,
    )

    return {
        "message": f"Started scraping category {classification_id}",
        "category": JOBSDB_CATEGORIES[classification_id].name,
    }


@v1_router.get("/{classification_id}/status")
async def get_scrape_status(classification_id: int):
    """Get scraping progress for a category."""
    progress = scrape_service.get_progress(classification_id)
    if not progress:
        return {"status": "not_started", "classification_id": classification_id}
    return progress


@v1_router.get("/scrape/status")
async def get_all_scrape_status():
    """Get scraping progress for all categories."""
    return scrape_service.get_all_progress()


router.include_router(v1_router)
router.include_router(compat_router)
