from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.skill import Skill
from app.models.skill_technology import SkillTechnology
from app.models.skill_category import SkillCategory


class SkillRepository:
    def get_or_create_skill(self, db: Session, name: str, category: str = None) -> Tuple[Skill, bool]:
        """Get or create skill by name (case-insensitive)"""
        skill = db.query(Skill).filter(func.lower(Skill.name) == name.lower()).first()
        if skill:
            return skill, False

        skill = Skill(name=name, category=category)
        db.add(skill)
        db.flush()
        return skill, True

    def search_skills(self, db: Session, query: str, limit: int = 10) -> List[Skill]:
        """Search skills for autocomplete"""
        return (
            db.query(Skill)
            .join(SkillTechnology, Skill.technology_id == SkillTechnology.id)
            .join(SkillCategory, SkillTechnology.category_id == SkillCategory.id)
            .filter(Skill.name.ilike(f"%{query}%"))
            .order_by(Skill.popularity.desc(), Skill.name.asc())
            .limit(limit)
            .all()
        )

    def get_skills_by_category(self, db: Session, category: str) -> List[Skill]:
        """Get skills by category"""
        return (
            db.query(Skill)
            .join(SkillTechnology, Skill.technology_id == SkillTechnology.id)
            .join(SkillCategory, SkillTechnology.category_id == SkillCategory.id)
            .filter(SkillCategory.name == category)
            .order_by(Skill.popularity.desc(), Skill.name.asc())
            .all()
        )
