from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable
from uuid import UUID

from sqlalchemy import and_, func
from sqlalchemy.orm import Session, joinedload

from app.ai.llm_client import LLMUpstreamError
from app.job_intelligence.foundation import normalized_content_hash
from app.models.canonical_job_taxonomy import (
    CanonicalJobTaxonomyActiveMappingRevision,
    CanonicalJobTaxonomyActiveRevision,
    CanonicalJobTaxonomyMappingRevision,
    CanonicalJobTaxonomyRelease,
    JobTaxonomyAssignment,
    JobTaxonomyReviewItem,
)
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.governance import GovernanceAuditEvent, GovernanceIdempotencyRecord
from app.models.job import Job
from app.models.source_job_attributes import (
    JobSourceClassificationPath,
    JobSourceClassificationPathNode,
)
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.services.ai_enrichment_service import (
    AIEnrichmentService,
    get_ai_enrichment_service,
)
from app.services.enrichment_run_service import EnrichmentRunService


RECOVERY_SOURCE_TYPE = "canonical_taxonomy_recovery"
RECOVERY_REASONS = (
    "classifier_output_invalid",
    "classifier_provenance_missing",
)
RECOVERY_MAX_SCOPE = 50_000
RECOVERY_SAMPLE_SIZE = 20


class CanonicalTaxonomyRecoveryError(ValueError):
    code = "CANONICAL_TAXONOMY_RECOVERY_INVALID"


class CanonicalTaxonomyRecoveryScopeChanged(CanonicalTaxonomyRecoveryError):
    code = "CANONICAL_TAXONOMY_RECOVERY_SCOPE_CHANGED"


class CanonicalTaxonomyRecoveryRunAbort(CanonicalTaxonomyRecoveryError):
    code = "CANONICAL_TAXONOMY_RECOVERY_DRIFT"
    abort_run = True


class CanonicalTaxonomyRecoveryNoItems(CanonicalTaxonomyRecoveryError):
    code = "CANONICAL_TAXONOMY_RECOVERY_NO_ITEMS"


@dataclass(frozen=True)
class CanonicalTaxonomyRecoveryScope:
    source_sites: tuple[str, ...] = ()
    source_classification_ids: tuple[str, ...] = ()
    source_subclassification_ids: tuple[str, ...] = ()
    posted_date_from: date | None = None
    posted_date_to: date | None = None
    job_ids: tuple[UUID, ...] = ()
    reason_codes: tuple[str, ...] = RECOVERY_REASONS
    pending_limit: int = RECOVERY_MAX_SCOPE

    def to_payload(self) -> dict[str, object]:
        return {
            "source_sites": list(self.source_sites),
            "source_classification_ids": list(self.source_classification_ids),
            "source_subclassification_ids": list(self.source_subclassification_ids),
            "posted_date_from": (
                self.posted_date_from.isoformat()
                if self.posted_date_from is not None
                else None
            ),
            "posted_date_to": (
                self.posted_date_to.isoformat()
                if self.posted_date_to is not None
                else None
            ),
            "job_ids": [str(job_id) for job_id in self.job_ids],
            "reason_codes": list(self.reason_codes),
            "pending_limit": self.pending_limit,
        }


@dataclass(frozen=True)
class CanonicalTaxonomyRecoveryPreview:
    taxonomy_revision: dict[str, object]
    mapping_revision: dict[str, object]
    scope_fingerprint: str
    selected_job_ids: tuple[UUID, ...]
    selected_review_ids: tuple[UUID, ...]
    counts_by_reason: dict[str, int]
    sample: tuple[dict[str, object], ...]

    @property
    def selected_count(self) -> int:
        return len(self.selected_job_ids)

    def to_payload(self) -> dict[str, object]:
        return {
            "taxonomy_revision": dict(self.taxonomy_revision),
            "mapping_revision": dict(self.mapping_revision),
            "scope_fingerprint": self.scope_fingerprint,
            "selected_count": self.selected_count,
            "selected_job_ids": [str(job_id) for job_id in self.selected_job_ids],
            "counts_by_reason": dict(self.counts_by_reason),
            "sample": [dict(item) for item in self.sample],
            "allowed_reasons": list(RECOVERY_REASONS),
        }


