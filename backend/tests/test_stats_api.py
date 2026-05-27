from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import stats
from app.database import get_db


class _FakeQuery:
    def __init__(self, *, one_result=None):
        self.one_result = one_result

    def filter(self, *args, **kwargs):
        return self

    def one(self):
        return self.one_result

    def count(self):
        raise AssertionError("count() should be replaced by a single aggregate query")


class _FakeDB:
    def __init__(self, queries):
        self._queries = list(queries)
        self.query_calls = []

    def query(self, *entities):
        self.query_calls.append(entities)
        if not self._queries:
            raise AssertionError("Unexpected query call")
        return self._queries.pop(0)


def test_stats_overview_uses_single_aggregate_query():
    app = FastAPI()
    app.include_router(stats.router)
    db = _FakeDB([_FakeQuery(one_result=(400, 4))])

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.get("/api/v1/stats/overview")

    assert response.status_code == 200
    assert response.json() == {
        "total_jobs": 400,
        "enriched_jobs": 4,
        "pending_enrichment": 396,
    }
