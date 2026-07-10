from __future__ import annotations

import importlib
import importlib.util
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.sources.contracts as contracts
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


def test_listing_parser_preserves_missing_encrypted_id_as_empty():
    listing = _parsed_listing(_sample_listing_raw_missing_encrypted())

    assert listing["job_id"] == "jid-1"
    assert listing["encrypted_job_id"] == ""


def test_detail_parser_preserves_missing_encrypted_id_as_empty():
    parsed = parse_offertoday_detail_response(
        {"code": 0, "data": _sample_detail_raw_missing_encrypted()}
    )

    assert parsed["job_id"] == "jid-1"
    assert parsed["encrypted_job_id"] == ""


def test_resolve_detail_identity_requires_encrypted_id_from_listing_evidence():
    identity_module = _identity_module()

    with pytest.raises(identity_module.OfferTodayIdentityError, match="encryptJobId"):
        identity_module.resolve_offertoday_detail_identity(
            source_job_id="jid-1",
            listing_payload=_parsed_listing(_sample_listing_raw_missing_encrypted()),
        )


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
    assert identity.__slots__ == ("job_id", "encrypted_job_id")
    with pytest.raises(FrozenInstanceError):
        identity.job_id = "other"


def test_validate_detail_identity_rejects_response_job_id_mismatch():
    identity_module = _identity_module()
    identity = identity_module.OfferTodayDetailIdentity(
        job_id="jid-1",
        encrypted_job_id="enc-jid-1",
    )

    with pytest.raises(
        identity_module.OfferTodayIdentityError,
        match=r"requested jobId=.*jid-1.*response jobId=.*jid-other",
    ):
        identity_module.validate_offertoday_detail_identity(
            identity,
            {"job_id": "jid-other", "raw_data": {"jobId": "jid-other"}},
        )


def test_build_offertoday_canonical_job_reads_description_from_raw_detail_shape():
    listing = _parsed_listing()

    assert listing["encrypted_job_id"] == "enc-jid-1"
    canonical = build_offertoday_canonical_job({**listing, **_sample_detail_raw()})

    assert canonical.source_job_id == "jid-1"
    assert canonical.source_url.endswith("/enc-jid-1")
    assert canonical.company_name == "Alpha Ltd"
    assert canonical.description == "<p>Build ETL pipelines.</p><p>Apply now.</p>"


@pytest.mark.parametrize(
    ("payload", "missing_field"),
    [
        ({"encryptJobId": "enc-jid-1", "jobName": "Data Engineer"}, "jobId"),
        ({"jobId": "jid-1", "jobName": "Data Engineer"}, "encryptJobId"),
    ],
)
def test_build_offertoday_canonical_job_rejects_missing_identity_field(
    payload: dict,
    missing_field: str,
):
    with pytest.raises(ValueError, match=missing_field):
        build_offertoday_canonical_job(payload)


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


def test_offertoday_job_repair_service_rejects_missing_encrypted_listing_identity():
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    identity_module = _identity_module()
    service = service_module.OfferTodayJobRepairService(db=None)

    with pytest.raises(identity_module.OfferTodayIdentityError, match="encryptJobId"):
        service.resolve_detail_identifiers(
            _job_stub(),
            _listing_stub(
                listing_payload=_parsed_listing(_sample_listing_raw_missing_encrypted())
            ),
        )


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
    assert result.parsed_detail["encrypted_job_id"] == ""
    assert result.parsed_detail["description_text"] == "Build ETL pipelines."
    assert result.canonical_detail["job_id"] == "jid-1"
    assert result.canonical_detail["encrypted_job_id"] == "enc-jid-1"

    response_payload["data"]["jobName"] = "Mutated after fetch"
    assert result.raw_response["data"]["jobName"] == "Data Engineer"


@pytest.mark.asyncio
async def test_offertoday_browser_detail_scraper_missing_encrypted_id_makes_zero_fetch_calls():
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    identity_module = _identity_module()
    calls = 0

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        nonlocal calls
        calls += 1
        return {"code": 0, "data": _sample_detail_raw()}

    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )

    with pytest.raises(identity_module.OfferTodayIdentityError, match="encryptJobId"):
        await scraper.fetch_job_detail("jid-1")

    assert calls == 0


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


