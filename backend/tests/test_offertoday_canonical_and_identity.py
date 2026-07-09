import importlib
import importlib.util
import pytest

import app.sources.contracts as contracts
from app.sources.contracts import build_offertoday_canonical_job
from app.scraper.manual_action import ManualActionRequiredError, RESUME_STRATEGY_REUSE_OPEN_BROWSER
from app.sources.offertoday.parsers import parse_offertoday_listing_response
from app.utils.source_identity import derive_source_company_id_from_raw_data


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


def _sample_detail_raw() -> dict:
    return {
        "jobId": "jid-1",
        "jobName": "Data Engineer",
        "jobDesc": "<p>Hello detail</p>",
        "companyName": "Alpha Ltd",
        "brandId": "brand-123",
        "brandName": "Alpha Brand",
        "salaryDesc": "HK $30K-40K",
        "jobTypeDesc": "Full-time",
        "locationDesc": "Wan Chai",
        "postDateDesc": "發布於06-26",
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


def test_build_offertoday_canonical_job_reads_description_from_raw_detail_shape():
    listing = parse_offertoday_listing_response(
        {
            "code": 0,
            "data": {
                "resultList": [_sample_listing_raw()],
            },
        }
    )[0]

    assert listing["encrypted_job_id"] == "enc-jid-1"
    canonical = build_offertoday_canonical_job({**listing, **_sample_detail_raw()})

    assert canonical.source_job_id == "jid-1"
    assert canonical.company_name == "Alpha Ltd"
    assert canonical.description == "<p>Hello detail</p>"


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
    assert job_data["description"] == "<p>Hello detail</p>"
    assert job_data["posted_date"] is not None


def test_offertoday_job_repair_service_builds_canonical_snapshot_from_listing_detail_payload():
    spec = importlib.util.find_spec("app.services.offertoday_job_repair_service")
    assert spec is not None

    service_module = importlib.import_module("app.services.offertoday_job_repair_service")
    service_cls = getattr(service_module, "OfferTodayJobRepairService", None)
    assert service_cls is not None

    service = service_cls(db=None)
    listing = type(
        "ListingStub",
        (),
        {
            "listing_payload": parse_offertoday_listing_response(
                {
                    "code": 0,
                    "data": {
                        "resultList": [_sample_listing_raw()],
                    },
                }
            )[0],
            "detail_payload": _sample_detail_raw(),
            "published_job_id": None,
        },
    )()
    job = type(
        "JobStub",
        (),
        {
            "source_site": "offertoday",
            "source_job_id": "jid-1",
            "job_id": "jid-1",
            "title": "Data Engineer",
            "description": "",
            "location": "Wan Chai",
            "salary_range": "HK $30K-40K",
            "employment_type": "Full-time",
            "posted_date": None,
            "raw_data": {},
            "company": None,
        },
    )()

    canonical = service.build_canonical_job_snapshot(job, listing)

    assert canonical.source_job_id == "jid-1"
    assert canonical.description == "<p>Hello detail</p>"


def test_offertoday_job_repair_service_builds_canonical_snapshot_from_live_detail_override():
    service_module = importlib.import_module("app.services.offertoday_job_repair_service")
    service_cls = getattr(service_module, "OfferTodayJobRepairService", None)
    assert service_cls is not None

    service = service_cls(db=None)
    job = type(
        "JobStub",
        (),
        {
            "source_site": "offertoday",
            "source_job_id": "jid-1",
            "job_id": "jid-1",
            "title": "Data Engineer",
            "description": "",
            "location": "Wan Chai",
            "salary_range": "HK $30K-40K",
            "employment_type": "Full-time",
            "posted_date": None,
            "raw_data": {},
            "company": None,
        },
    )()

    canonical = service.build_canonical_job_snapshot(
        job,
        detail_payload_override=_sample_detail_raw(),
    )

    assert canonical.source_job_id == "jid-1"
    assert canonical.description == "<p>Hello detail</p>"


def test_offertoday_job_repair_service_resolves_distinct_detail_identifiers_from_listing_payload():
    service_module = importlib.import_module("app.services.offertoday_job_repair_service")
    service_cls = getattr(service_module, "OfferTodayJobRepairService", None)
    assert service_cls is not None

    service = service_cls(db=None)
    listing = type(
        "ListingStub",
        (),
        {
            "listing_payload": parse_offertoday_listing_response(
                {
                    "code": 0,
                    "data": {
                        "resultList": [_sample_listing_raw()],
                    },
                }
            )[0],
        },
    )()
    job = type(
        "JobStub",
        (),
        {
            "source_site": "offertoday",
            "source_job_id": "jid-1",
            "job_id": "jid-1",
            "raw_data": {},
        },
    )()

    job_id, encrypted_job_id = service.resolve_detail_identifiers(job, listing)

    assert job_id == "jid-1"
    assert encrypted_job_id == "enc-jid-1"


@pytest.mark.asyncio
async def test_offertoday_browser_detail_scraper_uses_injected_fetcher():
    spec = importlib.util.find_spec("app.scraper.offertoday_browser_detail_scraper")
    assert spec is not None

    scraper_module = importlib.import_module("app.scraper.offertoday_browser_detail_scraper")
    scraper_cls = getattr(scraper_module, "OfferTodayBrowserDetailScraper", None)
    assert scraper_cls is not None

    async def fake_fetcher(job_id: str):
        assert job_id == "jid-1"
        return {
            "code": 0,
            "data": _sample_detail_raw(),
        }

    scraper = scraper_cls(detail_json_fetcher=fake_fetcher)
    detail_payload = await scraper.fetch_job_detail("jid-1")

    assert detail_payload["jobId"] == "jid-1"
    assert detail_payload["jobDesc"] == "<p>Hello detail</p>"


@pytest.mark.asyncio
async def test_offertoday_browser_detail_scraper_raises_for_ip_block():
    scraper_module = importlib.import_module("app.scraper.offertoday_browser_detail_scraper")
    scraper_cls = getattr(scraper_module, "OfferTodayBrowserDetailScraper", None)
    blocked_error_cls = getattr(scraper_module, "OfferTodayIPBlockedError", None)
    assert scraper_cls is not None
    assert blocked_error_cls is not None

    async def blocked_fetcher(job_id: str):
        assert job_id == "jid-1"
        return {
            "code": -1000035,
            "msg": "IP blocked",
            "data": {},
        }

    scraper = scraper_cls(detail_json_fetcher=blocked_fetcher)

    with pytest.raises(blocked_error_cls):
        await scraper.fetch_job_detail("jid-1")


@pytest.mark.asyncio
async def test_offertoday_browser_detail_scraper_builds_runtime_from_resume_strategy_request_payload(
    monkeypatch,
):
    scraper_module = importlib.import_module("app.scraper.offertoday_browser_detail_scraper")
    scraper_cls = getattr(scraper_module, "OfferTodayBrowserDetailScraper", None)
    assert scraper_cls is not None

    runtime_calls: list[dict[str, object]] = []
    fetch_calls: list[tuple[str, str | None]] = []

    class _FakeRuntime:
        def __init__(self, **kwargs) -> None:
            runtime_calls.append(dict(kwargs))
            self._page = object()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def fetch_detail_json(self, *, job_id: str, encrypted_job_id: str | None = None):
            fetch_calls.append((job_id, encrypted_job_id))
            return {
                "code": 0,
                "data": _sample_detail_raw(),
            }

    monkeypatch.setattr(scraper_module, "OfferTodayBrowserRuntime", _FakeRuntime, raising=False)

    async with scraper_cls(
        request_payload={"resume_strategy": RESUME_STRATEGY_REUSE_OPEN_BROWSER}
    ) as scraper:
        detail_payload = await scraper.fetch_job_detail("jid-1", encrypted_job_id="enc-jid-1")

    assert runtime_calls == [
        {
            "headed": False,
            "auth_state_path": None,
            "resume_strategy": RESUME_STRATEGY_REUSE_OPEN_BROWSER,
        }
    ]
    assert fetch_calls == [("jid-1", "enc-jid-1")]
    assert detail_payload["jobId"] == "jid-1"


@pytest.mark.asyncio
async def test_offertoday_browser_detail_scraper_propagates_manual_action_required_error(monkeypatch):
    scraper_module = importlib.import_module("app.scraper.offertoday_browser_detail_scraper")
    scraper_cls = getattr(scraper_module, "OfferTodayBrowserDetailScraper", None)
    assert scraper_cls is not None

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

    monkeypatch.setattr(scraper_module, "OfferTodayBrowserRuntime", _FakeRuntime, raising=False)

    with pytest.raises(ManualActionRequiredError) as exc_info:
        async with scraper_cls(
            request_payload={"resume_strategy": RESUME_STRATEGY_REUSE_OPEN_BROWSER}
        ):
            pass

    assert exc_info.value is expected_error


def test_offertoday_browser_detail_scraper_detects_waf_challenge_urls():
    scraper_module = importlib.import_module("app.scraper.offertoday_browser_detail_scraper")
    scraper_cls = getattr(scraper_module, "OfferTodayBrowserDetailScraper", None)
    assert scraper_cls is not None

    assert scraper_cls.is_waf_challenge_url(
        "https://www.offertoday.com/web/passport/cm/verify.html?callbackUrl=test"
    )
    assert not scraper_cls.is_waf_challenge_url("https://www.offertoday.com/hk/search")
