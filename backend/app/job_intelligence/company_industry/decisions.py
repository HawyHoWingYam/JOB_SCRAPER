from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.job_intelligence.company_industry.contracts import CompanyIndustryEvidence
from app.job_intelligence.company_industry.read_model import CompanyIndustry
from app.job_intelligence.foundation import (
    DecisionCommand,
    DecisionEffect,
    DecisionResult,
    GovernanceUnitOfWork,
    OutboxEvent,
    Provenance,
)
from app.models.company_industry import (
    CompanyIndustryActiveRevision,
    CompanyIndustryReviewItem,
    CompanyIndustryTaxonomyNode,
    SourceIndustryMapping,
)
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.utils.time import utc_now


class CompanyIndustryDecisionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CompanyIndustryDecisionAdapter:
    """Trusted-local adapter for Company Industry Review Item decisions."""

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
        ).execute(command, _CompanyIndustryReviewTransition())


class _CompanyIndustryReviewTransition:
    domain = "company-industry"
    subject_type = "company-industry-review-item"

    def load_for_update(
        self,
        db: Session,
        subject_id: str,
    ) -> CompanyIndustryReviewItem | None:
        try:
            review_id = UUID(subject_id)
        except (TypeError, ValueError):
            return None
        return (
            db.query(CompanyIndustryReviewItem)
            .filter(CompanyIndustryReviewItem.id == review_id)
            .with_for_update()
            .one_or_none()
        )

    @staticmethod
    def version(subject: CompanyIndustryReviewItem) -> int:
        return subject.lock_version

    @staticmethod
    def snapshot(subject: CompanyIndustryReviewItem) -> dict[str, object]:
        return {
            "id": str(subject.id),
            "company_id": str(subject.company_id),
            "status": subject.status,
            "reason": subject.reason,
            "assignment_id": (
                str(subject.assignment_id)
                if subject.assignment_id is not None
                else None
            ),
            "mapping_id": (
                str(subject.mapping_id) if subject.mapping_id is not None else None
            ),
            "version": subject.lock_version,
        }

    def _target(
        self,
        db: Session,
        target_id: str | None,
    ) -> CompanyIndustryTaxonomyNode:
        try:
            node_id = UUID(str(target_id))
        except (TypeError, ValueError):
            raise CompanyIndustryDecisionError(
                "COMPANY_INDUSTRY_DECISION_TARGET_REQUIRED",
                "A governed Company Industry target is required",
            ) from None
        active = db.get(CompanyIndustryActiveRevision, "company-industry")
        node = db.get(CompanyIndustryTaxonomyNode, node_id)
        if active is None or node is None or node.revision_id != active.revision_id:
            raise CompanyIndustryDecisionError(
                "COMPANY_INDUSTRY_DECISION_TARGET_INVALID",
                "The target must belong to the active Company Industry revision",
            )
        return node

    def apply(
        self,
        db: Session,
        subject: CompanyIndustryReviewItem,
        command: DecisionCommand,
    ) -> DecisionEffect:
        if subject.status != "active":
            raise CompanyIndustryDecisionError(
                "COMPANY_INDUSTRY_REVIEW_NOT_ACTIVE",
                "Only an active Company Industry Review Item can be decided",
            )
        terminal_actions = {
            "mark_insufficient_evidence": "insufficient_evidence",
            "mark_not_company_industry": "not_company_industry",
        }
        if command.action in terminal_actions:
            if command.target_id is not None:
                raise CompanyIndustryDecisionError(
                    "COMPANY_INDUSTRY_DECISION_TARGET_FORBIDDEN",
                    f"{command.action} does not accept a target",
                )
            subject.status = terminal_actions[command.action]
            subject.reason = (
                "not_company_industry"
                if command.action == "mark_not_company_industry"
                else subject.reason
            )
            subject.lock_version += 1
            subject.resolved_at = utc_now()
            projection = {
                "company_id": str(subject.company_id),
                "state": "unassigned",
                "review_item_id": str(subject.id),
                "version": subject.lock_version,
            }
            return self._effect(subject, projection)

        assign_actions = {
            "assign_existing_industry": (False, False),
            "assign_existing_primary_industry": (False, True),
            "approve_mapping_and_assign": (True, False),
            "approve_mapping_and_assign_primary": (True, True),
        }
        if command.action not in assign_actions:
            raise CompanyIndustryDecisionError(
                "COMPANY_INDUSTRY_DECISION_ACTION_INVALID",
                f"Unsupported Company Industry decision action {command.action!r}",
            )
        approve_mapping, make_primary = assign_actions[command.action]
        target = self._target(db, command.target_id)
        mapping: SourceIndustryMapping | None = None
        if approve_mapping:
            if not all(
                (
                    subject.source_site,
                    subject.key_kind,
                    subject.raw_value,
                    subject.normalized_key,
                )
            ):
                raise CompanyIndustryDecisionError(
                    "COMPANY_INDUSTRY_MAPPING_EVIDENCE_REQUIRED",
                    "A reusable mapping requires Source code or label evidence",
                )
            existing = (
                db.query(SourceIndustryMapping)
                .filter(
                    SourceIndustryMapping.source_site == subject.source_site,
                    SourceIndustryMapping.key_kind == subject.key_kind,
                    SourceIndustryMapping.normalized_key == subject.normalized_key,
                    SourceIndustryMapping.status == "active",
                )
                .with_for_update()
                .one_or_none()
            )
            if existing is not None and existing.target_node_id != target.id:
                raise CompanyIndustryDecisionError(
                    "COMPANY_INDUSTRY_MAPPING_CONFLICT",
                    "An active Source Industry mapping already targets another node",
                )
            mapping = existing or SourceIndustryMapping(
                source_site=subject.source_site,
                key_kind=subject.key_kind,
                raw_value=subject.raw_value,
                normalized_key=subject.normalized_key,
                taxonomy_revision_id=target.revision_id,
                target_node_id=target.id,
                status="active",
                lock_version=1,
                approved_by="local-operator",
                approved_at=utc_now(),
            )
            if existing is None:
                db.add(mapping)
                db.flush()

        evidence = CompanyIndustryEvidence(
            evidence_kind="source_industry" if subject.source_site else "manual",
            source_site=subject.source_site,
            raw_code=(subject.raw_value if subject.key_kind == "code" else None),
            raw_label=(subject.raw_value if subject.key_kind == "label" else None),
            provenance=Provenance(
                method="operator",
                source_site=subject.source_site,
                evidence_refs=tuple(dict(item) for item in _evidence_refs(subject)),
                captured_at=utc_now(),
                mapping_id=str(mapping.id) if mapping is not None else None,
            ),
        )
        assignment, _changed = CompanyIndustry(db)._create_assignment(
            company_id=subject.company_id,
            node=target,
            evidence=evidence,
            evidence_hash=subject.evidence_hash,
            method="operator",
            mapping=mapping,
            primary_basis="operator" if make_primary else None,
            emit_event=False,
        )
        subject.status = "assigned"
        subject.assignment_id = assignment.id
        subject.mapping_id = mapping.id if mapping is not None else None
        subject.lock_version += 1
        subject.resolved_at = utc_now()
        projection = {
            "company_id": str(subject.company_id),
            "state": "assigned",
            "review_item_id": str(subject.id),
            "assignment_id": str(assignment.id),
            "mapping_id": str(mapping.id) if mapping is not None else None,
            "taxonomy_revision_id": str(target.revision_id),
            "node_id": str(target.id),
            "version": subject.lock_version,
        }
        return self._effect(subject, projection)

    def _effect(
        self,
        subject: CompanyIndustryReviewItem,
        projection: dict[str, object],
    ) -> DecisionEffect:
        return DecisionEffect(
            subject=self.snapshot(subject),
            resulting_projection=projection,
            version=subject.lock_version,
            evidence_refs=tuple(dict(item) for item in _evidence_refs(subject)),
            outbox_events=(
                OutboxEvent(
                    topic="job-intelligence-projections",
                    aggregate_type="company",
                    aggregate_id=str(subject.company_id),
                    event_type="company.industry_decided",
                    source_service="company-industry",
                    payload={
                        **projection,
                        "invalidate": [
                            "company-industry-read-model",
                            "company-industry-review-queue",
                            "job-search",
                        ],
                    },
                ),
            ),
        )

    @staticmethod
    def attach_audit_reference(
        db: Session,
        subject: CompanyIndustryReviewItem,
        audit_id: UUID,
    ) -> None:
        subject.decision_audit_id = audit_id
        if subject.mapping_id is not None:
            mapping = db.get(SourceIndustryMapping, subject.mapping_id)
            if mapping is not None and mapping.decision_audit_id is None:
                mapping.decision_audit_id = audit_id


def _evidence_refs(subject: CompanyIndustryReviewItem) -> tuple[dict[str, object], ...]:
    provenance = dict(subject.provenance)
    raw_refs = provenance.get("evidence_refs")
    if not isinstance(raw_refs, list):
        return ()
    return tuple(dict(item) for item in raw_refs if isinstance(item, dict))


__all__ = ["CompanyIndustryDecisionAdapter", "CompanyIndustryDecisionError"]
