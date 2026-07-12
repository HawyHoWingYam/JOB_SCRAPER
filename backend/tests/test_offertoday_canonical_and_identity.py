from __future__ import annotations

from copy import deepcopy
import importlib
import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.sources.contracts as contracts
from app.database import Base
from app.models.company import Company
from app.models.crawl_job_listing import CrawlJobListing
from app.models.job import Job
from app.scraper.manual_action import (
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
    ManualActionRequiredError,
)
from app.sources.contracts import build_offertoday_canonical_job
from app.sources.offertoday.parsers import (
    parse_offertoday_detail_response,
    parse_offertoday_listing_response,
)
from app.sources.offertoday.response_policy import (
    OfferTodayResponseKind,
    OfferTodayTransportError,
)
from app.utils.source_identity import derive_source_company_id_from_raw_data


def _identity_module():
    return importlib.import_module("app.sources.offertoday.detail_identity")


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "offertoday"


def _fixture_row(name: str) -> dict:
    payload = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    return payload["data"]["resultList"][0]


def _sample_listing_raw() -> dict:
    return {
        "jobId": "jid-1",
        "encryptJobId": "enc-jid-1",
        "jobName": "Data Engineer",
        "companyName": "Alpha Ltd",
        "locationDesc": "Wan Chai",
        "salaryDesc": "HK $30K-40K",
        "jobTypeDesc": "Full-time",
        "jobFunctions": [
            {
                "code": "118000",
                "name": "Information Technology",
                "children": [
                    {
                        "code": "118101",
                        "name": "Software",
                    }
                ],
            }
        ],
    }


def _sample_listing_raw_missing_encrypted() -> dict:
    payload = _sample_listing_raw()
    payload.pop("encryptJobId")
    return payload


def _sample_detail_raw() -> dict:
    return {
        "jobId": "jid-1",
        "encryptJobId": "enc-jid-1",
        "jobName": "Data Engineer",
        "jobDesc": "<p>Build ETL pipelines.</p><p>Apply now.</p>",
        "companyName": "Alpha Ltd",
        "brandId": "brand-123",
        "brandName": "Alpha Brand",
        "salaryDesc": "HK $30K-40K",
        "jobTypeDesc": "Full-time",
        "locationDesc": "Wan Chai",
        "postDateDesc": "2026-06-26",
        "jobFunctions": [
            {
                "code": "118000",
                "name": "Information Technology",
                "children": [
                    {
                        "code": "118101",
                        "name": "Software",
                    }
                ],
            }
        ],
    }


def _sample_detail_raw_missing_encrypted() -> dict:
    payload = _sample_detail_raw()
    payload.pop("encryptJobId")
    return payload


def _parsed_listing(raw: dict | None = None) -> dict:
    return parse_offertoday_listing_response(
        {
            "code": 0,
            "data": {
                "resultList": [raw or _sample_listing_raw()],
            },
        }
    )[0]


def _job_stub() -> SimpleNamespace:
    return SimpleNamespace(
        source_site="offertoday",
        source_job_id="jid-1",
        job_id="jid-1",
        title="Data Engineer",
        description="",
        location="Wan Chai",
        salary_range="HK $30K-40K",
        employment_type="Full-time",
        posted_date=None,
        raw_data={},
        company=None,
        company_id="old-company",
    )


def _listing_stub(*, listing_payload: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        listing_payload=listing_payload or _parsed_listing(),
        detail_payload=None,
        detail_status="pending",
        detail_error_message=None,
        detail_completed_at=None,
        published_job_id=None,
    )


class _FakeIdentityHistoryRepository:
    def __init__(self, rows=()) -> None:
        self.rows = list(rows)
        self.calls = 0

    def list_offertoday_identity_history(self, db):
        self.calls += 1
        return list(self.rows)


class _FakeIdentityObservationRepository:
    def __init__(self, observations=()) -> None:
        self.observations = [deepcopy(item) for item in observations]
        self.calls = 0

    def list_offertoday_listing_identity_observations(self, db):
        self.calls += 1
        return deepcopy(self.observations)


def _repair_service(
    service_module,
    *,
    db,
    identity_history=(),
    identity_observations=(),
    **kwargs,
):
    return service_module.OfferTodayJobRepairService(
        db=db,
        crawl_job_listing_repository=_FakeIdentityHistoryRepository(
            identity_history
        ),
        crawl_job_repository=_FakeIdentityObservationRepository(
            identity_observations
        ),
        **kwargs,
    )


def _fallback_listing_payload(job_id: str = "jid-1") -> dict:
    return {
        "job_id": job_id,
        "encrypted_job_id": job_id,
        "encrypted_job_id_source": "jobId_fallback",
        "raw_data": {"jobId": job_id},
    }


def _identity_history_row(job_id: str, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        source_job_id=job_id,
        listing_payload=deepcopy(payload),
    )


def _explicit_identity_observation(job_id: str, route_id: str) -> dict:
    return {
        "source_job_id": job_id,
        "job_id": job_id,
        "encrypted_job_id": route_id,
        "encrypted_job_id_source": "encryptJobId",
    }


def _repair_database() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__,
            Job.__table__,
            CrawlJobListing.__table__,
        ],
    )
    return Session(engine)


def _database_company() -> Company:
    return Company(
        id=uuid4(),
        company_id="offertoday:brand-old",
        source_site="offertoday",
        source_company_id="brand-old",
        name="Old Company",
        is_deleted=False,
    )


def _database_job(
    source_job_id: str,
    *,
    company_id,
    description: str = "",
    updated_offset: int = 0,
) -> Job:
    timestamp = datetime(2026, 7, 10, tzinfo=UTC) + timedelta(
        seconds=updated_offset
    )
    return Job(
        id=uuid4(),
        job_id=f"offertoday:{source_job_id}",
        source_site="offertoday",
        source_job_id=source_job_id,
        company_id=company_id,
        title=f"OfferToday {source_job_id}",
        description=description,
        raw_data={},
        is_deleted=False,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _database_listing(
    source_job_id: str,
    *,
    source_site: str = "offertoday",
    detail_status: str = "pending",
    listing_payload: dict | None = None,
    created_offset: int = 0,
) -> CrawlJobListing:
    timestamp = datetime(2026, 7, 10, tzinfo=UTC) + timedelta(
        seconds=created_offset
    )
    return CrawlJobListing(
        id=uuid4(),
        crawl_job_id=uuid4(),
        source_site=source_site,
        source_job_id=source_job_id,
        source_url=f"https://example.test/{source_site}/{source_job_id}",
        listing_payload=listing_payload
        or {
            "jobId": source_job_id,
            "encryptJobId": f"enc-{source_job_id}",
        },
        detail_status=detail_status,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _detail_fetch_result(
    *,
    job_id: str = "jid-1",
    encrypted_job_id: str = "enc-jid-1",
    encrypted_job_id_source: str = "encryptJobId",
    payload: dict | None = None,
    canonical_detail: dict | None = None,
):
    identity_module = _identity_module()
    policy_module = importlib.import_module("app.sources.offertoday.response_policy")
    raw_response = payload or {
        "code": 0,
        "data": {
            "jobId": job_id,
        },
    }
    classification = policy_module.classify_offertoday_response(
        raw_response,
        operation="detail",
        expected_job_id=job_id,
    )
    if classification.kind is OfferTodayResponseKind.SUCCESS:
        parsed_detail = {
            "job_id": job_id,
            "encrypted_job_id": "",
            "raw_data": {"jobId": job_id},
        }
        resolved_canonical_detail = canonical_detail or {
            **parsed_detail,
            "encrypted_job_id": encrypted_job_id,
            "encrypted_job_id_source": encrypted_job_id_source,
        }
    else:
        parsed_detail = None
        resolved_canonical_detail = None
    return identity_module.OfferTodayDetailFetchResult(
        identity=identity_module.OfferTodayDetailIdentity(
            job_id=job_id,
            encrypted_job_id=encrypted_job_id,
            encrypted_job_id_source=encrypted_job_id_source,
        ),
        classification=classification,
        raw_response=raw_response,
        parsed_detail=parsed_detail,
        canonical_detail=resolved_canonical_detail,
    )


def test_derive_source_company_id_from_raw_data_uses_offertoday_brand_id():
    assert (
        derive_source_company_id_from_raw_data(
            "offertoday",
            {
                "brandId": "brand-123",
                "companyName": "Alpha Ltd",
            },
        )
        == "brand-123"
    )


@pytest.mark.parametrize(
    ("fixture_name", "expected_job_id"),
    [
        ("jobid_only_search_page.json", "RbeDGc1VoBZwKIInWPjDCA=="),
        ("jobid_only_browse_page.json", "lxwa-xaLLtVD4diDhVRUjw=="),
    ],
)
def test_real_jobid_only_listing_identity_resolves_fallback_without_raw_mutation(
    fixture_name: str,
    expected_job_id: str,
) -> None:
    identity_module = _identity_module()
    raw = _fixture_row(fixture_name)
    before = deepcopy(raw)

    identity = identity_module.resolve_offertoday_listing_identity(raw)

    assert identity.job_id == expected_job_id
    assert identity.encrypted_job_id == expected_job_id
    assert identity.encrypted_job_id_source == "jobId_fallback"
    assert raw == before
    assert "encryptJobId" not in raw


def test_explicit_encrypted_identity_remains_distinct_and_preferred() -> None:
    identity_module = _identity_module()

    identity = identity_module.resolve_offertoday_listing_identity(
        {"jobId": "jid-1", "encryptJobId": "enc-jid-1"}
    )

    assert identity.job_id == "jid-1"
    assert identity.encrypted_job_id == "enc-jid-1"
    assert identity.encrypted_job_id_source == "encryptJobId"


def test_explicit_encrypted_identity_equal_to_jobid_stays_explicit() -> None:
    identity_module = _identity_module()

    identity = identity_module.resolve_offertoday_listing_identity(
        {"jobId": "same-token", "encryptJobId": "same-token"}
    )

    assert identity.encrypted_job_id == "same-token"
    assert identity.encrypted_job_id_source == "encryptJobId"


@pytest.mark.parametrize("missing_value", [None, "", "   "])
def test_null_or_blank_encrypted_evidence_uses_jobid_fallback(missing_value) -> None:
    identity_module = _identity_module()

    identity = identity_module.resolve_offertoday_listing_identity(
        {"jobId": "jid-1", "encryptJobId": missing_value}
    )

    assert identity.encrypted_job_id == "jid-1"
    assert identity.encrypted_job_id_source == "jobId_fallback"


def test_non_string_explicit_encrypted_evidence_is_a_structured_failure() -> None:
    identity_module = _identity_module()

    with pytest.raises(identity_module.OfferTodayIdentityError) as exc_info:
        identity_module.resolve_offertoday_listing_identity(
            {"jobId": "jid-1", "encryptJobId": ["invalid"]}
        )

    assert exc_info.value.classification == "invalid_encrypted_job_id_evidence"


@pytest.mark.parametrize(
    ("payload", "classification"),
    [
        (
            {
                "job_id": "j-normalized",
                "raw_data": {"jobId": "j-upstream"},
            },
            "job_id_alias_conflict",
        ),
        (
            {
                "jobId": "j-1",
                "encrypted_job_id": "enc-normalized",
                "raw_data": {
                    "jobId": "j-1",
                    "encryptJobId": "enc-upstream",
                },
            },
            "encrypted_job_id_alias_conflict",
        ),
    ],
)
def test_conflicting_identity_aliases_are_structured_failures(
    payload: dict,
    classification: str,
) -> None:
    identity_module = _identity_module()

    with pytest.raises(identity_module.OfferTodayIdentityError) as exc_info:
        identity_module.resolve_offertoday_listing_identity(payload)

    assert exc_info.value.classification == classification


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "job_id": "jid-1",
            "encrypted_job_id": "other",
            "encrypted_job_id_source": "jobId_fallback",
        },
        {
            "job_id": "jid-1",
            "encrypted_job_id": "jid-1",
            "encrypted_job_id_source": "unknown",
        },
    ],
)
def test_typed_identity_rejects_invalid_source_or_fallback_route(kwargs) -> None:
    identity_module = _identity_module()

    with pytest.raises(identity_module.OfferTodayIdentityError):
        identity_module.OfferTodayDetailIdentity(**kwargs)


