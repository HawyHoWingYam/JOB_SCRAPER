"""Legacy category routes projected from published Source Catalog revisions."""

from typing import Optional
from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from app.source_catalog.errors import SourceCatalogError
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
        categories = await run_in_threadpool(registry.list_categories, source_site=normalized)
    except SourceCatalogError as exc:
        status_code = 404 if exc.code == "CATALOG_NOT_PUBLISHED" else 422
        raise HTTPException(status_code=status_code, detail=exc.to_detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface storage failures as 502
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
async def get_category(classification_id: str):
    """Get one JobsDB legacy category from the published revision."""
    payload = await _list_categories_impl(source_site="jobsdb")
    for category in payload["categories"]:
        if str(category.get("id")) == str(classification_id):
            return category
    raise HTTPException(
        status_code=404,
        detail={"code": "SOURCE_CLASSIFICATION_UNKNOWN", "message": "Category not found"},
    )


router.include_router(v1_router)
router.include_router(compat_router)
