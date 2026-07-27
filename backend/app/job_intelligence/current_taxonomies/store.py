from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.job_intelligence.current_taxonomies.contracts import (
    AssignCurrentJobTaxonomyCommand,
    CurrentTaxonomySnapshot,
    ReplaceCurrentCompanyIndustriesCommand,
    ReplaceCurrentJobSkillsCommand,
    TaxonomyKind,
)
from app.models.current_taxonomy import (
    CurrentCompanyIndustryAssignment,
    CurrentJobSkillAssignment,
    CurrentJobTaxonomyAssignment,
    CurrentTaxonomyAliasRecord,
    CurrentTaxonomyNodeRecord,
    CurrentSourceTaxonomyMapping,
)


class CurrentTaxonomyStore:
    """Persist one mutable current hierarchy per taxonomy, without releases."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def synchronize(self, snapshot: CurrentTaxonomySnapshot) -> None:
        existing = {
            row.code: row
            for row in self.db.scalars(
                select(CurrentTaxonomyNodeRecord).where(
                    CurrentTaxonomyNodeRecord.taxonomy == snapshot.taxonomy
                )
            )
        }
        observed_codes: set[str] = set()
        for node in snapshot.nodes:
            row = existing.get(node.code)
            if row is None:
                row = CurrentTaxonomyNodeRecord(
                    taxonomy=snapshot.taxonomy,
                    code=node.code,
                )
                self.db.add(row)
                existing[node.code] = row
            row.parent_code = node.parent_code
            row.level = node.level
            row.labels = dict(node.labels)
            row.sort_order = node.order
            row.is_assignable = node.is_assignable
            row.is_active = node.is_active
            observed_codes.add(node.code)
            self.db.flush()

        for code, row in existing.items():
            if code not in observed_codes:
                row.is_active = False

        self.db.execute(
            delete(CurrentTaxonomyAliasRecord).where(
                CurrentTaxonomyAliasRecord.taxonomy == snapshot.taxonomy
            )
        )
        self.db.add_all(
            CurrentTaxonomyAliasRecord(
                taxonomy=alias.taxonomy,
                node_code=alias.node_code,
                alias=alias.alias,
                normalized_alias=alias.normalized_alias,
            )
            for alias in snapshot.aliases
        )
        self.db.flush()

    def list_nodes(
        self,
        taxonomy: TaxonomyKind,
        *,
        active_only: bool = True,
    ) -> tuple[CurrentTaxonomyNodeRecord, ...]:
        statement = select(CurrentTaxonomyNodeRecord).where(
            CurrentTaxonomyNodeRecord.taxonomy == taxonomy
        )
        if active_only:
            statement = statement.where(CurrentTaxonomyNodeRecord.is_active.is_(True))
        return tuple(
            self.db.scalars(
                statement.order_by(
                    CurrentTaxonomyNodeRecord.level,
                    CurrentTaxonomyNodeRecord.sort_order,
                    CurrentTaxonomyNodeRecord.code,
                )
            )
        )

    def resolve_allowed_codes(
        self,
        taxonomy: TaxonomyKind,
        *,
        source_site: str,
        source_key: str,
    ) -> tuple[str, ...]:
        mapped_codes = tuple(
            self.db.scalars(
                select(CurrentSourceTaxonomyMapping.target_code)
                .join(
                    CurrentTaxonomyNodeRecord,
                    (
                        CurrentTaxonomyNodeRecord.taxonomy
                        == CurrentSourceTaxonomyMapping.taxonomy
                    )
                    & (
                        CurrentTaxonomyNodeRecord.code
                        == CurrentSourceTaxonomyMapping.target_code
                    ),
                )
                .where(
                    CurrentSourceTaxonomyMapping.taxonomy == taxonomy,
                    CurrentSourceTaxonomyMapping.source_site == source_site,
                    CurrentSourceTaxonomyMapping.source_key == source_key,
                    CurrentTaxonomyNodeRecord.is_active.is_(True),
                    CurrentTaxonomyNodeRecord.is_assignable.is_(True),
                )
                .order_by(CurrentSourceTaxonomyMapping.target_code)
            )
        )
        if mapped_codes:
            return mapped_codes
        return tuple(
            self.db.scalars(
                select(CurrentTaxonomyNodeRecord.code)
                .where(
                    CurrentTaxonomyNodeRecord.taxonomy == taxonomy,
                    CurrentTaxonomyNodeRecord.is_active.is_(True),
                    CurrentTaxonomyNodeRecord.is_assignable.is_(True),
                )
                .order_by(CurrentTaxonomyNodeRecord.code)
            )
        )

    def assign_job(self, command: AssignCurrentJobTaxonomyCommand) -> None:
        self._require_assignable_codes("job", (command.taxonomy_code,))
        row = self.db.get(CurrentJobTaxonomyAssignment, command.job_id)
        if row is None:
            row = CurrentJobTaxonomyAssignment(
                job_id=command.job_id,
                taxonomy="job",
            )
            self.db.add(row)
        row.taxonomy_code = command.taxonomy_code
        row.method = command.method
        row.evidence_hash = command.evidence_hash
        row.source_evidence_refs = list(command.source_evidence_refs)
        row.mapping_ids = list(command.mapping_ids)
        row.model_provenance = (
            dict(command.model_provenance)
            if command.model_provenance is not None
            else None
        )
        row.breadcrumb = dict(command.breadcrumb)
        row.captured_at = command.captured_at
        self.db.flush()

    def replace_company_industries(
        self,
        command: ReplaceCurrentCompanyIndustriesCommand,
    ) -> None:
        codes = tuple(row.taxonomy_code for row in command.assignments)
        self._require_unique_codes(codes, label="Company Industry")
        self._require_assignable_codes("company_industry", codes)
        if sum(row.is_primary for row in command.assignments) > 1:
            raise ValueError("Company Industry assignments contain multiple primaries")
        self.db.execute(
            delete(CurrentCompanyIndustryAssignment).where(
                CurrentCompanyIndustryAssignment.company_id == command.company_id
            )
        )
        self.db.add_all(
            CurrentCompanyIndustryAssignment(
                company_id=command.company_id,
                taxonomy="company_industry",
                taxonomy_code=row.taxonomy_code,
                method=row.method,
                provenance=dict(row.provenance),
                evidence_hash=row.evidence_hash,
                breadcrumb=dict(row.breadcrumb),
                is_primary=row.is_primary,
                primary_basis=row.primary_basis,
                captured_at=row.captured_at,
            )
            for row in command.assignments
        )
        self.db.flush()

    def replace_job_skills(self, command: ReplaceCurrentJobSkillsCommand) -> None:
        codes = tuple(row.skill_code for row in command.skills)
        self._require_unique_codes(codes, label="Job Skill")
        self._require_assignable_codes("skill", codes)
        if any(row.mention_count < 1 for row in command.skills):
            raise ValueError("Job Skill mention_count must be positive")
        self.db.execute(
            delete(CurrentJobSkillAssignment).where(
                CurrentJobSkillAssignment.job_id == command.job_id
            )
        )
        self.db.add_all(
            CurrentJobSkillAssignment(
                job_id=command.job_id,
                skill_code=row.skill_code,
                taxonomy="skill",
                source=row.source,
                confidence=row.confidence,
                provenance=dict(row.provenance),
                mention_count=row.mention_count,
                updated_at=row.updated_at,
            )
            for row in command.skills
        )
        self.db.flush()

    def _require_assignable_codes(
        self,
        taxonomy: TaxonomyKind,
        codes: tuple[str, ...],
    ) -> None:
        if not codes:
            return
        available = set(
            self.db.scalars(
                select(CurrentTaxonomyNodeRecord.code).where(
                    CurrentTaxonomyNodeRecord.taxonomy == taxonomy,
                    CurrentTaxonomyNodeRecord.code.in_(codes),
                    CurrentTaxonomyNodeRecord.is_active.is_(True),
                    CurrentTaxonomyNodeRecord.is_assignable.is_(True),
                )
            )
        )
        missing = sorted(set(codes) - available)
        if missing:
            raise ValueError(
                f"Unknown or non-assignable current {taxonomy} codes: {missing}"
            )

    @staticmethod
    def _require_unique_codes(codes: tuple[str, ...], *, label: str) -> None:
        if len(codes) != len(set(codes)):
            raise ValueError(f"{label} assignments contain duplicate codes")