def test_legacy_normalized_jobid_alias_does_not_claim_upstream_encrypted_evidence() -> None:
    identity_module = _identity_module()

    identity = identity_module.resolve_offertoday_listing_identity(
        {
            "job_id": "jid-1",
            "encrypted_job_id": "jid-1",
            "raw_data": {"jobId": "jid-1"},
        }
    )

    assert identity.encrypted_job_id_source == "jobId_fallback"


def test_authority_index_promotes_explicit_and_detects_reverse_collision() -> None:
    identity_module = _identity_module()
    fallback = identity_module.OfferTodayDetailIdentity(
        "j-1", "j-1", "jobId_fallback"
    )
    explicit = identity_module.OfferTodayDetailIdentity(
        "j-1", "enc-shared", "encryptJobId"
    )
    reverse = identity_module.OfferTodayDetailIdentity(
        "j-2", "enc-shared", "encryptJobId"
    )

    index = identity_module.build_offertoday_identity_authority_index(
        (fallback, explicit, reverse)
    )

    assert index.authoritative_identity_by_job["j-1"] == explicit
    assert index.fallback_job_ids == ("j-1",)
    assert index.explicit_ids_by_job["j-1"] == ("enc-shared",)
    assert index.route_to_job_ids["enc-shared"] == ("j-1", "j-2")
    assert dict(index.conflict_reason_by_job) == {
        "j-1": "reverse_collision",
        "j-2": "reverse_collision",
    }


def test_authority_index_keeps_multiple_explicit_routes_conflicting() -> None:
    identity_module = _identity_module()
    identities = (
        identity_module.OfferTodayDetailIdentity(
            "j-1", "enc-a", "encryptJobId"
        ),
        identity_module.OfferTodayDetailIdentity(
            "j-1", "enc-b", "encryptJobId"
        ),
    )

    index = identity_module.build_offertoday_identity_authority_index(identities)

    assert "j-1" not in index.authoritative_identity_by_job
    assert dict(index.conflict_reason_by_job) == {
        "j-1": "multiple_explicit_encrypted_ids"
    }


def test_listing_parser_resolves_missing_encrypted_id_without_mutating_raw_data():
    raw = _sample_listing_raw_missing_encrypted()
    before = deepcopy(raw)

    listing = _parsed_listing(raw)

    assert listing["job_id"] == "jid-1"
    assert listing["encrypted_job_id"] == "jid-1"
    assert listing["encrypted_job_id_source"] == "jobId_fallback"
    assert listing["raw_data"] == before
    assert "encryptJobId" not in listing["raw_data"]


def test_detail_parser_resolves_missing_encrypted_id_without_mutating_raw_data():
    raw = _sample_detail_raw_missing_encrypted()
    before = deepcopy(raw)

    parsed = parse_offertoday_detail_response({"code": 0, "data": raw})

    assert parsed["job_id"] == "jid-1"
    assert parsed["encrypted_job_id"] == "jid-1"
    assert parsed["encrypted_job_id_source"] == "jobId_fallback"
    assert parsed["raw_data"] == before
    assert "encryptJobId" not in parsed["raw_data"]


def test_resolve_detail_identity_uses_jobid_fallback_from_listing_evidence() -> None:
    identity_module = _identity_module()
    listing_payload = _parsed_listing(_sample_listing_raw_missing_encrypted())

    identity = identity_module.resolve_offertoday_detail_identity(
        source_job_id="jid-1",
        listing_payload=listing_payload,
    )

    assert identity.job_id == "jid-1"
    assert identity.encrypted_job_id == "jid-1"
    assert identity.encrypted_job_id_source == "jobId_fallback"


def test_resolve_detail_identity_rejects_listing_source_job_id_mismatch():
    identity_module = _identity_module()

    with pytest.raises(
        identity_module.OfferTodayIdentityError,
        match=r"source_job_id=.*jid-other.*jobId=.*jid-1",
    ):
        identity_module.resolve_offertoday_detail_identity(
            source_job_id="jid-other",
            listing_payload=_parsed_listing(),
        )


def test_resolve_detail_identity_returns_frozen_distinct_identifiers():
    identity_module = _identity_module()

    identity = identity_module.resolve_offertoday_detail_identity(
        source_job_id="jid-1",
        listing_payload=_parsed_listing(),
    )

    assert identity.job_id == "jid-1"
    assert identity.encrypted_job_id == "enc-jid-1"
    assert identity.__slots__ == (
        "job_id",
        "encrypted_job_id",
        "encrypted_job_id_source",
    )
    with pytest.raises(FrozenInstanceError):
        identity.job_id = "other"


def test_resolve_detail_identity_rejects_present_non_string_alias():
    identity_module = _identity_module()
    listing_payload = {
        "job_id": 123,
        "encrypted_job_id": "enc-jid-1",
        "raw_data": {
            "jobId": "jid-1",
            "encryptJobId": "enc-jid-1",
        },
    }

    with pytest.raises(
        identity_module.OfferTodayIdentityError,
        match=r"job_id.*nonblank string",
    ):
        identity_module.resolve_offertoday_detail_identity(
            source_job_id="jid-1",
            listing_payload=listing_payload,
        )


def test_validate_detail_identity_rejects_response_job_id_mismatch():
    identity_module = _identity_module()
    identity = identity_module.OfferTodayDetailIdentity(
        job_id="jid-1",
        encrypted_job_id="enc-jid-1",
        encrypted_job_id_source="encryptJobId",
    )

    with pytest.raises(
        identity_module.OfferTodayIdentityError,
        match=r"requested jobId=.*jid-1.*response jobId=.*jid-other",
    ):
        identity_module.validate_offertoday_detail_identity(
            identity,
            {"job_id": "jid-other", "raw_data": {"jobId": "jid-other"}},
        )


def test_validate_detail_identity_rejects_response_encrypted_job_id_mismatch():
    identity_module = _identity_module()
    identity = identity_module.OfferTodayDetailIdentity(
        job_id="jid-1",
        encrypted_job_id="enc-jid-1",
        encrypted_job_id_source="encryptJobId",
    )

    with pytest.raises(
        identity_module.OfferTodayIdentityError,
        match=r"requested encryptJobId=.*enc-jid-1.*response encryptJobId=.*enc-other",
    ):
        identity_module.validate_offertoday_detail_identity(
            identity,
            {
                "job_id": "jid-1",
                "encrypted_job_id": "enc-other",
                "raw_data": {
                    "jobId": "jid-1",
                    "encryptJobId": "enc-other",
                },
            },
        )


def test_validate_detail_identity_accepts_matching_jobid_without_encrypted_evidence() -> None:
    identity_module = _identity_module()
    identity = identity_module.OfferTodayDetailIdentity(
        "j-1",
        "enc-1",
        "encryptJobId",
    )

    identity_module.validate_offertoday_detail_identity(
        identity,
        {"jobId": "j-1"},
    )


def test_build_offertoday_canonical_job_reads_description_from_raw_detail_shape():
    listing = _parsed_listing()

    assert listing["encrypted_job_id"] == "enc-jid-1"
    canonical = build_offertoday_canonical_job({**listing, **_sample_detail_raw()})

    assert canonical.source_job_id == "jid-1"
    assert canonical.source_url.endswith("/enc-jid-1")
    assert canonical.company_name == "Alpha Ltd"
    assert canonical.description == "<p>Build ETL pipelines.</p><p>Apply now.</p>"


def test_canonical_builder_accepts_jobid_only_payload_and_uses_fallback_url():
    raw = _sample_detail_raw_missing_encrypted()
    before = deepcopy(raw)
    parsed = parse_offertoday_detail_response({"code": 0, "data": raw})

    canonical = build_offertoday_canonical_job(parsed)

    assert canonical.source_job_id == "jid-1"
    assert canonical.source_url.endswith("/jid-1")
    assert canonical.raw_data["encrypted_job_id"] == "jid-1"
    assert canonical.raw_data["encrypted_job_id_source"] == "jobId_fallback"
    assert canonical.raw_data["raw_data"] == before
    assert "encryptJobId" not in canonical.raw_data["raw_data"]


