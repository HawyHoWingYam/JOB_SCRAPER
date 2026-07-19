from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session, joinedload, selectinload, undefer

from app.job_intelligence.source_attributes import (
    SourceJobAttributeRebuildInspector,
)
from app.models.canonical_job_taxonomy import (
    CanonicalJobTaxonomyActiveMappingRevision,
    CanonicalJobTaxonomyActiveRevision,
    CanonicalJobTaxonomyMappingCoverage,
    JobTaxonomyAssignment,
    JobTaxonomyReviewItem,
    SourceJobTaxonomyMapping,
    SourceJobTaxonomyMappingTarget,
)
from app.models.job import Job
from app.models.job_category import JobCategory
from app.models.job_subcategory import JobSubcategory
from app.models.source_job_attributes import JobSourceClassificationPath


_CLASSIFIER_REVIEW_REASONS = {
    "canonical_target_invalid",
    "canonical_target_unknown",
    "classifier_output_invalid",
    "classifier_output_missing",
    "classifier_provenance_missing",
    "classifier_target_out_of_slice",
    "create_new_forbidden",
    "fallback_output",
}


@dataclass(frozen=True)
class CanonicalTaxonomyRebuildReport:
    jobs_inspected: int
    taxonomy_revision: dict[str, str] | None
    mapping_revision: dict[str, str] | None
    job_states: dict[str, int]
    accepted_by_method: dict[str, int]
    review_by_status: dict[str, int]
    review_by_reason: dict[str, int]
    mapping_evidence: dict[str, object]
    classifier_provenance: dict[str, int]
    legacy_comparison: dict[str, int]
    source_attribute_rebuild: dict[str, object]
    unrecoverable_parser_evidence: dict[str, object]

    def to_payload(self) -> dict[str, object]:
        return {
            "mode": "read-only",
            "jobs_inspected": self.jobs_inspected,
            "taxonomy_revision": (
                dict(self.taxonomy_revision)
                if self.taxonomy_revision is not None
                else None
            ),
            "mapping_revision": (
                dict(self.mapping_revision)
                if self.mapping_revision is not None
                else None
            ),
            "job_states": _sorted_counts(self.job_states),
            "accepted_by_method": _sorted_counts(self.accepted_by_method),
            "review_by_status": _sorted_counts(self.review_by_status),
            "review_by_reason": _sorted_counts(self.review_by_reason),
            "mapping_evidence": _sorted_payload(self.mapping_evidence),
            "classifier_provenance": _sorted_counts(self.classifier_provenance),
            "legacy_comparison": _sorted_counts(self.legacy_comparison),
            "source_attribute_rebuild": _sorted_payload(self.source_attribute_rebuild),
            "unrecoverable_parser_evidence": _sorted_payload(
                self.unrecoverable_parser_evidence
            ),
        }


