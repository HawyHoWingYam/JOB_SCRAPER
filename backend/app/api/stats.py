"""
Statistics API Endpoints

Provides aggregated data for dashboard charts.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, literal
from typing import List, Dict, Any

from app.database import get_db
from app.models.job import Job
from app.models.job_category import JobCategory
from app.models.job_domain import JobDomain
from app.models.job_subcategory import JobSubcategory
from app.models.skill import Skill
from app.models.job_skill_mention import JobSkillMention
from app.models.skill_technology import SkillTechnology
from app.models.skill_category import SkillCategory
from app.utils.skill_taxonomy_policy import apply_governed_skill_filters

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


@router.get("/overview")
async def get_overview(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get dashboard overview statistics."""
    total_jobs = db.query(Job).filter(Job.is_deleted == False).count()
    enriched = db.query(Job).filter(
        Job.ai_enriched_at.isnot(None),
        Job.is_deleted == False
    ).count()

    return {
        "total_jobs": total_jobs,
        "enriched_jobs": enriched,
        "pending_enrichment": total_jobs - enriched,
    }


@router.get("/skills")
async def get_skill_stats(
    limit: int = 20,
    category: str = None,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Get top skills by frequency using governed canonical skill mentions."""
    query = db.query(
        Skill.name,
        SkillCategory.name.label("category"),
        func.count(func.distinct(JobSkillMention.job_id)).label("count")
    ).join(
        JobSkillMention,
        JobSkillMention.skill_id == Skill.id,
    ).join(
        SkillTechnology,
        Skill.technology_id == SkillTechnology.id,
    ).join(
        SkillCategory,
        SkillTechnology.category_id == SkillCategory.id,
    ).filter(
        JobSkillMention.resolution == "match_existing",
        JobSkillMention.skill_id.isnot(None),
    ).group_by(Skill.id, Skill.name, SkillCategory.name)

    query = apply_governed_skill_filters(query)

    if category:
        query = query.filter(SkillCategory.name == category)

    results = query.order_by(desc("count")).limit(limit).all()

    return {
        "skills": [
            {"name": r.name, "category": r.category, "count": r.count}
            for r in results
        ]
    }


@router.get("/categories")
async def get_category_stats(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """Get job distribution by canonical job taxonomy path."""
    category_label = (
        JobDomain.name
        + literal(" / ")
        + JobCategory.name
        + literal(" / ")
        + JobSubcategory.name
    ).label("category")

    results = db.query(
        category_label,
        func.count(Job.id).label("count")
    ).outerjoin(
        JobSubcategory,
        Job.subcategory_id == JobSubcategory.id,
    ).outerjoin(
        JobCategory,
        JobSubcategory.category_id == JobCategory.id,
    ).outerjoin(
        JobDomain,
        JobCategory.domain_id == JobDomain.id,
    ).filter(
        Job.is_deleted.is_(False),
        Job.subcategory_id.isnot(None),
        category_label.isnot(None),
        category_label != "",
    ).group_by(category_label).order_by(desc("count")).all()

    return [
        {"category": cat, "count": count}
        for cat, count in results
    ]