@pytest.mark.parametrize(
    ("payload", "missing_field"),
    [
        ({"encryptJobId": "enc-jid-1", "jobName": "Data Engineer"}, "jobId"),
    ],
)
def test_build_offertoday_canonical_job_rejects_missing_identity_field(
    payload: dict,
    missing_field: str,
):
    with pytest.raises(ValueError, match=missing_field):
        build_offertoday_canonical_job(payload)


def test_build_offertoday_canonical_job_rejects_present_non_string_encrypted_alias():
    with pytest.raises(ValueError, match=r"encryptJobId.*nonblank string"):
        build_offertoday_canonical_job(
            {
                "jobId": "jid-1",
                "encrypted_job_id": "enc-jid-1",
                "encryptJobId": [],
                "jobName": "Data Engineer",
            }
        )


def test_build_offertoday_company_data_uses_brand_id_for_source_identity():
    build_company_data = getattr(contracts, "build_offertoday_company_data", None)
    assert build_company_data is not None

    canonical = build_offertoday_canonical_job(_sample_detail_raw())
    company_data = build_company_data(canonical)

    assert company_data["source_site"] == "offertoday"
    assert company_data["source_company_id"] == "brand-123"
    assert company_data["company_id"] == "brand-123"
    assert company_data["name"] == "Alpha Ltd"


def test_build_offertoday_job_data_maps_source_ids_and_description():
    build_job_data = getattr(contracts, "build_offertoday_job_data", None)
    assert build_job_data is not None

    canonical = build_offertoday_canonical_job(_sample_detail_raw())
    job_data = build_job_data(canonical, "company-uuid")

    assert job_data["job_id"] == "jid-1"
    assert job_data["source_site"] == "offertoday"
    assert job_data["source_job_id"] == "jid-1"
    assert job_data["company_id"] == "company-uuid"
    assert job_data["description"] == "<p>Build ETL pipelines.</p><p>Apply now.</p>"
    assert job_data["posted_date"] is not None


def test_offertoday_job_repair_service_builds_canonical_snapshot_from_listing_detail_payload():
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = service_module.OfferTodayJobRepairService(db=None)
    listing = _listing_stub()
    listing.detail_payload = _sample_detail_raw()

    canonical = service.build_canonical_job_snapshot(_job_stub(), listing)

    assert canonical.source_job_id == "jid-1"
    assert canonical.source_url.endswith("/enc-jid-1")
    assert canonical.description == "<p>Build ETL pipelines.</p><p>Apply now.</p>"


def test_offertoday_job_repair_service_builds_canonical_snapshot_from_live_detail_override():
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = service_module.OfferTodayJobRepairService(db=None)

    canonical = service.build_canonical_job_snapshot(
        _job_stub(),
        detail_payload_override=_sample_detail_raw(),
    )

    assert canonical.source_job_id == "jid-1"
    assert canonical.source_url.endswith("/enc-jid-1")
    assert canonical.description == "<p>Build ETL pipelines.</p><p>Apply now.</p>"


def test_offertoday_job_repair_service_resolves_distinct_detail_identifiers_from_listing_payload():
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = service_module.OfferTodayJobRepairService(db=None)

    job_id, encrypted_job_id = service.resolve_detail_identifiers(
        _job_stub(),
        _listing_stub(),
    )

    assert job_id == "jid-1"
    assert encrypted_job_id == "enc-jid-1"


def test_repair_service_resolves_missing_encrypted_listing_identity_as_jobid_fallback() -> None:
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = service_module.OfferTodayJobRepairService(db=None)

    job_id, route_id = service.resolve_detail_identifiers(
        _job_stub(),
        _listing_stub(
            listing_payload=_parsed_listing(
                _sample_listing_raw_missing_encrypted()
            )
        ),
    )

    assert (job_id, route_id) == ("jid-1", "jid-1")


def test_repair_fallback_db_none_does_not_construct_authority_repositories(
    monkeypatch,
):
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )

    def fail_repository_construction():
        raise AssertionError("db=None must not construct authority repositories")

    monkeypatch.setattr(
        service_module,
        "CrawlJobListingRepository",
        fail_repository_construction,
    )
    monkeypatch.setattr(
        service_module,
        "CrawlJobRepository",
        fail_repository_construction,
    )

    service = service_module.OfferTodayJobRepairService(db=None)
    identity = service.resolve_detail_identity(
        _job_stub(),
        _listing_stub(listing_payload=_fallback_listing_payload()),
    )

    assert identity.encrypted_job_id_source == "jobId_fallback"
    assert service.crawl_job_listing_repository is None
    assert service.crawl_job_repository is None


def test_repair_authority_promotes_durable_explicit_event_without_listing_mutation():
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    fallback_payload = _fallback_listing_payload()
    listing = _listing_stub(listing_payload=fallback_payload)
    listing_before = deepcopy(listing.listing_payload)
    history_repository = _FakeIdentityHistoryRepository(
        [_identity_history_row("jid-1", fallback_payload)]
    )
    event_repository = _FakeIdentityObservationRepository(
        [_explicit_identity_observation("jid-1", "enc-jid-1")]
    )
    service = service_module.OfferTodayJobRepairService(
        db=object(),
        crawl_job_listing_repository=history_repository,
        crawl_job_repository=event_repository,
    )

    identity = service.resolve_detail_identity(_job_stub(), listing)
    identifiers = service.resolve_detail_identifiers(_job_stub(), listing)

    assert identity.job_id == "jid-1"
    assert identity.encrypted_job_id == "enc-jid-1"
    assert identity.encrypted_job_id_source == "encryptJobId"
    assert identifiers == ("jid-1", "enc-jid-1")
    assert listing.listing_payload == listing_before
    assert history_repository.calls == 1
    assert event_repository.calls == 1


def test_repair_authority_malformed_evidence_isolated_while_valid_jobs_collide():
    identity_module = _identity_module()
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    history_repository = _FakeIdentityHistoryRepository(
        [
            _identity_history_row(
                "jid-bad",
                {
                    "raw_data": {
                        "jobId": "jid-bad",
                        "encryptJobId": ["invalid"],
                    }
                },
            )
        ]
    )
    event_repository = _FakeIdentityObservationRepository(
        [
            _explicit_identity_observation("jid-1", "enc-shared"),
            _explicit_identity_observation("jid-2", "enc-shared"),
            _explicit_identity_observation("jid-ok", "enc-ok"),
        ]
    )
    service = service_module.OfferTodayJobRepairService(
        db=object(),
        crawl_job_listing_repository=history_repository,
        crawl_job_repository=event_repository,
    )

    with pytest.raises(identity_module.OfferTodayIdentityError) as malformed:
        service.resolve_detail_identity(
            SimpleNamespace(source_job_id="jid-bad"),
            _listing_stub(
                listing_payload=_fallback_listing_payload("jid-bad")
            ),
        )
    assert malformed.value.classification == "invalid_encrypted_job_id_evidence"

    unrelated = service.resolve_detail_identity(
        SimpleNamespace(source_job_id="jid-ok"),
        _listing_stub(listing_payload=_fallback_listing_payload("jid-ok")),
    )
    assert unrelated.encrypted_job_id == "enc-ok"

    with pytest.raises(identity_module.OfferTodayIdentityError) as collision:
        service.resolve_detail_identity(
            SimpleNamespace(source_job_id="jid-1"),
            _listing_stub(listing_payload=_fallback_listing_payload("jid-1")),
        )
    assert collision.value.classification == "reverse_collision"
    assert history_repository.calls == 1
    assert event_repository.calls == 1


def test_repair_authority_global_history_and_events_are_cached_once_for_two_jobs():
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    history_repository = _FakeIdentityHistoryRepository(
        [
            _identity_history_row("jid-1", _fallback_listing_payload("jid-1")),
            _identity_history_row("jid-2", _fallback_listing_payload("jid-2")),
        ]
    )
    event_repository = _FakeIdentityObservationRepository(
        [
            _explicit_identity_observation("jid-1", "enc-jid-1"),
            _explicit_identity_observation("jid-2", "enc-jid-2"),
        ]
    )
    service = service_module.OfferTodayJobRepairService(
        db=object(),
        crawl_job_listing_repository=history_repository,
        crawl_job_repository=event_repository,
    )

    resolved = []
    for job_id in ("jid-1", "jid-2"):
        job = SimpleNamespace(source_job_id=job_id)
        listing = _listing_stub(
            listing_payload=_fallback_listing_payload(job_id)
        )
        resolved.append(service.resolve_detail_identity(job, listing))

    assert [identity.encrypted_job_id for identity in resolved] == [
        "enc-jid-1",
        "enc-jid-2",
    ]
    assert history_repository.calls == 1
    assert event_repository.calls == 1


def test_repair_authority_two_explicit_routes_raise_before_write(monkeypatch):
    identity_module = _identity_module()
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    listing = _listing_stub(listing_payload=_fallback_listing_payload())
    service = _repair_service(
        service_module,
        db=object(),
        identity_history=[
            _identity_history_row("jid-1", _fallback_listing_payload()),
        ],
        identity_observations=[
            _explicit_identity_observation("jid-1", "enc-a"),
            _explicit_identity_observation("jid-1", "enc-b"),
        ],
    )
    monkeypatch.setattr(service, "get_latest_completed_listing", lambda _id: listing)
    monkeypatch.setattr(service, "get_latest_listing", lambda _id: listing)
    write_calls = []
    monkeypatch.setattr(
        service,
        "_persist_canonical_job",
        lambda *args, **kwargs: write_calls.append((args, kwargs)),
    )

    with pytest.raises(identity_module.OfferTodayIdentityError) as exc_info:
        service.repair_job(_job_stub())

    assert exc_info.value.classification == "multiple_explicit_encrypted_ids"
    assert write_calls == []


