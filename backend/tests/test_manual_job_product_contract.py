from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import jobs as jobs_api
from app.database import get_db
from app.models.job import Job
from app.services.manual_job_intake import ManualJobMutationResult


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "job_intelligence_product_surfaces.json"
)


class _ResultQuery:
    def __init__(self, db):
        self._db = db

    def options(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def first(self):
        return self._db.job


class _FakeSession:
    def __init__(self):
        self.job = None
        self.commits = 0
        self.rollbacks = 0

    def query(self, _model):
        return _ResultQuery(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _client(monkeypatch, db, captured):
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["job_detail"]

    class _Service:
        def __init__(self, session):
            assert session is db

        def create(self, command, *, idempotency_key):
            return self._result("create", command, idempotency_key)

        def update(self, job_id, command, *, idempotency_key):
            captured["updated_job_id"] = str(job_id)
            return self._result("update", command, idempotency_key)

        def _result(self, kind, command, idempotency_key):
            captured.update(
                {
                    "kind": kind,
                    "command": command,
                    "idempotency_key": idempotency_key,
                }
            )
            company_id = (
                command.company.company_id
                if command.company.mode == "existing"
                else uuid4()
            )
            company = SimpleNamespace(
                id=company_id,
                name=(
                    fixture["company_name"]
                    if command.company.mode == "existing"
                    else command.company.name
                ),
            )
            job = Job(
                id=uuid4(),
                job_id=f"manual:{uuid4()}",
                source_site="manual",
                source_job_id=f"manual:{uuid4()}",
                company_id=company_id,
                title=command.title,
            )
            db.job = job
            return ManualJobMutationResult(job=job, company=company)

        def replay(self, *_args, **_kwargs):
            raise AssertionError("replay should not be needed in this contract test")

    monkeypatch.setattr(jobs_api, "ManualJobIntake", _Service)
    monkeypatch.setattr(
        jobs_api,
        "compose_current_job_detail",
        lambda session, job: fixture,
    )

    app = FastAPI()
    app.include_router(jobs_api.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_manual_job_http_contract_accepts_governed_structured_input(
    monkeypatch,
) -> None:
    db = _FakeSession()
    captured = {}
    client = _client(monkeypatch, db, captured)

    response = client.post(
        "/api/jobs/manual",
        headers={"Idempotency-Key": "manual-create-1"},
        json={
            "company": {
                "mode": "existing",
                "company_id": "30000000-0000-0000-0000-000000000010",
            },
            "title": "  Platform Engineer  ",
            "salary_min": 40000,
            "salary_max": 60000,
            "salary_currency": "hkd",
            "employment_type_codes": ["full_time", "permanent", "full_time"],
        },
    )

    assert response.status_code == 200
    command = captured["command"]
    assert captured["kind"] == "create"
    assert captured["idempotency_key"] == "manual-create-1"
    assert command.title == "Platform Engineer"
    assert command.salary_currency == "HKD"
    assert command.employment_type_codes == ["full_time", "permanent"]
    assert db.commits == 1
    assert db.rollbacks == 0


def test_manual_job_http_contract_keeps_new_company_as_one_command(
    monkeypatch,
) -> None:
    db = _FakeSession()
    captured = {}
    client = _client(monkeypatch, db, captured)

    response = client.post(
        "/api/jobs/manual",
        headers={"Idempotency-Key": "manual-create-new-company"},
        json={
            "company": {
                "mode": "new",
                "name": " Evidence Company ",
                "website": "Example.COM/",
                "industry": " Software Consulting ",
                "location": " Central ",
            },
            "title": "Engineer",
        },
    )

    assert response.status_code == 200
    company = captured["command"].company
    assert company.name == "Evidence Company"
    assert company.website == "https://example.com"
    assert company.industry == "Software Consulting"
    assert company.location == "Central"


def test_manual_job_http_contract_rejects_legacy_or_invalid_input(monkeypatch) -> None:
    db = _FakeSession()
    client = _client(monkeypatch, db, {})
    base = {
        "company": {
            "mode": "existing",
            "company_id": "30000000-0000-0000-0000-000000000010",
        },
        "title": "Platform Engineer",
    }

    missing_key = client.post("/api/jobs/manual", json=base)
    legacy_salary = client.post(
        "/api/jobs/manual",
        headers={"Idempotency-Key": "legacy-salary"},
        json={**base, "salary_range": "$40k-$60k"},
    )
    legacy_employment = client.post(
        "/api/jobs/manual",
        headers={"Idempotency-Key": "legacy-employment"},
        json={**base, "employment_type": "Full-time"},
    )
    reversed_range = client.post(
        "/api/jobs/manual",
        headers={"Idempotency-Key": "reversed-range"},
        json={**base, "salary_min": 60000, "salary_max": 40000},
    )
    unsupported_currency = client.post(
        "/api/jobs/manual",
        headers={"Idempotency-Key": "unsupported-currency"},
        json={**base, "salary_currency": "ZZZ"},
    )

    assert missing_key.status_code == 422
    assert legacy_salary.status_code == 422
    assert legacy_employment.status_code == 422
    assert reversed_range.status_code == 422
    assert unsupported_currency.status_code == 422
    assert db.commits == 0


def test_manual_job_http_contract_routes_manual_update_through_same_command(
    monkeypatch,
) -> None:
    db = _FakeSession()
    captured = {}
    client = _client(monkeypatch, db, captured)
    job_id = uuid4()

    response = client.patch(
        f"/api/jobs/manual/{job_id}",
        headers={"Idempotency-Key": "manual-update-1"},
        json={
            "company": {
                "mode": "existing",
                "company_id": "30000000-0000-0000-0000-000000000010",
            },
            "title": "Updated Platform Engineer",
            "description": "Updated evidence",
        },
    )

    assert response.status_code == 200
    assert captured["kind"] == "update"
    assert captured["updated_job_id"] == str(job_id)
    assert captured["command"].description == "Updated evidence"
