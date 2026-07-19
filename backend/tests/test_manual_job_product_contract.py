from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import jobs as jobs_api
from app.database import get_db
from app.models.job import Job
from app.models.source_job_attributes import JobEmploymentType


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "job_intelligence_product_surfaces.json"
)


class _RegistryQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_args):
        return self

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self):
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, _model):
        return _RegistryQuery(
            [
                SimpleNamespace(code="full_time", label="Full-time", sort_order=1),
                SimpleNamespace(code="permanent", label="Permanent", sort_order=3),
            ]
        )

    def add(self, value):
        self.added.append(value)

    def flush(self):
        for value in self.added:
            if isinstance(value, Job) and value.id is None:
                value.id = uuid4()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _client(monkeypatch, db):
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["job_detail"]

    class _Service:
        def __init__(self, session):
            assert session is db

        def create_manual_job_run(self, job_id):
            UUID(job_id)
            return SimpleNamespace(id="manual-run")

    monkeypatch.setattr(jobs_api, "ensure_profile_runtime_ready", lambda _profile: None)
    monkeypatch.setattr(jobs_api, "EnrichmentRunService", _Service)
    monkeypatch.setattr(
        jobs_api,
        "_publish_run_request",
        lambda session, **_kwargs: session.commit(),
    )

    async def _wait(_run_id):
        return None

    monkeypatch.setattr(jobs_api, "_wait_for_terminal_run", _wait)
    monkeypatch.setattr(jobs_api, "_load_job_snapshot", lambda _job_id: fixture)

    app = FastAPI()
    app.include_router(jobs_api.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_manual_job_http_contract_persists_governed_employment_type_codes(
    monkeypatch,
) -> None:
    db = _FakeSession()
    client = _client(monkeypatch, db)

    response = client.post(
        "/api/v1/jobs/manual",
        json={
            "company_id": "30000000-0000-0000-0000-000000000010",
            "title": "Platform Engineer",
            "employment_type_codes": ["full_time", "permanent"],
        },
    )

    assert response.status_code == 200
    job = next(value for value in db.added if isinstance(value, Job))
    assignments = [
        value for value in db.added if isinstance(value, JobEmploymentType)
    ]
    assert job.employment_type is None
    assert [assignment.employment_type_code for assignment in assignments] == [
        "full_time",
        "permanent",
    ]
    assert all(assignment.job_id == job.id for assignment in assignments)
    assert all(assignment.evidence_label_ids == [] for assignment in assignments)
    assert all(
        assignment.provenance
        == {
            "method": "manual_operator_selection",
            "actor": "local-operator",
            "source": "add-job",
        }
        for assignment in assignments
    )
    assert db.commits == 1
    assert db.rollbacks == 0


def test_manual_job_http_contract_rejects_unknown_or_conflicting_employment_input(
    monkeypatch,
) -> None:
    db = _FakeSession()
    client = _client(monkeypatch, db)
    base = {
        "company_id": "30000000-0000-0000-0000-000000000010",
        "title": "Platform Engineer",
    }

    unknown = client.post(
        "/api/v1/jobs/manual",
        json={**base, "employment_type_codes": ["other"]},
    )
    conflicting = client.post(
        "/api/v1/jobs/manual",
        json={
            **base,
            "employment_type": "Full-time",
            "employment_type_codes": ["full_time"],
        },
    )

    assert unknown.status_code == 422
    assert conflicting.status_code == 422
    assert db.added == []
