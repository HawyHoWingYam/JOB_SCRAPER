from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.job_intelligence.canonical_taxonomy.breadcrumbs import canonical_breadcrumb
from app.job_intelligence.foundation import (
    DecisionCommand,
    DecisionEffect,
    DecisionResult,
    GovernanceUnitOfWork,
    OutboxEvent,
    normalized_content_hash,
)
from app.models.canonical_job_taxonomy import (
    CanonicalJobSubcategory,
    CanonicalJobTaxonomyActiveRevision,
    JobTaxonomyAssignment,
    JobTaxonomyReviewItem,
)
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.utils.time import utc_now


class CanonicalTaxonomyDecisionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CanonicalTaxonomyDecisionAdapter:
    """Trusted-local adapter for human Job Taxonomy Review Item decisions."""

    def __init__(
        self,
        db: Session,
        *,
        outbox_repository: EventOutboxRepository | None = None,
    ) -> None:
        self.db = db
        self.outbox_repository = outbox_repository or EventOutboxRepository()

    def decide(self, command: DecisionCommand) -> DecisionResult:
        return GovernanceUnitOfWork(
            self.db,
            outbox_repository=self.outbox_repository,
        ).execute(command, _JobTaxonomyReviewTransition())


class _JobTaxonomyReviewTransition:
    domain = "job-taxonomy"
    subject_type = "job-taxonomy-review-item"

    def load_for_update(
        self,
        db: Session,
        subject_id: str,
    ) -> JobTaxonomyReviewItem | None:
        try:
            review_id = UUID(subject_id)
        except (TypeError, ValueError):
            return None
        return (
            db.query(JobTaxonomyReviewItem)
            .filter(JobTaxonomyReviewItem.id == review_id)
            .with_for_update()
            .one_or_none()
        )

    @staticmethod
    def version(subject: JobTaxonomyReviewItem) -> int:
        return subject.lock_version

    @staticmethod
    def snapshot(subject: JobTaxonomyReviewItem) -> dict[str, object]:
        return {
            "id": str(subject.id),
            "job_id": str(subject.job_id),
            "status": subject.status,
            "reasons": list(subject.reasons),
            "assignment_id": (
                str(subject.assignment_id)
                if subject.assignment_id is not None
                else None
            ),
            "version": subject.lock_version,
        }

    def apply(
        self,
        db: Session,
        subject: JobTaxonomyReviewItem,
        command: DecisionCommand,
    ) -> DecisionEffect:
        if subject.status != "active":
            raise CanonicalTaxonomyDecisionError(
                "JOB_TAXONOMY_REVIEW_NOT_ACTIVE",
                "Only an active Job Taxonomy Review Item can be decided",
            )
        current_assignment = (
            db.query(JobTaxonomyAssignment)
            .filter(
                JobTaxonomyAssignment.job_id == subject.job_id,
                JobTaxonomyAssignment.is_current.is_(True),
            )
            .with_for_update()
            .one_or_none()
        )
        if current_assignment is not None:
            raise CanonicalTaxonomyDecisionError(
                "JOB_TAXONOMY_CURRENT_ASSIGNMENT_EXISTS",
                "An active review cannot overwrite a current assignment",
            )
        if command.action == "mark_insufficient_evidence":
            if command.target_id is not None:
                raise CanonicalTaxonomyDecisionError(
                    "JOB_TAXONOMY_DECISION_TARGET_FORBIDDEN",
                    "mark_insufficient_evidence does not accept a target",
                )
            version = subject.lock_version + 1
            subject.status = "insufficient_evidence"
            subject.lock_version = version
            subject.resolved_at = utc_now()
            projection = {
                "job_id": str(subject.job_id),
                "state": "unassigned",
                "review_item_id": str(subject.id),
                "taxonomy_revision_id": str(subject.taxonomy_revision_id),
                "version": version,
                "reasons": ["insufficient_evidence"],
            }
            return DecisionEffect(
                subject=self.snapshot(subject),
                resulting_projection=projection,
                version=version,
                evidence_refs=tuple(dict(item) for item in subject.evidence_refs),
                outbox_events=(
                    OutboxEvent(
                        topic="job-intelligence-projections",
                        aggregate_type="job",
                        aggregate_id=str(subject.job_id),
                        event_type="job.canonical_taxonomy_decided",
                        source_service="canonical-job-taxonomy",
                        payload={
                            **projection,
                            "invalidate": [
                                "canonical-taxonomy-read-model",
                                "job-embedding",
                            ],
                        },
                    ),
                ),
            )
        if command.action != "assign_existing_subcategory":
            raise CanonicalTaxonomyDecisionError(
                "JOB_TAXONOMY_DECISION_ACTION_INVALID",
                f"Unsupported Job Taxonomy decision action {command.action!r}",
            )
        target_id = _required_uuid(command.target_id)
        active_taxonomy = db.get(
            CanonicalJobTaxonomyActiveRevision,
            "canonical-job-taxonomy",
        )
        if active_taxonomy is None:
            raise CanonicalTaxonomyDecisionError(
                "JOB_TAXONOMY_ACTIVE_REVISION_MISSING",
                "Canonical Job Taxonomy has no active revision",
            )
        target = (
            db.query(CanonicalJobSubcategory)
            .filter(
                CanonicalJobSubcategory.id == target_id,
                CanonicalJobSubcategory.revision_id == active_taxonomy.revision_id,
                CanonicalJobSubcategory.is_assignable.is_(True),
            )
            .one_or_none()
        )
        if target is None:
            raise CanonicalTaxonomyDecisionError(
                "JOB_TAXONOMY_DECISION_TARGET_INVALID",
                "Operator target must be assignable in the active taxonomy revision",
            )
        version = subject.lock_version + 1
        assignment_id = uuid4()
        assignment = JobTaxonomyAssignment(
            id=assignment_id,
            job_id=subject.job_id,
            taxonomy_revision_id=active_taxonomy.revision_id,
            subcategory_id=target.id,
            mapping_revision_id=None,
            method="operator",
            evidence_hash=normalized_content_hash(
                {
                    "review_evidence_hash": subject.evidence_hash,
                    "action": command.action,
                    "target_id": str(target.id),
                    "note": command.note,
                }
            ),
            source_evidence_refs=list(subject.evidence_refs),
            mapping_ids=[],
            model_provider=None,
            model_name=None,
            model_version=None,
            breadcrumb=canonical_breadcrumb(
                db,
                target.id,
                taxonomy_revision_id=active_taxonomy.revision_id,
            ),
            lock_version=version,
            is_current=True,
            captured_at=utc_now(),
        )
        db.add(assignment)
        subject.status = "assigned"
        subject.assignment_id = assignment_id
        subject.lock_version = version
        subject.resolved_at = utc_now()
        projection = {
            "job_id": str(subject.job_id),
            "state": "assigned",
            "assignment_id": str(assignment_id),
            "taxonomy_revision_id": str(active_taxonomy.revision_id),
            "version": version,
        }
        return DecisionEffect(
            subject=self.snapshot(subject),
            resulting_projection=projection,
            version=version,
            evidence_refs=tuple(dict(item) for item in subject.evidence_refs),
            outbox_events=(
                OutboxEvent(
                    topic="job-intelligence-projections",
                    aggregate_type="job",
                    aggregate_id=str(subject.job_id),
                    event_type="job.canonical_taxonomy_decided",
                    source_service="canonical-job-taxonomy",
                    payload={
                        **projection,
                        "review_item_id": str(subject.id),
                        "invalidate": [
                            "canonical-taxonomy-read-model",
                            "job-embedding",
                        ],
                    },
                ),
            ),
        )

    @staticmethod
    def attach_audit_reference(
        _db: Session,
        subject: JobTaxonomyReviewItem,
        audit_event_id: UUID,
    ) -> None:
        subject.decision_audit_id = audit_event_id


def _required_uuid(value: str | None) -> UUID:
    if value is None:
        raise CanonicalTaxonomyDecisionError(
            "JOB_TAXONOMY_DECISION_TARGET_REQUIRED",
            "assign_existing_subcategory requires a target",
        )
    try:
        return UUID(value)
    except (TypeError, ValueError) as exc:
        raise CanonicalTaxonomyDecisionError(
            "JOB_TAXONOMY_DECISION_TARGET_INVALID",
            "Job Taxonomy decision target must be a UUID",
        ) from exc