def test_repair_reverse_collision_raises_before_write(monkeypatch):
    identity_module = _identity_module()
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    listing = _listing_stub(listing_payload=_fallback_listing_payload())
    service = _repair_service(
        service_module,
        db=object(),
        identity_history=[
            _identity_history_row("jid-1", _fallback_listing_payload()),
        ],
        identity_observations=[
            _explicit_identity_observation("jid-1", "enc-shared"),
            _explicit_identity_observation("jid-2", "enc-shared"),
        ],
    )
    monkeypatch.setattr(service, "get_latest_completed_listing", lambda _id: listing)
    monkeypatch.setattr(service, "get_latest_listing", lambda _id: listing)
    write_calls = []
    monkeypatch.setattr(
        service,
        "_persist_canonical_job",
        lambda *args, **kwargs: write_calls.append((args, kwargs)),
    )

    with pytest.raises(identity_module.OfferTodayIdentityError) as exc_info:
        service.repair_job(_job_stub())

    assert exc_info.value.classification == "reverse_collision"
    assert write_calls == []


@pytest.mark.asyncio
async def test_offertoday_browser_detail_scraper_passes_both_ids_and_builds_typed_success(
    monkeypatch,
):
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    calls: list[dict[str, str]] = []
    parse_calls: list[dict] = []
    classify_calls: list[dict] = []
    response_payload = {
        "code": 0,
        "data": _sample_detail_raw_missing_encrypted(),
    }

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        calls.append({"job_id": job_id, "encrypted_job_id": encrypted_job_id})
        return response_payload

    real_parse = parse_offertoday_detail_response
    real_classify = scraper_module.classify_offertoday_response

    def parse_spy(payload: dict) -> dict:
        parse_calls.append(payload)
        return real_parse(payload)

    def classify_spy(payload, **kwargs):
        classify_calls.append({"payload": payload, **kwargs})
        return real_classify(payload, **kwargs)

    monkeypatch.setattr(scraper_module, "parse_offertoday_detail_response", parse_spy)
    monkeypatch.setattr(scraper_module, "classify_offertoday_response", classify_spy)

    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )
    result = await scraper.fetch_job_detail(
        "jid-1",
        encrypted_job_id="enc-jid-1",
    )

    assert calls == [{"job_id": "jid-1", "encrypted_job_id": "enc-jid-1"}]
    assert len(classify_calls) == 1
    assert len(parse_calls) == 1
    assert result.classification.kind is OfferTodayResponseKind.SUCCESS
    assert result.identity.job_id == "jid-1"
    assert result.identity.encrypted_job_id == "enc-jid-1"
    assert result.raw_response == response_payload
    assert result.parsed_detail["job_id"] == "jid-1"
    assert result.parsed_detail["encrypted_job_id"] == "jid-1"
    assert result.parsed_detail["encrypted_job_id_source"] == "jobId_fallback"
    assert result.parsed_detail["description_text"] == "Build ETL pipelines."
    assert result.canonical_detail["job_id"] == "jid-1"
    assert result.canonical_detail["encrypted_job_id"] == "enc-jid-1"
    assert result.canonical_detail["encrypted_job_id_source"] == "encryptJobId"

    response_payload["data"]["jobName"] = "Mutated after fetch"
    assert result.raw_response["data"]["jobName"] == "Data Engineer"


@pytest.mark.asyncio
async def test_browser_detail_scraper_jobid_fallback_uses_same_tokens_and_preserves_source():
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    calls: list[tuple[str, str]] = []
    raw_response = {
        "code": 0,
        "data": _sample_detail_raw_missing_encrypted(),
    }
    raw_before = deepcopy(raw_response)

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        calls.append((job_id, encrypted_job_id))
        return raw_response

    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )
    result = await scraper.fetch_job_detail(
        "jid-1",
        encrypted_job_id="jid-1",
        encrypted_job_id_source="jobId_fallback",
    )

    assert calls == [("jid-1", "jid-1")]
    assert result.identity.encrypted_job_id_source == "jobId_fallback"
    assert result.canonical_detail["encrypted_job_id_source"] == "jobId_fallback"
    assert result.raw_response == raw_before
    assert "encryptJobId" not in result.raw_response["data"]


@pytest.mark.asyncio
async def test_browser_detail_scraper_keeps_explicit_target_when_response_omits_encrypted_id():
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    raw_response = {"code": 0, "data": _sample_detail_raw_missing_encrypted()}

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        assert (job_id, encrypted_job_id) == ("jid-1", "enc-jid-1")
        return raw_response

    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )
    result = await scraper.fetch_job_detail(
        "jid-1",
        encrypted_job_id="enc-jid-1",
        encrypted_job_id_source="encryptJobId",
    )

    assert result.identity.encrypted_job_id == "enc-jid-1"
    assert result.identity.encrypted_job_id_source == "encryptJobId"
    assert result.canonical_detail["encrypted_job_id"] == "enc-jid-1"
    assert result.canonical_detail["encrypted_job_id_source"] == "encryptJobId"
    assert result.canonical_detail["raw_data"] == raw_response["data"]
    assert "encryptJobId" not in result.canonical_detail["raw_data"]


@pytest.mark.asyncio
async def test_offertoday_browser_detail_scraper_types_malformed_nested_payload():
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    response_payload = {
        "code": 0,
        "data": {
            **_sample_detail_raw(),
            "industry": "not-an-object",
        },
    }

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        return response_payload

    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )

    result = await scraper.fetch_job_detail(
        "jid-1",
        encrypted_job_id="enc-jid-1",
    )

    assert result.classification.kind is OfferTodayResponseKind.INVALID_PAYLOAD
    assert result.classification.retryable is False
    assert result.classification.stop_batch is False
    assert result.raw_response == response_payload
    assert result.parsed_detail is None
    assert result.canonical_detail is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field_name",
    ["benefits", "skills", "skillList", "keywords"],
)
async def test_offertoday_browser_detail_scraper_types_malformed_collection_payload(
    field_name: str,
):
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    response_payload = {
        "code": 0,
        "data": {
            **_sample_detail_raw(),
            field_name: 1,
        },
    }

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        return response_payload

    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )

    result = await scraper.fetch_job_detail(
        "jid-1",
        encrypted_job_id="enc-jid-1",
    )

    assert result.classification.kind is OfferTodayResponseKind.INVALID_PAYLOAD
    assert result.classification.retryable is False
    assert result.classification.stop_batch is False
    assert result.raw_response == response_payload
    assert result.parsed_detail is None
    assert result.canonical_detail is None


@pytest.mark.asyncio
async def test_detail_fetch_result_isolates_nested_evidence_representations():
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    response_payload = {"code": 0, "data": _sample_detail_raw()}

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        return response_payload

    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )
    result = await scraper.fetch_job_detail(
        "jid-1",
        encrypted_job_id="enc-jid-1",
    )

    result.canonical_detail["job_functions"][0]["children"][0][
        "name"
    ] = "Mutated canonical evidence"

    assert result.parsed_detail["job_functions"][0]["children"][0]["name"] == (
        "Software"
    )
    assert result.raw_response["data"]["jobFunctions"][0]["children"][0]["name"] == (
        "Software"
    )
    assert response_payload["data"]["jobFunctions"][0]["children"][0]["name"] == (
        "Software"
    )


@pytest.mark.asyncio
async def test_browser_detail_scraper_omitted_route_uses_jobid_fallback():
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    calls: list[tuple[str, str]] = []

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        calls.append((job_id, encrypted_job_id))
        return {
            "code": 0,
            "data": _sample_detail_raw_missing_encrypted(),
        }

    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )

    result = await scraper.fetch_job_detail("jid-1")

    assert calls == [("jid-1", "jid-1")]
    assert result.identity.encrypted_job_id_source == "jobId_fallback"


@pytest.mark.asyncio
async def test_offertoday_browser_detail_scraper_response_id_mismatch_is_typed_and_not_parsed(
    monkeypatch,
):
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        return {
            "code": 0,
            "data": {**_sample_detail_raw(), "jobId": "jid-other"},
        }

    parse_calls = 0

    def parse_spy(payload: dict):
        nonlocal parse_calls
        parse_calls += 1
        return parse_offertoday_detail_response(payload)

    monkeypatch.setattr(scraper_module, "parse_offertoday_detail_response", parse_spy)
    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )

    result = await scraper.fetch_job_detail(
        "jid-1",
        encrypted_job_id="enc-jid-1",
    )

    assert result.classification.kind is OfferTodayResponseKind.ID_MISMATCH
    assert result.parsed_detail is None
    assert result.canonical_detail is None
    assert parse_calls == 0


