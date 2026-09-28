from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.job_intelligence.foundation import normalized_content_hash
from app.models.company import Company
from app.models.current_taxonomy import CurrentJobSkillMention
from app.models.job import Job
from app.models.jev import (
    JevOnlineSkillClassification,
    JevOperationBatch,
    JevOperationBatchItem,
    JevRun,
)
from app.services.jev_duplicate_association import JevDuplicateAssociationService
from app.services.jev_evaluator_factory import build_jev_evaluator
from app.services.jev_online_skill_case_builder import (
    OnlineSkillCaseBuildContext,
    build_online_skill_case,
)
from app.services.jev_online_skill_runner import JevOnlineSkillRunner
from app.services.jev_related_jobs import JevRelatedJobsService
from app.services.jev_run_service import JevRunService
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService
from app.services.jev_skill_backfill import JevSkillBackfillService
from app.utils.time import utc_now


OPERATIONS = ("skills", "duplicate", "related_jobs")
ACTIVE_BATCH_STATUSES = ("pending", "running", "stopping")


class JevDuplicateRunFailed(RuntimeError):
    """A Job-level duplicate operation had failed bounded-run items."""


@dataclass(frozen=True)
class OperationEligibility:
    operation: str
    job_id: UUID
    eligible: bool
    reason: str
    input_fingerprint: str | None
    conservative_requests: int


