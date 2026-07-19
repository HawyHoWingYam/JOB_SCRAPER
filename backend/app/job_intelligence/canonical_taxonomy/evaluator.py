from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.job_intelligence.canonical_taxonomy.breadcrumbs import canonical_breadcrumb
from app.job_intelligence.foundation import Provenance, normalized_content_hash
from app.job_intelligence.source_attributes import SourceJobAttributesView
from app.models.canonical_job_taxonomy import (
    CanonicalJobCategory,
    CanonicalJobDomain,
    CanonicalJobSubcategory,
    CanonicalJobTaxonomyActiveMappingRevision,
    CanonicalJobTaxonomyActiveRevision,
    CanonicalJobTaxonomyMappingCoverage,
    JobTaxonomyAssignment,
    JobTaxonomyReviewItem,
    SourceJobTaxonomyMapping,
    SourceJobTaxonomyMappingTarget,
)
from app.models.job import Job
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.utils.time import utc_now


_REVIEW_REASON_ORDER = (
    "source_classification_paths_missing",
    "unsupported_source",
    "source_catalog_provenance_missing",
    "source_catalog_provenance_mismatch",
    "source_mapping_missing",
    "source_mapping_excluded",
    "source_mapping_unmapped",
    "conflicting_mapping",
    "canonical_target_invalid",
    "classifier_output_missing",
    "classifier_provenance_missing",
    "fallback_output",
    "create_new_forbidden",
    "classifier_output_invalid",
    "canonical_target_unknown",
    "classifier_target_out_of_slice",
)


@dataclass(frozen=True)
class EvaluationResult:
    state: Literal["assigned", "unassigned"]
    changed: bool
    replayed: bool
    version: int
    evidence_hash: str
    assignment_id: UUID | None = None
    review_item_id: UUID | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class CanonicalClassifierOutput:
    decision: Literal[
        "select_existing",
        "fallback_default",
        "create_new",
        "invalid",
    ]
    target_code: str | None
    provenance: Provenance | None

    def to_payload(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "target_code": self.target_code,
            "provenance": (
                self.provenance.to_payload() if self.provenance is not None else None
            ),
        }


@dataclass(frozen=True)
class CanonicalClassifierTarget:
    code: str
    label: str
    breadcrumb: str

    def to_payload(self) -> dict[str, str]:
        return {
            "code": self.code,
            "label": self.label,
            "breadcrumb": self.breadcrumb,
        }


@dataclass(frozen=True)
class CanonicalClassifierContext:
    taxonomy_revision_id: UUID
    mapping_revision_id: UUID
    source_classification_paths: tuple[dict[str, object], ...]
    canonical_targets: tuple[CanonicalClassifierTarget, ...]
    blocking_reasons: tuple[str, ...]

    def to_prompt_payload(self) -> dict[str, object]:
        return {
            "authority": "canonical-job-taxonomy",
            "taxonomy_revision_id": str(self.taxonomy_revision_id),
            "mapping_revision_id": str(self.mapping_revision_id),
            "source_classification_paths": [
                dict(path) for path in self.source_classification_paths
            ],
            "canonical_targets": [
                target.to_payload() for target in self.canonical_targets
            ],
            "blocking_reasons": list(self.blocking_reasons),
        }


class CanonicalEvaluationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _MappingPolicyOutcome:
    target_id: UUID | None
    method: Literal["reviewed_mapping", "constrained_ai"] | None
    reasons: tuple[str, ...] = ()
    recommendation_ids: tuple[UUID, ...] = ()


