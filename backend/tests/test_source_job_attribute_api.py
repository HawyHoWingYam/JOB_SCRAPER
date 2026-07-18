from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.jobs import create_job as create_collected_job
from app.schemas.job import JobCreateSchema, JobDetailSchema
from app.schemas.job_search import JobSearchFiltersSchema


def test_job_search_filter_contract_uses_stable_arrays_and_one_legacy_label_adapter():
    current = JobSearchFiltersSchema(
        source_classification_ids=["jobsdb:6281", "offertoday:118000"],
        employment_type_codes=["permanent", "part_time"],
    )
    legacy = JobSearchFiltersSchema(employment_type="Permanent")

    assert {
        "current": (
            current.source_classification_ids,
            current.employment_type_codes,
        ),
        "legacy": legacy.employment_type_codes,
    } == {
        "current": (
            ["jobsdb:6281", "offertoday:118000"],
            ["permanent", "part_time"],
        ),
        "legacy": ["permanent"],
    }

    with pytest.raises(ValidationError, match="recognized Employment Type label"):
        JobSearchFiltersSchema(employment_type="Full-time, Permanent")


def test_exported_job_detail_fixture_matches_the_backend_contract():
    fixture_path = (
        Path(__file__).parent / "fixtures" / "source_job_attributes_job_detail.json"
    )

    payload = JobDetailSchema.model_validate(
        json.loads(fixture_path.read_text())
    ).model_dump(mode="json")

    assert {
        "paths": [
            [node["source_classification_id"] for node in path["nodes"]]
            for path in payload["source_classification_paths"]
        ],
        "employment_types": [item["code"] for item in payload["employment_types"]],
        "source_labels": [
            item["raw_label"] for item in payload["source_employment_labels"]
        ],
    } == {
        "paths": [["jobsdb:6281", "jobsdb:6287"]],
        "employment_types": ["full_time", "permanent"],
        "source_labels": ["Full-time", "Permanent"],
    }


def test_legacy_collected_job_create_route_is_retired_before_database_access():
    class NoDatabaseAccess:
        def query(self, *_args, **_kwargs):
            raise AssertionError("retired route must not access the database")

    payload = JobCreateSchema(
        job_id="legacy-collected-create",
        company_id=uuid4(),
        title="Legacy collected Job",
        employment_type="Full-time",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_collected_job(payload, NoDatabaseAccess()))

    assert exc_info.value.status_code == 410
    assert exc_info.value.detail == {
        "code": "COLLECTED_JOB_CREATE_RETIRED",
        "message": (
            "Collected Jobs must be written through a source ingestion path; "
            "use POST /api/v1/jobs/manual for manually entered Jobs."
        ),
    }