@pytest.mark.asyncio
async def test_offertoday_browser_detail_scraper_builds_runtime_from_resume_strategy_request_payload(
    monkeypatch,
):
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    runtime_calls: list[dict[str, object]] = []
    fetch_calls: list[tuple[str, str]] = []

    class _FakePage:
        url = "https://www.offertoday.com/hk/search"

    class _FakeRuntime:
        def __init__(self, **kwargs) -> None:
            runtime_calls.append(dict(kwargs))
            self._page = _FakePage()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def fetch_detail_json(self, *, job_id: str, encrypted_job_id: str):
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
    assert fetch_calls == [("jid-1", "enc-jid-1")]
    assert result.classification.kind is OfferTodayResponseKind.SUCCESS
    assert result.canonical_detail["job_id"] == "jid-1"


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

    class _FakeRuntime:
        def __init__(self, **kwargs) -> None:
            self.kwargs = dict(kwargs)

        async def __aenter__(self):
            raise expected_error

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(
        scraper_module,
        "OfferTodayBrowserRuntime",
        _FakeRuntime,
        raising=False,
    )

    with pytest.raises(ManualActionRequiredError) as exc_info:
        async with scraper_module.OfferTodayBrowserDetailScraper(
            request_payload={"resume_strategy": RESUME_STRATEGY_REUSE_OPEN_BROWSER}
        ):
            pass

    assert exc_info.value is expected_error


def test_offertoday_browser_detail_scraper_detects_waf_challenge_urls():
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    scraper_cls = scraper_module.OfferTodayBrowserDetailScraper

    assert scraper_cls.is_waf_challenge_url(
        "https://www.offertoday.com/web/passport/cm/verify.html?callbackUrl=test"
    )
    assert not scraper_cls.is_waf_challenge_url("https://www.offertoday.com/hk/search")


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

    service = service_module.OfferTodayJobRepairService(db=object())
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


@pytest.mark.parametrize(
    ("payload", "expected_kind"),
    [
        (
            {"code": 2520, "msg": "Position unavailable", "data": None},
            OfferTodayResponseKind.TERMINAL_UNAVAILABLE,
        ),
        (
            {"code": 1002, "msg": "Login expired", "data": None},
            OfferTodayResponseKind.AUTH_EXPIRED,
        ),
    ],
)
def test_repair_non_success_records_evidence_without_merging_job(
    monkeypatch,
    payload: dict,
    expected_kind: OfferTodayResponseKind,
):
    identity_module = _identity_module()
    policy_module = importlib.import_module("app.sources.offertoday.response_policy")
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    identity = identity_module.OfferTodayDetailIdentity(
        job_id="jid-1",
        encrypted_job_id="enc-jid-1",
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
    service = service_module.OfferTodayJobRepairService(db=object())
    listing = _listing_stub()
    job = _job_stub()
    job_before = dict(vars(job))

    monkeypatch.setattr(service, "get_latest_listing", lambda source_job_id: listing)

    def fail_persist(*args, **kwargs):
        raise AssertionError("non-success response must not merge into Job")

    monkeypatch.setattr(service, "_persist_canonical_job", fail_persist)

    repair_result = service.repair_job_with_detail_result(job, fetch_result)

    assert repair_result.action == expected_kind.value
    assert repair_result.description_repaired is False
    assert vars(job) == job_before
    assert listing.detail_status == "failed"
    assert listing.detail_payload == payload
    evidence = json.loads(listing.detail_error_message)
    assert evidence == {
        "code": classification.code,
        "encrypted_job_id": "enc-jid-1",
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


def test_repair_cli_consumes_typed_result_without_reclassification_or_reparsing():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "repair_offertoday_jobs.py"
    )
    source = script_path.read_text(encoding="utf-8")

    assert "repair_job_with_detail_result" in source
    assert "repair_job_with_detail_payload" not in source
    assert "classify_offertoday_response" not in source
    assert "parse_offertoday_detail_response" not in source