class JevOperationBatchService:
    """Durable, explicit manual authority for combined Job-level Jev work."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def preview(self, request) -> dict[str, object]:
        operations = self._operations(request.operations)
        jobs = self._select_jobs(request)
        skill_context = (
            OnlineSkillCaseBuildContext(self.db) if "skills" in operations else None
        )
        skill_mentions, latest_skills = (
            self._load_skill_preview_inputs(jobs)
            if "skills" in operations
            else ({}, {})
        )
        states = [
            self._eligibility(
                job,
                operation,
                force=request.force_reevaluation,
                skill_context=skill_context,
                extracted_skills=skill_mentions.get(job.id, ()),
                latest_skill=latest_skills.get(job.id),
            )
            for job in jobs
            for operation in operations
        ]
        if request.processing_status != "all":
            wanted = request.processing_status
            allowed_job_ids = {
                state.job_id
                for state in states
                if (
                    (wanted == "eligible" and state.eligible)
                    or (
                        wanted == "successful"
                        and state.reason == "successful_unchanged"
                    )
                    or (wanted == "failed" and state.reason == "previously_failed")
                )
            }
            jobs = [job for job in jobs if job.id in allowed_job_ids]
            states = [state for state in states if state.job_id in allowed_job_ids]
        settings = JevRuntimeSettingsService(self.db).get_or_create()
        counts = {}
        for operation in operations:
            selected = [state for state in states if state.operation == operation]
            counts[operation] = {
                "selected": len(selected),
                "eligible": sum(state.eligible for state in selected),
                "skipped": sum(not state.eligible for state in selected),
                "reasons": self._reason_counts(selected),
            }
        snapshot = self._selection_snapshot(request, operations=operations)
        identity = {
            "selection": snapshot,
            "selected_job_ids": [str(job.id) for job in jobs],
            "items": [
                {
                    "job_id": str(state.job_id),
                    "operation": state.operation,
                    "eligible": state.eligible,
                    "reason": state.reason,
                    "input_fingerprint": state.input_fingerprint,
                }
                for state in states
            ],
            "runtime": {
                "model": settings.model,
                "duplicate_candidate_limit": settings.duplicate_candidate_limit,
                "duplicate_corpus_limit": settings.duplicate_corpus_limit,
            },
        }
        return {
            "preview_fingerprint": normalized_content_hash(identity),
            "selection": snapshot,
            "selected_job_ids": [str(job.id) for job in jobs],
            "selected_job_count": len(jobs),
            "operations": counts,
            "items": states,
        }

    @staticmethod
    def _selection_snapshot(request, *, operations: Iterable[str]) -> dict[str, object]:
        return {
            "source_sites": list(request.source_sites),
            "keyword": request.keyword,
            "job_ids": [str(value) for value in request.job_ids],
            "posted_date_from": (
                request.posted_date_from.isoformat()
                if request.posted_date_from is not None
                else None
            ),
            "posted_date_to": (
                request.posted_date_to.isoformat()
                if request.posted_date_to is not None
                else None
            ),
            "processing_status": request.processing_status,
            "job_offset": request.job_offset,
            "max_jobs": request.max_jobs,
            "execution_batch_size": request.execution_batch_size,
            "start_execution_batch": request.start_execution_batch,
            "operations": list(operations),
            "force_reevaluation": request.force_reevaluation,
        }

    def start(
        self,
        request,
        *,
        preview_fingerprint: str | None,
        idempotency_key: str,
    ) -> JevOperationBatch:
        operations = self._operations(request.operations)
        snapshot = self._selection_snapshot(request, operations=operations)
        existing = self.db.scalar(
            select(JevOperationBatch).where(
                JevOperationBatch.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            if existing.selection_snapshot != snapshot:
                raise ValueError(
                    "Idempotency key was used for a different Jev batch scope"
                )
            return existing
        if preview_fingerprint is not None:
            preview = self.preview(request)
            if preview["preview_fingerprint"] != preview_fingerprint:
                raise ValueError("Preview is stale; preview the batch again")
            jobs = [
                self.db.get(Job, UUID(job_id)) for job_id in preview["selected_job_ids"]
            ]
            jobs = [job for job in jobs if job is not None]
            item_states = preview["items"]
            plan_fingerprint = preview_fingerprint
        else:
            jobs = self._select_jobs(request)
            item_states = None
            plan_fingerprint = normalized_content_hash(
                {
                    "selection": snapshot,
                    "selected_job_ids": [str(job.id) for job in jobs],
                }
            )
        batch = JevOperationBatch(
            idempotency_key=idempotency_key,
            preview_fingerprint=plan_fingerprint,
            status="pending",
            selection_snapshot=snapshot,
            selected_job_ids=[str(job.id) for job in jobs],
            operations=list(operations),
            force_reevaluation=request.force_reevaluation,
        )
        self.db.add(batch)
        self.db.flush()
        items = []
        states = item_states or [
            OperationEligibility(operation, job.id, True, "deferred", None, 0)
            for job in jobs
            for operation in operations
        ]
        for position, state in enumerate(states):
            items.append(
                JevOperationBatchItem(
                    batch_id=batch.id,
                    job_id=state.job_id,
                    operation=state.operation,
                    position=position,
                    status="pending" if state.eligible else "skipped",
                    eligibility_reason=state.reason,
                    input_fingerprint=state.input_fingerprint,
                    completed_at=None if state.eligible else utc_now(),
                )
            )
        self.db.add_all(items)
        self.db.flush()
        self._refresh_counts(batch)
        if batch.pending_items == 0:
            batch.status = "completed"
            batch.completed_at = utc_now()
        self.db.flush()
        return batch

    async def execute(self, batch_id: str) -> JevOperationBatch:
        batch = self.get(batch_id)
        if batch.status not in {"pending", "running"}:
            return batch
        batch.status = "running"
        batch.started_at = batch.started_at or utc_now()
        self.db.commit()
        while True:
            self.db.expire_all()
            batch = self.get(batch_id)
            if batch.stop_requested_at is not None or batch.status == "stopping":
                batch.status = "stopped"
                self._stop_pending_items(batch)
                self._refresh_counts(batch)
                self.db.commit()
                return batch
            item = self.db.scalar(
                select(JevOperationBatchItem)
                .where(
                    JevOperationBatchItem.batch_id == batch.id,
                    JevOperationBatchItem.status == "pending",
                )
                .order_by(JevOperationBatchItem.position)
                .limit(1)
            )
            if item is None:
                self._finish(batch)
                self.db.commit()
                return batch
            if item.eligibility_reason == "deferred":
                self._prepare_job_items(batch, item.job_id)
                self._refresh_counts(batch)
                self.db.commit()
                continue
            item.status = "running"
            item.attempt_count += 1
            item.started_at = utc_now()
            item.error_code = None
            item.error_message = None
            self._refresh_counts(batch)
            self.db.commit()
            try:
                result = await self._execute_item(item, force=batch.force_reevaluation)
                self.db.expire_all()
                item = self.db.get(JevOperationBatchItem, item.id)
                item.status = "completed"
                item.result = result
                item.completed_at = utc_now()
            except Exception as exc:  # item isolation is the batch contract
                self.db.rollback()
                item = self.db.get(JevOperationBatchItem, item.id)
                item.status = "failed"
                item.error_code = type(exc).__name__
                item.error_message = str(exc)[:2_000]
                item.completed_at = utc_now()
            batch = self.get(batch_id)
            self._refresh_counts(batch)
            self.db.commit()

    def _prepare_job_items(self, batch: JevOperationBatch, job_id: UUID) -> None:
        job = self.db.get(Job, job_id)
        job_items = [
            item
            for item in batch.items
            if item.job_id == job_id and item.eligibility_reason == "deferred"
        ]
        if job is None:
            for item in job_items:
                item.status = "skipped"
                item.eligibility_reason = "job_unavailable"
                item.completed_at = utc_now()
            return
        skill_context = (
            OnlineSkillCaseBuildContext(self.db)
            if any(item.operation == "skills" for item in job_items)
            else None
        )
        skill_mentions, latest_skills = (
            self._load_skill_preview_inputs([job])
            if skill_context is not None
            else ({}, {})
        )
        states = {
            item.operation: self._eligibility(
                job,
                item.operation,
                force=batch.force_reevaluation,
                skill_context=skill_context,
                extracted_skills=skill_mentions.get(job.id, ()),
                latest_skill=latest_skills.get(job.id),
            )
            for item in job_items
        }
        wanted = (batch.selection_snapshot or {}).get("processing_status", "all")
        allowed = wanted == "all" or any(
            (wanted == "eligible" and state.eligible)
            or (wanted == "successful" and state.reason == "successful_unchanged")
            or (wanted == "failed" and state.reason == "previously_failed")
            for state in states.values()
        )
        for item in job_items:
            state = states[item.operation]
            item.eligibility_reason = state.reason
            item.input_fingerprint = state.input_fingerprint
            if not allowed or not state.eligible:
                item.status = "skipped"
                item.completed_at = utc_now()

    def request_stop(self, batch_id: str) -> JevOperationBatch:
        batch = self.get(batch_id)
        if batch.status in ACTIVE_BATCH_STATUSES:
            batch.status = "stopping"
            batch.stop_requested_at = batch.stop_requested_at or utc_now()
            self.db.flush()
        return batch

    def resume(self, batch_id: str) -> JevOperationBatch:
        batch = self.get(batch_id)
        if batch.status != "stopped":
            raise ValueError("Only a stopped Jev batch can be resumed")
        for item in batch.items:
            if item.status == "stopped":
                item.status = "pending"
                item.completed_at = None
        batch.status = "pending"
        batch.stop_requested_at = None
        batch.completed_at = None
        self._refresh_counts(batch)
        self.db.flush()
        return batch

    def retry_failed(self, batch_id: str) -> JevOperationBatch:
        batch = self.get(batch_id)
        self.reconcile_duplicate_failures(batch_id)
        failed = [item for item in batch.items if item.status == "failed"]
        if not failed:
            raise ValueError("Jev batch has no failed items to retry")
        for item in failed:
            item.status = "pending"
            item.error_code = None
            item.error_message = None
            item.completed_at = None
        batch.status = "pending"
        batch.stop_requested_at = None
        batch.completed_at = None
        self._refresh_counts(batch)
        self.db.flush()
        return batch

    def reconcile_duplicate_failures(self, batch_id: str) -> int:
        """Correct legacy outer successes without dispatching provider work."""
        batch = self.get(batch_id)
        candidates: list[tuple[JevOperationBatchItem, str]] = []
        for item in batch.items:
            if item.operation != "duplicate" or item.status != "completed":
                continue
            result = item.result if isinstance(item.result, dict) else {}
            run_id = result.get("jev_run_id")
            if isinstance(run_id, str) and run_id:
                candidates.append((item, run_id))
        if not candidates:
            return 0
        runs = {
            run.id: run
            for run in self.db.scalars(
                select(JevRun).where(
                    JevRun.id.in_({run_id for _item, run_id in candidates})
                )
            )
        }
        reconciled = 0
        for item, run_id in candidates:
            run = runs.get(run_id)
            if run is None or run.status != "completed_with_failures":
                continue
            item.status = "failed"
            item.error_code = JevDuplicateRunFailed.__name__
            item.error_message = "duplicate_run_completed_with_failures"
            reconciled += 1
        if reconciled:
            self._refresh_counts(batch)
            self.db.flush()
        return reconciled

    def recover_interrupted(self) -> int:
        batches = list(
            self.db.scalars(
                select(JevOperationBatch).where(
                    JevOperationBatch.status.in_(("running", "stopping"))
                )
            )
        )
        for batch in batches:
            batch.status = "stopped"
            batch.stop_requested_at = batch.stop_requested_at or utc_now()
            for item in batch.items:
                if item.status in {"pending", "running"}:
                    item.status = "stopped"
                    item.error_code = "service_restarted"
                    item.error_message = (
                        "Manual resume is required after service restart."
                    )
                    item.completed_at = utc_now()
            self._refresh_counts(batch)
        self.db.flush()
        return len(batches)

    def get(self, batch_id: str) -> JevOperationBatch:
        batch = self.db.get(JevOperationBatch, batch_id)
        if batch is None:
            raise KeyError(batch_id)
        return batch

    def list(self, *, limit: int = 20) -> list[JevOperationBatch]:
        return list(
            self.db.scalars(
                select(JevOperationBatch)
                .order_by(JevOperationBatch.created_at.desc())
                .limit(max(1, min(limit, 100)))
            )
        )

    def _select_jobs(self, request) -> list[Job]:
        query = (
            select(Job)
            .outerjoin(Company, Company.id == Job.company_id)
            .where(Job.is_deleted.is_(False))
        )
        if request.job_ids:
            query = query.where(Job.id.in_(request.job_ids))
        if request.source_sites:
            query = query.where(Job.source_site.in_(request.source_sites))
        if request.posted_date_from is not None:
            query = query.where(func.date(Job.posted_date) >= request.posted_date_from)
        if request.posted_date_to is not None:
            query = query.where(func.date(Job.posted_date) <= request.posted_date_to)
        if request.keyword:
            term = f"%{request.keyword.strip()}%"
            query = query.where(
                or_(
                    Job.title.ilike(term),
                    Job.description.ilike(term),
                    Company.name.ilike(term),
                )
            )
        execution_offset = (
            request.start_execution_batch - 1
        ) * request.execution_batch_size
        query = query.order_by(Job.created_at.asc(), Job.id.asc()).offset(
            request.job_offset + execution_offset
        )
        if request.max_jobs is not None:
            query = query.limit(request.max_jobs - execution_offset)
        return list(self.db.scalars(query).unique())

    def _eligibility(
        self,
        job: Job,
        operation: str,
        *,
        force: bool,
        skill_context: OnlineSkillCaseBuildContext | None = None,
        extracted_skills: tuple[dict[str, object], ...] = (),
        latest_skill: JevOnlineSkillClassification | None = None,
    ) -> OperationEligibility:
        if operation == "skills":
            case = build_online_skill_case(
                self.db,
                job_id=job.id,
                source_site=job.source_site,
                title=job.title,
                evidence_text=job.description or "",
                extracted_skills=extracted_skills,
                context=skill_context,
            )
            if case is None:
                return OperationEligibility(
                    operation, job.id, False, "missing_skill_evidence", None, 0
                )
            runner = JevOnlineSkillRunner(self.db)
            fingerprint = runner.dispatch(case).input_fingerprint
            if force:
                return OperationEligibility(
                    operation, job.id, True, "force_reevaluation", fingerprint, 1
                )
            if (
                latest_skill is not None
                and latest_skill.input_fingerprint == fingerprint
            ):
                if latest_skill.status == "answered":
                    return OperationEligibility(
                        operation, job.id, False, "successful_unchanged", fingerprint, 0
                    )
                if latest_skill.status in {"pending", "running"}:
                    return OperationEligibility(
                        operation, job.id, False, "already_running", fingerprint, 0
                    )
                return OperationEligibility(
                    operation, job.id, True, "previously_failed", fingerprint, 1
                )
            return OperationEligibility(
                operation, job.id, True, "eligible", fingerprint, 1
            )
        if operation == "related_jobs":
            settings = JevRuntimeSettingsService(self.db).get_or_create()
            plan = JevRelatedJobsService(self.db).plan(job.id, force=force)
            eligible = force or plan.eligibility != "successful_unchanged"
            return OperationEligibility(
                operation,
                job.id,
                eligible,
                plan.eligibility,
                plan.input_fingerprint,
                1 if eligible and plan.candidates else 0,
            )
        settings = JevRuntimeSettingsService(self.db).get_or_create()
        current = JevDuplicateAssociationService(self.db).list_for_job(job.id)
        fingerprint = normalized_content_hash(
            {
                "job_id": str(job.id),
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
                "candidate_limit": settings.duplicate_candidate_limit,
                "corpus_limit": settings.duplicate_corpus_limit,
            }
        )
        if current and not force:
            return OperationEligibility(
                operation, job.id, False, "successful_unchanged", fingerprint, 0
            )
        return OperationEligibility(
            operation,
            job.id,
            True,
            "force_reevaluation" if force else "eligible",
            fingerprint,
            settings.duplicate_candidate_limit,
        )

    def _load_skill_preview_inputs(
        self,
        jobs: list[Job],
    ) -> tuple[
        dict[UUID, tuple[dict[str, object], ...]],
        dict[UUID, JevOnlineSkillClassification],
    ]:
        job_ids = [job.id for job in jobs]
        if not job_ids:
            return {}, {}
        grouped_mentions: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        mentions = self.db.scalars(
            select(CurrentJobSkillMention)
            .where(
                CurrentJobSkillMention.job_id.in_(job_ids),
                CurrentJobSkillMention.status == "active",
                CurrentJobSkillMention.resolution.in_(("match_existing", "candidate")),
            )
            .order_by(
                CurrentJobSkillMention.job_id,
                CurrentJobSkillMention.created_at,
                CurrentJobSkillMention.id,
            )
        )
        for mention in mentions:
            grouped_mentions[mention.job_id].append(
                {
                    "name": mention.raw_name,
                    "existing_skill": mention.skill_code,
                    "evidence": "Historical active Skill mention; inspect the Job text.",
                }
            )
        latest_by_job: dict[UUID, JevOnlineSkillClassification] = {}
        classifications = self.db.scalars(
            select(JevOnlineSkillClassification)
            .where(JevOnlineSkillClassification.job_id.in_(job_ids))
            .order_by(
                JevOnlineSkillClassification.job_id,
                JevOnlineSkillClassification.created_at.desc(),
                JevOnlineSkillClassification.id.desc(),
            )
        )
        for classification in classifications:
            latest_by_job.setdefault(classification.job_id, classification)
        return (
            {job_id: tuple(values) for job_id, values in grouped_mentions.items()},
            latest_by_job,
        )

    async def _execute_item(
        self, item: JevOperationBatchItem, *, force: bool
    ) -> dict[str, object]:
        if item.operation == "skills":
            result = await JevSkillBackfillService().enrich_job_id(
                item.job_id,
                force=force,
                retry_terminal_failure=item.attempt_count > 1,
            )
            classification = result.get("jev_skill_classification") or {}
            if (
                result.get("status") != "success"
                or classification.get("status") != "answered"
            ):
                raise RuntimeError(
                    str(
                        result.get("error")
                        or classification.get("error_code")
                        or "Jev Skill correction failed"
                    )
                )
            return result
        if item.operation == "duplicate":
            settings = JevRuntimeSettingsService(self.db).get_or_create()
            duplicate_service = JevDuplicateAssociationService(self.db)
            plan = duplicate_service.start_for_job(
                item.job_id,
                candidate_limit=settings.duplicate_candidate_limit,
                corpus_limit=settings.duplicate_corpus_limit,
                force=force,
            )
            self.db.commit()
            if plan.run_id is None:
                return {
                    "status": "completed",
                    "candidate_count": 0,
                    "skipped_current_count": plan.skipped_current_count,
                }
            run = JevRunService(self.db).get(plan.run_id)
            evaluator = build_jev_evaluator(self.db, run)
            try:
                await duplicate_service.execute(run.id, evaluator=evaluator)
                self.db.commit()
            finally:
                await evaluator.aclose()
            self.db.expire_all()
            run = JevRunService(self.db).get(plan.run_id)
            if run.status != "completed":
                raise JevDuplicateRunFailed("duplicate_run_completed_with_failures")
            return {
                "status": "completed",
                "jev_run_id": run.id,
                "candidate_count": plan.candidate_count,
            }
        related_service = JevRelatedJobsService(self.db)
        evaluation = related_service.start(item.job_id, force=force)
        self.db.commit()
        if evaluation.status == "completed":
            return {
                "status": "completed",
                "evaluation_id": evaluation.id,
                "result_count": 0,
            }
        run = JevRunService(self.db).get(evaluation.jev_run_id)
        evaluator = build_jev_evaluator(self.db, run)
        try:
            evaluation = await related_service.execute(
                evaluation.id, evaluator=evaluator
            )
            self.db.commit()
        finally:
            await evaluator.aclose()
        if evaluation.status != "completed":
            raise RuntimeError(
                evaluation.error_code or "Related Jobs evaluation failed"
            )
        return {
            "status": "completed",
            "evaluation_id": evaluation.id,
            "jev_run_id": evaluation.jev_run_id,
            "result_count": len(evaluation.ordered_results or []),
        }

    @staticmethod
    def _operations(values: Iterable[str]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(str(value) for value in values))
        if not normalized or any(value not in OPERATIONS for value in normalized):
            raise ValueError("Select at least one supported Jev operation")
        return normalized

    @staticmethod
    def _reason_counts(states: list[OperationEligibility]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for state in states:
            counts[state.reason] = counts.get(state.reason, 0) + 1
        return counts

    @staticmethod
    def _stop_pending_items(batch: JevOperationBatch) -> None:
        for item in batch.items:
            if item.status == "pending":
                item.status = "stopped"
                item.completed_at = utc_now()

    @staticmethod
    def _refresh_counts(batch: JevOperationBatch) -> None:
        batch.total_items = len(batch.items)
        batch.pending_items = sum(item.status == "pending" for item in batch.items)
        batch.running_items = sum(item.status == "running" for item in batch.items)
        batch.completed_items = sum(item.status == "completed" for item in batch.items)
        batch.failed_items = sum(item.status == "failed" for item in batch.items)
        batch.skipped_items = sum(item.status == "skipped" for item in batch.items)

    def _finish(self, batch: JevOperationBatch) -> None:
        self._refresh_counts(batch)
        if any(item.status == "stopped" for item in batch.items):
            batch.status = "stopped"
            batch.completed_at = None
            return
        batch.status = "completed_with_failures" if batch.failed_items else "completed"
        batch.completed_at = utc_now()


def execute_jev_operation_batch(batch_id: str) -> None:
    """Run a durable batch outside the API event loop.

    Starlette dispatches synchronous background tasks through its worker thread
    pool. The batch service contains CPU-heavy candidate preparation and
    synchronous SQLAlchemy work around its awaited provider calls, so exposing
    this entry point as ``async`` would otherwise monopolize the API loop.
    """
    asyncio.run(_execute_jev_operation_batch(batch_id))


async def _execute_jev_operation_batch(batch_id: str) -> None:
    db = SessionLocal()
    try:
        await JevOperationBatchService(db).execute(batch_id)
    finally:
        db.close()


__all__ = [
    "JevOperationBatchService",
    "OperationEligibility",
    "execute_jev_operation_batch",
]
