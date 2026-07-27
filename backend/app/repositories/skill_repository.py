from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.current_taxonomy import (
    CurrentTaxonomyAliasRecord,
    CurrentTaxonomyNodeRecord,
)


@dataclass(frozen=True)
class CurrentSkillSearchResult:
    id: str
    name: str
    category_name: str


def _label(labels: dict[str, str]) -> str:
    return str(
        labels.get("en") or labels.get("zh_HK") or next(iter(labels.values()), "")
    )


class SkillRepository:
    @staticmethod
    def _tree(db: Session):
        from app.job_intelligence.current_taxonomies.read_model import (
            CurrentTaxonomyReader,
        )

        return CurrentTaxonomyReader(db).get_tree("skill").nodes

    def get_or_create_skill(self, *_args, **_kwargs):
        raise RuntimeError(
            "Direct Skill creation is unavailable; new Skills are created by "
            "automatic candidate processing"
        )

    def search_skills(
        self,
        db: Session,
        query: str,
        limit: int = 10,
    ) -> list[CurrentSkillSearchResult]:
        pattern = f"%{query.strip()}%"
        rows = db.scalars(
            select(CurrentTaxonomyNodeRecord)
            .outerjoin(
                CurrentTaxonomyAliasRecord,
                (CurrentTaxonomyAliasRecord.taxonomy == "skill")
                & (
                    CurrentTaxonomyAliasRecord.node_code
                    == CurrentTaxonomyNodeRecord.code
                ),
            )
            .where(
                CurrentTaxonomyNodeRecord.taxonomy == "skill",
                CurrentTaxonomyNodeRecord.level == "skill",
                CurrentTaxonomyNodeRecord.is_active.is_(True),
                CurrentTaxonomyNodeRecord.is_assignable.is_(True),
                or_(
                    CurrentTaxonomyNodeRecord.labels["en"]
                    .as_string()
                    .ilike(pattern),
                    CurrentTaxonomyAliasRecord.alias.ilike(pattern),
                ),
            )
            .distinct()
            .order_by(
                CurrentTaxonomyNodeRecord.sort_order,
                CurrentTaxonomyNodeRecord.code,
            )
            .limit(limit)
        )
        tree = self._tree(db)
        by_code = {node.code: node for node in tree}
        results: list[CurrentSkillSearchResult] = []
        for row in rows:
            technology = by_code.get(row.parent_code or "")
            category = by_code.get(technology.parent_code or "") if technology else None
            results.append(
                CurrentSkillSearchResult(
                    id=row.code,
                    name=_label(dict(row.labels)),
                    category_name=_label(category.labels) if category else "",
                )
            )
        return results

    def get_skills_by_category(
        self,
        db: Session,
        category: str,
    ) -> list[CurrentSkillSearchResult]:
        return [
            skill
            for skill in self.search_skills(db, "", limit=10_000)
            if skill.category_name == category
        ]

    def get_visible_categories(self, db: Session) -> list[str]:
        return [
            _label(node.labels)
            for node in self._tree(db)
            if node.level == "category"
        ]
