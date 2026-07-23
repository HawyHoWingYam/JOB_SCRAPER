from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import UUID, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.api import companies as companies_api
from app.api.companies import (
    CompanyEnrichmentRunRequest,
    _run_persisted_company_enrichment,
    _serialize_run,
    create_company_enrichment_run,
)
from app.models import Company
from app.models.company_enrichment_run import (
    CompanyEnrichmentRun,
    CompanyEnrichmentRunItem,
)
from app.services.company_enrichment_run_service import CompanyEnrichmentRunService
from app.services.company_enrichment_service import CompanyEnrichmentService


@compiles(UUID, "sqlite")
def _compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


class _EmptyJobsQuery:
    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def limit(self, _limit):
        return self

    def all(self):
        return []


class _EmptyJobsDB:
    def query(self, *_args):
        return _EmptyJobsQuery()


class _RecordingLLM:
    def __init__(self):
        self.calls = []

    async def generate(self, prompt: str, **kwargs):
        self.calls.append({"prompt": prompt, "kwargs": kwargs})
        return "A factual company description."


class _FailingLLM:
    async def generate(self, _prompt: str, **_kwargs):
        raise RuntimeError("search transport failed")


def _company():
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Example Limited",
        industry="Technology",
        location="Hong Kong",
        ai_description=None,
    )


async def _generate_with_search_flag(enabled: bool):
    llm = _RecordingLLM()
    service = CompanyEnrichmentService(llm=llm)
    result = await service._generate_company_description(
        _company(),
        _EmptyJobsDB(),
        web_search_enabled=enabled,
    )
    return llm, result


def test_company_run_request_defaults_web_search_off():
    assert CompanyEnrichmentRunRequest().web_search_enabled is False


def test_company_run_serializer_returns_persisted_search_mode():
    run = SimpleNamespace(
        id="run-1",
        status="pending",
        total_items=1,
        pending_items=1,
        completed_items=0,
        failed_items=0,
        web_search_enabled=True,
        started_at=None,
        completed_at=None,
        current_company_name=None,
        error_message=None,
        created_at=None,
    )

    assert _serialize_run(run)["web_search_enabled"] is True


@pytest.mark.asyncio
async def test_company_generation_never_searches_implicitly():
    llm, result = await _generate_with_search_flag(False)

    assert result == "A factual company description."
    assert llm.calls[0]["kwargs"] == {"web_search": False}
    assert "Use only the provided" in llm.calls[0]["prompt"]


@pytest.mark.asyncio
async def test_company_generation_searches_only_when_explicitly_enabled():
    llm, _result = await _generate_with_search_flag(True)

    assert llm.calls[0]["kwargs"] == {"web_search": True}
    assert "Search the web first" in llm.calls[0]["prompt"]


@pytest.mark.asyncio
async def test_company_search_failure_does_not_persist_or_fallback_description():
    company = _company()

    class NoWriteDB(_EmptyJobsDB):
        def commit(self):
            pytest.fail("failed generation must not commit")

        def refresh(self, _company):
            pytest.fail("failed generation must not refresh")

    db = NoWriteDB()
    service = CompanyEnrichmentService(llm=_FailingLLM())

    with pytest.raises(RuntimeError, match="search transport failed"):
        await service.enrich_company_description(
            company,
            db,
            web_search_enabled=True,
        )

    assert company.ai_description is None


@pytest.mark.asyncio
async def test_active_company_run_keeps_its_persisted_search_mode(monkeypatch):
    active_run = SimpleNamespace(
        id="active-run",
        status="completed",
        total_items=2,
        pending_items=0,
        completed_items=2,
        failed_items=0,
        web_search_enabled=True,
        started_at=None,
        completed_at=None,
        current_company_name=None,
        error_message=None,
        created_at=None,
    )

    class StubRunService:
        def __init__(self, _db):
            pass

        def get_active_run(self):
            return active_run

    monkeypatch.setattr(companies_api, "ensure_profile_runtime_ready", lambda _scope: None)
    monkeypatch.setattr(companies_api, "CompanyEnrichmentRunService", StubRunService)

    result = await create_company_enrichment_run(
        BackgroundTasks(),
        CompanyEnrichmentRunRequest(web_search_enabled=False),
        db=SimpleNamespace(),
    )

    assert result["id"] == "active-run"
    assert result["web_search_enabled"] is True


