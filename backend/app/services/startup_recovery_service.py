from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.enrichment_run import EnrichmentRun
from app.models.company_enrichment_run import CompanyEnrichmentRun
from app.models.schedule import ScheduleExecution
from app.services.company_enrichment_run_service import (
    ACTIVE_RUN_STATUSES as ACTIVE_COMPANY_RUN_STATUSES,
    CompanyEnrichmentRunService,
)
from app.services.enrichment_run_service import (
    ACTIVE_RUN_STATUSES as ACTIVE_AI_RUN_STATUSES,
    EnrichmentRunService,
)
from app.utils.time import utc_now

AI_RESTART_MESSAGE = "Service restarted before AI enrichment run could finish."
COMPANY_RESTART_MESSAGE = "Service restarted before company enrichment run could finish."
SCHEDULE_RESTART_MESSAGE = "Service restarted before scheduled scrape execution could finish."
ACTIVE_SCHEDULE_EXECUTION_STATUSES = ("pending", "running", "ai_running")


class StartupRecoveryService:
    """Convert interrupted in-process work into explicit terminal failure states on startup."""

    def __init__(self, db: Session):
        self.db = db

    def recover_interrupted_operations(self) -> dict[str, int]:
        ai_run_ids = [
            run_id
            for (run_id,) in (
                self.db.query(EnrichmentRun.id)
                .filter(EnrichmentRun.status.in_(ACTIVE_AI_RUN_STATUSES))
                .all()
            )
        ]
        company_run_ids = [
            run_id
            for (run_id,) in (
                self.db.query(CompanyEnrichmentRun.id)
                .filter(CompanyEnrichmentRun.status.in_(ACTIVE_COMPANY_RUN_STATUSES))
                .all()
            )
        ]
        schedule_executions = (
            self.db.query(ScheduleExecution)
            .filter(ScheduleExecution.status.in_(ACTIVE_SCHEDULE_EXECUTION_STATUSES))
            .all()
        )

        ai_service = EnrichmentRunService(self.db)
        for run_id in ai_run_ids:
            ai_service.mark_run_failed(run_id, AI_RESTART_MESSAGE)

        company_service = CompanyEnrichmentRunService(self.db)
        for run_id in company_run_ids:
            company_service.mark_run_failed(run_id, COMPANY_RESTART_MESSAGE)

        recovery_timestamp = utc_now()
        for execution in schedule_executions:
            execution.status = "failed"
            execution.completed_at = execution.completed_at or recovery_timestamp
            execution.error_message = SCHEDULE_RESTART_MESSAGE
            if execution.duration_seconds is None and execution.started_at is not None:
                try:
                    execution.duration_seconds = max(
                        0,
                        int((execution.completed_at - execution.started_at).total_seconds()),
                    )
                except TypeError:
                    execution.duration_seconds = None

        self.db.commit()
        return {
            "ai_runs_recovered": len(ai_run_ids),
            "company_runs_recovered": len(company_run_ids),
            "schedule_executions_recovered": len(schedule_executions),
        }
