from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.source_classification_registry import SourceClassificationRegistry
from app.source_classifications.domain import SUPPORTED_SOURCE_SITES


router = APIRouter(prefix="/source-classifications", tags=["source-classifications"])


@router.get("/{source_site}")
def list_source_classifications(
    source_site: str,
    *,
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    normalized = source_site.strip().lower()
    if normalized not in SUPPORTED_SOURCE_SITES:
        raise HTTPException(status_code=404, detail="Unsupported Source")
    rows = SourceClassificationRegistry(db).list_top_level(
        normalized,
        active_only=active_only,
    )
    return {
        "source_site": normalized,
        "classifications": [
            {
                "id": row.classification_id,
                "label": row.label,
                "native_id": row.native_id,
                "active": row.is_active,
            }
            for row in rows
        ],
    }