class CanonicalJobTaxonomy:
    """Evaluate Source evidence against the active governed mapping release."""

    def __init__(
        self,
        db: Session,
        *,
        outbox_repository: EventOutboxRepository | None = None,
    ) -> None:
        self.db = db
        self.outbox_repository = outbox_repository or EventOutboxRepository()

    def build_classifier_context(
        self,
        evidence: SourceJobAttributesView,
    ) -> CanonicalClassifierContext:
        """Build the stable-code prompt boundary from the active mapping."""
        job = self.db.get(Job, evidence.job_id)
        if job is None:
            raise CanonicalEvaluationError(
                "JOB_NOT_FOUND",
                f"Job {evidence.job_id} does not exist",
            )
        if evidence.source_site != job.source_site:
            raise CanonicalEvaluationError(
                "SOURCE_EVIDENCE_JOB_MISMATCH",
                "Source Job Attribute evidence does not belong to the evaluated Job",
            )

        active_taxonomy, active_mapping = self._active_revisions()
        mappings, _source_refs, evidence_reasons = self._load_complete_mapping_evidence(
            evidence,
            mapping_revision_id=active_mapping.mapping_revision_id,
        )
        deterministic_ids, allowed_ids = self._mapping_target_ids(mappings)
        target_ids = tuple(dict.fromkeys([*deterministic_ids, *allowed_ids]))
        blocking_reasons = [*evidence_reasons]
        blocking_reasons.extend(
            "source_mapping_excluded"
            if mapping.disposition == "excluded"
            else "source_mapping_unmapped"
            for mapping in mappings
            if mapping.disposition in {"excluded", "unmapped"}
        )
        targets = self._classifier_targets(
            target_ids,
            taxonomy_revision_id=active_taxonomy.revision_id,
        )
        if not blocking_reasons:
            if len(deterministic_ids) > 1 or (
                deterministic_ids
                and allowed_ids
                and deterministic_ids[0] not in allowed_ids
            ):
                blocking_reasons.append("conflicting_mapping")
            elif not target_ids or len(targets) != len(target_ids):
                blocking_reasons.append("canonical_target_invalid")

        return CanonicalClassifierContext(
            taxonomy_revision_id=active_taxonomy.revision_id,
            mapping_revision_id=active_mapping.mapping_revision_id,
            source_classification_paths=tuple(
                {
                    "source_order": path.source_order,
                    "nodes": [
                        {
                            "id": node.source_classification_id,
                            "label": node.label,
                        }
                        for node in path.nodes
                    ],
                }
                for path in evidence.source_classification_paths
            ),
            canonical_targets=targets,
            blocking_reasons=_canonical_reasons(blocking_reasons),
        )

    def get_active_revision(self):
        from app.job_intelligence.canonical_taxonomy.read_model import (
            CanonicalTaxonomyReader,
        )

        return CanonicalTaxonomyReader(self.db).get_active_revision()

    def get_tree(self):
        from app.job_intelligence.canonical_taxonomy.read_model import (
            CanonicalTaxonomyReader,
        )

        return CanonicalTaxonomyReader(self.db).get_tree()

    def get_job_state(self, job_id: UUID):
        from app.job_intelligence.canonical_taxonomy.read_model import (
            CanonicalTaxonomyReader,
        )

        return CanonicalTaxonomyReader(self.db).get_job_state(job_id)

    def list_review_items(self, query):
        from app.job_intelligence.canonical_taxonomy.read_model import (
            CanonicalTaxonomyReader,
        )

        return CanonicalTaxonomyReader(self.db).list_review_items(query)

    def get_review_item(self, review_item_id: UUID):
        from app.job_intelligence.canonical_taxonomy.read_model import (
            CanonicalTaxonomyReader,
        )

        return CanonicalTaxonomyReader(self.db).get_review_item(review_item_id)

    def build_filters(self, query):
        from app.job_intelligence.canonical_taxonomy.read_model import (
            CanonicalTaxonomyReader,
        )

        return CanonicalTaxonomyReader(self.db).build_filters(query)

    def build_embedding_document(self, job_id: UUID):
        from app.job_intelligence.canonical_taxonomy.read_model import (
            CanonicalTaxonomyReader,
        )

        return CanonicalTaxonomyReader(self.db).build_embedding_document(job_id)

    def inspect_rebuild(self, job_ids=None):
        from app.job_intelligence.canonical_taxonomy.rebuild import (
            CanonicalTaxonomyRebuildInspector,
        )

        return CanonicalTaxonomyRebuildInspector(self.db).inspect(job_ids)

    def evaluate(
        self,
        job_id: UUID,
        evidence: SourceJobAttributesView,
        classifier_output: CanonicalClassifierOutput | None = None,
    ) -> EvaluationResult:
        """Flush one automatic evaluation transition without committing it."""
        job = (
            self.db.query(Job).filter(Job.id == job_id).with_for_update().one_or_none()
        )
        if job is None:
            raise CanonicalEvaluationError(
                "JOB_NOT_FOUND",
                f"Job {job_id} does not exist",
            )
        if evidence.job_id != job_id or evidence.source_site != job.source_site:
            raise CanonicalEvaluationError(
                "SOURCE_EVIDENCE_JOB_MISMATCH",
                "Source Job Attribute evidence does not belong to the evaluated Job",
            )

        active_taxonomy, active_mapping = self._active_revisions()

        mappings, source_refs, evidence_reasons = self._load_complete_mapping_evidence(
            evidence,
            mapping_revision_id=active_mapping.mapping_revision_id,
        )
        evidence_hash = normalized_content_hash(
            {
                "source_attribute_evidence_hash": evidence.evidence_hash,
                "source_attribute_version": evidence.version,
                "taxonomy_revision_id": str(active_taxonomy.revision_id),
                "mapping_revision_id": str(active_mapping.mapping_revision_id),
                "mapping_ids": [str(mapping.id) for mapping in mappings],
                "classifier_output": (
                    classifier_output.to_payload()
                    if classifier_output is not None
                    else None
                ),
            }
        )
        policy = (
            _MappingPolicyOutcome(
                target_id=None,
                method=None,
                reasons=evidence_reasons,
            )
            if evidence_reasons
            else self._resolve_mapping_policy(
                mappings,
                taxonomy_revision_id=active_taxonomy.revision_id,
                classifier_output=classifier_output,
            )
        )
        if policy.reasons:
            policy = _MappingPolicyOutcome(
                target_id=policy.target_id,
                method=policy.method,
                reasons=_canonical_reasons(policy.reasons),
                recommendation_ids=policy.recommendation_ids,
            )
        evaluation_refs = list(source_refs)
        if classifier_output is not None and classifier_output.provenance is not None:
            evaluation_refs.extend(
                dict(reference)
                for reference in classifier_output.provenance.evidence_refs
            )

        current_assignment = (
            self.db.query(JobTaxonomyAssignment)
            .filter(
                JobTaxonomyAssignment.job_id == job_id,
                JobTaxonomyAssignment.is_current.is_(True),
            )
            .with_for_update()
            .one_or_none()
        )
        target_id = policy.target_id
        if target_id is None:
            return self._create_review(
                job_id=job_id,
                taxonomy_revision_id=active_taxonomy.revision_id,
                mapping_revision_id=active_mapping.mapping_revision_id,
                evidence_hash=evidence_hash,
                source_refs=evaluation_refs,
                reasons=policy.reasons,
                recommendation_ids=policy.recommendation_ids,
                current_assignment=current_assignment,
            )

        classifier_provenance = (
            classifier_output.provenance
            if policy.method == "constrained_ai" and classifier_output is not None
            else None
        )
        model_identity = (
            classifier_provenance.model_provider
            if classifier_provenance is not None
            else None,
            classifier_provenance.model_name
            if classifier_provenance is not None
            else None,
            classifier_provenance.model_version
            if classifier_provenance is not None
            else None,
        )
        current_review = (
            self.db.query(JobTaxonomyReviewItem)
            .filter(
                JobTaxonomyReviewItem.job_id == job_id,
                JobTaxonomyReviewItem.status == "active",
            )
            .with_for_update()
            .one_or_none()
        )
        assignment_version = 1
        if current_assignment is not None:
            current_identity = (
                current_assignment.taxonomy_revision_id,
                current_assignment.subcategory_id,
                current_assignment.mapping_revision_id,
                current_assignment.method,
                current_assignment.evidence_hash,
                current_assignment.model_provider,
                current_assignment.model_name,
                current_assignment.model_version,
            )
            expected_identity = (
                active_taxonomy.revision_id,
                target_id,
                active_mapping.mapping_revision_id,
                policy.method,
                evidence_hash,
                *model_identity,
            )
            if current_identity == expected_identity:
                return EvaluationResult(
                    state="assigned",
                    changed=False,
                    replayed=True,
                    version=current_assignment.lock_version,
                    evidence_hash=evidence_hash,
                    assignment_id=current_assignment.id,
                )
            assignment_version = current_assignment.lock_version + 1
            current_assignment.is_current = False
            current_assignment.superseded_at = utc_now()
            self.db.flush()
        if current_review is not None:
            assignment_version = max(
                assignment_version,
                current_review.lock_version + 1,
            )

        assignment_id = uuid4()
        if current_review is not None:
            current_review.status = "assigned"
            current_review.lock_version = assignment_version
            current_review.assignment_id = assignment_id
            current_review.resolved_at = utc_now()
        assignment = JobTaxonomyAssignment(
            id=assignment_id,
            job_id=job_id,
            taxonomy_revision_id=active_taxonomy.revision_id,
            subcategory_id=target_id,
            mapping_revision_id=active_mapping.mapping_revision_id,
            method=policy.method,
            evidence_hash=evidence_hash,
            source_evidence_refs=evaluation_refs,
            mapping_ids=[str(mapping.id) for mapping in mappings],
            model_provider=model_identity[0],
            model_name=model_identity[1],
            model_version=model_identity[2],
            breadcrumb=canonical_breadcrumb(
                self.db,
                target_id,
                taxonomy_revision_id=active_taxonomy.revision_id,
            ),
            lock_version=assignment_version,
            is_current=True,
        )
        self.db.add(assignment)
        self._enqueue_change(
            job_id=job_id,
            state="assigned",
            taxonomy_revision_id=active_taxonomy.revision_id,
            mapping_revision_id=active_mapping.mapping_revision_id,
            evidence_hash=evidence_hash,
            version=assignment_version,
            assignment_id=assignment_id,
        )
        self.db.flush()
        return EvaluationResult(
            state="assigned",
            changed=True,
            replayed=False,
            version=assignment_version,
            evidence_hash=evidence_hash,
            assignment_id=assignment_id,
        )

    def _load_complete_mapping_evidence(
        self,
        evidence: SourceJobAttributesView,
        *,
        mapping_revision_id: UUID,
    ) -> tuple[
        list[SourceJobTaxonomyMapping],
        list[dict[str, object]],
        tuple[str, ...],
    ]:
        if not evidence.source_classification_paths:
            return [], [], ("source_classification_paths_missing",)

        coverage = (
            self.db.query(CanonicalJobTaxonomyMappingCoverage)
            .filter(
                CanonicalJobTaxonomyMappingCoverage.mapping_revision_id
                == mapping_revision_id,
                CanonicalJobTaxonomyMappingCoverage.source_site == evidence.source_site,
            )
            .one_or_none()
        )
        if coverage is None:
            unsupported_source_refs = [
                {
                    "kind": "source-classification-path",
                    "id": str(path.id),
                    "source_site": evidence.source_site,
                    "source_order": path.source_order,
                    "source_catalog_revision_id": (
                        str(path.source_catalog_revision.revision_id)
                        if path.source_catalog_revision is not None
                        else None
                    ),
                    "source_classification_ids": [
                        node.source_classification_id for node in path.nodes
                    ],
                }
                for path in evidence.source_classification_paths
            ]
            return (
                [],
                unsupported_source_refs,
                ("unsupported_source",),
            )

        ordered_identity_ids: list[str] = []
        source_refs: list[dict[str, object]] = []
        evidence_reasons: list[str] = []
        for path in evidence.source_classification_paths:
            revision = path.source_catalog_revision
            identities = [node.source_classification_id for node in path.nodes]
            ordered_identity_ids.extend(identities)
            source_refs.append(
                {
                    "kind": "source-classification-path",
                    "id": str(path.id),
                    "source_site": evidence.source_site,
                    "source_order": path.source_order,
                    "source_catalog_revision_id": (
                        str(revision.revision_id) if revision is not None else None
                    ),
                    "source_classification_ids": identities,
                }
            )
            if revision is None:
                evidence_reasons.append("source_catalog_provenance_missing")
            elif (
                revision.source_site != evidence.source_site
                or revision.revision_id != coverage.source_catalog_revision_id
                or revision.fingerprint != coverage.source_catalog_fingerprint
            ):
                evidence_reasons.append("source_catalog_provenance_mismatch")

        unique_identity_ids = list(dict.fromkeys(ordered_identity_ids))
        rows = (
            self.db.query(SourceJobTaxonomyMapping)
            .filter(
                SourceJobTaxonomyMapping.mapping_revision_id == mapping_revision_id,
                SourceJobTaxonomyMapping.source_site == evidence.source_site,
                SourceJobTaxonomyMapping.source_classification_id.in_(
                    unique_identity_ids
                ),
            )
            .all()
        )
        by_identity = {row.source_classification_id: row for row in rows}
        missing = [
            identity for identity in unique_identity_ids if identity not in by_identity
        ]
        if missing:
            evidence_reasons.append("source_mapping_missing")
        return (
            [
                by_identity[identity]
                for identity in unique_identity_ids
                if identity in by_identity
            ],
            source_refs,
            tuple(dict.fromkeys(evidence_reasons)),
        )

    def _active_revisions(
        self,
    ) -> tuple[
        CanonicalJobTaxonomyActiveRevision,
        CanonicalJobTaxonomyActiveMappingRevision,
    ]:
        active_taxonomy = self.db.get(
            CanonicalJobTaxonomyActiveRevision,
            "canonical-job-taxonomy",
        )
        if active_taxonomy is None:
            raise CanonicalEvaluationError(
                "CANONICAL_TAXONOMY_NOT_ACTIVE",
                "Canonical Job Taxonomy has no active revision",
            )
        active_mapping = self.db.get(
            CanonicalJobTaxonomyActiveMappingRevision,
            "canonical-job-taxonomy-mapping",
        )
        if (
            active_mapping is None
            or active_mapping.taxonomy_revision_id != active_taxonomy.revision_id
        ):
            raise CanonicalEvaluationError(
                "CANONICAL_MAPPING_NOT_ACTIVE",
                "Canonical Job Taxonomy has no compatible active mapping release",
            )
        return active_taxonomy, active_mapping

    def _mapping_target_ids(
        self,
        mappings: list[SourceJobTaxonomyMapping],
    ) -> tuple[tuple[UUID, ...], tuple[UUID, ...]]:
        if not mappings:
            return (), ()
        targets = (
            self.db.query(SourceJobTaxonomyMappingTarget)
            .filter(
                SourceJobTaxonomyMappingTarget.mapping_revision_id
                == mappings[0].mapping_revision_id,
                SourceJobTaxonomyMappingTarget.mapping_id.in_(
                    [mapping.id for mapping in mappings]
                ),
            )
            .order_by(
                SourceJobTaxonomyMappingTarget.mapping_id,
                SourceJobTaxonomyMappingTarget.source_order,
            )
            .all()
        )
        targets_by_mapping: dict[
            UUID, list[SourceJobTaxonomyMappingTarget]
        ] = defaultdict(list)
        for target in targets:
            targets_by_mapping[target.mapping_id].append(target)

        deterministic_targets: list[UUID] = []
        allowed_targets: list[UUID] = []
        for mapping in mappings:
            mapping_targets = targets_by_mapping[mapping.id]
            if mapping.disposition == "deterministic":
                _extend_unique(
                    deterministic_targets,
                    (
                        target.subcategory_id
                        for target in mapping_targets
                        if target.role == "deterministic"
                    ),
                )
            elif mapping.disposition == "allowed_slice":
                _extend_unique(
                    allowed_targets,
                    (
                        target.subcategory_id
                        for target in mapping_targets
                        if target.role == "allowed"
                    ),
                )
        return tuple(deterministic_targets), tuple(allowed_targets)

    def _classifier_targets(
        self,
        subcategory_ids: tuple[UUID, ...],
        *,
        taxonomy_revision_id: UUID,
    ) -> tuple[CanonicalClassifierTarget, ...]:
        if not subcategory_ids:
            return ()
        rows = (
            self.db.query(
                CanonicalJobSubcategory,
                CanonicalJobCategory,
                CanonicalJobDomain,
            )
            .join(
                CanonicalJobCategory,
                CanonicalJobCategory.id == CanonicalJobSubcategory.category_id,
            )
            .join(
                CanonicalJobDomain,
                CanonicalJobDomain.id == CanonicalJobCategory.domain_id,
            )
            .filter(
                CanonicalJobSubcategory.id.in_(subcategory_ids),
                CanonicalJobSubcategory.revision_id == taxonomy_revision_id,
                CanonicalJobSubcategory.is_assignable.is_(True),
            )
            .order_by(
                CanonicalJobDomain.source_order,
                CanonicalJobCategory.source_order,
                CanonicalJobSubcategory.source_order,
            )
            .all()
        )
        return tuple(
            CanonicalClassifierTarget(
                code=subcategory.code,
                label=subcategory.label,
                breadcrumb=(f"{domain.label} / {category.label} / {subcategory.label}"),
            )
            for subcategory, category, domain in rows
        )

    def _resolve_mapping_policy(
        self,
        mappings: list[SourceJobTaxonomyMapping],
        *,
        taxonomy_revision_id: UUID,
        classifier_output: CanonicalClassifierOutput | None,
    ) -> _MappingPolicyOutcome:
        deterministic_target_ids, allowed_target_ids = self._mapping_target_ids(
            mappings
        )
        deterministic_targets = list(deterministic_target_ids)
        allowed_targets = list(allowed_target_ids)

        blocking_reasons = tuple(
            dict.fromkeys(
                "source_mapping_excluded"
                if mapping.disposition == "excluded"
                else "source_mapping_unmapped"
                for mapping in mappings
                if mapping.disposition in {"excluded", "unmapped"}
            )
        )
        if blocking_reasons:
            return _MappingPolicyOutcome(
                target_id=None,
                method=None,
                reasons=blocking_reasons,
                recommendation_ids=tuple(allowed_targets),
            )

        if len(deterministic_targets) > 1:
            return _MappingPolicyOutcome(
                target_id=None,
                method=None,
                reasons=("conflicting_mapping",),
                recommendation_ids=tuple(
                    dict.fromkeys([*deterministic_targets, *allowed_targets])
                ),
            )
        if not deterministic_targets and classifier_output is None:
            return _MappingPolicyOutcome(
                target_id=None,
                method=None,
                reasons=("classifier_output_missing",),
                recommendation_ids=tuple(allowed_targets),
            )

        if not deterministic_targets:
            assert classifier_output is not None
            invalid_decision_reasons = {
                "fallback_default": "fallback_output",
                "create_new": "create_new_forbidden",
                "invalid": "classifier_output_invalid",
            }
            if classifier_output.decision != "select_existing":
                return _MappingPolicyOutcome(
                    target_id=None,
                    method=None,
                    reasons=(invalid_decision_reasons[classifier_output.decision],),
                    recommendation_ids=tuple(allowed_targets),
                )
            provenance = classifier_output.provenance
            if (
                provenance is None
                or not provenance.evidence_refs
                or not provenance.model_provider
                or not provenance.model_name
                or not provenance.model_version
            ):
                return _MappingPolicyOutcome(
                    target_id=None,
                    method=None,
                    reasons=("classifier_provenance_missing",),
                    recommendation_ids=tuple(allowed_targets),
                )
            if not classifier_output.target_code:
                return _MappingPolicyOutcome(
                    target_id=None,
                    method=None,
                    reasons=("classifier_output_invalid",),
                    recommendation_ids=tuple(allowed_targets),
                )
            selected = (
                self.db.query(CanonicalJobSubcategory)
                .filter(
                    CanonicalJobSubcategory.revision_id == taxonomy_revision_id,
                    CanonicalJobSubcategory.code == classifier_output.target_code,
                    CanonicalJobSubcategory.is_assignable.is_(True),
                )
                .one_or_none()
            )
            if selected is None:
                return _MappingPolicyOutcome(
                    target_id=None,
                    method=None,
                    reasons=("canonical_target_unknown",),
                    recommendation_ids=tuple(allowed_targets),
                )
            if selected.id not in allowed_targets:
                return _MappingPolicyOutcome(
                    target_id=None,
                    method=None,
                    reasons=("classifier_target_out_of_slice",),
                    recommendation_ids=tuple(allowed_targets),
                )
            return _MappingPolicyOutcome(
                target_id=selected.id,
                method="constrained_ai",
            )

        target_id = deterministic_targets[0]
        if allowed_targets and target_id not in allowed_targets:
            return _MappingPolicyOutcome(
                target_id=None,
                method=None,
                reasons=("conflicting_mapping",),
                recommendation_ids=tuple(dict.fromkeys([target_id, *allowed_targets])),
            )

        subcategory = self.db.get(CanonicalJobSubcategory, target_id)
        if (
            subcategory is None
            or subcategory.revision_id != taxonomy_revision_id
            or subcategory.is_assignable is not True
        ):
            return _MappingPolicyOutcome(
                target_id=None,
                method=None,
                reasons=("canonical_target_invalid",),
            )
        return _MappingPolicyOutcome(
            target_id=target_id,
            method="reviewed_mapping",
        )

    def _create_review(
        self,
        *,
        job_id: UUID,
        taxonomy_revision_id: UUID,
        mapping_revision_id: UUID,
        evidence_hash: str,
        source_refs: list[dict[str, object]],
        reasons: tuple[str, ...],
        recommendation_ids: tuple[UUID, ...],
        current_assignment: JobTaxonomyAssignment | None,
    ) -> EvaluationResult:
        review_version = 1
        if current_assignment is not None:
            review_version = current_assignment.lock_version + 1
            current_assignment.is_current = False
            current_assignment.superseded_at = utc_now()
            self.db.flush()
        current_review = (
            self.db.query(JobTaxonomyReviewItem)
            .filter(
                JobTaxonomyReviewItem.job_id == job_id,
                JobTaxonomyReviewItem.status == "active",
            )
            .with_for_update()
            .one_or_none()
        )
        if current_review is not None:
            current_identity = (
                current_review.taxonomy_revision_id,
                current_review.mapping_revision_id,
                current_review.evidence_hash,
                tuple(current_review.reasons),
            )
            expected_identity = (
                taxonomy_revision_id,
                mapping_revision_id,
                evidence_hash,
                reasons,
            )
            if current_identity == expected_identity:
                return EvaluationResult(
                    state="unassigned",
                    changed=False,
                    replayed=True,
                    version=current_review.lock_version,
                    evidence_hash=evidence_hash,
                    review_item_id=current_review.id,
                    reasons=tuple(current_review.reasons),
                )
            review_version = max(
                review_version,
                current_review.lock_version + 1,
            )
            current_review.status = "superseded"
            current_review.lock_version = review_version
            current_review.resolved_at = utc_now()
            self.db.flush()

        review_id = uuid4()
        review = JobTaxonomyReviewItem(
            id=review_id,
            job_id=job_id,
            taxonomy_revision_id=taxonomy_revision_id,
            mapping_revision_id=mapping_revision_id,
            status="active",
            reasons=list(reasons),
            evidence_hash=evidence_hash,
            evidence_refs=source_refs,
            recommendations=self._recommendations(
                recommendation_ids,
                taxonomy_revision_id=taxonomy_revision_id,
            ),
            lock_version=review_version,
        )
        self.db.add(review)
        self._enqueue_change(
            job_id=job_id,
            state="unassigned",
            taxonomy_revision_id=taxonomy_revision_id,
            mapping_revision_id=mapping_revision_id,
            evidence_hash=evidence_hash,
            version=review_version,
            review_item_id=review_id,
            reasons=reasons,
        )
        self.db.flush()
        return EvaluationResult(
            state="unassigned",
            changed=True,
            replayed=False,
            version=review_version,
            evidence_hash=evidence_hash,
            review_item_id=review_id,
            reasons=reasons,
        )

    def _recommendations(
        self,
        subcategory_ids: tuple[UUID, ...],
        *,
        taxonomy_revision_id: UUID,
    ) -> list[dict[str, str]]:
        if not subcategory_ids:
            return []
        rows = (
            self.db.query(
                CanonicalJobSubcategory,
                CanonicalJobCategory,
                CanonicalJobDomain,
            )
            .join(
                CanonicalJobCategory,
                CanonicalJobCategory.id == CanonicalJobSubcategory.category_id,
            )
            .join(
                CanonicalJobDomain,
                CanonicalJobDomain.id == CanonicalJobCategory.domain_id,
            )
            .filter(
                CanonicalJobSubcategory.id.in_(subcategory_ids),
                CanonicalJobSubcategory.revision_id == taxonomy_revision_id,
            )
            .order_by(
                CanonicalJobDomain.source_order,
                CanonicalJobCategory.source_order,
                CanonicalJobSubcategory.source_order,
            )
            .all()
        )
        return [
            {
                "subcategory_id": str(subcategory.id),
                "code": subcategory.code,
                "label": subcategory.label,
            }
            for subcategory, _category, _domain in rows
        ]

    def _enqueue_change(
        self,
        *,
        job_id: UUID,
        state: Literal["assigned", "unassigned"],
        taxonomy_revision_id: UUID,
        mapping_revision_id: UUID,
        evidence_hash: str,
        version: int,
        assignment_id: UUID | None = None,
        review_item_id: UUID | None = None,
        reasons: tuple[str, ...] = (),
    ) -> None:
        payload: dict[str, object] = {
            "job_id": str(job_id),
            "state": state,
            "taxonomy_revision_id": str(taxonomy_revision_id),
            "mapping_revision_id": str(mapping_revision_id),
            "evidence_hash": evidence_hash,
            "version": version,
        }
        if assignment_id is not None:
            payload["assignment_id"] = str(assignment_id)
        if review_item_id is not None:
            payload["review_item_id"] = str(review_item_id)
        if reasons:
            payload["reasons"] = list(reasons)
        payload["invalidate"] = [
            "canonical-taxonomy-read-model",
            "job-embedding",
        ]
        self.outbox_repository.enqueue(
            self.db,
            topic="job-intelligence-projections",
            aggregate_type="job",
            aggregate_id=str(job_id),
            event_type="job.canonical_taxonomy_changed",
            source_service="canonical-job-taxonomy",
            payload=payload,
            auto_commit=False,
        )


def _extend_unique(target: list[UUID], values: Iterable[UUID]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _canonical_reasons(reasons: Iterable[str]) -> tuple[str, ...]:
    unique = set(reasons)
    ordered = [reason for reason in _REVIEW_REASON_ORDER if reason in unique]
    ordered.extend(sorted(unique - set(_REVIEW_REASON_ORDER)))
    return tuple(ordered)
