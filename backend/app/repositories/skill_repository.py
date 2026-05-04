from typing import List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.models.skill import Skill
from app.models.skill_technology import SkillTechnology
from app.models.skill_category import SkillCategory
from app.utils.skill_taxonomy_policy import (
    apply_governed_skill_category_filters,
    apply_governed_skill_filters,
)


class SkillRepository:
    def get_or_create_skill(self, db: Session, *, technology_id, name: str) -> Tuple[Skill, bool]:
        """Get or create a canonical skill under one technology."""
        skill = db.query(Skill).filter(
            and_(
                Skill.technology_id == technology_id,
                func.lower(Skill.name) == name.lower(),
            )
        ).first()
        if skill:
            return skill, False

        skill = Skill(name=name, technology_id=technology_id)
        db.add(skill)
        db.flush()
        return skill, True

    def search_skills(self, db: Session, query: str, limit: int = 10) -> List[Skill]:
        """Search skills for autocomplete"""
        search_query = (
            db.query(Skill)
            .join(SkillTechnology, Skill.technology_id == SkillTechnology.id)
            .join(SkillCategory, SkillTechnology.category_id == SkillCategory.id)
            .filter(Skill.name.ilike(f"%{query}%"))
        )

        search_query = apply_governed_skill_filters(search_query)

        return search_query.order_by(Skill.popularity.desc(), Skill.name.asc()).limit(limit).all()

    def get_skills_by_category(self, db: Session, category: str) -> List[Skill]:
        """Get skills by category"""
        skills_query = (
            db.query(Skill)
            .join(SkillTechnology, Skill.technology_id == SkillTechnology.id)
            .join(SkillCategory, SkillTechnology.category_id == SkillCategory.id)
            .filter(SkillCategory.name == category)
        )

        skills_query = apply_governed_skill_filters(skills_query)

        return skills_query.order_by(Skill.popularity.desc(), Skill.name.asc()).all()

    def get_visible_categories(self, db: Session) -> List[str]:
        """Get governed skill categories suitable for user-facing filters."""
        query = db.query(SkillCategory.name).distinct()
        query = apply_governed_skill_category_filters(query)
        return [row[0] for row in query.order_by(SkillCategory.name.asc()).all()]
