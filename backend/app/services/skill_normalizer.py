"""Skill normalization service for hierarchical taxonomy."""
from typing import Tuple, Optional, List
import uuid
from difflib import SequenceMatcher

from sqlalchemy.orm import Session
from app.models import SkillCategory, SkillTechnology, Skill


class SkillNormalizer:
    def __init__(self, db: Session):
        self.db = db
        self._skill_cache = {}
        self._load_cache()

    def _load_cache(self):
        """Load all skills with aliases into memory cache."""
        skills = self.db.query(Skill).all()
        for skill in skills:
            self._skill_cache[skill.name.lower()] = skill.id
            if skill.aliases:
                for alias in skill.aliases:
                    self._skill_cache[alias.lower()] = skill.id

    def normalize_skill(self, name: str) -> Tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
        """
        Normalize skill name and return (skill_id, technology_id, category_id).

        Logic:
        1. Check exact match in cache (name or aliases)
        2. Fuzzy match against existing skills (similarity > 0.9)
        3. If not found, create new skill with inferred hierarchy
        """
        name_lower = name.lower().strip()

        # Check cache
        if name_lower in self._skill_cache:
            skill_id = self._skill_cache[name_lower]
            skill = self.db.query(Skill).filter_by(id=skill_id).first()
            return (skill.id, skill.technology_id, skill.technology.category_id)

        # Fuzzy match
        best_match = self._fuzzy_match(name_lower)
        if best_match:
            skill = self.db.query(Skill).filter_by(id=best_match).first()
            return (skill.id, skill.technology_id, skill.technology.category_id)

        # Create new skill
        return self._create_new_skill(name)

    def _fuzzy_match(self, name: str) -> Optional[uuid.UUID]:
        """Find best fuzzy match for skill name."""
        best_ratio = 0.0
        best_id = None

        for cached_name, skill_id in self._skill_cache.items():
            ratio = SequenceMatcher(None, name, cached_name).ratio()
            if ratio > 0.9 and ratio > best_ratio:
                best_ratio = ratio
                best_id = skill_id

        return best_id

    def _infer_hierarchy(self, name: str) -> Tuple[str, str]:
        """Infer category and technology from skill name."""
        name_lower = name.lower()

        # Frontend
        if any(x in name_lower for x in ['react', 'vue', 'angular', 'svelte', 'next']):
            return ("Frontend", "JavaScript")
        if any(x in name_lower for x in ['css', 'sass', 'tailwind', 'bootstrap']):
            return ("Frontend", "CSS")
        if 'typescript' in name_lower:
            return ("Frontend", "TypeScript")

        # Backend
        if any(x in name_lower for x in ['django', 'flask', 'fastapi']):
            return ("Backend", "Python")
        if any(x in name_lower for x in ['express', 'nest']):
            return ("Backend", "Node.js")
        if any(x in name_lower for x in ['spring', 'hibernate']):
            return ("Backend", "Java")

        # Database
        if any(x in name_lower for x in ['postgres', 'mysql', 'sql']):
            return ("Database", "SQL")
        if any(x in name_lower for x in ['mongo', 'redis']):
            return ("Database", "NoSQL")

        # DevOps
        if any(x in name_lower for x in ['docker', 'kubernetes', 'k8s']):
            return ("DevOps", "Containers")

        return ("Other", "General")

    def _create_new_skill(self, name: str) -> Tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
        """Create new skill with inferred hierarchy."""
        category_name, tech_name = self._infer_hierarchy(name)

        # Get or create category
        category = self.db.query(SkillCategory).filter_by(name=category_name).first()
        if not category:
            category = SkillCategory(
                name=category_name,
                created_by="ai",
                is_auto_created=True,
                is_filter_visible=False,
                usage_count=0,
                distinct_job_count=0,
            )
            self.db.add(category)
            self.db.flush()

        # Get or create technology
        technology = self.db.query(SkillTechnology).filter_by(
            category_id=category.id, name=tech_name
        ).first()
        if not technology:
            technology = SkillTechnology(
                category_id=category.id,
                name=tech_name,
                created_by="ai",
                is_auto_created=True,
                is_filter_visible=False,
                usage_count=0,
                distinct_job_count=0,
            )
            self.db.add(technology)
            self.db.flush()

        # Create skill
        skill = Skill(
            technology_id=technology.id,
            name=name,
            aliases=[name.lower()],
            created_by="ai",
            is_auto_created=True,
            is_filter_visible=False,
            usage_count=0,
            distinct_job_count=0,
        )
        self.db.add(skill)
        self.db.flush()

        # Update cache
        self._skill_cache[name.lower()] = skill.id

        return (skill.id, technology.id, category.id)

    def get_taxonomy_candidate_slice(self, name: str, limit: int = 10) -> dict:
        """Return a focused taxonomy slice to guide AI skill extraction decisions."""
        category_hint, technology_hint = self._infer_hierarchy(name)
        categories = self.db.query(SkillCategory).all()

        hinted_category = self.db.query(SkillCategory).filter_by(name=category_hint).first()
        if hinted_category:
            technologies = self.db.query(SkillTechnology).filter_by(
                category_id=hinted_category.id
            ).all()
        else:
            technologies = self.db.query(SkillTechnology).all()

        hinted_technology = None
        if hinted_category:
            hinted_technology = self.db.query(SkillTechnology).filter_by(
                category_id=hinted_category.id,
                name=technology_hint,
            ).first()

        if hinted_technology:
            skills = self.db.query(Skill).filter_by(
                technology_id=hinted_technology.id
            ).all()
        else:
            skills = self.db.query(Skill).all()

        return {
            "category_hint": category_hint,
            "technology_hint": technology_hint,
            "existing_categories": [category.name for category in categories[:limit]],
            "existing_technologies": [technology.name for technology in technologies[:limit]],
            "existing_skills": [skill.name for skill in skills[:limit]],
        }

    def get_skill_hierarchy(self, skill_id: uuid.UUID) -> dict:
        """Return full hierarchy path for a skill."""
        skill = self.db.query(Skill).filter_by(id=skill_id).first()
        if not skill:
            return {}

        return {
            "skill": skill.name,
            "technology": skill.technology.name,
            "category": skill.technology.category.name
        }


_normalizer_instance = None

def get_skill_normalizer(db: Session) -> SkillNormalizer:
    """Get or create skill normalizer singleton."""
    global _normalizer_instance
    if _normalizer_instance is None:
        _normalizer_instance = SkillNormalizer(db)
    return _normalizer_instance
