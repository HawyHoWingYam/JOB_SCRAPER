from typing import TYPE_CHECKING, List
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.job_intelligence.skill_governance.read_model import GovernedSkillView


class SkillRepository:
    def get_or_create_skill(self, *_args, **_kwargs):
        """Retired: governed Skills are created only by a confirmed Candidate decision."""

        raise RuntimeError(
            "Direct Skill creation is retired; use SkillCandidateDecisionAdapter"
        )

    def search_skills(
        self,
        db: Session,
        query: str,
        limit: int = 10,
    ) -> List["GovernedSkillView"]:
        from app.job_intelligence.skill_governance.read_model import (
            SkillGovernanceReader,
        )

        return list(SkillGovernanceReader(db).search_skills(query, limit=limit))

    def get_skills_by_category(
        self,
        db: Session,
        category: str,
    ) -> List["GovernedSkillView"]:
        from app.job_intelligence.skill_governance.read_model import (
            SkillGovernanceReader,
        )

        return [
            skill
            for category_view in SkillGovernanceReader(db).get_tree().categories
            if category_view.name == category
            for technology in category_view.technologies
            for skill in technology.skills
        ]

    def get_visible_categories(self, db: Session) -> List[str]:
        """Get governed skill categories suitable for user-facing filters."""
        from app.job_intelligence.skill_governance.read_model import (
            SkillGovernanceReader,
        )

        return [
            category.name
            for category in SkillGovernanceReader(db).get_tree().categories
        ]
