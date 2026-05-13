"""Category API routes.

Task 2:
- Source-aware category listing (JobsDB + CTgoodjobs).
- CTgoodjobs category registry is cached in-memory with a TTL (see service).
"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from app.scraper.categories import JOBSDB_CATEGORIES
from app.services.source_category_registry import get_source_category_registry

# Combined router mounted under /api in backend/app/main.py.
router = APIRouter(tags=["categories"])
v1_router = APIRouter(prefix="/v1/categories", tags=["categories"])
compat_router = APIRouter(prefix="/categories", tags=["categories"])


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


router.include_router(v1_router)
router.include_router(compat_router)
