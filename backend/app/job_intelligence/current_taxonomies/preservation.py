from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.canonical_job_taxonomy import (
    CanonicalJobSubcategory,
    CanonicalJobTaxonomyActiveMappingRevision,
    CanonicalJobTaxonomyActiveRevision,
    JobTaxonomyAssignment,
    SourceJobTaxonomyMapping,
    SourceJobTaxonomyMappingTarget,
)
from app.models.company_industry import (
    CompanyIndustryActiveRevision,
    CompanyIndustryAssignment,
    CompanyIndustryTaxonomyNode,
    SourceIndustryMapping,
)
from app.models.governance import GovernanceAuditEvent
from app.models.skill_governance import (
    GovernedJobSkill,
    GovernedJobSkillMention,
    GovernedSkill,
    SkillCandidate,
    SkillTaxonomyActiveRevision,
)


class TaxonomyPreservationError(ValueError):
    pass


@dataclass(frozen=True)
class PreservedJobTaxonomyAssignment:
    legacy_assignment_id: UUID
    job_id: UUID
    taxonomy_code: str
    method: str
    evidence_hash: str
    source_evidence_refs: list[object]
    mapping_ids: list[object]
    model_provenance: dict[str, object] | None
    breadcrumb: dict[str, object]
    captured_at: datetime


@dataclass(frozen=True)
class PreservedCompanyIndustryAssignment:
    legacy_assignment_id: UUID
    company_id: UUID
    taxonomy_code: str
    method: str
    provenance: dict[str, object]
    evidence_hash: str
    breadcrumb: dict[str, object]
    is_primary: bool
    primary_basis: str | None
    captured_at: datetime


@dataclass(frozen=True)
class PreservedJobSkillAssignment:
    legacy_projection_id: UUID
    job_id: UUID
    skill_code: str
    source: str
    confidence: float | None
    provenance: dict[str, object]
    mention_count: int
    updated_at: datetime


@dataclass(frozen=True)
class PreservedSkillCandidateEvidence:
    id: UUID
    normalized_key: str
    canonical_raw_name: str
    raw_variants: list[object]
    occurrence_count: int
    distinct_job_count: int
    evidence_summary: dict[str, object]
    resolved_skill_code: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PreservedJobSkillMentionEvidence:
    id: UUID
    job_id: UUID
    raw_name: str
    normalized_key: str
    resolution: str
    status: str
    skill_code: str | None
    candidate_id: UUID | None
    origin_candidate_id: UUID | None
    generic_tag: str | None
    rejection_reason: str | None
    source: str
    confidence: float | None
    provenance: dict[str, object]
    evidence_hash: str
    created_at: datetime
    updated_at: datetime
    superseded_at: datetime | None


@dataclass(frozen=True)
class PreservedTaxonomyAuditEvent:
    id: UUID
    domain: str
    subject_type: str
    subject_id: str
    action: str
    actor: str
    command_hash: str
    idempotency_key: str
    before_summary: dict[str, object]
    after_summary: dict[str, object]
    evidence_refs: list[object]
    correlation_id: str | None
    created_at: datetime


@dataclass(frozen=True)
class PreservedSourceTaxonomyMapping:
    taxonomy: str
    source_site: str
    source_key: str
    target_code: str
    source_label: str | None
    role: str
    evidence: dict[str, object]


@dataclass(frozen=True)
class PersistedTaxonomyPreservationSnapshot:
    job_assignments: tuple[PreservedJobTaxonomyAssignment, ...]
    company_assignments: tuple[PreservedCompanyIndustryAssignment, ...]
    skill_assignments: tuple[PreservedJobSkillAssignment, ...]
    skill_candidates: tuple[PreservedSkillCandidateEvidence, ...]
    skill_mentions: tuple[PreservedJobSkillMentionEvidence, ...]
    source_mappings: tuple[PreservedSourceTaxonomyMapping, ...] = ()
    audit_events: tuple[PreservedTaxonomyAuditEvent, ...] = ()