@pytest.mark.asyncio
async def test_offertoday_browser_detail_scraper_response_encrypted_id_mismatch_is_typed_and_not_parsed(
    monkeypatch,
):
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        return {
            "code": 0,
            "data": {
                **_sample_detail_raw(),
                "encryptJobId": "enc-other",
            },
        }

    parse_calls = 0

    def parse_spy(payload: dict):
        nonlocal parse_calls
        parse_calls += 1
        return parse_offertoday_detail_response(payload)

    monkeypatch.setattr(scraper_module, "parse_offertoday_detail_response", parse_spy)
    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )

    result = await scraper.fetch_job_detail(
        "jid-1",
        encrypted_job_id="enc-jid-1",
    )

    assert result.classification.kind is OfferTodayResponseKind.ID_MISMATCH
    assert result.parsed_detail is None
    assert result.canonical_detail is None
    assert parse_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport_error", "expected_kind", "expected_raw"),
    [
        (
            TimeoutError("request timed out"),
            OfferTodayResponseKind.TRANSIENT_TRANSPORT,
            None,
        ),
        (
            OfferTodayTransportError(
                "HTTP 429",
                http_status=429,
                response_url="https://www.offertoday.com/wapi/detail",
                payload={"error": "rate limited"},
                error_kind="http",
            ),
            OfferTodayResponseKind.TRANSIENT_TRANSPORT,
            {"error": "rate limited"},
        ),
        (
            OfferTodayTransportError(
                "OfferToday returned HTML",
                http_status=200,
                response_url="https://www.offertoday.com/wapi/detail",
                payload=None,
                error_kind="invalid_json",
            ),
            OfferTodayResponseKind.INVALID_PAYLOAD,
            None,
        ),
    ],
)
async def test_offertoday_browser_detail_scraper_classifies_transport_without_parsing(
    monkeypatch,
    transport_error: BaseException,
    expected_kind: OfferTodayResponseKind,
    expected_raw: dict | None,
):
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        raise transport_error

    parse_calls = 0

    def parse_spy(payload: dict):
        nonlocal parse_calls
        parse_calls += 1
        return parse_offertoday_detail_response(payload)

    monkeypatch.setattr(scraper_module, "parse_offertoday_detail_response", parse_spy)
    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )

    result = await scraper.fetch_job_detail(
        "jid-1",
        encrypted_job_id="enc-jid-1",
    )

    assert result.classification.kind is expected_kind
    assert result.raw_response == expected_raw
    assert result.parsed_detail is None
    assert result.canonical_detail is None
    assert parse_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception_type",
    (AssertionError, TypeError, RuntimeError, FileNotFoundError),
)
async def test_offertoday_browser_detail_scraper_propagates_unexpected_fetch_errors(
    monkeypatch,
    exception_type,
):
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    unexpected = exception_type("unexpected detail fetch failure")
    fetch_calls: list[tuple[str, str]] = []

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        fetch_calls.append((job_id, encrypted_job_id))
        raise unexpected

    classification_calls = 0
    original_classifier = scraper_module.classify_offertoday_response

    def classify_spy(*args, **kwargs):
        nonlocal classification_calls
        classification_calls += 1
        return original_classifier(*args, **kwargs)

    parse_calls = 0

    def parse_spy(payload: dict):
        nonlocal parse_calls
        parse_calls += 1
        return parse_offertoday_detail_response(payload)

    monkeypatch.setattr(scraper_module, "classify_offertoday_response", classify_spy)
    monkeypatch.setattr(scraper_module, "parse_offertoday_detail_response", parse_spy)
    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )

    with pytest.raises(exception_type) as raised:
        await scraper.fetch_job_detail(
            "jid-1",
            encrypted_job_id="enc-jid-1",
        )

    assert raised.value is unexpected
    assert fetch_calls == [("jid-1", "enc-jid-1")]
    assert classification_calls == 0
    assert parse_calls == 0


@pytest.mark.asyncio
async def test_offertoday_browser_detail_scraper_returns_typed_ip_block():
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )

    async def blocked_fetcher(*, job_id: str, encrypted_job_id: str):
        return {
            "code": -1000035,
            "msg": "IP blocked",
            "data": {},
        }

    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=blocked_fetcher
    )
    result = await scraper.fetch_job_detail(
        "jid-1",
        encrypted_job_id="enc-jid-1",
    )

    assert result.classification.kind is OfferTodayResponseKind.IP_BLOCKED
    assert result.parsed_detail is None
    assert result.canonical_detail is None


@pytest.mark.parametrize(
    "terminal_status",
    ["terminal_unavailable", "identity_conflict"],
)
def test_repair_candidates_exclude_any_historical_terminal_canonical_id(
    terminal_status: str,
):
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    db = _repair_database()
    try:
        company = _database_company()
        blocked = _database_job(
            "blocked",
            company_id=company.id,
            updated_offset=1,
        )
        eligible = _database_job(
            "eligible",
            company_id=company.id,
            updated_offset=2,
        )
        db.add_all(
            [
                company,
                blocked,
                eligible,
                _database_listing(
                    "blocked",
                    detail_status=terminal_status,
                    created_offset=1,
                ),
                _database_listing(
                    "blocked",
                    detail_status="pending",
                    created_offset=2,
                ),
                _database_listing(
                    "eligible",
                    source_site="jobsdb",
                    detail_status=terminal_status,
                    created_offset=3,
                ),
            ]
        )
        db.commit()

        candidates = service_module.OfferTodayJobRepairService(
            db
        ).iter_repair_candidates()

        assert [job.source_job_id for job in candidates] == ["eligible"]
    finally:
        db.close()


@pytest.mark.asyncio
async def test_offertoday_browser_detail_scraper_builds_runtime_from_resume_strategy_request_payload(
    monkeypatch,
):
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    runtime_calls: list[dict[str, object]] = []
    fetch_calls: list[tuple[str, str]] = []
    lifecycle: list[str] = []

    class _FakePage:
        url = "https://www.offertoday.com/hk/search"

    class _FakeRuntime:
        def __init__(self, **kwargs) -> None:
            runtime_calls.append(dict(kwargs))
            self._page = _FakePage()

        async def __aenter__(self):
            lifecycle.append("enter")
            return self

        async def __aexit__(self, exc_type, exc, tb):
            lifecycle.append("exit")
            return None

        async def require_healthy_session(self):
            lifecycle.append("preflight")

        async def fetch_detail_json(self, *, job_id: str, encrypted_job_id: str):
            lifecycle.append("fetch")
            fetch_calls.append((job_id, encrypted_job_id))
            return {
                "code": 0,
                "data": _sample_detail_raw(),
            }

    monkeypatch.setattr(
        scraper_module,
        "OfferTodayBrowserRuntime",
        _FakeRuntime,
        raising=False,
    )

    async with scraper_module.OfferTodayBrowserDetailScraper(
        request_payload={"resume_strategy": RESUME_STRATEGY_REUSE_OPEN_BROWSER}
    ) as scraper:
        result = await scraper.fetch_job_detail(
            "jid-1",
            encrypted_job_id="enc-jid-1",
        )

    assert runtime_calls == [
        {
            "headed": False,
            "auth_state_path": None,
            "resume_strategy": RESUME_STRATEGY_REUSE_OPEN_BROWSER,
        }
    ]
    assert lifecycle == ["enter", "preflight", "fetch", "exit"]
    assert fetch_calls == [("jid-1", "enc-jid-1")]
    assert result.classification.kind is OfferTodayResponseKind.SUCCESS
    assert result.canonical_detail["job_id"] == "jid-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("classification", "api_code"),
    [
        (OfferTodayResponseKind.AUTH_EXPIRED, 1002),
        (OfferTodayResponseKind.WAF_CHALLENGE, None),
    ],
)
async def test_repair_browser_preflight_manual_action_exits_and_clears_runtime_before_fetch(
    monkeypatch,
    classification: OfferTodayResponseKind,
    api_code: int | None,
):
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    expected_error = ManualActionRequiredError(
        source_site="offertoday",
        stage="browser_session",
        blocked_url="https://www.offertoday.com/hk/search",
        message=f"preflight {classification.value}",
        resume_context={
            "classification": classification.value,
            "api_code": api_code,
        },
    )
    lifecycle: list[object] = []

    class _FakePage:
        url = "https://www.offertoday.com/hk/search"

    class _FakeRuntime:
        def __init__(self, **kwargs) -> None:
            self._page = _FakePage()

        async def __aenter__(self):
            lifecycle.append("enter")
            return self

        async def require_healthy_session(self):
            lifecycle.append("preflight")
            raise expected_error

        async def fetch_detail_json(self, **kwargs):
            lifecycle.append("fetch")
            raise AssertionError("detail fetch must not run before healthy preflight")

        async def __aexit__(self, exc_type, exc, tb):
            lifecycle.append(("exit", exc_type, exc, tb))
            return None

    monkeypatch.setattr(
        scraper_module,
        "OfferTodayBrowserRuntime",
        _FakeRuntime,
        raising=False,
    )
    scraper = scraper_module.OfferTodayBrowserDetailScraper()

    with pytest.raises(ManualActionRequiredError) as exc_info:
        await scraper.__aenter__()

    assert exc_info.value is expected_error
    assert lifecycle[:2] == ["enter", "preflight"]
    assert "fetch" not in lifecycle
    exit_call = lifecycle[2]
    assert exit_call[0] == "exit"
    assert exit_call[1] is ManualActionRequiredError
    assert exit_call[2] is expected_error
    assert exit_call[3] is not None
    assert scraper._runtime is None
    assert scraper._page is None


@pytest.mark.asyncio
async def test_injected_detail_fetcher_skips_browser_runtime_and_preflight(monkeypatch):
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )

    class _UnexpectedRuntime:
        def __init__(self, **kwargs) -> None:
            raise AssertionError("offline fetcher must own the full fetch path")

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        return {"code": 0, "data": _sample_detail_raw()}

    monkeypatch.setattr(
        scraper_module,
        "OfferTodayBrowserRuntime",
        _UnexpectedRuntime,
        raising=False,
    )

    async with scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    ) as scraper:
        result = await scraper.fetch_job_detail(
            "jid-1",
            encrypted_job_id="enc-jid-1",
        )

    assert result.classification.kind is OfferTodayResponseKind.SUCCESS
    assert scraper._runtime is None
    assert scraper._page is None


@pytest.mark.asyncio
async def test_offertoday_browser_detail_scraper_propagates_manual_action_required_error(
    monkeypatch,
):
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    expected_error = ManualActionRequiredError(
        source_site="offertoday",
        stage="browser_session",
        blocked_url="https://www.offertoday.com/hk/search",
        message="Manual action required",
    )
    exit_calls: list[tuple[object, object, object]] = []

    class _FakeRuntime:
        def __init__(self, **kwargs) -> None:
            self.kwargs = dict(kwargs)

        async def __aenter__(self):
            raise expected_error

        async def __aexit__(self, exc_type, exc, tb):
            exit_calls.append((exc_type, exc, tb))
            return None

    monkeypatch.setattr(
        scraper_module,
        "OfferTodayBrowserRuntime",
        _FakeRuntime,
        raising=False,
    )

    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        request_payload={"resume_strategy": RESUME_STRATEGY_REUSE_OPEN_BROWSER}
    )
    with pytest.raises(ManualActionRequiredError) as exc_info:
        async with scraper:
            pass

    assert exc_info.value is expected_error
    assert len(exit_calls) == 1
    assert exit_calls[0][0] is ManualActionRequiredError
    assert exit_calls[0][1] is expected_error
    assert exit_calls[0][2] is not None
    assert scraper._runtime is None
    assert scraper._page is None


