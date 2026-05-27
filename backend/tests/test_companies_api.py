from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

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
