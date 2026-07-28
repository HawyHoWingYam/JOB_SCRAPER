from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
        website=None,
        industry="Technology",
        location="Hong Kong",
        ai_description=None,
        ai_description_updated_at=None,
    )


@pytest.fixture
def company_run_db():
    engine = create_engine("sqlite:///:memory:")
    Company.__table__.create(engine)
    CompanyEnrichmentRun.__table__.create(engine)
    CompanyEnrichmentRunItem.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _stored_company(
    db,
    *,
    identity: str,
    row_id: str,
    created_at: datetime,
    description: str | None = None,
    description_updated_at: datetime | None = None,
):
    company = Company(
        id=uuid.UUID(row_id),
        company_id=identity,
        source_site="jobsdb",
        source_company_id=identity,
        name=identity,
        ai_description=description,
        ai_description_updated_at=description_updated_at,
        created_at=created_at,
        is_deleted=False,
    )
    db.add(company)
    db.flush()
    return company


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
    request = CompanyEnrichmentRunRequest(requested_limit=25)
    assert request.web_search_enabled is False
    assert request.mode == "generate_missing"


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
    company.ai_description = "Existing description"
    original_timestamp = datetime(2026, 7, 1, tzinfo=timezone.utc)
    company.ai_description_updated_at = original_timestamp

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
            force=True,
            web_search_enabled=True,
        )

    assert company.ai_description == "Existing description"
    assert company.ai_description_updated_at == original_timestamp


@pytest.mark.asyncio
async def test_company_generation_updates_description_and_timestamp_together():
    company = _company()

    class RecordingDB(_EmptyJobsDB):
        committed = False

        def commit(self):
            self.committed = True

        def refresh(self, _company):
            pass

    db = RecordingDB()
    result = await CompanyEnrichmentService(llm=_RecordingLLM()).enrich_company_description(
        company,
        db,
    )

    assert result["ai_description"] == "A factual company description."
    assert company.ai_description == "A factual company description."
    assert company.ai_description_updated_at is not None
    assert db.committed is True


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
        CompanyEnrichmentRunRequest(web_search_enabled=False, requested_limit=25),
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
            CompanyEnrichmentRunRequest(web_search_enabled=True, requested_limit=25),
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


def test_global_company_run_keeps_missing_only_targeting_and_persists_mode(company_run_db):
    now = datetime(2026, 7, 1)
    missing_company = _stored_company(
        company_run_db,
        identity="missing",
        row_id="00000000-0000-0000-0000-000000000001",
        created_at=now,
    )
    _stored_company(
        company_run_db,
        identity="ready",
        row_id="00000000-0000-0000-0000-000000000002",
        created_at=now,
        description="Already present",
    )
    company_run_db.commit()

    run = CompanyEnrichmentRunService(company_run_db).create_pending_run(
        requested_limit=25,
        web_search_enabled=True,
    )
    company_run_db.commit()

    assert run.web_search_enabled is True
    assert run.mode == "generate_missing"
    assert run.requested_limit == 25
    assert run.total_items == 1
    assert [item.company_id for item in run.items] == [missing_company.id]


def test_generate_run_has_no_product_maximum_and_orders_created_at_then_id(company_run_db):
    now = datetime(2026, 7, 1)
    newest = _stored_company(
        company_run_db,
        identity="newest",
        row_id="00000000-0000-0000-0000-000000000003",
        created_at=now + timedelta(days=1),
    )
    tie_second = _stored_company(
        company_run_db,
        identity="tie-second",
        row_id="00000000-0000-0000-0000-000000000002",
        created_at=now,
    )
    tie_first = _stored_company(
        company_run_db,
        identity="tie-first",
        row_id="00000000-0000-0000-0000-000000000001",
        created_at=now,
    )
    company_run_db.commit()

    run = CompanyEnrichmentRunService(company_run_db).create_pending_run(
        requested_limit=100_000,
    )
    company_run_db.commit()

    assert run.requested_limit == 100_000
    assert [item.company_id for item in run.items] == [
        tie_first.id,
        tie_second.id,
        newest.id,
    ]


def test_regenerate_run_orders_null_then_oldest_description_timestamp(company_run_db):
    now = datetime(2026, 7, 1)
    newer = _stored_company(
        company_run_db,
        identity="newer",
        row_id="00000000-0000-0000-0000-000000000004",
        created_at=now,
        description="Newer",
        description_updated_at=now + timedelta(days=1),
    )
    oldest = _stored_company(
        company_run_db,
        identity="oldest",
        row_id="00000000-0000-0000-0000-000000000003",
        created_at=now,
        description="Oldest",
        description_updated_at=now,
    )
    null_second = _stored_company(
        company_run_db,
        identity="null-second",
        row_id="00000000-0000-0000-0000-000000000002",
        created_at=now,
        description="Legacy second",
    )
    null_first = _stored_company(
        company_run_db,
        identity="null-first",
        row_id="00000000-0000-0000-0000-000000000001",
        created_at=now,
        description="Legacy first",
    )
    company_run_db.commit()

    run = CompanyEnrichmentRunService(company_run_db).create_pending_run(
        mode="regenerate_existing",
        requested_limit=4,
    )
    company_run_db.commit()

    assert [item.company_id for item in run.items] == [
        null_first.id,
        null_second.id,
        oldest.id,
        newer.id,
    ]


def test_retry_preserves_failed_company_ids_mode_limit_and_web_search(company_run_db):
    now = datetime(2026, 7, 1)
    first = _stored_company(
        company_run_db,
        identity="first",
        row_id="00000000-0000-0000-0000-000000000001",
        created_at=now,
        description="First",
    )
    second = _stored_company(
        company_run_db,
        identity="second",
        row_id="00000000-0000-0000-0000-000000000002",
        created_at=now,
        description="Second",
    )
    company_run_db.commit()
    service = CompanyEnrichmentRunService(company_run_db)
    original = service.create_pending_run(
        mode="regenerate_existing",
        requested_limit=500_000,
        web_search_enabled=True,
    )
    company_run_db.flush()
    original.items[0].status = "failed"
    original.items[1].status = "completed"
    original.status = "completed_with_failures"
    original.pending_items = 0
    original.completed_items = 1
    original.failed_items = 1
    company_run_db.commit()

    retry = service.create_retry_run_from_failed_items(original.id)
    company_run_db.commit()

    assert retry.mode == "regenerate_existing"
    assert retry.requested_limit == 500_000
    assert retry.web_search_enabled is True
    assert [item.company_id for item in retry.items] == [first.id]
    assert second.id not in [item.company_id for item in retry.items]
