"""Legacy routes projected from ordinary top-level Source classifications."""

from typing import Optional
from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from app.services.source_category_registry import get_source_category_registry

router = APIRouter(prefix="/categories", tags=["categories"])


async def _list_categories_impl(source_site: Optional[str] = None):
    """List all available categories for a source site."""
    normalized = (source_site or "jobsdb").strip().lower()
    try:
        registry = get_source_category_registry()
        categories = await run_in_threadpool(registry.list_categories, source_site=normalized)
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


@router.get("")
async def list_categories(source_site: Optional[str] = None):
    return await _list_categories_impl(source_site=source_site)


@router.get("/{classification_id}")
async def get_category(classification_id: str):
    """Get one JobsDB legacy category from the ordinary registry."""
    payload = await _list_categories_impl(source_site="jobsdb")
    for category in payload["categories"]:
        if str(category.get("id")) == str(classification_id):
            return category
    raise HTTPException(
        status_code=404,
        detail={"code": "SOURCE_CLASSIFICATION_UNKNOWN", "message": "Category not found"},
    )