def _normalized_values(values: Iterable[object], *, lowercase: bool = False) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if lowercase:
            text = text.lower()
        if text and text not in seen:
            normalized.append(text)
            seen.add(text)
    return tuple(normalized)


class CanonicalTaxonomyRecoveryService:
    """Preview and execute bounded, Canonical-only historical recovery."""

    def __init__(
        self,
        db: Session,
        *,
        enrichment_service: AIEnrichmentService | None = None,
    ) -> None:
        self.db = db
        self.enrichment_service = enrichment_service or get_ai_enrichment_service()
        self.outbox_repository = EventOutboxRepository()

    @staticmethod
    def validate_scope(scope: CanonicalTaxonomyRecoveryScope) -> None:
        unknown = set(scope.reason_codes) - set(RECOVERY_REASONS)
        if unknown:
            raise CanonicalTaxonomyRecoveryError(
                "Only classifier output/provenance recovery is supported: "
                + ", ".join(sorted(unknown))
            )
        if not 1 <= int(scope.pending_limit) <= RECOVERY_MAX_SCOPE:
            raise CanonicalTaxonomyRecoveryError(
                f"Recovery scope limit must be between 1 and {RECOVERY_MAX_SCOPE}"
            )
        if (
            scope.posted_date_from is not None
            and scope.posted_date_to is not None
            and scope.posted_date_from > scope.posted_date_to
        ):
            raise CanonicalTaxonomyRecoveryError(
                "posted_date_from must be on or before posted_date_to"
            )

    def _active_revision_snapshot(self) -> tuple[dict[str, object], dict[str, object]]:
        taxonomy_active = self.db.get(
            CanonicalJobTaxonomyActiveRevision,
            "canonical-job-taxonomy",
        )
        mapping_active = self.db.get(
            CanonicalJobTaxonomyActiveMappingRevision,
            "canonical-job-taxonomy-mapping",
        )
        taxonomy_release = (
            self.db.get(CanonicalJobTaxonomyRelease, taxonomy_active.revision_id)
            if taxonomy_active is not None
            else None
        )
        mapping_release = (
            self.db.get(
                CanonicalJobTaxonomyMappingRevision,
                mapping_active.mapping_revision_id,
            )
            if mapping_active is not None
            else None
        )
        if (
            taxonomy_active is None
            or mapping_active is None
            or taxonomy_release is None
            or taxonomy_release.status != "ready"
            or mapping_release is None
            or mapping_release.status != "ready"
            or mapping_active.taxonomy_revision_id != taxonomy_active.revision_id
        ):
            raise CanonicalTaxonomyRecoveryError(
                "Active Canonical Taxonomy and Source Mapping must both be ready"
            )
        taxonomy = {
            "id": str(taxonomy_active.revision_id),
            "content_hash": taxonomy_active.content_hash,
            "lock_version": int(taxonomy_active.lock_version),
        }
        mapping = {
            "id": str(mapping_active.mapping_revision_id),
            "content_hash": mapping_active.content_hash,
            "lock_version": int(mapping_active.lock_version),
        }
        return taxonomy, mapping

    def _query_scope_rows(
        self,
        scope: CanonicalTaxonomyRecoveryScope,
    ) -> list[tuple[JobTaxonomyReviewItem, Job]]:
        query = (
            self.db.query(JobTaxonomyReviewItem, Job)
            .join(Job, Job.id == JobTaxonomyReviewItem.job_id)
            .options(joinedload(Job.company))
            .filter(
                JobTaxonomyReviewItem.status == "active",
                Job.is_deleted.is_(False),
            )
        )
        if scope.job_ids:
            query = query.filter(Job.id.in_(scope.job_ids))
        if scope.source_sites:
            query = query.filter(func.lower(Job.source_site).in_(scope.source_sites))
        if scope.source_classification_ids:
            query = query.filter(
                Job.source_classification_paths.any(
                    JobSourceClassificationPath.nodes.any(
                        and_(
                            JobSourceClassificationPathNode.source_position == 0,
                            JobSourceClassificationPathNode.source_classification_id.in_(
                                scope.source_classification_ids
                            ),
                        )
                    )
                )
            )
        if scope.source_subclassification_ids:
            query = query.filter(
                Job.source_classification_paths.any(
                    JobSourceClassificationPath.nodes.any(
                        and_(
                            JobSourceClassificationPathNode.source_position > 0,
                            JobSourceClassificationPathNode.source_classification_id.in_(
                                scope.source_subclassification_ids
                            ),
                        )
                    )
                )
            )
        if scope.posted_date_from is not None:
            query = query.filter(func.date(Job.posted_date) >= scope.posted_date_from)
        if scope.posted_date_to is not None:
            query = query.filter(func.date(Job.posted_date) <= scope.posted_date_to)

        rows = query.order_by(
            JobTaxonomyReviewItem.created_at.asc(),
            JobTaxonomyReviewItem.id.asc(),
        ).all()
        wanted = set(scope.reason_codes)
        selected: list[tuple[JobTaxonomyReviewItem, Job]] = []
        # When the AI handoff carries the exact bounded Job list, that list is
        # the authority. ``pending_limit`` is the legacy per-run UI limit and
        # must not silently truncate a confirmed 17k-item recovery batch.
        selection_limit = RECOVERY_MAX_SCOPE if scope.job_ids else scope.pending_limit
        for review, job in rows:
            reasons = set(str(reason) for reason in (review.reasons or []))
            if not reasons.intersection(wanted):
                continue
            selected.append((review, job))
            if len(selected) >= selection_limit:
                break
        return selected

    def preview(
        self,
        scope: CanonicalTaxonomyRecoveryScope,
    ) -> CanonicalTaxonomyRecoveryPreview:
        self.validate_scope(scope)
        taxonomy, mapping = self._active_revision_snapshot()
        rows = self._query_scope_rows(scope)
        selected_job_ids = tuple(job.id for _review, job in rows)
        selected_review_ids = tuple(review.id for review, _job in rows)
        identities = [
            {
                "review_id": str(review.id),
                "job_id": str(job.id),
                "reasons": list(review.reasons or []),
                "evidence_hash": review.evidence_hash,
                "updated_at": review.updated_at.isoformat()
                if review.updated_at is not None
                else None,
            }
            for review, job in rows
        ]
        fingerprint = normalized_content_hash(
            {
                "scope": scope.to_payload(),
                "taxonomy_revision": taxonomy,
                "mapping_revision": mapping,
                "selected": identities,
            }
        )
        counts = {reason: 0 for reason in scope.reason_codes}
        sample: list[dict[str, object]] = []
        for review, job in rows:
            reasons = [
                reason
                for reason in review.reasons or []
                if reason in scope.reason_codes
            ]
            for reason in reasons:
                counts[reason] = counts.get(reason, 0) + 1
            if len(sample) < RECOVERY_SAMPLE_SIZE:
                sample.append(
                    {
                        "job_id": str(job.id),
                        "title": job.title,
                        "company_name": job.company_name,
                        "reasons": reasons,
                    }
                )
        return CanonicalTaxonomyRecoveryPreview(
            taxonomy_revision=taxonomy,
            mapping_revision=mapping,
            scope_fingerprint=fingerprint,
            selected_job_ids=selected_job_ids,
            selected_review_ids=selected_review_ids,
            counts_by_reason=counts,
            sample=tuple(sample),
        )

    def create_run(
        self,
        scope: CanonicalTaxonomyRecoveryScope,
        *,
        expected_scope_fingerprint: str,
        expected_taxonomy_revision_id: UUID,
        expected_mapping_revision_id: UUID,
        confirmed: bool,
    ) -> EnrichmentRun:
        if not confirmed:
            raise CanonicalTaxonomyRecoveryError(
                "Canonical Taxonomy recovery requires explicit confirmation"
            )
        preview = self.preview(scope)
        if (
            preview.scope_fingerprint != expected_scope_fingerprint
            or preview.taxonomy_revision["id"] != str(expected_taxonomy_revision_id)
            or preview.mapping_revision["id"] != str(expected_mapping_revision_id)
        ):
            raise CanonicalTaxonomyRecoveryScopeChanged(
                "The taxonomy, mapping, or selected Job scope changed; preview again"
            )
        if not preview.selected_job_ids:
            raise CanonicalTaxonomyRecoveryNoItems(
                "No active Review items match the approved classifier recovery reasons"
            )

        EnrichmentRunService(self.db)._require_active_slot()
        snapshot = {
            "scope": scope.to_payload(),
            "scope_fingerprint": preview.scope_fingerprint,
            "taxonomy_revision": dict(preview.taxonomy_revision),
            "mapping_revision": dict(preview.mapping_revision),
            "review_ids": [str(review_id) for review_id in preview.selected_review_ids],
            "reason_codes": list(scope.reason_codes),
        }
        return EnrichmentRunService(self.db)._create_run(
            source_type=RECOVERY_SOURCE_TYPE,
            job_ids=[str(job_id) for job_id in preview.selected_job_ids],
            run_snapshot=snapshot,
        )

    def create_retry_run(self, run_id: str) -> EnrichmentRun:
        source_run = self.db.get(EnrichmentRun, run_id)
        if source_run is None:
            raise CanonicalTaxonomyRecoveryError("Recovery run not found")
        if source_run.source_type != RECOVERY_SOURCE_TYPE:
            raise CanonicalTaxonomyRecoveryError(
                "Only Canonical Taxonomy recovery runs support upstream retry"
            )
        failed_items = (
            self.db.query(EnrichmentRunItem)
            .filter(
                EnrichmentRunItem.run_id == run_id,
                EnrichmentRunItem.status == "failed",
                EnrichmentRunItem.error_code == "ai_upstream_failed",
            )
            .order_by(EnrichmentRunItem.position.asc())
            .all()
        )
        if not failed_items:
            raise CanonicalTaxonomyRecoveryNoItems(
                "This recovery run has no retryable AI upstream failures"
            )
        snapshot = dict(source_run.run_snapshot or {})
        current_taxonomy, current_mapping = self._active_revision_snapshot()
        if (
            snapshot.get("taxonomy_revision") != current_taxonomy
            or snapshot.get("mapping_revision") != current_mapping
        ):
            raise CanonicalTaxonomyRecoveryScopeChanged(
                "The active taxonomy or mapping changed; create a fresh preview"
            )
        snapshot["retry_of_run_id"] = source_run.id
        snapshot["retry_item_ids"] = [str(item.id) for item in failed_items]
        EnrichmentRunService(self.db)._require_active_slot()
        return EnrichmentRunService(self.db)._create_run(
            source_type=RECOVERY_SOURCE_TYPE,
            job_ids=[str(item.job_id) for item in failed_items],
            run_snapshot=snapshot,
        )

    def _assert_run_revisions(self, run: EnrichmentRun) -> dict[str, object]:
        snapshot = dict(run.run_snapshot or {})
        expected_taxonomy = snapshot.get("taxonomy_revision")
        expected_mapping = snapshot.get("mapping_revision")
        current_taxonomy, current_mapping = self._active_revision_snapshot()
        if expected_taxonomy != current_taxonomy or expected_mapping != current_mapping:
            raise CanonicalTaxonomyRecoveryRunAbort(
                "Active taxonomy or mapping changed while recovery was running"
            )
        return snapshot

    @staticmethod
    def _state_summary(db: Session, job_id: UUID) -> dict[str, object]:
        assignment = (
            db.query(JobTaxonomyAssignment)
            .filter(
                JobTaxonomyAssignment.job_id == job_id,
                JobTaxonomyAssignment.is_current.is_(True),
            )
            .one_or_none()
        )
        review = (
            db.query(JobTaxonomyReviewItem)
            .filter(
                JobTaxonomyReviewItem.job_id == job_id,
                JobTaxonomyReviewItem.status == "active",
            )
            .one_or_none()
        )
        return {
            "job_id": str(job_id),
            "assignment_id": str(assignment.id) if assignment is not None else None,
            "review_id": str(review.id) if review is not None else None,
            "review_status": review.status if review is not None else None,
            "review_reasons": list(review.reasons or []) if review is not None else [],
        }

    def _record_recovery_audit(
        self,
        *,
        run: EnrichmentRun,
        job_id: UUID,
        before: dict[str, object],
        after: dict[str, object],
        reasons: list[str],
    ) -> None:
        key = f"canonical-taxonomy-recovery:{run.id}:{job_id}"
        command = {
            "run_id": run.id,
            "job_id": str(job_id),
            "scope_fingerprint": (run.run_snapshot or {}).get("scope_fingerprint"),
            "taxonomy_revision": (run.run_snapshot or {}).get("taxonomy_revision"),
            "mapping_revision": (run.run_snapshot or {}).get("mapping_revision"),
        }
        command_hash = normalized_content_hash(command)
        existing = (
            self.db.query(GovernanceIdempotencyRecord)
            .filter(
                GovernanceIdempotencyRecord.domain == "job-taxonomy",
                GovernanceIdempotencyRecord.idempotency_key == key,
            )
            .one_or_none()
        )
        if existing is not None:
            return
        subject_id = str(
            after.get("review_id") or before.get("review_id") or job_id
        )
        audit = GovernanceAuditEvent(
            domain="job-taxonomy",
            subject_type="job-taxonomy-review-item",
            subject_id=subject_id,
            action="canonical_taxonomy_recovery",
            actor="local-operator",
            command_hash=command_hash,
            idempotency_key=key,
            before_summary=before,
            after_summary=after,
            evidence_refs=[
                {
                    "kind": "canonical-taxonomy-recovery",
                    "run_id": run.id,
                    "job_id": str(job_id),
                    "reasons": reasons,
                }
            ],
            correlation_id=run.id,
        )
        self.db.add(audit)
        self.db.flush()
        self.db.add(
            GovernanceIdempotencyRecord(
                domain="job-taxonomy",
                idempotency_key=key,
                command_hash=command_hash,
                audit_event_id=audit.id,
                result_payload={
                    "audit_event_id": str(audit.id),
                    "job_id": str(job_id),
                    "reasons": reasons,
                },
            )
        )
        self.outbox_repository.enqueue(
            self.db,
            topic="job-intelligence-projections",
            aggregate_type="job",
            aggregate_id=str(job_id),
            event_type="job.canonical_taxonomy_recovery_completed",
            source_service="canonical-taxonomy-recovery",
            payload={
                "run_id": run.id,
                "job_id": str(job_id),
                "governance_audit_event_id": str(audit.id),
                "governance_idempotency_key": key,
                "reasons": reasons,
            },
            auto_commit=False,
        )
        self.db.flush()

    async def process_job(
        self,
        run_id: str,
        job: Job,
        db: Session,
    ) -> dict[str, object]:
        run = db.get(EnrichmentRun, run_id)
        if run is None:
            raise CanonicalTaxonomyRecoveryRunAbort("Recovery run disappeared")
        self._assert_run_revisions(run)
        before = self._state_summary(db, job.id)
        key = f"canonical-taxonomy-recovery:{run.id}:{job.id}"
        if (
            db.query(GovernanceIdempotencyRecord)
            .filter(
                GovernanceIdempotencyRecord.domain == "job-taxonomy",
                GovernanceIdempotencyRecord.idempotency_key == key,
            )
            .one_or_none()
            is not None
        ):
            return {"status": "success", "recovery_outcome": "replayed"}

        try:
            result = await self.enrichment_service.classify_job_taxonomy(job, db)
        except LLMUpstreamError:
            db.rollback()
            return {
                "status": "error",
                "error_code": "ai_upstream_failed",
                "error": "ai_upstream_failed",
            }
        except ValueError:
            db.rollback()
            run = db.get(EnrichmentRun, run_id)
            if run is None:
                raise CanonicalTaxonomyRecoveryRunAbort(
                    "Recovery run disappeared after source evidence failure"
                )
            reasons = ["source_classification_paths_missing"]
            after = self._state_summary(db, job.id)
            self._record_recovery_audit(
                run=run,
                job_id=job.id,
                before=before,
                after=after,
                reasons=reasons,
            )
            return {
                "status": "success",
                "recovery_outcome": "unresolved",
                "error_code": "review_remains_active",
                "error": "Review remains active: source evidence needs repair",
            }

        evaluation = result.get("evaluation")
        if evaluation is not None:
            outcome = evaluation.state
            reasons = list(evaluation.reasons)
        else:
            outcome = "unresolved"
            reasons = list(result.get("unresolved_reasons") or [])
        after = self._state_summary(db, job.id)
        self._record_recovery_audit(
            run=run,
            job_id=job.id,
            before=before,
            after=after,
            reasons=reasons,
        )
        return {
            "status": "success",
            "recovery_outcome": outcome,
            "error_code": "review_remains_active" if outcome != "assigned" else None,
            "error": (
                "Review remains active: " + ", ".join(reasons)
                if outcome != "assigned" and reasons
                else None
            ),
        }
