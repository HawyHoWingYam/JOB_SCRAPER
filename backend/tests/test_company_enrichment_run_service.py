from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.company import Company
from app.models.company_enrichment_run import CompanyEnrichmentRun, CompanyEnrichmentRunItem
from app.services.company_enrichment_run_service import CompanyEnrichmentRunService


class _FakeQuery:
    def __init__(self, *, all_result=None, first_result=None):
        self.all_result = list(all_result or [])
        self.first_result = first_result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.all_result)

    def first(self):
        return self.first_result


class _FakeDB:
    def __init__(self, queries):
        self._queries = list(queries)
        self.query_calls = []
        self.added = []

    def query(self, *entities):
        self.query_calls.append(entities)
        if not self._queries:
            raise AssertionError("Unexpected query call")
        return self._queries.pop(0)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        for obj in self.added:
            if isinstance(obj, CompanyEnrichmentRun) and not getattr(obj, "id", None):
                obj.id = "run-1"


def _create_company_enrichment_service_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__,
            CompanyEnrichmentRun.__table__,
            CompanyEnrichmentRunItem.__table__,
        ],
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session_factory()

    company_ids = [uuid4(), uuid4()]
    db.add_all(
        [
            Company(
                id=company_ids[0],
                company_id="company-1",
                source_site="jobsdb",
                source_company_id="company-1",
                name="Example Co 1",
            ),
            Company(
                id=company_ids[1],
                company_id="company-2",
                source_site="jobsdb",
                source_company_id="company-2",
                name="Example Co 2",
            ),
        ]
    )
    db.commit()
    return engine, db, company_ids


def test_create_pending_run_queries_pending_company_ids_only():
    company_id_a = uuid4()
    company_id_b = uuid4()
    db = _FakeDB([
        _FakeQuery(all_result=[(company_id_a,), (company_id_b,)]),
    ])
    service = CompanyEnrichmentRunService(db)

    run = service.create_pending_run()

    assert db.query_calls[0] == (Company.id,)
    assert run is not None
    assert run.total_items == 2
    assert run.pending_items == 2

    items = [obj for obj in db.added if isinstance(obj, CompanyEnrichmentRunItem)]
    assert [item.company_id for item in items] == [company_id_a, company_id_b]


def test_create_pending_run_with_force_company_ids_queries_ids_only_and_preserves_requested_order():
    company_id_a = uuid4()
    company_id_b = uuid4()
    db = _FakeDB([
        _FakeQuery(all_result=[(company_id_a,), (company_id_b,)]),
    ])
    service = CompanyEnrichmentRunService(db)

    run = service.create_pending_run(force_company_ids=[str(company_id_b), str(company_id_a)])

    assert db.query_calls[0] == (Company.id,)
    assert run is not None
    items = [obj for obj in db.added if isinstance(obj, CompanyEnrichmentRunItem)]
    assert [item.company_id for item in items] == [company_id_b, company_id_a]


def test_get_current_run_uses_single_query_for_active_or_latest_terminal_selection():
    active_run = object()
    db = _FakeDB([
        _FakeQuery(first_result=active_run),
    ])
    service = CompanyEnrichmentRunService(db)

    result = service.get_current_run()

    assert result is active_run
    assert len(db.query_calls) == 1


def test_get_current_run_uses_single_query_when_only_terminal_run_exists():
    terminal_run = object()
    db = _FakeDB([
        _FakeQuery(first_result=terminal_run),
    ])
    service = CompanyEnrichmentRunService(db)

    result = service.get_current_run()

    assert result is terminal_run
    assert len(db.query_calls) == 1