class CurrentTaxonomyPreservationLoader:
    """Read the active legacy projections into revision-free preservation rows."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def load(
        self,
        *,
        current_job_codes: set[str],
        current_company_codes: set[str],
        current_skill_codes: set[str],
        legacy_identity_to_code: dict[str, str] | None = None,
    ) -> PersistedTaxonomyPreservationSnapshot:
        job_revision = self._active_revision(
            CanonicalJobTaxonomyActiveRevision,
            "canonical-job-taxonomy",
        )
        company_revision = self._active_revision(
            CompanyIndustryActiveRevision,
            "company-industry",
        )
        skill_revision = self._active_revision(
            SkillTaxonomyActiveRevision,
            "skill-taxonomy",
        )
        active_job_mapping = self.db.get(
            CanonicalJobTaxonomyActiveMappingRevision,
            "canonical-job-taxonomy-mapping",
        )

        job_rows = tuple(
            self.db.execute(
                select(JobTaxonomyAssignment, CanonicalJobSubcategory)
                .join(
                    CanonicalJobSubcategory,
                    (
                        CanonicalJobSubcategory.id
                        == JobTaxonomyAssignment.subcategory_id
                    )
                    & (
                        CanonicalJobSubcategory.revision_id
                        == JobTaxonomyAssignment.taxonomy_revision_id
                    ),
                )
                .where(
                    JobTaxonomyAssignment.taxonomy_revision_id == job_revision,
                    JobTaxonomyAssignment.is_current.is_(True),
                )
                .order_by(JobTaxonomyAssignment.job_id)
            )
        )
        company_rows = tuple(
            self.db.execute(
                select(CompanyIndustryAssignment, CompanyIndustryTaxonomyNode)
                .join(
                    CompanyIndustryTaxonomyNode,
                    (
                        CompanyIndustryTaxonomyNode.id
                        == CompanyIndustryAssignment.node_id
                    )
                    & (
                        CompanyIndustryTaxonomyNode.revision_id
                        == CompanyIndustryAssignment.taxonomy_revision_id
                    ),
                )
                .where(
                    CompanyIndustryAssignment.taxonomy_revision_id
                    == company_revision,
                    CompanyIndustryAssignment.status == "active",
                )
                .order_by(
                    CompanyIndustryAssignment.company_id,
                    CompanyIndustryAssignment.is_primary.desc(),
                    CompanyIndustryAssignment.id,
                )
            )
        )
        skill_rows = tuple(
            self.db.execute(
                select(GovernedJobSkill, GovernedSkill)
                .join(
                    GovernedSkill,
                    (GovernedSkill.id == GovernedJobSkill.skill_id)
                    & (
                        GovernedSkill.revision_id
                        == GovernedJobSkill.taxonomy_revision_id
                    ),
                )
                .where(GovernedJobSkill.taxonomy_revision_id == skill_revision)
                .order_by(GovernedJobSkill.job_id, GovernedSkill.code)
            )
        )
        candidate_rows = tuple(
            self.db.execute(
                select(SkillCandidate, GovernedSkill.code)
                .outerjoin(
                    GovernedSkill,
                    (GovernedSkill.id == SkillCandidate.resolved_skill_id)
                    & (GovernedSkill.revision_id == SkillCandidate.taxonomy_revision_id),
                )
                .where(SkillCandidate.taxonomy_revision_id == skill_revision)
                .order_by(SkillCandidate.normalized_key, SkillCandidate.id)
            )
        )
        mention_rows = tuple(
            self.db.execute(
                select(GovernedJobSkillMention, GovernedSkill.code)
                .outerjoin(
                    GovernedSkill,
                    (GovernedSkill.id == GovernedJobSkillMention.skill_id)
                    & (
                        GovernedSkill.revision_id
                        == GovernedJobSkillMention.taxonomy_revision_id
                    ),
                )
                .where(GovernedJobSkillMention.taxonomy_revision_id == skill_revision)
                .order_by(
                    GovernedJobSkillMention.job_id,
                    GovernedJobSkillMention.normalized_key,
                    GovernedJobSkillMention.id,
                )
            )
        )
        job_mapping_rows = ()
        if active_job_mapping is not None:
            job_mapping_rows = tuple(
                self.db.execute(
                    select(
                        SourceJobTaxonomyMapping,
                        SourceJobTaxonomyMappingTarget,
                        CanonicalJobSubcategory,
                    )
                    .join(
                        SourceJobTaxonomyMappingTarget,
                        (
                            SourceJobTaxonomyMappingTarget.mapping_id
                            == SourceJobTaxonomyMapping.id
                        )
                        & (
                            SourceJobTaxonomyMappingTarget.mapping_revision_id
                            == SourceJobTaxonomyMapping.mapping_revision_id
                        ),
                    )
                    .join(
                        CanonicalJobSubcategory,
                        (
                            CanonicalJobSubcategory.id
                            == SourceJobTaxonomyMappingTarget.subcategory_id
                        )
                        & (
                            CanonicalJobSubcategory.revision_id
                            == SourceJobTaxonomyMappingTarget.taxonomy_revision_id
                        ),
                    )
                    .where(
                        SourceJobTaxonomyMapping.mapping_revision_id
                        == active_job_mapping.mapping_revision_id,
                        SourceJobTaxonomyMapping.disposition.in_(
                            ("deterministic", "allowed_slice")
                        ),
                    )
                    .order_by(
                        SourceJobTaxonomyMapping.source_site,
                        SourceJobTaxonomyMapping.source_classification_id,
                        SourceJobTaxonomyMappingTarget.source_order,
                    )
                )
            )
        company_mapping_rows = tuple(
            self.db.execute(
                select(SourceIndustryMapping, CompanyIndustryTaxonomyNode)
                .join(
                    CompanyIndustryTaxonomyNode,
                    (
                        CompanyIndustryTaxonomyNode.id
                        == SourceIndustryMapping.target_node_id
                    )
                    & (
                        CompanyIndustryTaxonomyNode.revision_id
                        == SourceIndustryMapping.taxonomy_revision_id
                    ),
                )
                .where(
                    SourceIndustryMapping.taxonomy_revision_id == company_revision,
                    SourceIndustryMapping.status == "active",
                )
                .order_by(
                    SourceIndustryMapping.source_site,
                    SourceIndustryMapping.key_kind,
                    SourceIndustryMapping.normalized_key,
                )
            )
        )
        audit_rows = tuple(
            self.db.scalars(
                select(GovernanceAuditEvent)
                .where(
                    GovernanceAuditEvent.domain.in_(
                        ("job-taxonomy", "company-industry", "skill-governance")
                    )
                )
                .order_by(GovernanceAuditEvent.created_at, GovernanceAuditEvent.id)
            )
        )

        snapshot = PersistedTaxonomyPreservationSnapshot(
            job_assignments=self._job_assignments(job_rows),
            company_assignments=self._company_assignments(company_rows),
            skill_assignments=self._skill_assignments(skill_rows),
            skill_candidates=self._skill_candidates(candidate_rows),
            skill_mentions=self._skill_mentions(mention_rows),
            source_mappings=(
                *self._job_source_mappings(job_mapping_rows),
                *self._company_source_mappings(company_mapping_rows),
            ),
            audit_events=self._audit_events(
                audit_rows,
                legacy_identity_to_code=legacy_identity_to_code or {},
            ),
        )
        self._validate_codes(
            snapshot,
            current_job_codes=current_job_codes,
            current_company_codes=current_company_codes,
            current_skill_codes=current_skill_codes,
        )
        self._validate_unique_targets(snapshot)
        return snapshot

    def _active_revision(self, model: type[Any], singleton_key: str) -> UUID:
        row = self.db.get(model, singleton_key)
        if row is None:
            raise TaxonomyPreservationError(
                f"Active taxonomy pointer is missing: {singleton_key}"
            )
        return row.revision_id

    @staticmethod
    def _job_assignments(rows) -> tuple[PreservedJobTaxonomyAssignment, ...]:
        return tuple(
            PreservedJobTaxonomyAssignment(
                legacy_assignment_id=assignment.id,
                job_id=assignment.job_id,
                taxonomy_code=node.code,
                method=assignment.method,
                evidence_hash=assignment.evidence_hash,
                source_evidence_refs=list(assignment.source_evidence_refs),
                mapping_ids=list(assignment.mapping_ids),
                model_provenance=_model_provenance(assignment),
                breadcrumb=dict(assignment.breadcrumb),
                captured_at=assignment.captured_at,
            )
            for assignment, node in rows
        )

    @staticmethod
    def _company_assignments(rows) -> tuple[PreservedCompanyIndustryAssignment, ...]:
        return tuple(
            PreservedCompanyIndustryAssignment(
                legacy_assignment_id=assignment.id,
                company_id=assignment.company_id,
                taxonomy_code=node.code,
                method=assignment.method,
                provenance=dict(assignment.provenance),
                evidence_hash=assignment.evidence_hash,
                breadcrumb=dict(assignment.breadcrumb),
                is_primary=assignment.is_primary,
                primary_basis=assignment.primary_basis,
                captured_at=assignment.captured_at,
            )
            for assignment, node in rows
        )

    @staticmethod
    def _skill_assignments(rows) -> tuple[PreservedJobSkillAssignment, ...]:
        return tuple(
            PreservedJobSkillAssignment(
                legacy_projection_id=assignment.id,
                job_id=assignment.job_id,
                skill_code=skill.code,
                source=assignment.source,
                confidence=assignment.confidence,
                provenance=dict(assignment.provenance),
                mention_count=assignment.mention_count,
                updated_at=assignment.updated_at,
            )
            for assignment, skill in rows
        )

    @staticmethod
    def _skill_candidates(rows) -> tuple[PreservedSkillCandidateEvidence, ...]:
        return tuple(
            PreservedSkillCandidateEvidence(
                id=candidate.id,
                normalized_key=candidate.normalized_key,
                canonical_raw_name=candidate.canonical_raw_name,
                raw_variants=list(candidate.raw_variants),
                occurrence_count=candidate.occurrence_count,
                distinct_job_count=candidate.distinct_job_count,
                evidence_summary=dict(candidate.evidence_summary),
                resolved_skill_code=resolved_skill_code,
                first_seen_at=candidate.first_seen_at,
                last_seen_at=candidate.last_seen_at,
                created_at=candidate.created_at,
                updated_at=candidate.updated_at,
            )
            for candidate, resolved_skill_code in rows
        )

    @staticmethod
    def _skill_mentions(rows) -> tuple[PreservedJobSkillMentionEvidence, ...]:
        return tuple(
            PreservedJobSkillMentionEvidence(
                id=mention.id,
                job_id=mention.job_id,
                raw_name=mention.raw_name,
                normalized_key=mention.normalized_key,
                resolution=(
                    "candidate"
                    if mention.resolution == "review_candidate"
                    else mention.resolution
                ),
                status=mention.status,
                skill_code=skill_code,
                candidate_id=mention.candidate_id,
                origin_candidate_id=mention.origin_candidate_id,
                generic_tag=mention.generic_tag,
                rejection_reason=mention.rejection_reason,
                source=mention.source,
                confidence=mention.confidence,
                provenance=dict(mention.provenance),
                evidence_hash=mention.evidence_hash,
                created_at=mention.created_at,
                updated_at=mention.updated_at,
                superseded_at=mention.superseded_at,
            )
            for mention, skill_code in rows
        )

    @staticmethod
    def _audit_events(
        rows,
        *,
        legacy_identity_to_code: dict[str, str],
    ) -> tuple[PreservedTaxonomyAuditEvent, ...]:
        return tuple(
            PreservedTaxonomyAuditEvent(
                id=row.id,
                domain=row.domain,
                subject_type=row.subject_type,
                subject_id=row.subject_id,
                action=row.action,
                actor=row.actor,
                command_hash=row.command_hash,
                idempotency_key=row.idempotency_key,
                before_summary=_sanitize_audit_value(
                    row.before_summary,
                    legacy_identity_to_code=legacy_identity_to_code,
                ),
                after_summary=_sanitize_audit_value(
                    row.after_summary,
                    legacy_identity_to_code=legacy_identity_to_code,
                ),
                evidence_refs=list(
                    _sanitize_audit_value(
                        row.evidence_refs,
                        legacy_identity_to_code=legacy_identity_to_code,
                    )
                ),
                correlation_id=row.correlation_id,
                created_at=row.created_at,
            )
            for row in rows
        )

    @staticmethod
    def _job_source_mappings(rows) -> tuple[PreservedSourceTaxonomyMapping, ...]:
        return tuple(
            PreservedSourceTaxonomyMapping(
                taxonomy="job",
                source_site=mapping.source_site,
                source_key=mapping.source_classification_id,
                target_code=node.code,
                source_label=mapping.source_label,
                role=target.role,
                evidence=dict(mapping.review_evidence),
            )
            for mapping, target, node in rows
        )

    @staticmethod
    def _company_source_mappings(
        rows,
    ) -> tuple[PreservedSourceTaxonomyMapping, ...]:
        return tuple(
            PreservedSourceTaxonomyMapping(
                taxonomy="company_industry",
                source_site=mapping.source_site,
                source_key=f"{mapping.key_kind}:{mapping.normalized_key}",
                target_code=node.code,
                source_label=mapping.raw_value,
                role="deterministic",
                evidence={
                    "key_kind": mapping.key_kind,
                    "normalized_key": mapping.normalized_key,
                },
            )
            for mapping, node in rows
        )

    @staticmethod
    def _validate_codes(
        snapshot: PersistedTaxonomyPreservationSnapshot,
        *,
        current_job_codes: set[str],
        current_company_codes: set[str],
        current_skill_codes: set[str],
    ) -> None:
        missing = sorted(
            {
                row.taxonomy_code
                for row in snapshot.job_assignments
                if row.taxonomy_code not in current_job_codes
            }
            | {
                row.taxonomy_code
                for row in snapshot.company_assignments
                if row.taxonomy_code not in current_company_codes
            }
            | {
                row.skill_code
                for row in snapshot.skill_assignments
                if row.skill_code not in current_skill_codes
            }
            | {
                row.resolved_skill_code
                for row in snapshot.skill_candidates
                if row.resolved_skill_code is not None
                and row.resolved_skill_code not in current_skill_codes
            }
            | {
                row.skill_code
                for row in snapshot.skill_mentions
                if row.skill_code is not None and row.skill_code not in current_skill_codes
            }
            | {
                row.target_code
                for row in snapshot.source_mappings
                if (
                    row.taxonomy == "job"
                    and row.target_code not in current_job_codes
                )
                or (
                    row.taxonomy == "company_industry"
                    and row.target_code not in current_company_codes
                )
            }
        )
        if missing:
            raise TaxonomyPreservationError(
                f"Persisted taxonomy rows reference unknown current codes: {missing}"
            )

    @staticmethod
    def _validate_unique_targets(
        snapshot: PersistedTaxonomyPreservationSnapshot,
    ) -> None:
        _require_unique(
            (str(row.job_id) for row in snapshot.job_assignments),
            "current Job Taxonomy assignment",
        )
        _require_unique(
            (
                f"{row.company_id}:{row.taxonomy_code}"
                for row in snapshot.company_assignments
            ),
            "current Company Industry assignment",
        )
        _require_unique(
            (f"{row.job_id}:{row.skill_code}" for row in snapshot.skill_assignments),
            "current Job Skill assignment",
        )
        _require_unique(
            (row.normalized_key for row in snapshot.skill_candidates),
            "current Skill Candidate evidence",
        )
        _require_unique(
            (
                f"{row.job_id}:{row.normalized_key}"
                for row in snapshot.skill_mentions
                if row.status == "active"
            ),
            "active current Job Skill Mention evidence",
        )
        _require_unique(
            (
                f"{row.taxonomy}:{row.source_site}:{row.source_key}:{row.target_code}"
                for row in snapshot.source_mappings
            ),
            "current Source Taxonomy mapping",
        )


def _model_provenance(assignment) -> dict[str, object] | None:
    values = {
        "provider": assignment.model_provider,
        "name": assignment.model_name,
        "version": assignment.model_version,
    }
    compact = {key: value for key, value in values.items() if value is not None}
    return compact or None


_AUDIT_VERSION_KEYS = frozenset(
    {
        "revision",
        "revision_id",
        "taxonomy_revision",
        "taxonomy_revision_id",
        "mapping_revision",
        "mapping_revision_id",
        "release_id",
        "lock_version",
        "version",
    }
)
_AUDIT_NODE_ID_KEYS = {
    "subcategory_id": "taxonomy_code",
    "node_id": "taxonomy_code",
    "skill_id": "skill_code",
    "resolved_skill_id": "resolved_skill_code",
}


def _sanitize_audit_value(
    value,
    *,
    legacy_identity_to_code: dict[str, str],
):
    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for key, nested in value.items():
            if key in _AUDIT_VERSION_KEYS:
                continue
            replacement_key = _AUDIT_NODE_ID_KEYS.get(key)
            legacy_identity = str(nested) if nested is not None else None
            if (
                replacement_key is not None
                and legacy_identity is not None
                and legacy_identity in legacy_identity_to_code
            ):
                sanitized[replacement_key] = legacy_identity_to_code[legacy_identity]
                continue
            sanitized[key] = _sanitize_audit_value(
                nested,
                legacy_identity_to_code=legacy_identity_to_code,
            )
        return sanitized
    if isinstance(value, (list, tuple)):
        return [
            _sanitize_audit_value(
                item,
                legacy_identity_to_code=legacy_identity_to_code,
            )
            for item in value
        ]
    return value


def _require_unique(values, label: str) -> None:
    observed: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in observed:
            duplicates.add(value)
        observed.add(value)
    if duplicates:
        raise TaxonomyPreservationError(
            f"Duplicate {label} targets: {sorted(duplicates)}"
        )


__all__ = [
    "CurrentTaxonomyPreservationLoader",
    "PersistedTaxonomyPreservationSnapshot",
    "PreservedCompanyIndustryAssignment",
    "PreservedJobSkillAssignment",
    "PreservedJobSkillMentionEvidence",
    "PreservedJobTaxonomyAssignment",
    "PreservedSkillCandidateEvidence",
    "PreservedSourceTaxonomyMapping",
    "PreservedTaxonomyAuditEvent",
    "TaxonomyPreservationError",
]
