from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.models.company_enrichment_run import CompanyEnrichmentRun, CompanyEnrichmentRunItem
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.utils.time import utc_now

AI_RESTART_MESSAGE = "Service restarted before AI enrichment run could finish."
COMPANY_RESTART_MESSAGE = "Service restarted before company enrichment run could finish."
SCHEDULE_RESTART_MESSAGE = "Service restarted before scheduled scrape execution could finish."
ACTIVE_SCHEDULE_EXECUTION_STATUSES = ("pending", "running", "ai_running")
ACTIVE_AI_RUN_STATUSES = ("pending", "running")
ACTIVE_COMPANY_RUN_STATUSES = ("pending", "running")

logger = logging.getLogger(__name__)


class StartupRecoveryService:
    """Convert interrupted in-process work into explicit terminal failure states on startup."""

    def __init__(self, db: Session):
        self.db = db

    def recover_interrupted_operations(self) -> dict[str, int]:
        ai_run_count = self._recover_ai_runs()
        company_run_count = self._recover_company_runs()
        self.db.commit()

        schedule_recovery_count = 0
        try:
            schedule_recovery_count = self._recover_schedule_executions()
            self.db.commit()
        except Exception:
            self.db.rollback()
            logger.exception("Startup schedule execution recovery failed")

        return {
            "ai_runs_recovered": ai_run_count,
            "company_runs_recovered": company_run_count,
            "schedule_executions_recovered": schedule_recovery_count,
        }

    def _recover_ai_runs(self) -> int:
        active_runs = (
            self.db.query(EnrichmentRun)
            .filter(EnrichmentRun.status.in_(ACTIVE_AI_RUN_STATUSES))
            .all()
        )
        timestamp = utc_now()
        if not active_runs:
            return 0

        for run in active_runs:
            items = (
                self.db.query(EnrichmentRunItem)
                .filter(EnrichmentRunItem.run_id == run.id)
                .all()
            )
            completed_items = 0
            failed_items = 0

            for item in items:
                if item.status == "completed":
                    completed_items += 1
                    continue

                item.status = "failed"
                item.error_message = AI_RESTART_MESSAGE
                item.started_at = item.started_at or timestamp
                item.completed_at = item.completed_at or timestamp
                failed_items += 1

            run.status = "failed" if completed_items == 0 else "completed_with_failures"
            run.pending_items = 0
            run.completed_items = completed_items
            run.failed_items = failed_items
            run.started_at = run.started_at or timestamp
            run.completed_at = timestamp
            run.current_job_title = None
            run.error_message = AI_RESTART_MESSAGE

        return len(active_runs)

    def _recover_company_runs(self) -> int:
        active_runs = (
            self.db.query(CompanyEnrichmentRun)
            .filter(CompanyEnrichmentRun.status.in_(ACTIVE_COMPANY_RUN_STATUSES))
            .all()
        )
        timestamp = utc_now()
        if not active_runs:
            return 0

        for run in active_runs:
            items = (
                self.db.query(CompanyEnrichmentRunItem)
                .filter(CompanyEnrichmentRunItem.run_id == run.id)
                .all()
            )
            completed_items = 0
            failed_items = 0

            for item in items:
                if item.status == "completed":
                    completed_items += 1
                    continue

                item.status = "failed"
                item.error_message = item.error_message or COMPANY_RESTART_MESSAGE
                item.started_at = item.started_at or timestamp
                item.completed_at = item.completed_at or timestamp
                failed_items += 1

            run.status = "failed" if completed_items == 0 else "completed_with_failures"
            run.pending_items = 0
            run.completed_items = completed_items
            run.failed_items = failed_items
            run.started_at = run.started_at or timestamp
            run.completed_at = timestamp
            run.current_company_name = None
            run.error_message = COMPANY_RESTART_MESSAGE

        return len(active_runs)

    def _recover_schedule_executions(self) -> int:
        inspector = inspect(self.db.get_bind())
        available_columns = {
            column["name"]
            for column in inspector.get_columns("schedule_executions")
        }
        if "id" not in available_columns or "status" not in available_columns:
            return 0

        select_columns = ["id", "status"]
        for optional_column in ("started_at", "completed_at", "duration_seconds"):
            if optional_column in available_columns:
                select_columns.append(optional_column)

        rows = self.db.execute(
            text(
                f"""
                SELECT {", ".join(select_columns)}
                FROM schedule_executions
                WHERE status IN ('pending', 'running', 'ai_running')
                """
            )
        ).mappings().all()

        recovery_timestamp = utc_now()
        for row in rows:
            updates = {
                "status": "failed",
            }
            if "completed_at" in available_columns:
                updates["completed_at"] = row.get("completed_at") or recovery_timestamp
            if "error_message" in available_columns:
                updates["error_message"] = SCHEDULE_RESTART_MESSAGE
            if "duration_seconds" in available_columns and row.get("duration_seconds") is None:
                started_at = row.get("started_at")
                completed_at = updates.get("completed_at")
                if started_at is not None and completed_at is not None:
                    try:
                        updates["duration_seconds"] = max(
                            0,
                            int((completed_at - started_at).total_seconds()),
                        )
                    except TypeError:
                        updates["duration_seconds"] = None

            assignments = ", ".join(f"{column} = :{column}" for column in updates)
            self.db.execute(
                text(f"UPDATE schedule_executions SET {assignments} WHERE id = :execution_id"),
                {"execution_id": row["id"], **updates},
            )

        return len(rows)
