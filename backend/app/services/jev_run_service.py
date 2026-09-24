from __future__ import annotations

import hashlib
from collections.abc import Sequence
from decimal import Decimal, ROUND_CEILING

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.ai.system_one import SystemOneRequest
from app.models.jev import JevRun, JevRunAttempt, JevRunItem
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService
from app.utils.time import utc_now


class JevRunConfigurationError(ValueError):
    pass


class JevRunService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def start(
        self,
        *,
        purpose: str,
        rubric_version: str,
        items: Sequence[dict[str, object]],
        profile: str = "online",
    ) -> JevRun:
        if not purpose.strip() or not rubric_version.strip():
            raise ValueError("purpose and rubric_version are required")
        if not items:
            raise ValueError("at least one work item is required")
        if profile not in {"online", "maintenance"}:
            raise ValueError("unknown Jev run profile")
        settings = JevRuntimeSettingsService(self.db).get_or_create()
        if not settings.enabled:
            raise JevRunConfigurationError("Jev is disabled")
        if not settings.api_key:
            raise JevRunConfigurationError("Jev API key is missing")
        subject_ids = [str(item.get("subject_id") or "").strip() for item in items]
        if any(not subject_id for subject_id in subject_ids):
            raise ValueError("every work item needs a subject_id")
        if len(subject_ids) != len(set(subject_ids)):
            raise ValueError("work item subject_id values must be unique")

        run = JevRun(
            purpose=purpose.strip(),
            rubric_version=rubric_version.strip(),
            status="pending",
            settings_snapshot=self._snapshot(settings, profile=profile),
            total_items=len(items),
            pending_items=len(items),
        )
        self.db.add(run)
        self.db.flush()
        for position, item in enumerate(items):
            payload = item.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("work item payload must be an object")
            evidence_refs = item.get("evidence_refs", [])
            if not isinstance(evidence_refs, list) or any(
                not isinstance(reference, str) or not reference.strip()
                for reference in evidence_refs
            ):
                raise ValueError("work item evidence_refs must be non-blank strings")
            self.db.add(
                JevRunItem(
                    run_id=run.id,
                    subject_id=subject_ids[position],
                    position=position,
                    evidence_refs=list(evidence_refs),
                    payload=dict(payload),
                    status="pending",
                )
            )
        self.db.flush()
        self.db.refresh(run)
        return run

    def request_stop(self, run_id: str) -> JevRun:
        run = self._locked_run(run_id)
        if run.status in {"completed", "completed_with_failures", "cancelled"}:
            return run
        now = utc_now()
        run.stop_requested_at = run.stop_requested_at or now
        self.db.execute(
            update(JevRunItem)
            .where(JevRunItem.run_id == run.id, JevRunItem.status == "pending")
            .values(status="cancelled", completed_at=now)
        )
        self.db.flush()
        self._refresh_counts(run)
        if run.running_items:
            run.status = "stopping"
        else:
            run.status = "cancelled"
            run.completed_at = now
        self.db.flush()
        self.db.expire_all()
        return self.get(run_id)

    def resume(self, run_id: str) -> JevRun:
        run = self._locked_run(run_id)
        if run.status != "cancelled":
            raise ValueError("only a cancelled Jev run can be resumed")
        self.db.execute(
            update(JevRunItem)
            .where(JevRunItem.run_id == run.id, JevRunItem.status == "cancelled")
            .values(
                status="pending",
                error_code=None,
                error_message=None,
                started_at=None,
                completed_at=None,
            )
        )
        run.status = "pending"
        run.stop_requested_at = None
        run.completed_at = None
        self.db.flush()
        self._refresh_counts(run)
        self.db.flush()
        self.db.expire_all()
        return self.get(run_id)

    def retry_failed(self, run_id: str) -> JevRun:
        run = self._locked_run(run_id)
        if run.status != "completed_with_failures":
            raise ValueError("only a failed terminal Jev run can be retried")
        retry_limit = run.settings_snapshot.get("retry_limit")
        if not isinstance(retry_limit, int):
            raise JevRunConfigurationError("run retry limit is invalid")
        failed_items = list(
            self.db.scalars(
                select(JevRunItem)
                .where(JevRunItem.run_id == run.id, JevRunItem.status == "failed")
                .order_by(JevRunItem.position, JevRunItem.id)
                .with_for_update()
            )
        )
        eligible = [item for item in failed_items if item.attempt_count <= retry_limit]
        if not eligible:
            raise ValueError("frozen retry limit has been reached")
        for item in eligible:
            item.status = "pending"
            item.error_code = None
            item.error_message = None
            item.started_at = None
            item.completed_at = None
        run.status = "pending"
        run.completed_at = None
        self.db.flush()
        self._refresh_counts(run)
        self.db.flush()
        self.db.expire_all()
        return self.get(run_id)

    def claim_next_item(self, run_id: str) -> JevRunItem | None:
        run = self._locked_run(run_id)
        if run.status not in {"pending", "running"} or run.stop_requested_at:
            return None
        concurrency = run.settings_snapshot.get("concurrency")
        if not isinstance(concurrency, int) or concurrency < 1:
            raise JevRunConfigurationError("run concurrency is invalid")
        if run.running_items >= concurrency:
            return None
        item = self.db.scalar(
            select(JevRunItem)
            .where(JevRunItem.run_id == run.id, JevRunItem.status == "pending")
            .order_by(JevRunItem.position, JevRunItem.id)
            .limit(1)
            .with_for_update()
        )
        if item is None:
            return None
        now = utc_now()
        if run.status == "pending":
            run.status = "running"
            run.started_at = now
        item.status = "running"
        item.started_at = now
        item.attempt_count += 1
        self.db.flush()
        self._refresh_counts(run)
        return item

    def get(self, run_id: str) -> JevRun:
        run = self.db.get(JevRun, run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    async def execute_next(self, run_id: str, *, evaluator) -> JevRunItem | None:
        item = self.claim_next_item(run_id)
        if item is None:
            return None
        run = self.get(run_id)
        request = SystemOneRequest.model_validate(
            {
                "state": item.payload.get("state"),
                "model": run.settings_snapshot["model"],
                "questions": item.payload.get("questions"),
            }
        )
        attempt_number = item.attempt_count
        attempt = JevRunAttempt(
            item_id=item.id,
            attempt_number=attempt_number,
            status="dispatched",
        )
        self.db.add(attempt)
        self.db.flush()

        try:
            result = await evaluator.evaluate(request)
        except Exception:
            now = utc_now()
            attempt.status = "unavailable"
            attempt.error_code = "transport_error"
            attempt.error_message = "External Jev request failed"
            attempt.completed_at = now
            item.status = "failed"
            item.error_code = attempt.error_code
            item.error_message = attempt.error_message
            item.completed_at = now
            self.db.flush()
            self._finish_if_terminal(run, now=now)
            return item
        now = utc_now()
        attempt.status = result.status
        attempt.model = result.model
        attempt.error_code = result.error_code
        attempt.error_message = result.error_message
        attempt.completed_at = now
        if result.usage is not None:
            attempt.input_tokens = result.usage.input_tokens
            attempt.output_tokens = result.usage.output_tokens
        if result.status in {"answered", "abstained"}:
            serialized_answers = {
                name: answer.model_dump() for name, answer in result.answers.items()
            }
            receipt = {
                "status": result.status,
                "model": result.model,
                "answers": serialized_answers,
                "usage": (
                    result.usage.model_dump(exclude_none=True) if result.usage else None
                ),
                "latency_ms": result.latency_ms,
            }
            if result.request_id is not None:
                receipt["request_id"] = result.request_id
            if result.provider is not None:
                receipt["provider"] = result.provider
            item.status = "completed"
            item.result = receipt
            item.completed_at = now
            attempt.result = receipt
            attempt.actual_microdollars = self._provider_cost_microdollars(
                usage=result.usage
            )
        else:
            item.status = "failed"
            item.error_code = result.error_code
            item.error_message = result.error_message
            item.completed_at = now
        self.db.flush()
        self._refresh_counts(run)
        self._finish_if_terminal(run, now=now)
        return item

    def _finish_if_terminal(self, run: JevRun, *, now) -> None:
        self._refresh_counts(run)
        if run.pending_items == 0 and run.running_items == 0:
            run.status = "completed_with_failures" if run.failed_items else "completed"
            run.completed_at = now
        self.db.flush()

    @staticmethod
    def _provider_cost_microdollars(*, usage) -> int | None:
        if usage is None or usage.cost is None:
            return None
        return int(
            (Decimal(str(usage.cost)) * 1_000_000).to_integral_value(
                rounding=ROUND_CEILING
            )
        )

    def _locked_run(self, run_id: str) -> JevRun:
        run = self.db.scalar(
            select(JevRun).where(JevRun.id == run_id).with_for_update()
        )
        if run is None:
            raise KeyError(run_id)
        return run

    def _refresh_counts(self, run: JevRun) -> None:
        counts = dict(
            self.db.execute(
                select(JevRunItem.status, func.count(JevRunItem.id))
                .where(JevRunItem.run_id == run.id)
                .group_by(JevRunItem.status)
            ).all()
        )
        run.pending_items = int(counts.get("pending", 0))
        run.running_items = int(counts.get("running", 0))
        run.completed_items = int(counts.get("completed", 0))
        run.failed_items = int(counts.get("failed", 0))
        run.cancelled_items = int(counts.get("cancelled", 0))

    @staticmethod
    def _snapshot(settings, *, profile: str) -> dict[str, object]:
        api_key_fingerprint = hashlib.sha256(
            settings.api_key.encode("utf-8")
        ).hexdigest()
        return {
            "endpoint": settings.endpoint,
            "model": (
                settings.maintenance_model
                if profile == "maintenance"
                else settings.model
            ),
            "api_key_fingerprint": api_key_fingerprint,
            "question_batch_limit": settings.question_batch_limit,
            "concurrency": settings.concurrency,
            "retry_limit": settings.retry_limit,
            "timeout_seconds": settings.timeout_seconds,
            "evidence_threshold_millis": settings.evidence_threshold_millis,
            "recommendation_threshold_millis": (
                settings.maintenance_threshold_millis
                if profile == "maintenance"
                else settings.recommendation_threshold_millis
            ),
        }


__all__ = ["JevRunConfigurationError", "JevRunService"]