def test_list_run_items_or_none_distinguishes_missing_empty_and_present_runs_with_single_select():
    engine, db, company_ids = _create_company_enrichment_service_db()
    db.add_all(
        [
            CompanyEnrichmentRun(
                id="run-empty",
                status="completed",
                total_items=0,
                pending_items=0,
                completed_items=0,
                failed_items=0,
                created_at=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
            ),
            CompanyEnrichmentRun(
                id="run-with-items",
                status="completed_with_failures",
                total_items=2,
                pending_items=0,
                completed_items=1,
                failed_items=1,
                created_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
            ),
        ]
    )
    db.add_all(
        [
            CompanyEnrichmentRunItem(
                id="item-completed",
                run_id="run-with-items",
                company_id=company_ids[0],
                position=0,
                status="completed",
                created_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
            ),
            CompanyEnrichmentRunItem(
                id="item-failed",
                run_id="run-with-items",
                company_id=company_ids[1],
                position=1,
                status="failed",
                created_at=datetime(2026, 5, 28, 9, 1, tzinfo=UTC),
            ),
        ]
    )
    db.commit()

    select_statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def _count_selects(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    try:
        service = CompanyEnrichmentRunService(db)
        missing_items = service.list_run_items_or_none("run-missing")
        empty_items = service.list_run_items_or_none("run-empty")
        present_items = service.list_run_items_or_none("run-with-items")
    finally:
        event.remove(engine, "before_cursor_execute", _count_selects)
        db.close()

    assert missing_items is None
    assert empty_items == []
    assert [item.id for item in present_items] == ["item-completed", "item-failed"]
    assert len(select_statements) == 3


def test_execute_run_preloads_companies_with_single_company_select():
    engine, db, company_ids = _create_company_enrichment_service_db()
    db.add(
        CompanyEnrichmentRun(
            id="run-execute",
            status="pending",
            total_items=2,
            pending_items=2,
            completed_items=0,
            failed_items=0,
            created_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
        )
    )
    db.add_all(
        [
            CompanyEnrichmentRunItem(
                id="item-1",
                run_id="run-execute",
                company_id=company_ids[0],
                position=0,
                status="pending",
                created_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
            ),
            CompanyEnrichmentRunItem(
                id="item-2",
                run_id="run-execute",
                company_id=company_ids[1],
                position=1,
                status="pending",
                created_at=datetime(2026, 5, 28, 9, 1, tzinfo=UTC),
            ),
        ]
    )
    db.commit()

    company_select_statements = []
    observed_company_names = []

    class _FakeEnrichmentService:
        async def enrich_company_description(self, company, db_session):
            observed_company_names.append(company.name)

    @event.listens_for(engine, "before_cursor_execute")
    def _count_company_selects(conn, cursor, statement, parameters, context, executemany):
        normalized_statement = statement.lstrip().upper()
        if normalized_statement.startswith("SELECT") and "FROM COMPANIES" in normalized_statement:
            company_select_statements.append(statement)

    try:
        run = asyncio.run(
            CompanyEnrichmentRunService(db).execute_run(
                "run-execute",
                enrichment_service=_FakeEnrichmentService(),
            )
        )
    finally:
        event.remove(engine, "before_cursor_execute", _count_company_selects)
        db.close()

    assert observed_company_names == ["Example Co 1", "Example Co 2"]
    assert run.status == "completed"
    assert run.completed_items == 2
    assert run.failed_items == 0
    assert len(company_select_statements) == 1


def test_execute_run_clears_current_company_identity_and_updates_counters():
    engine, db, company_ids = _create_company_enrichment_service_db()
    service = CompanyEnrichmentRunService(db)
    run = service.create_pending_run(force_company_ids=[company_ids[0]])
    db.commit()

    flush_snapshots = []

    @event.listens_for(db, "after_flush")
    def _capture_run_state(session, flush_context):
        tracked_run = next(
            (
                obj
                for obj in session.identity_map.values()
                if isinstance(obj, CompanyEnrichmentRun) and obj.id == run.id
            ),
            None,
        )
        if tracked_run is None:
            return

        tracked_items = [
            obj
            for obj in session.identity_map.values()
            if isinstance(obj, CompanyEnrichmentRunItem) and obj.run_id == run.id
        ]
        flush_snapshots.append(
            {
                "status": tracked_run.status,
                "pending_items": tracked_run.pending_items,
                "completed_items": tracked_run.completed_items,
                "failed_items": tracked_run.failed_items,
                "current_company_name": tracked_run.current_company_name,
                "running_item_count": sum(
                    1 for item in tracked_items if item.status == "running"
                ),
            }
        )

    class StubEnrichmentService:
        async def enrich_company_description(self, company, db_session, force=False):
            company.ai_description = "AI summary"
            return {
                "company_id": str(company.id),
                "ai_description": company.ai_description,
            }

    try:
        completed_run = asyncio.run(
            service.execute_run(run.id, enrichment_service=StubEnrichmentService())
        )
    finally:
        event.remove(db, "after_flush", _capture_run_state)
        db.close()

    assert completed_run.status == "completed"
    assert completed_run.current_company_name is None
    assert completed_run.pending_items == 0
    assert completed_run.completed_items == 1
    assert completed_run.failed_items == 0
    assert not any(
        snapshot["current_company_name"] is not None
        and snapshot["running_item_count"] == 0
        for snapshot in flush_snapshots
    )
