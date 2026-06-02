from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import and_, case, or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import NoResultFound

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
            self.db.query(Company.id)
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
        current_statuses = ACTIVE_RUN_STATUSES + TERMINAL_RUN_STATUSES
        status_priority = case(
            (CompanyEnrichmentRun.status.in_(ACTIVE_RUN_STATUSES), 0),
            else_=1,
        )
        recency_timestamp = case(
            (CompanyEnrichmentRun.status.in_(ACTIVE_RUN_STATUSES), CompanyEnrichmentRun.created_at),
            else_=CompanyEnrichmentRun.completed_at,
        )
        return (
            self.db.query(CompanyEnrichmentRun)
            .filter(CompanyEnrichmentRun.status.in_(current_statuses))
            .order_by(
                status_priority.asc(),
                recency_timestamp.desc(),
                CompanyEnrichmentRun.created_at.desc(),
                CompanyEnrichmentRun.id.desc(),
            )
            .first()
        )

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

    def list_run_items_or_none(self, run_id: str) -> Optional[List[CompanyEnrichmentRunItem]]:
        """List items for an existing company run in one query, or return None when the run is missing."""
        rows = (
            self.db.query(
                CompanyEnrichmentRun.id.label("run_id"),
                CompanyEnrichmentRunItem,
            )
            .select_from(CompanyEnrichmentRun)
            .outerjoin(
                CompanyEnrichmentRunItem,
                CompanyEnrichmentRunItem.run_id == CompanyEnrichmentRun.id,
            )
            .filter(CompanyEnrichmentRun.id == run_id)
            .order_by(
                CompanyEnrichmentRunItem.position.asc(),
                CompanyEnrichmentRunItem.id.asc(),
            )
            .all()
        )
        if not rows:
            return None
        return [item for _, item in rows if item is not None]

    def create_pending_run(
        self,
        force_company_ids: Optional[List[str]] = None,
    ) -> Optional[CompanyEnrichmentRun]:
        if force_company_ids is None:
            company_ids = [company_id for (company_id,) in self._pending_company_query().all()]
        else:
            normalized_company_ids = [uuid.UUID(str(company_id)) for company_id in force_company_ids]
            existing_company_ids = {
                company_id
                for (company_id,) in (
                    self.db.query(Company.id)
                    .filter(
                        Company.id.in_(normalized_company_ids),
                        Company.is_deleted == False,
                    )
                    .all()
                )
            }
            company_ids = [
                company_id
                for company_id in normalized_company_ids
                if company_id in existing_company_ids
            ]

        if not company_ids:
            return None

        run = CompanyEnrichmentRun(
            status="pending",
            total_items=len(company_ids),
            pending_items=len(company_ids),
            completed_items=0,
            failed_items=0,
        )
        self.db.add(run)
        self.db.flush()

        for position, company_id in enumerate(company_ids):
            self.db.add(
                CompanyEnrichmentRunItem(
                    run_id=run.id,
                    company_id=company_id,
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
        first_error_message = None
        company_ids = [item.company_id for item in items]
        companies_by_id = {
            company.id: company
            for company in (
                self.db.query(Company)
                .filter(
                    Company.id.in_(company_ids),
                    Company.is_deleted == False,
                )
                .all()
            )
        }

        for item in items:
            company = companies_by_id.get(item.company_id)
            if company is None:
                raise NoResultFound(f"Company not found for enrichment run item {item.id}")
            item.status = "running"
            item.started_at = item.started_at or utc_now()
            item.completed_at = None
            item.error_message = None
            run.current_company_name = company.name
            self.db.flush()

            try:
                await service.enrich_company_description(company, self.db)
                item.status = "completed"
                item.error_message = None
                item.completed_at = utc_now()
                completed_items += 1
            except Exception as exc:
                item.status = "failed"
                item.error_message = str(exc)
                item.completed_at = utc_now()
                failed_items += 1
                if first_error_message is None:
                    first_error_message = str(exc)

            run.current_company_name = None
            run.pending_items = max(run.total_items - completed_items - failed_items, 0)
            run.completed_items = completed_items
            run.failed_items = failed_items
            if run.pending_items == 0:
                run.completed_at = item.completed_at or utc_now()
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
            else:
                run.status = "running"
                run.completed_at = None
                run.error_message = None
            self.db.flush()

        return run
