from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.classification_batch import (
    ClassificationBatchRun,
    ClassificationBatchRunItem,
)
from app.utils.time import utc_now


ACTIVE_STATUSES = ("pending", "running", "stopping")
TERMINAL_STATUSES = (
    "completed",
    "completed_with_failures",
    "failed",
    "cancelled",
)
ITEM_TERMINAL_STATUSES = ("completed", "failed", "cancelled")
SUPPORTED_DOMAINS = ("job_taxonomy", "company_industry", "skill")


class ClassificationBatchError(ValueError):
    """Base error exposed by the classification batch public interface."""


class ActiveClassificationBatchError(ClassificationBatchError):
    def __init__(self, domain: str, run_id: str):
        super().__init__(f"An active {domain} classification batch already exists")
        self.domain = domain
        self.run_id = run_id


@dataclass(frozen=True)
class ClassificationCandidate:
    subject_id: str
    subject_label: str | None = None
    payload: dict[str, object] | None = None


@dataclass(frozen=True)
class ClassificationBatchPreview:
    domain: str
    selected_item_count: int
    items: tuple[ClassificationCandidate, ...]


class ClassificationDomainAdapter(Protocol):
    domain: str

    def select_candidates(
        self,
        db: Session,
        *,
        filters: dict[str, object],
        limit: int,
    ) -> tuple[ClassificationCandidate, ...]: ...

    async def process_candidate(
        self,
        db: Session,
        candidate: ClassificationCandidate,
    ) -> None: ...


