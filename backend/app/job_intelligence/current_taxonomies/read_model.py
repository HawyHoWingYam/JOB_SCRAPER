from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import exists, false, select
from sqlalchemy.orm import Session

from app.job_intelligence.current_taxonomies.contracts import TaxonomyKind
from app.job_intelligence.foundation import normalized_content_hash
from app.models.company import Company
from app.models.current_taxonomy import (
    CurrentCompanyIndustryAssignment,
    CurrentJobSkillAssignment,
    CurrentJobSkillMention,
    CurrentJobTaxonomyAssignment,
    CurrentTaxonomyNodeRecord,
)
from app.models.job import Job


class CurrentTaxonomyReadError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = dict(context or {})


@dataclass(frozen=True)
class CurrentTaxonomyNodeView:
    code: str
    parent_code: str | None
    level: str
    labels: dict[str, str]
    order: int
    is_assignable: bool


@dataclass(frozen=True)
class CurrentTaxonomyTreeView:
    taxonomy: TaxonomyKind
    nodes: tuple[CurrentTaxonomyNodeView, ...]


@dataclass(frozen=True)
class CurrentJobTaxonomyAssignmentView:
    job_id: UUID
    taxonomy_code: str
    method: str
    breadcrumb: dict[str, object]
    model_provenance: dict[str, object] | None


@dataclass(frozen=True)
class CurrentJobTaxonomyStateView:
    job_id: UUID
    state: Literal["assigned", "unassigned"]
    assignment: CurrentJobTaxonomyAssignmentView | None


@dataclass(frozen=True)
class CurrentCompanyIndustryAssignmentView:
    id: int
    company_id: UUID
    taxonomy_code: str
    method: str
    breadcrumb: dict[str, object]
    is_primary: bool
    primary_basis: str | None
    provenance: dict[str, object]


@dataclass(frozen=True)
class CurrentCompanyIndustryStateView:
    company_id: UUID
    assignments: tuple[CurrentCompanyIndustryAssignmentView, ...]


@dataclass(frozen=True)
class CurrentJobSkillView:
    code: str
    name: str
    source: str
    confidence: float | None
    provenance: dict[str, object]
    mention_count: int


@dataclass(frozen=True)
class CurrentSkillCandidateMentionView:
    id: UUID
    raw_name: str
    normalized_key: str
    candidate_id: UUID
    source: str
    confidence: float | None
    provenance: dict[str, object]


@dataclass(frozen=True)
class CurrentJobSkillStateView:
    job_id: UUID
    skills: tuple[CurrentJobSkillView, ...]
    candidate_mentions: tuple[CurrentSkillCandidateMentionView, ...]


@dataclass(frozen=True)
class CurrentJobTaxonomyEmbeddingDocument:
    job_id: UUID
    taxonomy_code: str
    method: str
    breadcrumb: dict[str, object]
    document_text: str
    document_hash: str


