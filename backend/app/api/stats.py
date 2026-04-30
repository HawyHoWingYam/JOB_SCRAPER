"""
Statistics API Endpoints

Provides aggregated data for dashboard charts.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Dict, Any

from app.database import get_db
from app.models.job import Job
from app.models.skill import Skill
from app.models.job_skill import JobSkill
from app.models.skill_technology import SkillTechnology
from app.models.skill_category import SkillCategory

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
    """Get top skills by frequency using relational tables."""
    query = db.query(
        Skill.name,
        SkillCategory.name.label("category"),
        func.count(JobSkill.job_id).label("count")
    ).join(JobSkill).join(SkillTechnology, Skill.technology_id == SkillTechnology.id).join(SkillCategory, SkillTechnology.category_id == SkillCategory.id).group_by(Skill.id, Skill.name, SkillCategory.name)

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
    """Get job distribution by AI category."""
    results = db.query(
        Job.ai_category,
        func.count(Job.id).label("count")
    ).filter(
        Job.ai_category.isnot(None),
        Job.is_deleted == False
    ).group_by(Job.ai_category).order_by(desc("count")).all()

    return [
        {"category": cat, "count": count}
        for cat, count in results
    ]