@pytest.mark.asyncio
async def test_company_run_rejects_unavailable_requested_search(monkeypatch):
    class StubRunService:
        def __init__(self, _db):
            pass

        def get_active_run(self):
            return None

    class StubSettingsService:
        def __init__(self, _db):
            pass

        def get_profile_runtime_metadata(self, _scope):
            return SimpleNamespace(
                web_search_available=False,
                web_search_reason="Run the Company profile Web Search test first.",
            )

    monkeypatch.setattr(companies_api, "ensure_profile_runtime_ready", lambda _scope: None)
    monkeypatch.setattr(companies_api, "CompanyEnrichmentRunService", StubRunService)
    monkeypatch.setattr(companies_api, "AIRuntimeSettingsService", StubSettingsService)

    with pytest.raises(HTTPException) as raised:
        await create_company_enrichment_run(
            BackgroundTasks(),
            CompanyEnrichmentRunRequest(web_search_enabled=True),
            db=SimpleNamespace(),
        )

    assert raised.value.status_code == 409
    assert "Web Search test" in str(raised.value.detail)


@pytest.mark.asyncio
async def test_background_run_persists_only_sanitized_failure_details(monkeypatch):
    recorded = {}
    leaked_detail = "secret-key private company prompt provider response body"

    class StubDB:
        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    class StubRunService:
        def __init__(self, _db):
            pass

        async def execute_run(self, _run_id):
            raise RuntimeError(leaked_detail)

        def mark_run_failed(self, run_id, error_message):
            recorded.update(run_id=run_id, error_message=error_message)

    monkeypatch.setattr(companies_api, "SessionLocal", StubDB)
    monkeypatch.setattr(companies_api, "CompanyEnrichmentRunService", StubRunService)

    with pytest.raises(RuntimeError, match="error_type=RuntimeError") as raised:
        await _run_persisted_company_enrichment("run-1")

    assert recorded["run_id"] == "run-1"
    assert recorded["error_message"] == (
        "LLM operation failed (error_type=RuntimeError)"
    )
    assert leaked_detail not in recorded["error_message"]
    assert leaked_detail not in str(raised.value)


def test_global_company_run_keeps_missing_only_targeting_and_persists_mode():
    engine = create_engine("sqlite:///:memory:")
    Company.__table__.create(engine)
    CompanyEnrichmentRun.__table__.create(engine)
    CompanyEnrichmentRunItem.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    try:
        missing_company = Company(
            company_id="missing",
            source_site="jobsdb",
            source_company_id="missing",
            name="Missing Description",
            ai_description=None,
            is_deleted=False,
        )
        ready_company = Company(
            company_id="ready",
            source_site="jobsdb",
            source_company_id="ready",
            name="Ready Description",
            ai_description="Already present",
            is_deleted=False,
        )
        db.add_all([missing_company, ready_company])
        db.commit()

        run = CompanyEnrichmentRunService(db).create_pending_run(
            web_search_enabled=True
        )
        db.commit()

        assert run.web_search_enabled is True
        assert run.total_items == 1
        assert len(run.items) == 1
        assert run.items[0].company_id == missing_company.id
    finally:
        db.close()
        engine.dispose()


def test_company_web_search_migration_has_single_head_lineage_and_reverse_drop():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20260723_120000_add_company_web_search_state.py"
    )
    spec = importlib.util.spec_from_file_location("company_web_search_migration", migration_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.revision == "20260723_120000"
    assert module.down_revision == "20260722_120000"
    added_columns = []
    dropped_columns = []
    module.op = SimpleNamespace(
        add_column=lambda table, column: added_columns.append((table, column)),
        drop_column=lambda table, name: dropped_columns.append((table, name)),
    )

    module.upgrade()
    module.downgrade()

    added_by_name = {
        (table, column.name): column for table, column in added_columns
    }
    run_flag = added_by_name[("company_enrichment_runs", "web_search_enabled")]
    assert run_flag.nullable is False
    assert run_flag.server_default is not None
    assert (
        "app_runtime_settings",
        "companies_web_search_last_test_status",
    ) in added_by_name
    assert dropped_columns[-1] == (
        "company_enrichment_runs",
        "web_search_enabled",
    )