def test_offertoday_browser_detail_scraper_detects_waf_challenge_urls():
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    scraper_cls = scraper_module.OfferTodayBrowserDetailScraper

    assert scraper_cls.is_waf_challenge_url(
        "https://www.offertoday.com/web/passport/cm/verify.html?callbackUrl=test"
    )
    assert not scraper_cls.is_waf_challenge_url("https://www.offertoday.com/hk/search")


def test_offertoday_browser_detail_scraper_removes_legacy_outcome_exceptions():
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )

    assert not hasattr(scraper_module, "OfferTodayIPBlockedError")
    assert not hasattr(scraper_module, "OfferTodayDetailUnavailableError")


def test_cached_repair_rejects_mismatched_raw_response_identity_before_persistence(
    monkeypatch,
):
    identity_module = _identity_module()
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = _repair_service(service_module, db=object())
    listing = _listing_stub(listing_payload=_fallback_listing_payload())
    listing.detail_status = "completed"
    listing.detail_payload = {
        **_fallback_listing_payload(),
        "raw_data": {
            "jobId": "jid-1",
            "encryptJobId": "enc-other",
        },
    }

    monkeypatch.setattr(service, "get_latest_completed_listing", lambda _id: listing)
    monkeypatch.setattr(service, "get_latest_listing", lambda _id: listing)

    def fail_persist(*args, **kwargs):
        raise AssertionError("mismatched cached detail must not be persisted")

    monkeypatch.setattr(service, "_persist_canonical_job", fail_persist)

    with pytest.raises(
        identity_module.OfferTodayIdentityError,
        match=r"requested encryptJobId=.*jid-1.*response encryptJobId=.*enc-other",
    ):
        service.repair_job(_job_stub())


def test_cached_repair_accepts_normalized_fallback_with_empty_raw_data(
    monkeypatch,
):
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = _repair_service(service_module, db=object())
    listing = _listing_stub(listing_payload=_fallback_listing_payload())
    listing.detail_status = "completed"
    listing.detail_payload = {
        **_fallback_listing_payload(),
        "raw_data": {},
    }
    expected_result = service_module.OfferTodayRepairResult(
        action="updated",
        description_repaired=False,
        company_reassigned=False,
        listing_attached=False,
    )
    captured = {}

    monkeypatch.setattr(service, "get_latest_completed_listing", lambda _id: listing)
    monkeypatch.setattr(service, "get_latest_listing", lambda _id: listing)

    def fake_persist(job, canonical, persisted_listing):
        captured["canonical"] = canonical
        captured["listing"] = persisted_listing
        return expected_result

    monkeypatch.setattr(service, "_persist_canonical_job", fake_persist)

    assert service.repair_job(_job_stub()) is expected_result
    assert captured["listing"] is listing
    assert captured["canonical"].raw_data["encrypted_job_id_source"] == (
        "jobId_fallback"
    )
    assert captured["canonical"].raw_data["raw_data"] == {}


def test_cached_repair_rejects_invalid_top_level_encrypted_alias_before_persistence(
    monkeypatch,
):
    identity_module = _identity_module()
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = _repair_service(service_module, db=object())
    listing = _listing_stub(listing_payload=_fallback_listing_payload())
    listing.detail_status = "completed"
    listing.detail_payload = {
        **_fallback_listing_payload(),
        "encryptJobId": [],
        "raw_data": {
            "jobId": "jid-1",
            "encryptJobId": "jid-1",
        },
    }

    monkeypatch.setattr(service, "get_latest_completed_listing", lambda _id: listing)
    monkeypatch.setattr(service, "get_latest_listing", lambda _id: listing)

    def fail_persist(*args, **kwargs):
        raise AssertionError("invalid cached identity evidence must not be persisted")

    monkeypatch.setattr(service, "_persist_canonical_job", fail_persist)

    with pytest.raises(
        identity_module.OfferTodayIdentityError,
        match=r"encryptJobId.*nonblank string",
    ):
        service.repair_job(_job_stub())


def test_offline_parsed_repair_rejects_foreign_full_identity_before_mutation(
    monkeypatch,
):
    identity_module = _identity_module()
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = _repair_service(service_module, db=object())
    listing = _listing_stub()
    listing_before = dict(vars(listing))
    parsed_detail = parse_offertoday_detail_response(
        {
            "code": 0,
            "data": {
                **_sample_detail_raw(),
                "jobId": "jid-other",
                "encryptJobId": "enc-other",
            },
        }
    )

    monkeypatch.setattr(service, "get_latest_listing", lambda source_job_id: listing)

    def fail_persist(*args, **kwargs):
        raise AssertionError("foreign offline detail must not be persisted")

    monkeypatch.setattr(service, "_persist_canonical_job", fail_persist)

    with pytest.raises(
        identity_module.OfferTodayIdentityError,
        match=r"requested jobId=.*jid-1.*response jobId=.*jid-other",
    ):
        service.repair_job_with_parsed_detail(_job_stub(), parsed_detail)

    assert vars(listing) == listing_before


def test_offline_parsed_repair_rejects_conflicting_encrypted_identity_before_mutation(
    monkeypatch,
):
    identity_module = _identity_module()
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = _repair_service(service_module, db=object())
    listing = _listing_stub()
    listing_before = dict(vars(listing))
    parsed_detail = parse_offertoday_detail_response(
        {
            "code": 0,
            "data": {
                **_sample_detail_raw(),
                "encryptJobId": "enc-other",
            },
        }
    )

    monkeypatch.setattr(service, "get_latest_listing", lambda source_job_id: listing)

    def fail_persist(*args, **kwargs):
        raise AssertionError("mismatched offline detail must not be persisted")

    monkeypatch.setattr(service, "_persist_canonical_job", fail_persist)

    with pytest.raises(
        identity_module.OfferTodayIdentityError,
        match=r"requested encryptJobId=.*enc-jid-1.*response encryptJobId=.*enc-other",
    ):
        service.repair_job_with_parsed_detail(_job_stub(), parsed_detail)

    assert vars(listing) == listing_before


def test_offline_parsed_repair_build_failure_leaves_listing_unchanged(monkeypatch):
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = _repair_service(service_module, db=object())
    listing = _listing_stub()
    listing_before = dict(vars(listing))
    parsed_detail = parse_offertoday_detail_response(
        {"code": 0, "data": _sample_detail_raw()}
    )

    monkeypatch.setattr(service, "get_latest_listing", lambda source_job_id: listing)

    def fail_build(*args, **kwargs):
        raise ValueError("offline canonical build failed")

    monkeypatch.setattr(service, "build_canonical_job_snapshot", fail_build)

    def fail_persist(*args, **kwargs):
        raise AssertionError("failed offline build must not be persisted")

    monkeypatch.setattr(service, "_persist_canonical_job", fail_persist)

    with pytest.raises(ValueError, match="offline canonical build failed"):
        service.repair_job_with_parsed_detail(_job_stub(), parsed_detail)

    assert vars(listing) == listing_before


def test_offline_parsed_repair_persist_failure_leaves_listing_unchanged(monkeypatch):
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = _repair_service(service_module, db=object())
    listing = _listing_stub()
    listing_before = dict(vars(listing))
    parsed_detail = parse_offertoday_detail_response(
        {"code": 0, "data": _sample_detail_raw_missing_encrypted()}
    )

    monkeypatch.setattr(service, "get_latest_listing", lambda source_job_id: listing)

    def fail_persist(*args, **kwargs):
        raise RuntimeError("offline persist failed")

    monkeypatch.setattr(service, "_persist_canonical_job", fail_persist)

    with pytest.raises(RuntimeError, match="offline persist failed"):
        service.repair_job_with_parsed_detail(_job_stub(), parsed_detail)

    assert vars(listing) == listing_before


def test_offline_parsed_repair_persists_canonical_identity_for_cached_round_trip(
    monkeypatch,
):
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = _repair_service(service_module, db=object())
    listing = _listing_stub()
    job = _job_stub()
    parsed_detail = parse_offertoday_detail_response(
        {"code": 0, "data": _sample_detail_raw_missing_encrypted()}
    )
    raw_before = deepcopy(parsed_detail["raw_data"])
    expected_repair_result = service_module.OfferTodayRepairResult(
        action="updated",
        description_repaired=True,
        company_reassigned=False,
        listing_attached=False,
    )
    persisted_canonical = []

    monkeypatch.setattr(service, "get_latest_listing", lambda source_job_id: listing)
    monkeypatch.setattr(
        service,
        "get_latest_completed_listing",
        lambda source_job_id: listing,
    )

    def fake_persist(job, canonical, persisted_listing):
        persisted_canonical.append(canonical)
        assert persisted_listing is listing
        return expected_repair_result

    monkeypatch.setattr(service, "_persist_canonical_job", fake_persist)

    assert (
        service.repair_job_with_parsed_detail(job, parsed_detail)
        is expected_repair_result
    )
    assert service.repair_job(job) is expected_repair_result

    assert listing.detail_payload["job_id"] == "jid-1"
    assert listing.detail_payload["encrypted_job_id"] == "enc-jid-1"
    assert listing.detail_payload["encrypted_job_id_source"] == "encryptJobId"
    assert listing.detail_payload["raw_data"] == raw_before
    assert "encryptJobId" not in listing.detail_payload["raw_data"]
    assert len(persisted_canonical) == 2
    assert all(
        canonical.source_url.endswith("/enc-jid-1") for canonical in persisted_canonical
    )


