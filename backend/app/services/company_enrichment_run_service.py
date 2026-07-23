from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import List, Optional

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import NoResultFound

from app.ai.llm_client import safe_llm_error_message
from app.models import Company
from app.models.company_enrichment_run import (
    CompanyEnrichmentRun,
    CompanyEnrichmentRunItem,
)
from app.services.ai_runtime_settings_service import AIRuntimeSettingsService
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
                Company.is_deleted.is_(False),
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

    def _count_items_by_status(self, run_id: str) -> dict[str, int]:
        counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
        rows = (
            self.db.query(
                CompanyEnrichmentRunItem.status,
                func.count(CompanyEnrichmentRunItem.id),
            )
            .filter(CompanyEnrichmentRunItem.run_id == run_id)
            .group_by(CompanyEnrichmentRunItem.status)
            .all()
        )
        for status, count in rows:
            counts[str(status)] = int(count)
        return counts

    def _resolve_latest_running_company_id(self, run_id: str):
        row = (
            self.db.query(CompanyEnrichmentRunItem.company_id)
            .filter(
                CompanyEnrichmentRunItem.run_id == run_id,
                CompanyEnrichmentRunItem.status == "running",
            )
            .order_by(
                CompanyEnrichmentRunItem.started_at.desc(),
                CompanyEnrichmentRunItem.position.desc(),
                CompanyEnrichmentRunItem.id.desc(),
            )
            .first()
        )
        return row[0] if row else None

    def _resolve_run_concurrency(self) -> int:
        try:
            return max(1, int(AIRuntimeSettingsService(self.db).get_effective_concurrency("companies") or 1))
        except Exception:
            return 1

    def _update_item_started(self, run_id: str, item_id: str, company_name: str) -> None:
        timestamp = utc_now()
        run = self.db.query(CompanyEnrichmentRun).filter(CompanyEnrichmentRun.id == run_id).one()
        item = self.db.query(CompanyEnrichmentRunItem).filter(CompanyEnrichmentRunItem.id == item_id).one()

        item.status = "running"
        item.started_at = item.started_at or timestamp
        item.completed_at = None
        item.error_message = None
        run.current_company_name = company_name
        run.error_message = None

        self.db.flush()
        counts = self._count_items_by_status(run_id)
        run.pending_items = counts["pending"]
        run.completed_items = counts["completed"]
        run.failed_items = counts["failed"]
        self.db.commit()

    def _update_item_finished(
        self,
        run_id: str,
        item_id: str,
        *,
        error_message: Optional[str],
        company_names_by_id: dict[uuid.UUID, str],
    ) -> None:
        timestamp = utc_now()
        run = self.db.query(CompanyEnrichmentRun).filter(CompanyEnrichmentRun.id == run_id).one()
        item = self.db.query(CompanyEnrichmentRunItem).filter(CompanyEnrichmentRunItem.id == item_id).one()

        if error_message is None:
            item.status = "completed"
            item.error_message = None
        else:
            item.status = "failed"
            item.error_message = error_message
        item.completed_at = timestamp

        # Clear the current label before any autoflush-triggering query so the run never
        # exposes a stale company name after the last running item has finished.
        run.current_company_name = None
        self.db.flush()
        counts = self._count_items_by_status(run_id)
        run.pending_items = counts["pending"]
        run.completed_items = counts["completed"]
        run.failed_items = counts["failed"]
        current_company_id = self._resolve_latest_running_company_id(run_id)
        run.current_company_name = company_names_by_id.get(current_company_id)
        self.db.commit()

    def create_pending_run(
        self,
        force_company_ids: Optional[List[str]] = None,
        web_search_enabled: bool = False,
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
                        Company.is_deleted.is_(False),
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
            web_search_enabled=bool(web_search_enabled),
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
        run.current_company_name = None
        self.db.commit()

        company_ids = [item.company_id for item in items]
        companies_by_id = {
            company.id: company
            for company in (
                self.db.query(Company)
                .filter(
                    Company.id.in_(company_ids),
                    Company.is_deleted.is_(False),
                )
                .all()
            )
        }
        company_names_by_id = {
            company_id: company.name
            for company_id, company in companies_by_id.items()
        }
        company_snapshots_by_id = {
            company_id: SimpleNamespace(
                id=company.id,
                name=company.name,
                industry=company.industry,
                location=company.location,
                ai_description=company.ai_description,
            )
            for company_id, company in companies_by_id.items()
        }

        concurrency = min(self._resolve_run_concurrency(), len(items) or 1)
        item_queue: asyncio.Queue[CompanyEnrichmentRunItem] = asyncio.Queue()
        for item in items:
            item_queue.put_nowait(item)

        try:
            async def worker() -> None:
                while True:
                    try:
                        item = item_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return

                    error_message = None
                    company = companies_by_id.get(item.company_id)
                    try:
                        if company is None:
                            raise NoResultFound(f"Company not found for enrichment run item {item.id}")
                        self._update_item_started(
                            run_id,
                            item.id,
                            company_names_by_id[item.company_id],
                        )
                        if hasattr(service, "enrich_company_id"):
                            await service.enrich_company_id(
                                item.company_id,
                                web_search_enabled=bool(run.web_search_enabled),
                            )
                        else:
                            await service.enrich_company_description(
                                company_snapshots_by_id[item.company_id],
                                self.db,
                                web_search_enabled=bool(run.web_search_enabled),
                            )
                    except Exception as exc:
                        error_message = safe_llm_error_message(exc)
                    finally:
                        self._update_item_finished(
                            run_id,
                            item.id,
                            error_message=error_message,
                            company_names_by_id=company_names_by_id,
                        )
                        item_queue.task_done()

            workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
            await asyncio.gather(*workers)
        except Exception as exc:
            failed_run = self.mark_run_failed(
                run_id,
                safe_llm_error_message(exc),
            )
            if failed_run is None:
                raise NoResultFound(f"Company Enrichment run not found: {run_id}")
            return failed_run

        self.db.expire_all()
        run = self.db.query(CompanyEnrichmentRun).filter(CompanyEnrichmentRun.id == run_id).one()
        counts = self._count_items_by_status(run_id)
        first_failed_item = (
            self.db.query(CompanyEnrichmentRunItem)
            .filter(
                CompanyEnrichmentRunItem.run_id == run_id,
                CompanyEnrichmentRunItem.status == "failed",
            )
            .order_by(
                CompanyEnrichmentRunItem.position.asc(),
                CompanyEnrichmentRunItem.id.asc(),
            )
            .first()
        )
        first_error_message = first_failed_item.error_message if first_failed_item is not None else None

        run.pending_items = counts["pending"]
        run.completed_items = counts["completed"]
        run.failed_items = counts["failed"]
        run.current_company_name = None
        run.completed_at = utc_now()
        if run.failed_items == 0:
            run.status = "completed"
            run.error_message = None
        elif run.completed_items == 0:
            run.status = "failed"
            run.error_message = first_error_message
        else:
            run.status = "completed_with_failures"
            run.error_message = (
                f"{run.failed_items} item(s) failed. First error: {first_error_message}"
                if first_error_message
                else f"{run.failed_items} item(s) failed"
            )
        self.db.commit()
        self.db.refresh(run)
        return run
