"""Filter endpoints for ordinary current taxonomies."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.job_intelligence.current_taxonomies import CurrentTaxonomyReader
from app.job_intelligence.current_taxonomies.contracts import TaxonomyKind

router = APIRouter(prefix="/filters", tags=["filters"])


def _label(labels: dict[str, str]) -> str:
    return str(
        labels.get("en") or labels.get("zh_HK") or next(iter(labels.values()), "")
    )


def _nodes(db: Session, taxonomy: TaxonomyKind, level: str):
    return [
        node
        for node in CurrentTaxonomyReader(db).get_tree(taxonomy).nodes
        if node.level == level
    ]


@router.get("/skill-categories")
def get_skill_categories(db: Session = Depends(get_db)):
    """Get all skill categories (Level 1)."""
    return [
        {"id": node.code, "name": _label(node.labels)}
        for node in _nodes(db, "skill", "category")
    ]


@router.get("/skill-technologies")
def get_skill_technologies(
    category_id: Optional[str] = Query(None), db: Session = Depends(get_db)
):
    """Get skill technologies, optionally filtered by category (Level 2)."""
    return [
        {
            "id": node.code,
            "name": _label(node.labels),
            "category_id": node.parent_code,
        }
        for node in _nodes(db, "skill", "technology")
        if category_id is None or node.parent_code == category_id
    ]


@router.get("/skills")
def get_skills(
    technology_id: Optional[str] = Query(None), db: Session = Depends(get_db)
):
    """Get skills, optionally filtered by technology (Level 3)."""
    return [
        {
            "id": node.code,
            "name": _label(node.labels),
            "technology_id": node.parent_code,
        }
        for node in _nodes(db, "skill", "skill")
        if technology_id is None or node.parent_code == technology_id
    ]
