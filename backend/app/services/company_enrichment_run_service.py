from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models import Company
from app.models.company_enrichment_run import (
    CompanyEnrichmentRun,
    CompanyEnrichmentRunItem,
)
from app.utils.time import utc_now

ACTIVE_RUN_STATUSES = ("pending", "running")
TERMINAL_RUN_STATUSES = ("completed", "completed_with_failures", "failed")


class CompanyEnrichmentRunService:
    """Persist and execute company enrichment runs."""

    def __init__(self, db: Session):
        self.db = db

    def _pending_company_query(self):
        return (
            self.db.query(Company)
            .filter(
                Company.is_deleted == False,
                or_(Company.ai_description.is_(None), Company.ai_description == ""),
            )
            .order_by(Company.created_at.asc(), Company.name.asc(), Company.id.asc())
        )

    def get_active_run(self) -> Optional[CompanyEnrichmentRun]:
        return (
            self.db.query(CompanyEnrichmentRun)
            .filter(CompanyEnrichmentRun.status.in_(ACTIVE_RUN_STATUSES))
            .order_by(
                CompanyEnrichmentRun.created_at.desc(),
                CompanyEnrichmentRun.id.desc(),
            )
            .first()
        )

    def get_latest_terminal_run(self) -> Optional[CompanyEnrichmentRun]:
        return (
            self.db.query(CompanyEnrichmentRun)
            .filter(CompanyEnrichmentRun.status.in_(TERMINAL_RUN_STATUSES))
            .order_by(
                CompanyEnrichmentRun.completed_at.desc(),
                CompanyEnrichmentRun.created_at.desc(),
                CompanyEnrichmentRun.id.desc(),
            )
            .first()
        )

    def get_current_run(self) -> Optional[CompanyEnrichmentRun]:
        return self.get_active_run() or self.get_latest_terminal_run()

    def get_run(self, run_id: str) -> Optional[CompanyEnrichmentRun]:
        return (
            self.db.query(CompanyEnrichmentRun)
            .filter(CompanyEnrichmentRun.id == run_id)
            .first()
        )

    def list_run_items(self, run_id: str) -> List[CompanyEnrichmentRunItem]:
        return (
            self.db.query(CompanyEnrichmentRunItem)
            .filter(CompanyEnrichmentRunItem.run_id == run_id)
            .order_by(CompanyEnrichmentRunItem.position.asc())
            .all()
        )

    def create_pending_run(
        self,
        force_company_ids: Optional[List[str]] = None,
    ) -> Optional[CompanyEnrichmentRun]:
        if force_company_ids is None:
            companies = self._pending_company_query().all()
        else:
            normalized_company_ids = [uuid.UUID(str(company_id)) for company_id in force_company_ids]
            company_rows = (
                self.db.query(Company)
                .filter(
                    Company.id.in_(normalized_company_ids),
                    Company.is_deleted == False,
                )
                .all()
            )
            company_map = {str(company.id): company for company in company_rows}
            companies = [
                company_map[str(company_id)]
                for company_id in normalized_company_ids
                if str(company_id) in company_map
            ]

        if not companies:
            return None

        run = CompanyEnrichmentRun(
            status="pending",
            total_items=len(companies),
            pending_items=len(companies),
            completed_items=0,
            failed_items=0,
        )
        self.db.add(run)
        self.db.flush()

        for position, company in enumerate(companies):
            self.db.add(
                CompanyEnrichmentRunItem(
                    run_id=run.id,
                    company_id=company.id,
                    position=position,
                    status="pending",
                )
            )

        self.db.flush()
        return run

    def mark_run_failed(self, run_id: str, error_message: str) -> Optional[CompanyEnrichmentRun]:
        run = self.get_run(run_id)
        if run is None:
            return None

        items = self.list_run_items(run_id)
        timestamp = utc_now()
        completed_items = 0
        failed_items = 0
        first_error_message = None

        for item in items:
            if item.status == "completed":
                completed_items += 1
                continue

            item.status = "failed"
            item.error_message = item.error_message or error_message
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
        run.error_message = error_message
        self.db.flush()
        return run

    async def execute_run(self, run_id: str, enrichment_service=None) -> CompanyEnrichmentRun:
        from app.services.company_enrichment_service import CompanyEnrichmentService

        run = self.db.query(CompanyEnrichmentRun).filter_by(id=run_id).one()
        items = (
            self.db.query(CompanyEnrichmentRunItem)
            .filter_by(run_id=run_id)
            .order_by(CompanyEnrichmentRunItem.position.asc())
            .all()
        )

        service = enrichment_service or CompanyEnrichmentService()
        now = utc_now()
        run.status = "running"
        run.started_at = run.started_at or now
        run.completed_at = None
        run.error_message = None
        self.db.flush()

        completed_items = 0
        failed_items = 0

        for item in items:
            company = (
                self.db.query(Company)
                .filter(
                    Company.id == item.company_id,
                    Company.is_deleted == False,
                )
                .one()
            )
            item.status = "running"
            item.started_at = item.started_at or utc_now()
            run.current_company_name = company.name
            self.db.flush()

            try:
                await service.enrich_company_description(company, self.db)
                item.status = "completed"
                item.completed_at = utc_now()
                completed_items += 1
            except Exception as exc:
                item.status = "failed"
                item.error_message = str(exc)
                item.completed_at = utc_now()
                failed_items += 1
                if first_error_message is None:
                    first_error_message = str(exc)

            run.pending_items = max(run.total_items - completed_items - failed_items, 0)
            run.completed_items = completed_items
            run.failed_items = failed_items
            self.db.flush()

        run.current_company_name = None
        run.completed_at = utc_now()
        if failed_items == 0:
            run.status = "completed"
            run.error_message = None
        elif completed_items == 0:
            run.status = "failed"
            run.error_message = first_error_message
        else:
            run.status = "completed_with_failures"
            run.error_message = (
                f"{failed_items} item(s) failed. First error: {first_error_message}"
                if first_error_message
                else f"{failed_items} item(s) failed"
            )
        self.db.flush()
        return run