def test_offline_parsed_repair_fallback_round_trip_preserves_source_and_raw(
    monkeypatch,
):
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = _repair_service(service_module, db=object())
    listing = _listing_stub(listing_payload=_fallback_listing_payload())
    parsed_detail = parse_offertoday_detail_response(
        {"code": 0, "data": _sample_detail_raw_missing_encrypted()}
    )
    raw_before = deepcopy(parsed_detail["raw_data"])
    expected_result = service_module.OfferTodayRepairResult(
        action="updated",
        description_repaired=True,
        company_reassigned=False,
        listing_attached=False,
    )
    persisted_canonical = []
    monkeypatch.setattr(service, "get_latest_listing", lambda _id: listing)

    def fake_persist(job, canonical, persisted_listing):
        persisted_canonical.append(canonical)
        assert persisted_listing is listing
        return expected_result

    monkeypatch.setattr(service, "_persist_canonical_job", fake_persist)

    assert service.repair_job_with_parsed_detail(_job_stub(), parsed_detail) is expected_result

    assert listing.detail_payload["job_id"] == "jid-1"
    assert listing.detail_payload["encrypted_job_id"] == "jid-1"
    assert listing.detail_payload["encrypted_job_id_source"] == "jobId_fallback"
    assert listing.detail_payload["raw_data"] == raw_before
    assert "encryptJobId" not in listing.detail_payload["raw_data"]
    assert persisted_canonical[0].source_url.endswith("/jid-1")


def test_repair_authority_promotes_cached_and_offline_parsed_repair_route(
    monkeypatch,
):
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    listing = _listing_stub(listing_payload=_fallback_listing_payload())
    parsed_detail = parse_offertoday_detail_response(
        {"code": 0, "data": _sample_detail_raw_missing_encrypted()}
    )
    listing.detail_status = "completed"
    listing.detail_payload = deepcopy(parsed_detail)
    listing_before = deepcopy(vars(listing))
    raw_before = deepcopy(parsed_detail["raw_data"])
    service = _repair_service(
        service_module,
        db=object(),
        identity_history=[
            _identity_history_row("jid-1", _fallback_listing_payload()),
        ],
        identity_observations=[
            _explicit_identity_observation("jid-1", "enc-promoted"),
        ],
    )
    expected_result = service_module.OfferTodayRepairResult(
        action="updated",
        description_repaired=True,
        company_reassigned=False,
        listing_attached=False,
    )
    persisted_canonical = []
    monkeypatch.setattr(service, "get_latest_listing", lambda _id: listing)
    monkeypatch.setattr(service, "get_latest_completed_listing", lambda _id: listing)

    def fake_persist(job, canonical, persisted_listing):
        persisted_canonical.append(canonical)
        assert persisted_listing is listing
        return expected_result

    monkeypatch.setattr(service, "_persist_canonical_job", fake_persist)

    assert service.repair_job(_job_stub()) is expected_result
    assert vars(listing) == listing_before
    assert persisted_canonical[-1].source_url.endswith("/enc-promoted")

    assert service.repair_job_with_parsed_detail(_job_stub(), parsed_detail) is expected_result
    assert listing.detail_payload["job_id"] == "jid-1"
    assert listing.detail_payload["encrypted_job_id"] == "enc-promoted"
    assert listing.detail_payload["encrypted_job_id_source"] == "encryptJobId"
    assert listing.detail_payload["raw_data"] == raw_before
    assert "encryptJobId" not in listing.detail_payload["raw_data"]
    assert persisted_canonical[-1].source_url.endswith("/enc-promoted")


def test_repair_authority_promotes_typed_detail_result_route_and_preserves_raw(
    monkeypatch,
):
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    listing = _listing_stub(listing_payload=_fallback_listing_payload())
    response_data = _sample_detail_raw_missing_encrypted()
    parsed_detail = parse_offertoday_detail_response(
        {"code": 0, "data": response_data}
    )
    canonical_detail = {
        **parsed_detail,
        "job_id": "jid-1",
        "encrypted_job_id": "enc-promoted",
        "encrypted_job_id_source": "encryptJobId",
    }
    result = _detail_fetch_result(
        encrypted_job_id="enc-promoted",
        encrypted_job_id_source="encryptJobId",
        payload={"code": 0, "data": response_data},
        canonical_detail=canonical_detail,
    )
    service = _repair_service(
        service_module,
        db=object(),
        identity_history=[
            _identity_history_row("jid-1", _fallback_listing_payload()),
        ],
        identity_observations=[
            _explicit_identity_observation("jid-1", "enc-promoted"),
        ],
    )
    expected_result = service_module.OfferTodayRepairResult(
        action="updated",
        description_repaired=True,
        company_reassigned=False,
        listing_attached=False,
    )
    persisted_canonical = []
    monkeypatch.setattr(service, "get_latest_listing", lambda _id: listing)

    def fake_persist(job, canonical, persisted_listing):
        persisted_canonical.append(canonical)
        return expected_result

    monkeypatch.setattr(service, "_persist_canonical_job", fake_persist)

    assert service.repair_job_with_detail_result(_job_stub(), result) is expected_result

    assert listing.detail_payload["job_id"] == "jid-1"
    assert listing.detail_payload["encrypted_job_id"] == "enc-promoted"
    assert listing.detail_payload["encrypted_job_id_source"] == "encryptJobId"
    assert listing.detail_payload["raw_data"] == response_data
    assert "encryptJobId" not in listing.detail_payload["raw_data"]
    assert persisted_canonical[-1].source_url.endswith("/enc-promoted")


@pytest.mark.asyncio
async def test_terminal_detail_is_classified_once_not_parsed_and_marks_all_canonical_rows(
    monkeypatch,
):
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    raw_response = {
        "code": 2520,
        "msg": "Position unavailable",
        "data": None,
    }
    classify_calls = 0
    parse_calls = 0
    real_classify = scraper_module.classify_offertoday_response

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        return raw_response

    def classify_spy(payload, **kwargs):
        nonlocal classify_calls
        classify_calls += 1
        return real_classify(payload, **kwargs)

    def fail_parse(payload):
        nonlocal parse_calls
        parse_calls += 1
        raise AssertionError("terminal responses must not be parsed")

    monkeypatch.setattr(scraper_module, "classify_offertoday_response", classify_spy)
    monkeypatch.setattr(scraper_module, "parse_offertoday_detail_response", fail_parse)
    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )

    fetch_result = await scraper.fetch_job_detail(
        "jid-1",
        encrypted_job_id="enc-jid-1",
    )

    latest = _listing_stub()
    historical = _listing_stub()
    service = _repair_service(service_module, db=object())
    monkeypatch.setattr(service, "get_latest_listing", lambda source_job_id: latest)
    monkeypatch.setattr(
        service,
        "get_listings_for_canonical_id",
        lambda source_job_id: [latest, historical],
        raising=False,
    )

    repair_result = service.repair_job_with_detail_result(
        _job_stub(),
        fetch_result,
    )

    assert classify_calls == 1
    assert parse_calls == 0
    assert fetch_result.classification.kind is OfferTodayResponseKind.TERMINAL_UNAVAILABLE
    assert fetch_result.raw_response == raw_response
    assert fetch_result.parsed_detail is None
    assert fetch_result.canonical_detail is None
    assert repair_result.action == "terminal_unavailable"
    assert [latest.detail_status, historical.detail_status] == [
        "terminal_unavailable",
        "terminal_unavailable",
    ]
    assert latest.detail_payload == raw_response
    assert historical.detail_payload == raw_response
    assert latest.detail_completed_at is not None
    assert historical.detail_completed_at is not None


@pytest.mark.asyncio
async def test_repair_success_consumes_parsed_once_typed_result(monkeypatch):
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    parse_calls = 0
    real_parse = parse_offertoday_detail_response

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        return {"code": 0, "data": _sample_detail_raw_missing_encrypted()}

    def parse_spy(payload: dict) -> dict:
        nonlocal parse_calls
        parse_calls += 1
        return real_parse(payload)

    monkeypatch.setattr(scraper_module, "parse_offertoday_detail_response", parse_spy)
    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )
    fetch_result = await scraper.fetch_job_detail(
        "jid-1",
        encrypted_job_id="enc-jid-1",
    )

    service = _repair_service(service_module, db=object())
    listing = _listing_stub()
    captured: dict[str, object] = {}
    expected_repair_result = service_module.OfferTodayRepairResult(
        action="updated",
        description_repaired=True,
        company_reassigned=False,
        listing_attached=False,
    )

    monkeypatch.setattr(service, "get_latest_listing", lambda source_job_id: listing)

    def fake_persist(job, canonical, persisted_listing):
        captured["canonical"] = canonical
        captured["listing"] = persisted_listing
        return expected_repair_result

    monkeypatch.setattr(service, "_persist_canonical_job", fake_persist)

    repair_result = service.repair_job_with_detail_result(_job_stub(), fetch_result)

    assert repair_result is expected_repair_result
    assert parse_calls == 1
    assert listing.detail_status == "completed"
    assert listing.detail_payload == fetch_result.canonical_detail
    assert captured["listing"] is listing
    assert captured["canonical"].raw_data["description_text"] == "Build ETL pipelines."
    assert captured["canonical"].source_url.endswith("/enc-jid-1")


@pytest.mark.asyncio
async def test_repair_success_updates_job_description_with_one_parse_across_scraper_and_service(
    monkeypatch,
):
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    parse_calls = 0
    real_parse = parse_offertoday_detail_response

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        return {"code": 0, "data": _sample_detail_raw_missing_encrypted()}

    def parse_spy(payload: dict) -> dict:
        nonlocal parse_calls
        parse_calls += 1
        return real_parse(payload)

    monkeypatch.setattr(scraper_module, "parse_offertoday_detail_response", parse_spy)
    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )
    fetch_result = await scraper.fetch_job_detail(
        "jid-1",
        encrypted_job_id="enc-jid-1",
    )

    db = _repair_database()
    try:
        company = _database_company()
        job = _database_job("jid-1", company_id=company.id)
        listing = _database_listing(
            "jid-1",
            listing_payload=_parsed_listing(),
        )
        db.add_all([company, job, listing])
        db.commit()

        repair_result = _repair_service(
            service_module,
            db=db,
        ).repair_job_with_detail_result(job, fetch_result)
        db.flush()
        db.refresh(job)
        db.refresh(listing)

        assert parse_calls == 1
        assert repair_result.description_repaired is True
        assert "Build ETL pipelines." in job.description
        assert listing.detail_status == "completed"
        assert listing.published_job_id == job.id
    finally:
        db.close()