class CurrentTaxonomyReader:
    """Read ordinary mutable taxonomies without release or revision identity."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_tree(self, taxonomy: TaxonomyKind) -> CurrentTaxonomyTreeView:
        rows = self._active_nodes(taxonomy)
        return CurrentTaxonomyTreeView(
            taxonomy=taxonomy,
            nodes=tuple(
                CurrentTaxonomyNodeView(
                    code=row.code,
                    parent_code=row.parent_code,
                    level=row.level,
                    labels=dict(row.labels),
                    order=row.sort_order,
                    is_assignable=row.is_assignable,
                )
                for row in rows
            ),
        )

    def get_job_taxonomy_state(self, job_id: UUID) -> CurrentJobTaxonomyStateView:
        return self.get_job_taxonomy_states((job_id,))[job_id]

    def get_job_taxonomy_states(
        self,
        job_ids: tuple[UUID, ...],
    ) -> dict[UUID, CurrentJobTaxonomyStateView]:
        ordered_ids = tuple(dict.fromkeys(job_ids))
        assignments = {
            row.job_id: row
            for row in self.db.scalars(
                select(CurrentJobTaxonomyAssignment).where(
                    CurrentJobTaxonomyAssignment.job_id.in_(ordered_ids)
                )
            )
        } if ordered_ids else {}
        return {
            job_id: self._job_taxonomy_state(job_id, assignments.get(job_id))
            for job_id in ordered_ids
        }

    def get_company_industry_state(
        self,
        company_id: UUID,
    ) -> CurrentCompanyIndustryStateView:
        return self.get_company_industry_states((company_id,))[company_id]

    def get_company_industry_states(
        self,
        company_ids: tuple[UUID, ...],
    ) -> dict[UUID, CurrentCompanyIndustryStateView]:
        ordered_ids = tuple(dict.fromkeys(company_ids))
        grouped: dict[UUID, list[CurrentCompanyIndustryAssignment]] = defaultdict(list)
        rows = self.db.scalars(
            select(CurrentCompanyIndustryAssignment)
            .where(CurrentCompanyIndustryAssignment.company_id.in_(ordered_ids))
            .order_by(
                CurrentCompanyIndustryAssignment.company_id,
                CurrentCompanyIndustryAssignment.is_primary.desc(),
                CurrentCompanyIndustryAssignment.captured_at,
                CurrentCompanyIndustryAssignment.id,
            )
        ) if ordered_ids else ()
        for row in rows:
            grouped[row.company_id].append(row)
        return {
            company_id: CurrentCompanyIndustryStateView(
                company_id=company_id,
                assignments=tuple(
                    self._company_industry_assignment(row)
                    for row in grouped[company_id]
                ),
            )
            for company_id in ordered_ids
        }

    def get_job_skills(self, job_id: UUID) -> CurrentJobSkillStateView:
        return self.get_job_skill_states((job_id,))[job_id]

    def get_job_skill_states(
        self,
        job_ids: tuple[UUID, ...],
    ) -> dict[UUID, CurrentJobSkillStateView]:
        ordered_ids = tuple(dict.fromkeys(job_ids))
        grouped: dict[UUID, list[CurrentJobSkillView]] = defaultdict(list)
        candidate_mentions: dict[
            UUID, list[CurrentSkillCandidateMentionView]
        ] = defaultdict(list)
        rows = self.db.execute(
            select(CurrentJobSkillAssignment, CurrentTaxonomyNodeRecord)
            .join(
                CurrentTaxonomyNodeRecord,
                (
                    CurrentTaxonomyNodeRecord.taxonomy
                    == CurrentJobSkillAssignment.taxonomy
                )
                & (
                    CurrentTaxonomyNodeRecord.code
                    == CurrentJobSkillAssignment.skill_code
                ),
            )
            .where(
                CurrentJobSkillAssignment.job_id.in_(ordered_ids),
                CurrentTaxonomyNodeRecord.is_active.is_(True),
                CurrentTaxonomyNodeRecord.is_assignable.is_(True),
            )
            .order_by(
                CurrentJobSkillAssignment.job_id,
                CurrentTaxonomyNodeRecord.sort_order,
                CurrentTaxonomyNodeRecord.code,
            )
        ) if ordered_ids else ()
        for assignment, node in rows:
            grouped[assignment.job_id].append(
                CurrentJobSkillView(
                    code=node.code,
                    name=self._display_label(node.labels),
                    source=assignment.source,
                    confidence=assignment.confidence,
                    provenance=dict(assignment.provenance),
                    mention_count=assignment.mention_count,
                )
            )
        mention_rows = self.db.scalars(
            select(CurrentJobSkillMention)
            .where(
                CurrentJobSkillMention.job_id.in_(ordered_ids),
                CurrentJobSkillMention.status == "active",
                CurrentJobSkillMention.resolution == "candidate",
            )
            .order_by(
                CurrentJobSkillMention.job_id,
                CurrentJobSkillMention.normalized_key,
                CurrentJobSkillMention.id,
            )
        ) if ordered_ids else ()
        for mention in mention_rows:
            if mention.candidate_id is None:
                continue
            candidate_mentions[mention.job_id].append(
                CurrentSkillCandidateMentionView(
                    id=mention.id,
                    raw_name=mention.raw_name,
                    normalized_key=mention.normalized_key,
                    candidate_id=mention.candidate_id,
                    source=mention.source,
                    confidence=mention.confidence,
                    provenance=dict(mention.provenance),
                )
            )
        return {
            job_id: CurrentJobSkillStateView(
                job_id=job_id,
                skills=tuple(grouped[job_id]),
                candidate_mentions=tuple(candidate_mentions[job_id]),
            )
            for job_id in ordered_ids
        }

    def build_job_taxonomy_embedding_document(
        self,
        job_id: UUID,
    ) -> CurrentJobTaxonomyEmbeddingDocument | None:
        assignment = self.db.get(CurrentJobTaxonomyAssignment, job_id)
        if assignment is None:
            return None
        breadcrumb = dict(assignment.breadcrumb)
        nodes = self._job_breadcrumb_nodes(breadcrumb)
        labels = " / ".join(label for _code, label in nodes)
        codes = " / ".join(code for code, _label in nodes)
        document_text = "\n".join(
            (
                f"Job Taxonomy: {labels}",
                f"Job Taxonomy Codes: {codes}",
                f"Assignment Method: {assignment.method}",
            )
        )
        document_hash = normalized_content_hash(
            {
                "job_id": str(job_id),
                "taxonomy_code": assignment.taxonomy_code,
                "method": assignment.method,
                "breadcrumb": breadcrumb,
                "document_text": document_text,
            }
        )
        return CurrentJobTaxonomyEmbeddingDocument(
            job_id=job_id,
            taxonomy_code=assignment.taxonomy_code,
            method=assignment.method,
            breadcrumb=breadcrumb,
            document_text=document_text,
            document_hash=document_hash,
        )

    def resolve_assignable_codes(
        self,
        taxonomy: TaxonomyKind,
        codes: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not codes:
            return ()
        rows = self._active_nodes(taxonomy)
        by_code = {row.code: row for row in rows}
        requested = set(codes)
        unknown = sorted(requested - by_code.keys())
        if unknown:
            raise CurrentTaxonomyReadError(
                "CURRENT_TAXONOMY_CODE_NOT_FOUND",
                "Current taxonomy code was not found",
                context={"taxonomy": taxonomy, "codes": unknown},
            )

        resolved: list[str] = []
        for row in rows:
            if not row.is_assignable:
                continue
            cursor: CurrentTaxonomyNodeRecord | None = row
            visited: set[str] = set()
            while cursor is not None and cursor.code not in visited:
                if cursor.code in requested:
                    resolved.append(row.code)
                    break
                visited.add(cursor.code)
                cursor = by_code.get(cursor.parent_code) if cursor.parent_code else None
        return tuple(resolved)

    def job_taxonomy_filter(self, codes: tuple[str, ...]) -> object:
        assignable_codes = self.resolve_assignable_codes("job", codes)
        if not assignable_codes:
            return false()
        return exists().where(
            CurrentJobTaxonomyAssignment.job_id == Job.id,
            CurrentJobTaxonomyAssignment.taxonomy_code.in_(assignable_codes),
        )

    def company_industry_filter(self, codes: tuple[str, ...]) -> object:
        assignable_codes = self.resolve_assignable_codes("company_industry", codes)
        if not assignable_codes:
            return false()
        return exists().where(
            CurrentCompanyIndustryAssignment.company_id == Company.id,
            CurrentCompanyIndustryAssignment.taxonomy_code.in_(assignable_codes),
        )

    def job_skill_filter(self, codes: tuple[str, ...]) -> object:
        assignable_codes = self.resolve_assignable_codes("skill", codes)
        if not assignable_codes:
            return false()
        return exists().where(
            CurrentJobSkillAssignment.job_id == Job.id,
            CurrentJobSkillAssignment.skill_code.in_(assignable_codes),
        )

    def _active_nodes(
        self,
        taxonomy: TaxonomyKind,
    ) -> tuple[CurrentTaxonomyNodeRecord, ...]:
        return tuple(
            self.db.scalars(
                select(CurrentTaxonomyNodeRecord)
                .where(
                    CurrentTaxonomyNodeRecord.taxonomy == taxonomy,
                    CurrentTaxonomyNodeRecord.is_active.is_(True),
                )
                .order_by(
                    CurrentTaxonomyNodeRecord.level,
                    CurrentTaxonomyNodeRecord.sort_order,
                    CurrentTaxonomyNodeRecord.code,
                )
            )
        )

    @staticmethod
    def _job_taxonomy_state(
        job_id: UUID,
        row: CurrentJobTaxonomyAssignment | None,
    ) -> CurrentJobTaxonomyStateView:
        if row is None:
            return CurrentJobTaxonomyStateView(
                job_id=job_id,
                state="unassigned",
                assignment=None,
            )
        return CurrentJobTaxonomyStateView(
            job_id=job_id,
            state="assigned",
            assignment=CurrentJobTaxonomyAssignmentView(
                job_id=row.job_id,
                taxonomy_code=row.taxonomy_code,
                method=row.method,
                breadcrumb=dict(row.breadcrumb),
                model_provenance=(
                    dict(row.model_provenance)
                    if row.model_provenance is not None
                    else None
                ),
            ),
        )

    @staticmethod
    def _company_industry_assignment(
        row: CurrentCompanyIndustryAssignment,
    ) -> CurrentCompanyIndustryAssignmentView:
        return CurrentCompanyIndustryAssignmentView(
            id=row.id,
            company_id=row.company_id,
            taxonomy_code=row.taxonomy_code,
            method=row.method,
            breadcrumb=dict(row.breadcrumb),
            is_primary=row.is_primary,
            primary_basis=row.primary_basis,
            provenance=dict(row.provenance),
        )

    @staticmethod
    def _display_label(labels: dict[str, Any]) -> str:
        for key in ("en", "en_HK", "zh_HK", "zh"):
            value = str(labels.get(key) or "").strip()
            if value:
                return value
        return next(
            (str(value).strip() for value in labels.values() if str(value).strip()),
            "",
        )

    @staticmethod
    def _job_breadcrumb_nodes(
        breadcrumb: dict[str, object],
    ) -> tuple[tuple[str, str], ...]:
        nodes: list[tuple[str, str]] = []
        for level in ("domain", "category", "subcategory"):
            node = breadcrumb.get(level)
            if not isinstance(node, dict):
                raise CurrentTaxonomyReadError(
                    "CURRENT_JOB_TAXONOMY_BREADCRUMB_INVALID",
                    "Current Job Taxonomy assignment has an invalid breadcrumb",
                )
            code = str(node.get("code") or "").strip()
            label = str(node.get("label") or "").strip()
            if not code or not label:
                raise CurrentTaxonomyReadError(
                    "CURRENT_JOB_TAXONOMY_BREADCRUMB_INVALID",
                    "Current Job Taxonomy assignment has an invalid breadcrumb",
                )
            nodes.append((code, label))
        return tuple(nodes)


__all__ = [
    "CurrentCompanyIndustryAssignmentView",
    "CurrentCompanyIndustryStateView",
    "CurrentJobSkillStateView",
    "CurrentJobSkillView",
    "CurrentSkillCandidateMentionView",
    "CurrentJobTaxonomyAssignmentView",
    "CurrentJobTaxonomyEmbeddingDocument",
    "CurrentJobTaxonomyStateView",
    "CurrentTaxonomyNodeView",
    "CurrentTaxonomyReadError",
    "CurrentTaxonomyReader",
    "CurrentTaxonomyTreeView",
]
