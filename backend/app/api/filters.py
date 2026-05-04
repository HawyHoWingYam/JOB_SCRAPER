"""Filter endpoints for hierarchical taxonomy."""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SkillCategory, SkillTechnology, Skill
from app.models import JobDomain, JobCategory, JobSubcategory
from app.utils.skill_taxonomy_policy import (
    apply_governed_skill_category_filters,
    apply_governed_skill_filters,
)

router = APIRouter(prefix="/filters", tags=["filters"])


def _visible_only(query, model):
    """Limit filter results to taxonomy nodes approved for filter exposure."""
    return query.filter(model.is_filter_visible.is_(True))


@router.get("/skill-categories")
def get_skill_categories(db: Session = Depends(get_db)):
    """Get all skill categories (Level 1)."""
    categories = db.query(SkillCategory)
    categories = apply_governed_skill_category_filters(categories)
    categories = categories.order_by(SkillCategory.name).all()
    return [{"id": str(c.id), "name": c.name} for c in categories]


@router.get("/skill-technologies")
def get_skill_technologies(
    category_id: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Get skill technologies, optionally filtered by category (Level 2)."""
    query = (
        db.query(SkillTechnology)
        .join(Skill, Skill.technology_id == SkillTechnology.id)
        .join(
        SkillCategory,
        SkillTechnology.category_id == SkillCategory.id,
    )
    )
    query = apply_governed_skill_filters(
        query,
        technology_model=SkillTechnology,
        category_model=SkillCategory,
        require_visible=True,
    ).with_entities(SkillTechnology).distinct()
    if category_id:
        query = query.filter(SkillTechnology.category_id == category_id)
    technologies = query.order_by(SkillTechnology.name).all()
    return [{"id": str(t.id), "name": t.name, "category_id": str(t.category_id)} for t in technologies]


@router.get("/skills")
def get_skills(
    technology_id: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Get skills, optionally filtered by technology (Level 3)."""
    query = (
        db.query(Skill)
        .join(SkillTechnology, Skill.technology_id == SkillTechnology.id)
        .join(SkillCategory, SkillTechnology.category_id == SkillCategory.id)
    )
    query = apply_governed_skill_filters(query)
    if technology_id:
        query = query.filter(Skill.technology_id == technology_id)
    skills = query.order_by(Skill.popularity.desc(), Skill.name).all()
    return [{"id": str(s.id), "name": s.name, "technology_id": str(s.technology_id)} for s in skills]


@router.get("/job-domains")
def get_job_domains(db: Session = Depends(get_db)):
    """Get all job domains (Level 1)."""
    domains = _visible_only(db.query(JobDomain), JobDomain).order_by(JobDomain.name).all()
    return [{"id": str(d.id), "name": d.name} for d in domains]


@router.get("/job-categories")
def get_job_categories(
    domain_id: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Get job categories, optionally filtered by domain (Level 2)."""
    query = _visible_only(db.query(JobCategory), JobCategory)
    if domain_id:
        query = query.filter(JobCategory.domain_id == domain_id)
    categories = query.order_by(JobCategory.name).all()
    return [{"id": str(c.id), "name": c.name, "domain_id": str(c.domain_id)} for c in categories]


@router.get("/job-subcategories")
def get_job_subcategories(
    category_id: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Get job subcategories, optionally filtered by category (Level 3)."""
    query = _visible_only(db.query(JobSubcategory), JobSubcategory)
    if category_id:
        query = query.filter(JobSubcategory.category_id == category_id)
    subcategories = query.order_by(JobSubcategory.name).all()
    return [{"id": str(s.id), "name": s.name, "category_id": str(s.category_id)} for s in subcategories]