@pytest.mark.asyncio
async def test_repair_fallback_result_accepts_matching_explicit_response_identity():
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    response_data = {
        **_sample_detail_raw(),
        "encryptJobId": "jid-1",
    }

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        assert (job_id, encrypted_job_id) == ("jid-1", "jid-1")
        return {"code": 0, "data": response_data}

    fetch_result = await scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    ).fetch_job_detail(
        "jid-1",
        encrypted_job_id="jid-1",
        encrypted_job_id_source="jobId_fallback",
    )

    db = _repair_database()
    try:
        company = _database_company()
        job = _database_job("jid-1", company_id=company.id)
        listing = _database_listing(
            "jid-1",
            listing_payload=_fallback_listing_payload(),
        )
        db.add_all([company, job, listing])
        db.commit()

        repair_result = _repair_service(
            service_module,
            db=db,
        ).repair_job_with_detail_result(job, fetch_result)
        db.flush()
        db.refresh(job)
        db.refresh(listing)

        assert repair_result.description_repaired is True
        assert "Build ETL pipelines." in job.description
        assert job.raw_data["encrypted_job_id_source"] == "jobId_fallback"
        assert job.raw_data["raw_data"]["encryptJobId"] == "jid-1"
        assert listing.detail_status == "completed"
        assert listing.detail_payload["encrypted_job_id_source"] == "jobId_fallback"
        assert listing.detail_payload["raw_data"] == response_data
        assert listing.published_job_id == job.id
        assert db.query(Company).filter(Company.name == "Alpha Ltd").one()
    finally:
        db.close()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"code": 2520, "msg": "Position unavailable", "data": None},
    ],
    ids=("success", "non_success"),
)
def test_repair_detail_result_rejects_result_owned_by_another_job_before_mutation(
    monkeypatch,
    payload: dict | None,
):
    identity_module = _identity_module()
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = _repair_service(service_module, db=object())
    listing = _listing_stub()
    listing_before = dict(vars(listing))
    result = _detail_fetch_result(
        job_id="jid-other",
        encrypted_job_id="enc-other",
        payload=payload,
    )

    monkeypatch.setattr(service, "get_latest_listing", lambda source_job_id: listing)

    def fail_persist(*args, **kwargs):
        raise AssertionError("foreign detail result must not be persisted")

    monkeypatch.setattr(service, "_persist_canonical_job", fail_persist)

    with pytest.raises(
        identity_module.OfferTodayIdentityError,
        match=r"expected.*jid-1.*result.*jid-other",
    ):
        service.repair_job_with_detail_result(_job_stub(), result)

    assert vars(listing) == listing_before


def test_repair_detail_result_rejects_same_route_provenance_mismatch_before_mutation(
    monkeypatch,
):
    identity_module = _identity_module()
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    listing = _listing_stub(listing_payload=_fallback_listing_payload())
    listing_before = deepcopy(vars(listing))
    service = _repair_service(
        service_module,
        db=object(),
        identity_history=[
            _identity_history_row("jid-1", _fallback_listing_payload()),
        ],
        identity_observations=[
            _explicit_identity_observation("jid-1", "jid-1"),
        ],
    )
    result = _detail_fetch_result(
        encrypted_job_id="jid-1",
        encrypted_job_id_source="jobId_fallback",
    )
    monkeypatch.setattr(service, "get_latest_listing", lambda _id: listing)

    def fail_persist(*args, **kwargs):
        raise AssertionError("provenance mismatch must fail before persistence")

    monkeypatch.setattr(service, "_persist_canonical_job", fail_persist)

    with pytest.raises(
        identity_module.OfferTodayIdentityError,
        match=r"expected.*source='encryptJobId'.*result.*source='jobId_fallback'",
    ):
        service.repair_job_with_detail_result(_job_stub(), result)

    assert vars(listing) == listing_before


def test_repair_detail_result_rejects_canonical_identity_mismatch_before_mutation(
    monkeypatch,
):
    identity_module = _identity_module()
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = _repair_service(service_module, db=object())
    listing = _listing_stub()
    listing_before = dict(vars(listing))
    result = _detail_fetch_result(
        canonical_detail={
            "job_id": "jid-1",
            "encrypted_job_id": "enc-other",
            "raw_data": {"jobId": "jid-1"},
        }
    )

    monkeypatch.setattr(service, "get_latest_listing", lambda source_job_id: listing)

    def fail_persist(*args, **kwargs):
        raise AssertionError("mismatched canonical detail must not be persisted")

    monkeypatch.setattr(service, "_persist_canonical_job", fail_persist)

    with pytest.raises(
        identity_module.OfferTodayIdentityError,
        match=r"requested encryptJobId=.*enc-jid-1.*response encryptJobId=.*enc-other",
    ):
        service.repair_job_with_detail_result(_job_stub(), result)

    assert vars(listing) == listing_before


def test_repair_detail_result_rejects_foreign_canonical_raw_identity_before_mutation(
    monkeypatch,
):
    identity_module = _identity_module()
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = _repair_service(service_module, db=object())
    listing = _listing_stub()
    listing_before = dict(vars(listing))
    result = _detail_fetch_result(
        canonical_detail={
            "job_id": "jid-1",
            "encrypted_job_id": "enc-jid-1",
            "encrypted_job_id_source": "encryptJobId",
            "raw_data": {
                "jobId": "jid-other",
                "encryptJobId": "enc-other",
            },
        }
    )

    monkeypatch.setattr(service, "get_latest_listing", lambda source_job_id: listing)

    def fail_persist(*args, **kwargs):
        raise AssertionError("foreign canonical raw identity must not be persisted")

    monkeypatch.setattr(service, "_persist_canonical_job", fail_persist)

    with pytest.raises(
        identity_module.OfferTodayIdentityError,
        match=r"requested jobId=.*jid-1.*response jobId=.*jid-other",
    ):
        service.repair_job_with_detail_result(_job_stub(), result)

    assert vars(listing) == listing_before


def test_repair_detail_result_build_failure_leaves_listing_unchanged(monkeypatch):
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = _repair_service(service_module, db=object())
    listing = _listing_stub()
    listing_before = dict(vars(listing))
    result = _detail_fetch_result()

    monkeypatch.setattr(service, "get_latest_listing", lambda source_job_id: listing)

    def fail_build(*args, **kwargs):
        raise ValueError("canonical build failed")

    monkeypatch.setattr(service, "build_canonical_job_snapshot", fail_build)

    def fail_persist(*args, **kwargs):
        raise AssertionError("failed canonical build must not be persisted")

    monkeypatch.setattr(service, "_persist_canonical_job", fail_persist)

    with pytest.raises(ValueError, match="canonical build failed"):
        service.repair_job_with_detail_result(_job_stub(), result)

    assert vars(listing) == listing_before


def test_repair_detail_result_persist_failure_leaves_listing_unchanged(monkeypatch):
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = _repair_service(service_module, db=object())
    listing = _listing_stub()
    listing_before = dict(vars(listing))
    result = _detail_fetch_result()

    monkeypatch.setattr(service, "get_latest_listing", lambda source_job_id: listing)

    def fail_persist(*args, **kwargs):
        raise RuntimeError("typed result persist failed")

    monkeypatch.setattr(service, "_persist_canonical_job", fail_persist)

    with pytest.raises(RuntimeError, match="typed result persist failed"):
        service.repair_job_with_detail_result(_job_stub(), result)

    assert vars(listing) == listing_before


@pytest.mark.parametrize(
    ("payload", "expected_kind", "expected_status"),
    [
        (
            {"code": 2520, "msg": "Position unavailable", "data": None},
            OfferTodayResponseKind.TERMINAL_UNAVAILABLE,
            "terminal_unavailable",
        ),
        (
            {"code": 1002, "msg": "Login expired", "data": None},
            OfferTodayResponseKind.AUTH_EXPIRED,
            "failed",
        ),
    ],
)
def test_repair_non_success_records_evidence_without_merging_job(
    monkeypatch,
    payload: dict,
    expected_kind: OfferTodayResponseKind,
    expected_status: str,
):
    identity_module = _identity_module()
    policy_module = importlib.import_module("app.sources.offertoday.response_policy")
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    identity = identity_module.OfferTodayDetailIdentity(
        job_id="jid-1",
        encrypted_job_id="enc-jid-1",
        encrypted_job_id_source="encryptJobId",
    )
    classification = policy_module.classify_offertoday_response(
        payload,
        operation="detail",
        expected_job_id="jid-1",
    )
    fetch_result = identity_module.OfferTodayDetailFetchResult(
        identity=identity,
        classification=classification,
        raw_response=payload,
        parsed_detail=None,
        canonical_detail=None,
    )
    service = _repair_service(service_module, db=object())
    listing = _listing_stub()
    job = _job_stub()
    job_before = dict(vars(job))

    monkeypatch.setattr(service, "get_latest_listing", lambda source_job_id: listing)
    monkeypatch.setattr(
        service,
        "get_listings_for_canonical_id",
        lambda source_job_id: [listing],
        raising=False,
    )

    def fail_persist(*args, **kwargs):
        raise AssertionError("non-success response must not merge into Job")

    monkeypatch.setattr(service, "_persist_canonical_job", fail_persist)

    repair_result = service.repair_job_with_detail_result(job, fetch_result)

    assert repair_result.action == expected_kind.value
    assert repair_result.description_repaired is False
    assert vars(job) == job_before
    assert listing.detail_status == expected_status
    assert listing.detail_payload == payload
    evidence = json.loads(listing.detail_error_message)
    assert evidence == {
        "code": classification.code,
        "encrypted_job_id": "enc-jid-1",
        "encrypted_job_id_source": "encryptJobId",
        "job_id": "jid-1",
        "kind": expected_kind.value,
        "message": classification.message,
        "retryable": classification.retryable,
        "stop_batch": classification.stop_batch,
    }
    assert listing.detail_completed_at is not None


def test_repair_service_keeps_offline_parsed_fixture_api_distinct_from_network_results():
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service_cls = service_module.OfferTodayJobRepairService

    assert hasattr(service_cls, "repair_job_with_parsed_detail")
    assert hasattr(service_cls, "repair_job_with_detail_result")
    assert not hasattr(service_cls, "repair_job_with_detail_payload")