class CanonicalTaxonomyRebuildInspector:
    """Inspect canonical rebuild inputs and current outcomes without writes."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def inspect(
        self,
        job_ids: Sequence[UUID] | None = None,
    ) -> CanonicalTaxonomyRebuildReport:
        requested_ids = tuple(dict.fromkeys(job_ids or ()))
        with self.db.no_autoflush:
            query = (
                self.db.query(Job)
                .options(
                    undefer(Job.source_site),
                    undefer(Job.source_job_id),
                    joinedload(Job.subcategory)
                    .joinedload(JobSubcategory.category)
                    .joinedload(JobCategory.domain),
                )
                .order_by(
                    Job.source_site.asc(),
                    Job.source_job_id.asc(),
                    Job.id.asc(),
                )
            )
            if job_ids is not None:
                query = query.filter(Job.id.in_(requested_ids))
            jobs = query.all()
            selected_ids = tuple(job.id for job in jobs)
            assignments = self._assignments(selected_ids)
            latest_reviews = self._latest_reviews(selected_ids)
            paths_by_job = self._classification_paths(selected_ids)
            active_taxonomy = self.db.get(
                CanonicalJobTaxonomyActiveRevision,
                "canonical-job-taxonomy",
            )
            active_mapping = self.db.get(
                CanonicalJobTaxonomyActiveMappingRevision,
                "canonical-job-taxonomy-mapping",
            )
            mapping_rows, mapping_targets, coverages = self._mapping_release(
                active_mapping
            )
            source_report = SourceJobAttributeRebuildInspector(self.db).inspect(
                selected_ids
            )

        assignments_by_job = {row.job_id: row for row in assignments}
        states: Counter[str] = Counter()
        accepted_by_method = Counter(row.method for row in assignments)
        review_by_status = Counter(row.status for row in latest_reviews.values())
        review_by_reason: Counter[str] = Counter()
        for review in latest_reviews.values():
            if review.status == "active":
                review_by_reason.update(review.reasons)
            elif review.status == "insufficient_evidence":
                review_by_reason.update(("insufficient_evidence",))

        for job in jobs:
            assignment = assignments_by_job.get(job.id)
            job_review = latest_reviews.get(job.id)
            if assignment is not None:
                states["assigned"] += 1
            elif job_review is None:
                states["unassigned_unevaluated"] += 1
            elif job_review.status == "active":
                states["unassigned_review_pending"] += 1
            elif job_review.status == "insufficient_evidence":
                states["unassigned_insufficient_evidence"] += 1
            else:
                states["unassigned_resolved_without_assignment"] += 1

        mapping_evidence = self._mapping_evidence(
            jobs=jobs,
            paths_by_job=paths_by_job,
            mapping_rows=mapping_rows,
            mapping_targets=mapping_targets,
            coverages=coverages,
        )
        classifier_provenance = self._classifier_provenance(
            jobs=jobs,
            assignments_by_job=assignments_by_job,
            latest_reviews=latest_reviews,
        )
        legacy_comparison = self._legacy_comparison(
            jobs,
            assignments_by_job=assignments_by_job,
        )
        source_payload = source_report.to_payload()
        unrecoverable_jobs = 0
        unrecoverable_causes: Counter[str] = Counter()
        for source in source_report.sources:
            unrecoverable_jobs += source.unrecoverable_jobs
            unrecoverable_causes.update(source.unrecoverable_cause_distribution)

        return CanonicalTaxonomyRebuildReport(
            jobs_inspected=len(jobs),
            taxonomy_revision=(
                {
                    "id": str(active_taxonomy.revision_id),
                    "content_hash": active_taxonomy.content_hash,
                }
                if active_taxonomy is not None
                else None
            ),
            mapping_revision=(
                {
                    "id": str(active_mapping.mapping_revision_id),
                    "content_hash": active_mapping.content_hash,
                }
                if active_mapping is not None
                else None
            ),
            job_states=dict(states),
            accepted_by_method=dict(accepted_by_method),
            review_by_status=dict(review_by_status),
            review_by_reason=dict(review_by_reason),
            mapping_evidence=mapping_evidence,
            classifier_provenance=classifier_provenance,
            legacy_comparison=legacy_comparison,
            source_attribute_rebuild=source_payload,
            unrecoverable_parser_evidence={
                "jobs": unrecoverable_jobs,
                "causes": dict(unrecoverable_causes),
            },
        )

    def _assignments(
        self,
        job_ids: tuple[UUID, ...],
    ) -> list[JobTaxonomyAssignment]:
        if not job_ids:
            return []
        return (
            self.db.query(JobTaxonomyAssignment)
            .filter(
                JobTaxonomyAssignment.job_id.in_(job_ids),
                JobTaxonomyAssignment.is_current.is_(True),
            )
            .order_by(JobTaxonomyAssignment.job_id)
            .all()
        )

    def _latest_reviews(
        self,
        job_ids: tuple[UUID, ...],
    ) -> dict[UUID, JobTaxonomyReviewItem]:
        if not job_ids:
            return {}
        rows = (
            self.db.query(JobTaxonomyReviewItem)
            .filter(
                JobTaxonomyReviewItem.job_id.in_(job_ids),
                JobTaxonomyReviewItem.status != "superseded",
            )
            .order_by(
                JobTaxonomyReviewItem.job_id,
                JobTaxonomyReviewItem.created_at.desc(),
                JobTaxonomyReviewItem.id.desc(),
            )
            .all()
        )
        latest: dict[UUID, JobTaxonomyReviewItem] = {}
        for row in rows:
            latest.setdefault(row.job_id, row)
        return latest

    def _classification_paths(
        self,
        job_ids: tuple[UUID, ...],
    ) -> dict[UUID, list[JobSourceClassificationPath]]:
        if not job_ids:
            return {}
        rows = (
            self.db.query(JobSourceClassificationPath)
            .options(
                selectinload(JobSourceClassificationPath.nodes),
                joinedload(JobSourceClassificationPath.source_catalog_revision),
            )
            .filter(JobSourceClassificationPath.job_id.in_(job_ids))
            .order_by(
                JobSourceClassificationPath.job_id,
                JobSourceClassificationPath.source_order,
            )
            .all()
        )
        grouped: dict[UUID, list[JobSourceClassificationPath]] = defaultdict(list)
        for row in rows:
            grouped[row.job_id].append(row)
        return grouped

    def _mapping_release(
        self,
        active_mapping: CanonicalJobTaxonomyActiveMappingRevision | None,
    ) -> tuple[
        list[SourceJobTaxonomyMapping],
        list[SourceJobTaxonomyMappingTarget],
        list[CanonicalJobTaxonomyMappingCoverage],
    ]:
        if active_mapping is None:
            return [], [], []
        revision_id = active_mapping.mapping_revision_id
        mappings = (
            self.db.query(SourceJobTaxonomyMapping)
            .filter(SourceJobTaxonomyMapping.mapping_revision_id == revision_id)
            .order_by(SourceJobTaxonomyMapping.source_order)
            .all()
        )
        targets = (
            self.db.query(SourceJobTaxonomyMappingTarget)
            .filter(SourceJobTaxonomyMappingTarget.mapping_revision_id == revision_id)
            .order_by(
                SourceJobTaxonomyMappingTarget.mapping_id,
                SourceJobTaxonomyMappingTarget.source_order,
            )
            .all()
        )
        coverages = (
            self.db.query(CanonicalJobTaxonomyMappingCoverage)
            .filter(
                CanonicalJobTaxonomyMappingCoverage.mapping_revision_id == revision_id
            )
            .order_by(CanonicalJobTaxonomyMappingCoverage.source_site)
            .all()
        )
        return mappings, targets, coverages

    @staticmethod
    def _mapping_evidence(
        *,
        jobs: Sequence[Job],
        paths_by_job: Mapping[UUID, list[JobSourceClassificationPath]],
        mapping_rows: Sequence[SourceJobTaxonomyMapping],
        mapping_targets: Sequence[SourceJobTaxonomyMappingTarget],
        coverages: Sequence[CanonicalJobTaxonomyMappingCoverage],
    ) -> dict[str, object]:
        coverage_by_source = {
            coverage.source_site: {
                "source_catalog_revision_id": str(coverage.source_catalog_revision_id),
                "source_catalog_fingerprint": (coverage.source_catalog_fingerprint),
                "identity_set_hash": coverage.identity_set_hash,
                "identity_count": coverage.identity_count,
            }
            for coverage in coverages
        }
        mapping_by_identity = {
            (mapping.source_site, mapping.source_classification_id): mapping
            for mapping in mapping_rows
        }
        targets_by_mapping: dict[
            UUID, list[SourceJobTaxonomyMappingTarget]
        ] = defaultdict(list)
        for target in mapping_targets:
            targets_by_mapping[target.mapping_id].append(target)

        policy_counts = Counter(
            {
                "projected_path_jobs": 0,
                "missing_mapping_jobs": 0,
                "excluded_mapping_jobs": 0,
                "unmapped_mapping_jobs": 0,
                "conflicting_mapping_jobs": 0,
                "source_catalog_provenance_missing_jobs": 0,
                "source_catalog_provenance_mismatch_jobs": 0,
            }
        )
        for job in jobs:
            paths = paths_by_job.get(job.id, [])
            if not paths:
                continue
            policy_counts["projected_path_jobs"] += 1
            missing_mapping = False
            excluded = False
            unmapped = False
            provenance_missing = False
            provenance_mismatch = False
            deterministic_targets: set[UUID] = set()
            allowed_targets: set[UUID] = set()
            for path in paths:
                coverage = next(
                    (
                        item
                        for item in coverages
                        if item.source_site == path.source_site
                    ),
                    None,
                )
                if path.source_catalog_revision_id is None:
                    provenance_missing = True
                elif (
                    coverage is None
                    or path.source_catalog_revision_id
                    != coverage.source_catalog_revision_id
                ):
                    provenance_mismatch = True
                for node in path.nodes:
                    mapping = mapping_by_identity.get(
                        (path.source_site, node.source_classification_id)
                    )
                    if mapping is None:
                        missing_mapping = True
                        continue
                    if mapping.disposition == "excluded":
                        excluded = True
                    elif mapping.disposition == "unmapped":
                        unmapped = True
                    for target in targets_by_mapping.get(mapping.id, []):
                        if target.role == "deterministic":
                            deterministic_targets.add(target.subcategory_id)
                        elif target.role == "allowed":
                            allowed_targets.add(target.subcategory_id)
            conflict = len(deterministic_targets) > 1 or (
                len(deterministic_targets) == 1
                and bool(allowed_targets)
                and not deterministic_targets <= allowed_targets
            )
            for condition, key in (
                (missing_mapping, "missing_mapping_jobs"),
                (excluded, "excluded_mapping_jobs"),
                (unmapped, "unmapped_mapping_jobs"),
                (conflict, "conflicting_mapping_jobs"),
                (
                    provenance_missing,
                    "source_catalog_provenance_missing_jobs",
                ),
                (
                    provenance_mismatch,
                    "source_catalog_provenance_mismatch_jobs",
                ),
            ):
                if condition:
                    policy_counts[key] += 1

        return {
            "coverage_by_source": coverage_by_source,
            "disposition_counts": dict(
                Counter(mapping.disposition for mapping in mapping_rows)
            ),
            "target_count": len(mapping_targets),
            "job_policy": dict(policy_counts),
        }

    @staticmethod
    def _classifier_provenance(
        *,
        jobs: Sequence[Job],
        assignments_by_job: Mapping[UUID, JobTaxonomyAssignment],
        latest_reviews: Mapping[UUID, JobTaxonomyReviewItem],
    ) -> dict[str, int]:
        counts = Counter(
            {
                "classifier_hash_only_jobs": 0,
                "constrained_ai_missing_model_provenance_jobs": 0,
                "mapping_provenance_missing_jobs": 0,
                "raw_classifier_output_available_jobs": 0,
                "raw_classifier_output_unavailable_jobs": 0,
            }
        )
        for job in jobs:
            assignment = assignments_by_job.get(job.id)
            review = latest_reviews.get(job.id)
            evidence_refs = []
            if assignment is not None:
                evidence_refs.extend(assignment.source_evidence_refs)
                if assignment.method in {"reviewed_mapping", "constrained_ai"} and (
                    assignment.mapping_revision_id is None or not assignment.mapping_ids
                ):
                    counts["mapping_provenance_missing_jobs"] += 1
                if assignment.method == "constrained_ai" and not all(
                    (
                        assignment.model_provider,
                        assignment.model_name,
                        assignment.model_version,
                    )
                ):
                    counts["constrained_ai_missing_model_provenance_jobs"] += 1
            elif review is not None:
                evidence_refs.extend(review.evidence_refs)
                if review.status == "active" and review.mapping_revision_id is None:
                    counts["mapping_provenance_missing_jobs"] += 1

            has_classifier_hash = any(
                isinstance(reference, Mapping)
                and reference.get("kind") == "ai-classifier-output"
                and isinstance(reference.get("content_hash"), str)
                for reference in evidence_refs
            )
            raw_available = _has_raw_classifier_output(job.raw_data)
            classifier_relevant = (
                assignment is not None and assignment.method == "constrained_ai"
            ) or (
                review is not None
                and bool(set(review.reasons) & _CLASSIFIER_REVIEW_REASONS)
            )
            if raw_available:
                counts["raw_classifier_output_available_jobs"] += 1
            if has_classifier_hash and not raw_available:
                counts["classifier_hash_only_jobs"] += 1
            if classifier_relevant and not raw_available:
                counts["raw_classifier_output_unavailable_jobs"] += 1
        return dict(counts)

    @staticmethod
    def _legacy_comparison(
        jobs: Sequence[Job],
        *,
        assignments_by_job: Mapping[UUID, JobTaxonomyAssignment],
    ) -> dict[str, int]:
        counts = Counter(
            {
                "legacy_assigned_jobs": 0,
                "canonical_only_jobs": 0,
                "legacy_only_jobs": 0,
                "both_assigned_jobs": 0,
                "agreement_jobs": 0,
                "disagreement_jobs": 0,
                "neither_assigned_jobs": 0,
                "legacy_auto_created_jobs": 0,
                "legacy_fallback_jobs": 0,
            }
        )
        for job in jobs:
            assignment = assignments_by_job.get(job.id)
            legacy = job.subcategory
            if legacy is not None:
                counts["legacy_assigned_jobs"] += 1
                if legacy.is_auto_created:
                    counts["legacy_auto_created_jobs"] += 1
                legacy_path = (
                    legacy.category.domain.name,
                    legacy.category.name,
                    legacy.name,
                )
                if any(label in {"General", "Unknown"} for label in legacy_path):
                    counts["legacy_fallback_jobs"] += 1
            else:
                legacy_path = None

            if assignment is not None and legacy_path is not None:
                counts["both_assigned_jobs"] += 1
                breadcrumb = assignment.breadcrumb
                canonical_path = tuple(
                    str((breadcrumb.get(level) or {}).get("label") or "")
                    for level in ("domain", "category", "subcategory")
                )
                if canonical_path == legacy_path:
                    counts["agreement_jobs"] += 1
                else:
                    counts["disagreement_jobs"] += 1
            elif assignment is not None:
                counts["canonical_only_jobs"] += 1
            elif legacy_path is not None:
                counts["legacy_only_jobs"] += 1
            else:
                counts["neither_assigned_jobs"] += 1
        return dict(counts)


def _has_raw_classifier_output(raw_data: object) -> bool:
    if not isinstance(raw_data, Mapping):
        return False
    if isinstance(raw_data.get("canonical_classifier_output"), Mapping):
        return True
    if isinstance(raw_data.get("ai_classifier_output"), Mapping):
        return True
    enrichment = raw_data.get("ai_enrichment")
    return isinstance(enrichment, Mapping) and isinstance(
        enrichment.get("classification"),
        Mapping,
    )


def _sorted_counts(value: Mapping[str, int]) -> dict[str, int]:
    return {key: int(value[key]) for key in sorted(value)}


def _sorted_payload(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _sorted_payload(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        return [_sorted_payload(item) for item in value]
    return value
