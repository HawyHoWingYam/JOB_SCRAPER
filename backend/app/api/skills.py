from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.repositories.skill_repository import SkillRepository

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("/search")
async def search_skills(q: str, limit: int = 10, db: Session = Depends(get_db)):
    """Search skills for autocomplete"""
    repo = SkillRepository()
    skills = repo.search_skills(db, q, limit)
    return {
        "skills": [
            {
                "id": str(s.id),
                "name": s.name,
                "category": s.category_name,
            }
            for s in skills
        ]
    }


@router.get("/categories")
async def get_skill_categories(db: Session = Depends(get_db)):
    """Get all skill categories"""
    repo = SkillRepository()
    return {"categories": repo.get_visible_categories(db)}
