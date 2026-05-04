"""Shared policy helpers for governed skill taxonomy reads."""

from __future__ import annotations

from sqlalchemy import and_, func, not_

from app.models.skill import Skill
from app.models.skill_category import SkillCategory
from app.models.skill_technology import SkillTechnology


def polluted_other_general_clause(
    category_model=SkillCategory,
    technology_model=SkillTechnology,
):
    """Return the legacy polluted branch predicate."""
    return and_(
        func.lower(category_model.name) == "other",
        func.lower(technology_model.name) == "general",
    )


def apply_governed_skill_filters(
    query,
    *,
    skill_model=Skill,
    technology_model=SkillTechnology,
    category_model=SkillCategory,
    require_visible: bool = True,
):
    """Restrict a joined skill query to governed canonical skills."""
    if require_visible:
        query = query.filter(
            skill_model.is_filter_visible.is_(True),
            technology_model.is_filter_visible.is_(True),
            category_model.is_filter_visible.is_(True),
        )

    return query.filter(
        not_(polluted_other_general_clause(category_model, technology_model))
    )


def apply_governed_skill_category_filters(
    query,
    *,
    category_model=SkillCategory,
    require_visible: bool = True,
):
    """Restrict category queries to governed, user-facing categories."""
    if require_visible:
        query = query.filter(category_model.is_filter_visible.is_(True))

    return query.filter(func.lower(category_model.name) != "other")


def is_governed_visible_skill_instance(skill: Skill | None) -> bool:
    """Return whether a skill instance belongs to the governed visible tree."""
    if skill is None or not bool(skill.is_filter_visible):
        return False

    technology = getattr(skill, "technology", None)
    if technology is None or not bool(technology.is_filter_visible):
        return False

    category = getattr(technology, "category", None)
    if category is None or not bool(category.is_filter_visible):
        return False

    return not (
        str(category.name or "").lower() == "other"
        and str(technology.name or "").lower() == "general"
    )
