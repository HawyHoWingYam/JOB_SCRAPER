from __future__ import annotations

from copy import deepcopy
from typing import Any
import uuid

from sqlalchemy import case, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.source_catalog import (
    SourceCatalogActiveRevision,
    SourceCatalogCandidate,
    SourceCatalogChangeReview,
    SourceCatalogPublication,
    SourceCatalogRevision,
    SourceCatalogValidationRun,
)
from app.utils.time import utc_now


class SourceCatalogStateError(ValueError):
    pass


class SourceCatalogConcurrentChangeError(RuntimeError):
    pass


def _coerce_uuid(value):
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


class SourceCatalogRepository:
    """Persistence boundary for immutable source catalog snapshots."""

    def lock_source_publication(self, db: Session, *, source_site: str) -> None:
        """Serialize pointer/revision sequence changes, including first publication."""

        bind = db.get_bind()
        if bind.dialect.name == "postgresql":
            db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": f"source-catalog:{source_site}"},
            )

    def create_or_get_candidate(
        self,
        db: Session,
        *,
        source_site: str,
        fingerprint: str,
        normalized_payload: dict[str, Any],
        source_payload: dict[str, Any],
        provenance: dict[str, Any],
        diff: dict[str, Any] | None = None,
        base_revision_id=None,
        auto_commit: bool = True,
    ) -> tuple[SourceCatalogCandidate, bool]:
        existing = (
            db.query(SourceCatalogCandidate)
            .filter(
                SourceCatalogCandidate.source_site == source_site,
                SourceCatalogCandidate.fingerprint == fingerprint,
                SourceCatalogCandidate.state != "superseded",
            )
            .one_or_none()
        )
        if existing is not None:
            return existing, False

        candidate = SourceCatalogCandidate(
            source_site=source_site,
            base_revision_id=base_revision_id,
            fingerprint=fingerprint,
            normalized_payload=normalized_payload,
            source_payload=source_payload,
            provenance=provenance,
            diff=diff or {},
        )
        db.add(candidate)
        if auto_commit:
            try:
                db.commit()
                db.refresh(candidate)
            except IntegrityError:
                db.rollback()
                existing = (
                    db.query(SourceCatalogCandidate)
                    .filter(
                        SourceCatalogCandidate.source_site == source_site,
                        SourceCatalogCandidate.fingerprint == fingerprint,
                        SourceCatalogCandidate.state != "superseded",
                    )
                    .one_or_none()
                )
                if existing is None:
                    raise
                return existing, False
        else:
            db.flush()
        return candidate, True

    def get_candidate(self, db: Session, candidate_id) -> SourceCatalogCandidate | None:
        normalized_id = _coerce_uuid(candidate_id)
        return db.get(SourceCatalogCandidate, normalized_id) if normalized_id else None

    def get_candidate_for_update(
        self, db: Session, candidate_id
    ) -> SourceCatalogCandidate | None:
        normalized_id = _coerce_uuid(candidate_id)
        if normalized_id is None:
            return None
        return (
            db.query(SourceCatalogCandidate)
            .filter(SourceCatalogCandidate.id == normalized_id)
            .with_for_update()
            .one_or_none()
        )

    def list_candidates(
        self,
        db: Session,
        *,
        source_site: str,
        limit: int = 50,
    ) -> list[SourceCatalogCandidate]:
        return (
            db.query(SourceCatalogCandidate)
            .filter(SourceCatalogCandidate.source_site == source_site)
            .order_by(SourceCatalogCandidate.created_at.desc())
            .limit(max(1, min(int(limit), 200)))
            .all()
        )

    def get_active_revision(
        self,
        db: Session,
        *,
        source_site: str,
    ) -> SourceCatalogRevision | None:
        return (
            db.query(SourceCatalogRevision)
            .join(
                SourceCatalogActiveRevision,
                SourceCatalogActiveRevision.revision_id == SourceCatalogRevision.id,
            )
            .filter(SourceCatalogActiveRevision.source_site == source_site)
            .one_or_none()
        )

    def get_active_pointer_for_update(
        self,
        db: Session,
        *,
        source_site: str,
    ) -> SourceCatalogActiveRevision | None:
        return (
            db.query(SourceCatalogActiveRevision)
            .filter(SourceCatalogActiveRevision.source_site == source_site)
            .with_for_update()
            .one_or_none()
        )

    def get_revision(self, db: Session, revision_id) -> SourceCatalogRevision | None:
        normalized_id = _coerce_uuid(revision_id)
        return db.get(SourceCatalogRevision, normalized_id) if normalized_id else None

    def get_revision_for_update(
        self, db: Session, revision_id
    ) -> SourceCatalogRevision | None:
        normalized_id = _coerce_uuid(revision_id)
        if normalized_id is None:
            return None
        return (
            db.query(SourceCatalogRevision)
            .filter(SourceCatalogRevision.id == normalized_id)
            .with_for_update()
            .one_or_none()
        )

    def list_revisions(
        self,
        db: Session,
        *,
        source_site: str,
    ) -> list[SourceCatalogRevision]:
        return (
            db.query(SourceCatalogRevision)
            .filter(SourceCatalogRevision.source_site == source_site)
            .order_by(SourceCatalogRevision.sequence.asc())
            .all()
        )

    def create_change_review(
        self,
        db: Session,
        *,
        token_hash: str,
        operation: str,
        source_site: str,
        automation_impact_digest: str,
        automation_impact: dict[str, Any],
        actor: str,
        expires_at,
        candidate_id=None,
        target_revision_id=None,
        candidate_fingerprint: str | None = None,
        base_active_revision_id=None,
        auto_commit: bool = True,
    ) -> SourceCatalogChangeReview:
        review = SourceCatalogChangeReview(
            token_hash=token_hash,
            operation=operation,
            source_site=source_site,
            candidate_id=candidate_id,
            target_revision_id=target_revision_id,
            candidate_fingerprint=candidate_fingerprint,
            base_active_revision_id=base_active_revision_id,
            automation_impact_digest=automation_impact_digest,
            automation_impact=automation_impact,
            actor=actor,
            expires_at=expires_at,
        )
        db.add(review)
        if auto_commit:
            db.commit()
            db.refresh(review)
        else:
            db.flush()
        return review

    def get_change_review_by_token_hash_for_update(
        self,
        db: Session,
        *,
        token_hash: str,
    ) -> SourceCatalogChangeReview | None:
        return (
            db.query(SourceCatalogChangeReview)
            .filter(SourceCatalogChangeReview.token_hash == token_hash)
            .with_for_update()
            .one_or_none()
        )

    def append_publication(
        self,
        db: Session,
        *,
        source_site: str,
        operation: str,
        revision_id,
        previous_revision_id,
        review_id,
        actor: str,
        candidate_id=None,
        auto_commit: bool = True,
    ) -> SourceCatalogPublication:
        publication = SourceCatalogPublication(
            source_site=source_site,
            operation=operation,
            revision_id=revision_id,
            previous_revision_id=previous_revision_id,
            candidate_id=candidate_id,
            review_id=review_id,
            actor=actor,
        )
        db.add(publication)
        if auto_commit:
            db.commit()
            db.refresh(publication)
        else:
            db.flush()
        return publication

    def list_publications(
        self,
        db: Session,
        *,
        source_site: str,
    ) -> list[SourceCatalogPublication]:
        return (
            db.query(SourceCatalogPublication)
            .filter(SourceCatalogPublication.source_site == source_site)
            .order_by(SourceCatalogPublication.created_at.asc())
            .all()
        )

    def create_validation_run(
        self,
        db: Session,
        *,
        candidate_id,
        validation_kind: str,
        expected_target_hash: str,
        node_key: str | None = None,
        classification_id: str | None = None,
        attempt: int = 1,
        auto_commit: bool = True,
    ) -> SourceCatalogValidationRun:
        run = SourceCatalogValidationRun(
            candidate_id=candidate_id,
            validation_kind=validation_kind,
            expected_target_hash=expected_target_hash,
            node_key=node_key,
            classification_id=classification_id,
            attempt=attempt,
        )
        db.add(run)
        if auto_commit:
            db.commit()
            db.refresh(run)
        else:
            db.flush()
        return run

    def list_validation_runs(
        self,
        db: Session,
        *,
        candidate_id,
    ) -> list[SourceCatalogValidationRun]:
        offline_first = case(
            (SourceCatalogValidationRun.validation_kind == "offline", 0),
            else_=1,
        )
        return (
            db.query(SourceCatalogValidationRun)
            .filter(SourceCatalogValidationRun.candidate_id == candidate_id)
            .order_by(
                offline_first.asc(),
                SourceCatalogValidationRun.created_at.asc(),
                SourceCatalogValidationRun.classification_id.asc(),
                SourceCatalogValidationRun.attempt.asc(),
            )
            .all()
        )

    def claim_next_validation_run(
        self,
        db: Session,
        *,
        candidate_id,
        worker_id: str,
    ) -> SourceCatalogValidationRun | None:
        offline_first = case(
            (SourceCatalogValidationRun.validation_kind == "offline", 0),
            else_=1,
        )
        run = (
            db.query(SourceCatalogValidationRun)
            .filter(
                SourceCatalogValidationRun.candidate_id == candidate_id,
                SourceCatalogValidationRun.status == "pending",
            )
            .order_by(
                offline_first.asc(),
                SourceCatalogValidationRun.created_at.asc(),
                SourceCatalogValidationRun.classification_id.asc(),
            )
            .with_for_update(skip_locked=True)
            .first()
        )
        if run is None:
            return None
        now = utc_now()
        run.status = "running"
        run.claimed_by = worker_id
        run.started_at = run.started_at or now
        run.heartbeat_at = now
        db.commit()
        db.refresh(run)
        return run

    def fail_stale_validation_runs(
        self,
        db: Session,
        *,
        candidate_id,
        stale_before,
        auto_commit: bool = True,
    ) -> int:
        rows = (
            db.query(SourceCatalogValidationRun)
            .filter(
                SourceCatalogValidationRun.candidate_id == candidate_id,
                SourceCatalogValidationRun.status == "running",
                SourceCatalogValidationRun.heartbeat_at < stale_before,
            )
            .with_for_update(skip_locked=True)
            .all()
        )
        for run in rows:
            run.status = "failed"
            run.error = {"error_type": "stale_worker_claim"}
            run.completed_at = utc_now()
        if rows:
            if auto_commit:
                db.commit()
            else:
                db.flush()
        return len(rows)

    def complete_validation_run(
        self,
        db: Session,
        *,
        run: SourceCatalogValidationRun,
        worker_id: str,
        status: str,
        evidence: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        manual_action: dict[str, Any] | None = None,
        auto_commit: bool = True,
    ) -> SourceCatalogValidationRun:
        current = (
            db.query(SourceCatalogValidationRun)
            .filter(SourceCatalogValidationRun.id == run.id)
            .populate_existing()
            .with_for_update()
            .one_or_none()
        )
        if (
            current is None
            or current.status != "running"
            or current.claimed_by != worker_id
        ):
            raise SourceCatalogConcurrentChangeError(
                "Validation claim is stale or owned by another worker"
            )
        if status not in {"passed", "failed", "manual_action_required"}:
            raise SourceCatalogStateError(f"Invalid validation result {status!r}")
        current.status = status
        current.evidence = evidence or {}
        current.error = error
        current.manual_action = manual_action
        current.completed_at = utc_now()
        current.heartbeat_at = current.completed_at
        if auto_commit:
            db.commit()
            db.refresh(current)
        else:
            db.flush()
        return current

    def mark_candidate_validated(
        self,
        db: Session,
        *,
        candidate: SourceCatalogCandidate,
        validation_summary: dict[str, Any] | None = None,
        auto_commit: bool = True,
    ) -> SourceCatalogCandidate:
        if candidate.state not in {"discovered", "validating", "validation_failed", "manual_action_required"}:
            raise SourceCatalogStateError(
                f"Candidate cannot be validated from state {candidate.state!r}"
            )
        candidate.state = "validated"
        candidate.validation_summary = validation_summary or {"status": "passed"}
        candidate.validated_at = utc_now()
        if auto_commit:
            db.commit()
            db.refresh(candidate)
        else:
            db.flush()
        return candidate

    def create_revision(
        self,
        db: Session,
        *,
        candidate: SourceCatalogCandidate,
        published_by: str,
        publication_metadata: dict[str, Any] | None = None,
        auto_commit: bool = True,
    ) -> SourceCatalogRevision:
        if candidate.state != "validated":
            raise SourceCatalogStateError("Only a validated candidate can become a revision")
        existing = (
            db.query(SourceCatalogRevision)
            .filter(SourceCatalogRevision.candidate_id == candidate.id)
            .one_or_none()
        )
        if existing is not None:
            return existing
        next_sequence = int(
            (
                db.query(func.coalesce(func.max(SourceCatalogRevision.sequence), 0))
                .filter(SourceCatalogRevision.source_site == candidate.source_site)
                .scalar()
            )
            + 1
        )
        revision = SourceCatalogRevision(
            source_site=candidate.source_site,
            sequence=next_sequence,
            fingerprint=candidate.fingerprint,
            normalized_payload=deepcopy(candidate.normalized_payload),
            source_payload=deepcopy(candidate.source_payload),
            provenance=deepcopy(candidate.provenance),
            candidate_id=candidate.id,
            predecessor_revision_id=candidate.base_revision_id,
            publication_metadata=publication_metadata or {},
            published_by=published_by,
        )
        db.add(revision)
        if auto_commit:
            db.commit()
            db.refresh(revision)
        else:
            db.flush()
        return revision

    def set_active_revision(
        self,
        db: Session,
        *,
        source_site: str,
        revision_id,
        expected_revision_id,
        updated_by: str,
        auto_commit: bool = True,
    ) -> SourceCatalogActiveRevision:
        revision = db.get(SourceCatalogRevision, revision_id)
        if revision is None or revision.source_site != source_site:
            raise SourceCatalogStateError("Revision does not belong to the requested source")
        pointer = (
            db.query(SourceCatalogActiveRevision)
            .filter(SourceCatalogActiveRevision.source_site == source_site)
            .with_for_update()
            .one_or_none()
        )
        current_revision_id = pointer.revision_id if pointer is not None else None
        if current_revision_id != expected_revision_id:
            raise SourceCatalogConcurrentChangeError(
                "Active Source Catalog revision changed after review"
            )
        if pointer is None:
            pointer = SourceCatalogActiveRevision(
                source_site=source_site,
                revision_id=revision_id,
                updated_by=updated_by,
            )
            db.add(pointer)
        else:
            pointer.revision_id = revision_id
            pointer.updated_by = updated_by
            pointer.updated_at = utc_now()
        if auto_commit:
            db.commit()
            db.refresh(pointer)
        else:
            db.flush()
        return pointer
