from __future__ import annotations

import asyncio
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.api import companies
from app.database import get_db


class _FakeQuery:
    def __init__(self, *, rows):
        self.rows = list(rows)

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def offset(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.rows)

    def count(self):
        raise AssertionError("count() should be skipped when a short first page proves the total")


class _FakeDB:
    def __init__(self, query):
        self.query_obj = query

    def query(self, *args, **kwargs):
        return self.query_obj


def _build_company(name: str):
    now = datetime(2026, 5, 28, 9, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=uuid4(),
        company_id=name.lower().replace(" ", "-"),
        source_site="jobsdb",
        source_company_id=name.lower().replace(" ", "-"),
        name=name,
        industry="Technology",
        location="Hong Kong",
        ai_description=None,
        is_deleted=False,
        created_at=now,
        updated_at=now,
    )


def test_list_companies_skips_total_count_for_short_first_page(monkeypatch):
    app = FastAPI()
    app.include_router(companies.router, prefix="/api/v1")

    query = _FakeQuery(rows=[_build_company("Acme Health"), _build_company("Cyan Retail")])
    db = _FakeDB(query)

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.get("/api/v1/companies?status=pending&page=1&page_size=25")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["page"] == 1
    assert payload["page_size"] == 25
    assert payload["total_pages"] == 1
    assert [item["name"] for item in payload["items"]] == ["Acme Health", "Cyan Retail"]


def test_list_companies_skips_total_count_for_short_later_page(monkeypatch):
    app = FastAPI()
    app.include_router(companies.router, prefix="/api/v1")
    query = _FakeQuery(rows=[_build_company("Zulu Health"), _build_company("Nova Labs")])
    db = _FakeDB(query)

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.get("/api/v1/companies?status=pending&page=2&page_size=25")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 27
    assert payload["page"] == 2
    assert payload["page_size"] == 25
    assert payload["total_pages"] == 2
    assert [item["name"] for item in payload["items"]] == ["Zulu Health", "Nova Labs"]


def test_get_company_enrichment_run_items_returns_404_when_service_reports_missing_run(monkeypatch):
    class _FakeService:
        def __init__(self, db):
            self.db = db

        def list_run_items_or_none(self, run_id):
            assert run_id == "run-missing"
            return None

    monkeypatch.setattr(companies, "CompanyEnrichmentRunService", _FakeService)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(companies.get_company_enrichment_run_items("run-missing", db=object()))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Run not found"


def test_get_current_company_enrichment_run_includes_current_company_id(monkeypatch):
    active_run = SimpleNamespace(
        id="run-current",
        status="running",
        total_items=3,
        pending_items=2,
        completed_items=1,
        failed_items=0,
        started_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
        completed_at=None,
        current_company_name="Acme Health",
        error_message=None,
        created_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
    )
    resolved_run_ids = []

    class _FakeService:
        def __init__(self, db):
            self.db = db

        def get_current_run(self):
            return active_run

    def resolve_current_company_id(db, run):
        resolved_run_ids.append(run.id)
        return "company-2"

    monkeypatch.setattr(companies, "CompanyEnrichmentRunService", _FakeService)
    monkeypatch.setattr(companies, "_resolve_current_company_id", resolve_current_company_id)

    payload = asyncio.run(companies.get_current_company_enrichment_run(db=object()))

    assert resolved_run_ids == ["run-current"]
    assert payload["current_company_id"] == "company-2"


def test_get_company_enrichment_run_includes_current_company_id(monkeypatch):
    active_run = SimpleNamespace(
        id="run-current",
        status="running",
        total_items=3,
        pending_items=2,
        completed_items=1,
        failed_items=0,
        started_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
        completed_at=None,
        current_company_name="Acme Health",
        error_message=None,
        created_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
    )
    resolved_run_ids = []

    class _FakeService:
        def __init__(self, db):
            self.db = db

        def get_run(self, run_id):
            assert run_id == "run-current"
            return active_run

    def resolve_current_company_id(db, run):
        resolved_run_ids.append(run.id)
        return "company-2"

    monkeypatch.setattr(companies, "CompanyEnrichmentRunService", _FakeService)
    monkeypatch.setattr(companies, "_resolve_current_company_id", resolve_current_company_id)

    payload = asyncio.run(companies.get_company_enrichment_run("run-current", db=object()))

    assert resolved_run_ids == ["run-current"]
    assert payload["current_company_id"] == "company-2"
