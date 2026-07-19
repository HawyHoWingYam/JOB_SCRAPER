"""Filter endpoints for hierarchical taxonomy."""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import JobDomain, JobCategory, JobSubcategory
from app.job_intelligence.skill_governance import (
    SkillGovernanceReadError,
    SkillGovernanceReader,
)

router = APIRouter(prefix="/filters", tags=["filters"])


def _visible_only(query, model):
    """Limit filter results to taxonomy nodes approved for filter exposure."""
    return query.filter(model.is_filter_visible.is_(True))


@router.get("/skill-categories")
def get_skill_categories(db: Session = Depends(get_db)):
    """Get all skill categories (Level 1)."""
    try:
        categories = SkillGovernanceReader(db).get_tree().categories
    except SkillGovernanceReadError:
        return []
    return [{"id": str(category.id), "name": category.name} for category in categories]


@router.get("/skill-technologies")
def get_skill_technologies(
    category_id: Optional[str] = Query(None), db: Session = Depends(get_db)
):
    """Get skill technologies, optionally filtered by category (Level 2)."""
    try:
        categories = SkillGovernanceReader(db).get_tree().categories
    except SkillGovernanceReadError:
        return []
    return [
        {
            "id": str(technology.id),
            "name": technology.name,
            "category_id": str(category.id),
        }
        for category in categories
        if category_id is None or str(category.id) == category_id
        for technology in category.technologies
    ]


@router.get("/skills")
def get_skills(
    technology_id: Optional[str] = Query(None), db: Session = Depends(get_db)
):
    """Get skills, optionally filtered by technology (Level 3)."""
    try:
        categories = SkillGovernanceReader(db).get_tree().categories
    except SkillGovernanceReadError:
        return []
    return [
        {
            "id": str(skill.id),
            "name": skill.name,
            "technology_id": str(technology.id),
        }
        for category in categories
        for technology in category.technologies
        if technology_id is None or str(technology.id) == technology_id
        for skill in technology.skills
    ]


@router.get("/job-domains")
def get_job_domains(db: Session = Depends(get_db)):
    """Get all job domains (Level 1)."""
    domains = (
        _visible_only(db.query(JobDomain), JobDomain).order_by(JobDomain.name).all()
    )
    return [{"id": str(d.id), "name": d.name} for d in domains]


@router.get("/job-categories")
def get_job_categories(
    domain_id: Optional[str] = Query(None), db: Session = Depends(get_db)
):
    """Get job categories, optionally filtered by domain (Level 2)."""
    query = _visible_only(db.query(JobCategory), JobCategory)
    if domain_id:
        query = query.filter(JobCategory.domain_id == domain_id)
    categories = query.order_by(JobCategory.name).all()
    return [
        {"id": str(c.id), "name": c.name, "domain_id": str(c.domain_id)}
        for c in categories
    ]


@router.get("/job-subcategories")
def get_job_subcategories(
    category_id: Optional[str] = Query(None), db: Session = Depends(get_db)
):
    """Get job subcategories, optionally filtered by category (Level 3)."""
    query = _visible_only(db.query(JobSubcategory), JobSubcategory)
    if category_id:
        query = query.filter(JobSubcategory.category_id == category_id)
    subcategories = query.order_by(JobSubcategory.name).all()
    return [
        {"id": str(s.id), "name": s.name, "category_id": str(s.category_id)}
        for s in subcategories
    ]