class ClassificationBatchRuntime:
    """Own the lifecycle; adapters own domain selection and one-item work."""

    def __init__(
        self,
        db: Session,
        adapters: Mapping[str, ClassificationDomainAdapter],
    ) -> None:
        self.db = db
        self.adapters = dict(adapters)

    def preview(
        self,
        domain: str,
        *,
        filters: dict[str, object],
        limit: int,
    ) -> ClassificationBatchPreview:
        adapter = self._adapter(domain)
        safe_limit = self._validate_limit(limit)
        candidates = adapter.select_candidates(
            self.db,
            filters=dict(filters),
            limit=safe_limit,
        )
        if len(candidates) > safe_limit:
            raise ClassificationBatchError("Domain adapter exceeded the requested limit")
        subject_ids = [candidate.subject_id for candidate in candidates]
        if any(not value for value in subject_ids) or len(set(subject_ids)) != len(subject_ids):
            raise ClassificationBatchError("Domain adapter returned invalid candidate identities")
        return ClassificationBatchPreview(
            domain=domain,
            selected_item_count=len(candidates),
            items=tuple(candidates),
        )

    def start(
        self,
        domain: str,
        *,
        filters: dict[str, object],
        limit: int,
    ) -> ClassificationBatchRun:
        preview = self.preview(domain, filters=filters, limit=limit)
        self._require_no_active_run(domain)
        run = self._create_run(
            domain=domain,
            filters=filters,
            requested_limit=limit,
            candidates=preview.items,
        )
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            active = self._active_run(domain)
            if active is not None:
                raise ActiveClassificationBatchError(domain, active.id) from exc
            raise
        return run

    def get_run(self, run_id: str) -> ClassificationBatchRun | None:
        return self.db.get(ClassificationBatchRun, run_id)

    def list_runs(
        self,
        *,
        domain: str | None = None,
        limit: int = 20,
    ) -> tuple[ClassificationBatchRun, ...]:
        query = select(ClassificationBatchRun)
        if domain is not None:
            self._adapter(domain)
            query = query.where(ClassificationBatchRun.domain == domain)
        return tuple(
            self.db.scalars(
                query.order_by(
                    ClassificationBatchRun.created_at.desc(),
                    ClassificationBatchRun.id.desc(),
                ).limit(max(1, min(int(limit), 100)))
            )
        )

    def request_stop(self, run_id: str) -> ClassificationBatchRun:
        run = self._require_run(run_id)
        if run.status in TERMINAL_STATUSES:
            return run
        now = utc_now()
        run.stop_requested_at = run.stop_requested_at or now
        if run.status == "pending":
            self._cancel_pending_items(run.id, now=now)
            run.status = "cancelled"
            run.completed_at = now
            self._refresh_counts(run)
        elif run.status == "running":
            run.status = "stopping"
        self.db.commit()
        return run

    def retry_failed(self, run_id: str) -> ClassificationBatchRun:
        source_run = self._require_run(run_id)
        if source_run.status not in TERMINAL_STATUSES:
            raise ClassificationBatchError("Only a terminal batch can be retried")
        failed_items = tuple(
            self.db.scalars(
                select(ClassificationBatchRunItem)
                .where(
                    ClassificationBatchRunItem.run_id == run_id,
                    ClassificationBatchRunItem.status == "failed",
                )
                .order_by(ClassificationBatchRunItem.position)
            )
        )
        if not failed_items:
            raise ClassificationBatchError("The batch has no failed items to retry")
        self._require_no_active_run(source_run.domain)
        candidates = tuple(
            ClassificationCandidate(
                subject_id=item.subject_id,
                subject_label=item.subject_label,
                payload=dict(item.payload or {}),
            )
            for item in failed_items
        )
        run = self._create_run(
            domain=source_run.domain,
            filters=dict(source_run.filters or {}),
            requested_limit=len(candidates),
            candidates=candidates,
            retry_of_run_id=source_run.id,
        )
        self.db.commit()
        return run

    async def execute(self, run_id: str) -> ClassificationBatchRun:
        run = self._require_run(run_id)
        if run.status in TERMINAL_STATUSES:
            return run
        if run.status == "pending":
            run.status = "running"
            run.started_at = run.started_at or utc_now()
            self.db.commit()

        adapter = self._adapter(run.domain)
        while True:
            self.db.expire_all()
            run = self._require_run(run_id)
            if run.status == "stopping":
                now = utc_now()
                self._cancel_pending_items(run.id, now=now)
                self._refresh_counts(run)
                run.status = "cancelled"
                run.completed_at = now
                self.db.commit()
                return run
            if run.status != "running":
                return run

            item = self.db.scalar(
                select(ClassificationBatchRunItem)
                .where(
                    ClassificationBatchRunItem.run_id == run.id,
                    ClassificationBatchRunItem.status == "pending",
                )
                .order_by(ClassificationBatchRunItem.position)
                .limit(1)
            )
            if item is None:
                return self._finish(run)

            item.status = "running"
            item.attempt_count += 1
            item.started_at = utc_now()
            item.error_code = None
            item.error_message = None
            self.db.commit()
            candidate = ClassificationCandidate(
                subject_id=item.subject_id,
                subject_label=item.subject_label,
                payload=dict(item.payload or {}),
            )
            try:
                await adapter.process_candidate(self.db, candidate)
                item = self.db.get(ClassificationBatchRunItem, item.id)
                if item is None:
                    raise ClassificationBatchError("Classification batch item disappeared")
                item.status = "completed"
                item.completed_at = utc_now()
                self.db.flush()
                run = self._require_run(run_id)
                self._refresh_counts(run)
                self.db.commit()
            except Exception as exc:
                self.db.rollback()
                item = self.db.get(ClassificationBatchRunItem, item.id)
                run = self._require_run(run_id)
                if item is None:
                    raise
                item.status = "failed"
                item.completed_at = utc_now()
                item.error_code = type(exc).__name__[:128]
                item.error_message = str(exc)[:2000]
                self.db.flush()
                self._refresh_counts(run)
                self.db.commit()

    def _create_run(
        self,
        *,
        domain: str,
        filters: dict[str, object],
        requested_limit: int,
        candidates: tuple[ClassificationCandidate, ...],
        retry_of_run_id: str | None = None,
    ) -> ClassificationBatchRun:
        now = utc_now()
        terminal = not candidates
        run = ClassificationBatchRun(
            domain=domain,
            status="completed" if terminal else "pending",
            filters=dict(filters),
            requested_limit=requested_limit,
            total_items=len(candidates),
            pending_items=len(candidates),
            completed_items=0,
            failed_items=0,
            cancelled_items=0,
            retry_of_run_id=retry_of_run_id,
            completed_at=now if terminal else None,
            created_at=now,
        )
        self.db.add(run)
        self.db.flush()
        for position, candidate in enumerate(candidates):
            self.db.add(
                ClassificationBatchRunItem(
                    run_id=run.id,
                    subject_id=candidate.subject_id,
                    subject_label=candidate.subject_label,
                    position=position,
                    payload=dict(candidate.payload or {}),
                    status="pending",
                    attempt_count=0,
                    created_at=now,
                )
            )
        self.db.flush()
        return run

    def _finish(self, run: ClassificationBatchRun) -> ClassificationBatchRun:
        self._refresh_counts(run)
        if run.pending_items:
            raise ClassificationBatchError("Cannot finish a batch with pending items")
        if run.failed_items and run.completed_items:
            run.status = "completed_with_failures"
        elif run.failed_items:
            run.status = "failed"
        elif run.cancelled_items:
            run.status = "cancelled"
        else:
            run.status = "completed"
        run.completed_at = utc_now()
        self.db.commit()
        return run

    def _refresh_counts(self, run: ClassificationBatchRun) -> None:
        rows = self.db.execute(
            select(
                ClassificationBatchRunItem.status,
                func.count(ClassificationBatchRunItem.id),
            )
            .where(ClassificationBatchRunItem.run_id == run.id)
            .group_by(ClassificationBatchRunItem.status)
        ).all()
        counts = {status: count for status, count in rows}
        run.pending_items = int(counts.get("pending", 0))
        run.completed_items = int(counts.get("completed", 0))
        run.failed_items = int(counts.get("failed", 0))
        run.cancelled_items = int(counts.get("cancelled", 0))

    def _cancel_pending_items(self, run_id: str, *, now) -> None:
        self.db.execute(
            update(ClassificationBatchRunItem)
            .where(
                ClassificationBatchRunItem.run_id == run_id,
                ClassificationBatchRunItem.status == "pending",
            )
            .values(status="cancelled", completed_at=now)
        )
        self.db.flush()

    def _require_no_active_run(self, domain: str) -> None:
        active = self._active_run(domain)
        if active is not None:
            raise ActiveClassificationBatchError(domain, active.id)

    def _active_run(self, domain: str) -> ClassificationBatchRun | None:
        return self.db.scalar(
            select(ClassificationBatchRun)
            .where(
                ClassificationBatchRun.domain == domain,
                ClassificationBatchRun.status.in_(ACTIVE_STATUSES),
            )
            .order_by(ClassificationBatchRun.created_at.desc())
            .limit(1)
        )

    def _require_run(self, run_id: str) -> ClassificationBatchRun:
        run = self.get_run(run_id)
        if run is None:
            raise ClassificationBatchError("Classification batch was not found")
        return run

    def _adapter(self, domain: str) -> ClassificationDomainAdapter:
        if domain not in SUPPORTED_DOMAINS:
            raise ClassificationBatchError(f"Unsupported classification domain '{domain}'")
        adapter = self.adapters.get(domain)
        if adapter is None:
            raise ClassificationBatchError(f"Classification domain '{domain}' is unavailable")
        return adapter

    @staticmethod
    def _validate_limit(limit: int) -> int:
        try:
            value = int(limit)
        except (TypeError, ValueError) as exc:
            raise ClassificationBatchError("Batch limit must be an integer") from exc
        if value < 1 or value > 5000:
            raise ClassificationBatchError("Batch limit must be between 1 and 5000")
        return value


__all__ = [
    "ACTIVE_STATUSES",
    "ActiveClassificationBatchError",
    "ClassificationBatchError",
    "ClassificationBatchPreview",
    "ClassificationBatchRuntime",
    "ClassificationCandidate",
    "ClassificationDomainAdapter",
    "SUPPORTED_DOMAINS",
    "TERMINAL_STATUSES",
]
