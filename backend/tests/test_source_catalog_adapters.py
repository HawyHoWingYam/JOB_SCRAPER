from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
import pytest

from app.scraper import category_scraper as category_scraper_module
from app.scraper.category_scraper import CategoryListScraper
from app.scraper.ctgoodjobs.category_registry import get_static_ctgoodjobs_categories
from app.source_catalog.adapters.ctgoodjobs import CTgoodjobsSourceCatalogAdapter
from app.source_catalog.adapters.jobsdb import JobsDBSourceCatalogAdapter
from app.source_catalog.adapters.offertoday import OfferTodaySourceCatalogAdapter
from app.source_catalog.domain import (
    CatalogValidationError,
    expand_catalog_scope,
    validate_catalog,
    validate_compiled_catalog,
)
from app.source_catalog.errors import SourceCatalogError
from app.sources.jobsdb import request as jobsdb_request_module
from app.sources.offertoday.constants import build_offertoday_listing_payload


SCRAPY_PROJECT = Path(__file__).resolve().parents[1] / "scrapy_project"
if str(SCRAPY_PROJECT) not in sys.path:
    sys.path.insert(0, str(SCRAPY_PROJECT))

from app.source_catalog.runtime import (  # noqa: E402
    PublishedSourceQueryPlan,
    ResolvedSourceQueryTarget,
)
from job_scraper_spiders.spiders import jobsdb as jobsdb_spider_module  # noqa: E402
from job_scraper_spiders.spiders import ctgoodjobs as ctgoodjobs_spider_module  # noqa: E402
from job_scraper_spiders.spiders import offertoday as offertoday_spider_module  # noqa: E402
from job_scraper_spiders.spiders.ctgoodjobs import CtgoodjobsSpider  # noqa: E402
from job_scraper_spiders.spiders.jobsdb import JobsdbSpider  # noqa: E402
from job_scraper_spiders.spiders.offertoday import OfferTodaySpider  # noqa: E402
from scripts import offertoday_standalone_crawl as offertoday_crawl  # noqa: E402
from scripts import ctgoodjobs_standalone_crawl as ctgoodjobs_crawl  # noqa: E402


def test_jobsdb_selected_classification_reaches_every_final_listing_request(monkeypatch):
    adapter = JobsDBSourceCatalogAdapter()
    catalog = adapter.discover()
    nodes = {
        node.classification_id: node
        for node in catalog.nodes
        if node.classification_id is not None
    }

    first_target = adapter.compile(nodes["jobsdb:1200"])[0]
    second_target = adapter.compile(nodes["jobsdb:6281"])[0]

    captured: list[httpx.Request] = []

    async def capture_standalone_requests() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"totalCount": 0, "data": []},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = CategoryListScraper()
            await scraper.fetch_page(first_target.payload["native_id"], client=client)
            await scraper.fetch_page(second_target.payload["native_id"], client=client)

    asyncio.run(capture_standalone_requests())
    standalone_classifications = [
        request.url.params["classification"] for request in captured
    ]

    monkeypatch.setattr(
        jobsdb_spider_module,
        "load_published_query_plan",
        lambda _source, _ids: PublishedSourceQueryPlan(
            source_site="jobsdb",
            revision_id="revision-1",
            revision_fingerprint="f" * 64,
            entries=(
                ResolvedSourceQueryTarget(nodes["jobsdb:1200"], first_target),
                ResolvedSourceQueryTarget(nodes["jobsdb:6281"], second_target),
            ),
        ),
    )
    spider = JobsdbSpider(category_ids="1200,6281", max_pages="1")
    scrapy_requests = list(spider.start_requests())
    scrapy_classifications = [
        request.url.split("classification=", 1)[1].split("&", 1)[0]
        for request in scrapy_requests
    ]

    assert standalone_classifications == ["1200", "6281"]
    assert scrapy_classifications == ["1200", "6281"]
    assert (
        category_scraper_module.build_jobsdb_search_params
        is jobsdb_request_module.build_jobsdb_search_params
    )
    assert (
        jobsdb_spider_module.build_jobsdb_search_url
        is jobsdb_request_module.build_jobsdb_search_url
    )
    assert first_target.fingerprint != second_target.fingerprint


def test_ctgoodjobs_catalog_compiles_known_native_paths_without_slug_guessing():
    categories = get_static_ctgoodjobs_categories()
    adapter = CTgoodjobsSourceCatalogAdapter(category_provider=lambda: categories)
    catalog = adapter.discover()
    nodes = {
        node.classification_id: node
        for node in catalog.nodes
        if node.classification_id is not None
    }

    information_technology = adapter.compile(nodes["ctgoodjobs:021"])[0]
    accounting = adapter.compile(nodes["ctgoodjobs:001"])[0]

    assert information_technology.to_payload() == {
        "version": 1,
        "adapter": "ctgoodjobs.category",
        "classification_id": "ctgoodjobs:021",
        "native_id": "021",
        "url_path": "/jobs/jobs-in-information-technology",
        "crawl_mode": "headless",
    }
    assert accounting.payload["url_path"] == "/jobs/jobs-in-accounting-auditing"
    assert accounting.fingerprint != information_technology.fingerprint
    with pytest.raises(CatalogValidationError):
        adapter.compile(
            replace(
                nodes["ctgoodjobs:021"],
                source_metadata={
                    **nodes["ctgoodjobs:021"].source_metadata,
                    "url_path": "/jobs/jobs-in-information-technology?guess=1",
                },
            )
        )


def test_ctgoodjobs_spider_uses_only_published_paths_and_rejects_unknown_before_request(
    monkeypatch,
):
    adapter = CTgoodjobsSourceCatalogAdapter(
        category_provider=get_static_ctgoodjobs_categories
    )
    catalog = adapter.discover()
    nodes = {node.classification_id: node for node in catalog.nodes}
    information_technology = adapter.compile(nodes["ctgoodjobs:021"])[0]
    accounting = adapter.compile(nodes["ctgoodjobs:001"])[0]
    monkeypatch.setattr(
        ctgoodjobs_spider_module,
        "load_published_query_plan",
        lambda _source, _ids: PublishedSourceQueryPlan(
            source_site="ctgoodjobs",
            revision_id="revision-1",
            revision_fingerprint="f" * 64,
            entries=(
                ResolvedSourceQueryTarget(
                    nodes["ctgoodjobs:021"], information_technology
                ),
                ResolvedSourceQueryTarget(nodes["ctgoodjobs:001"], accounting),
            ),
        ),
    )

    requests = list(
        CtgoodjobsSpider(
            category_ids="ctgoodjobs:021,ctgoodjobs:001",
            max_pages="1",
        ).start_requests()
    )
    assert [request.url for request in requests] == [
        "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology",
        "https://jobs.ctgoodjobs.hk/jobs/jobs-in-accounting-auditing",
    ]
    assert all(request.meta["playwright"] is True for request in requests)
    assert CtgoodjobsSpider.custom_settings["PLAYWRIGHT_LAUNCH_OPTIONS"] == {
        "headless": True
    }

    def reject_unknown(_source, _ids):
        raise SourceCatalogError(
            "SOURCE_CLASSIFICATION_UNKNOWN", "Unknown Source Classification"
        )

    monkeypatch.setattr(
        ctgoodjobs_spider_module, "load_published_query_plan", reject_unknown
    )
    with pytest.raises(SourceCatalogError) as unknown:
        list(CtgoodjobsSpider(category_ids="ctgoodjobs:999").start_requests())
    assert unknown.value.code == "SOURCE_CLASSIFICATION_UNKNOWN"


@pytest.mark.asyncio
async def test_ctgoodjobs_catalog_target_and_smoke_preserve_explicit_headless_mode():
    class Browser:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def fetch_page_html(self, *_args, **_kwargs):
            return "<html><body>parser-valid fixture</body></html>"

    adapter = CTgoodjobsSourceCatalogAdapter(
        category_provider=get_static_ctgoodjobs_categories,
        browser_scraper_factory=Browser,
        crawl_mode="headless",
    )
    catalog = adapter.discover()
    node = next(
        item for item in catalog.nodes if item.classification_id == "ctgoodjobs:021"
    )
    target = adapter.compile(node)[0]

    assert target.payload["crawl_mode"] == "headless"
    assert (await adapter.smoke(target))["crawl_mode"] == "headless"


def test_ctgoodjobs_standalone_uses_published_url_before_headed_fetch(monkeypatch):
    adapter = CTgoodjobsSourceCatalogAdapter(
        category_provider=get_static_ctgoodjobs_categories
    )
    catalog = adapter.discover()
    node = next(
        item for item in catalog.nodes if item.classification_id == "ctgoodjobs:021"
    )
    target = adapter.compile(node)[0]
    plan = PublishedSourceQueryPlan(
        source_site="ctgoodjobs",
        revision_id="revision-1",
        revision_fingerprint="f" * 64,
        entries=(ResolvedSourceQueryTarget(node, target),),
    )
    monkeypatch.setattr(
        ctgoodjobs_crawl,
        "load_published_scope_query_plan",
        lambda _source, *, mode: plan,
    )
    monkeypatch.setattr(
        ctgoodjobs_crawl,
        "parse_category_page",
        lambda *_args, **_kwargs: {"job_ids": [], "job_urls": []},
    )

    class Browser:
        def __init__(self):
            self.urls = []

        async def fetch_page_html(self, url, **_kwargs):
            self.urls.append(url)
            return "<html></html>"

    class Runtime:
        def stage_listing_batch(self, **_kwargs):
            return SimpleNamespace(
                job_ids_seen=0,
                raw_job_ids_seen=0,
                rows_staged=0,
                skipped_existing=0,
            )

        def write_progress_event(self, **_kwargs):
            return None

    browser = Browser()
    args = SimpleNamespace(
        category_ids=["ctgoodjobs:021"],
        crawl_job_id="job-1",
        crawl_mode="headed",
        max_pages=1,
        skip_existing=False,
        cancellation_token=SimpleNamespace(raise_if_cancelled=lambda: None),
    )
    totals = {
        "pages_processed": 0,
        "job_ids_collected": 0,
        "raw_job_ids_collected": 0,
        "listings_staged": 0,
        "jobs_skipped_existing": 0,
    }

    asyncio.run(
        ctgoodjobs_crawl._run_listing_phase_impl(
            args,
            Runtime(),
            browser,
            totals=totals,
            current_page_context={},
        )
    )

    assert browser.urls == [
        "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology"
    ]
    with pytest.raises(RuntimeError, match="Unknown CTGoodJobs"):
        ctgoodjobs_crawl._resolve_category(
            ctgoodjobs_crawl._categories_by_id(), "ctgoodjobs:999"
        )

    browser.urls.clear()
    args.category_ids = ["ctgoodjobs:999"]
    with pytest.raises(RuntimeError, match="Unknown CTGoodJobs"):
        asyncio.run(
            ctgoodjobs_crawl._run_listing_phase_impl(
                args,
                Runtime(),
                browser,
                totals=totals,
                current_page_context={},
            )
        )
    assert browser.urls == []


def test_offertoday_hierarchy_keeps_aliases_auditable_and_compiles_only_bounded_categories():
    adapter = OfferTodaySourceCatalogAdapter()
    catalog = adapter.discover()
    report = validate_catalog(catalog)
    aliases = [node for node in catalog.nodes if node.alias_of_node_key is not None]

    exact_root = expand_catalog_scope(
        catalog,
        mode="exact",
        classification_ids=("offertoday:118000",),
    )
    it_subtree = expand_catalog_scope(
        catalog,
        mode="subtree",
        classification_ids=("offertoday:118000",),
    )
    all_scope = expand_catalog_scope(catalog, mode="all")
    targets = [target for node in it_subtree for target in adapter.compile(node)]
    outbound_payloads = [
        build_offertoday_listing_payload(
            category_id=int(target.payload["category_code"]),
            keyword=str(target.payload["keyword"]),
            page=1,
            rcd_type=int(target.payload["rcd_type"]),
        )
        for target in targets
    ]

    assert report.node_count == 493
    assert report.queryable_count == 462
    assert len(aliases) == 31
    assert all(node.classification_id is None and not node.queryable for node in aliases)
    assert [node.classification_id for node in exact_root] == ["offertoday:118000"]
    assert len({node.classification_id for node in it_subtree}) == len(it_subtree)
    assert len(all_scope) == report.queryable_count
    assert len({node.classification_id for node in all_scope}) == len(all_scope)
    assert [target.payload["category_code"] for target in targets].count(118000) == 1
    assert all(target.payload["keyword"] == "" for target in targets)
    assert all(payload["jobFunctionCodes"] for payload in outbound_payloads)
    assert not any("jobFunctionCodes" not in payload for payload in outbound_payloads)


def test_offertoday_catalog_smokes_isolate_temporary_browser_profiles(monkeypatch):
    captured_profiles: list[str | None] = []

    class BrowserRuntime:
        def __init__(self, *, headed, user_data_dir=None):
            assert headed is True
            captured_profiles.append(user_data_dir)

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return None

        async def fetch_listing_page(self, _payload, *, listing_url):
            assert listing_url.endswith("/wapi/geek/recommend/list")
            return SimpleNamespace(payload={"data": {}}, http_status=200)

    monkeypatch.setattr(
        "app.source_catalog.adapters.offertoday.OfferTodayBrowserRuntime",
        BrowserRuntime,
    )
    adapter = OfferTodaySourceCatalogAdapter()
    targets = [
        adapter.compile(node)[0]
        for node in adapter.discover().nodes
        if node.queryable
    ][:2]

    results = [asyncio.run(adapter.smoke(target)) for target in targets]

    assert [result["status"] for result in results] == ["passed", "passed"]
    assert len(captured_profiles) == 2
    assert None not in captured_profiles
    assert len(set(captured_profiles)) == 2
    assert all(not Path(profile).exists() for profile in captured_profiles if profile)


def test_offertoday_validation_smokes_reuse_one_isolated_browser_session(monkeypatch):
    captured_profiles: list[str | None] = []
    runtime_entries = 0
    runtime_exits = 0

    class BrowserRuntime:
        def __init__(self, *, headed, user_data_dir=None):
            assert headed is True
            captured_profiles.append(user_data_dir)

        async def start(self):
            nonlocal runtime_entries
            runtime_entries += 1

        async def stop(self):
            nonlocal runtime_exits
            runtime_exits += 1

        async def fetch_listing_page(self, _payload, *, listing_url):
            assert listing_url.endswith("/wapi/geek/recommend/list")
            return SimpleNamespace(payload={"data": {}}, http_status=200)

    monkeypatch.setattr(
        "app.source_catalog.adapters.offertoday.OfferTodayBrowserRuntime",
        BrowserRuntime,
    )
    adapter = OfferTodaySourceCatalogAdapter()
    targets = [
        adapter.compile(node)[0]
        for node in adapter.discover().nodes
        if node.queryable
    ][:2]

    async def run_smokes():
        async with adapter.validation_smoke_session() as smoke:
            return [await smoke(target) for target in targets]

    results = asyncio.run(run_smokes())

    assert [result["status"] for result in results] == ["passed", "passed"]
    assert len(captured_profiles) == 1
    assert captured_profiles[0] is not None
    assert runtime_entries == 1
    assert runtime_exits == 1
    assert not Path(captured_profiles[0]).exists()


def test_offertoday_scrapy_requests_consume_published_category_targets_without_keywords(
    monkeypatch,
):
    adapter = OfferTodaySourceCatalogAdapter()
    catalog = adapter.discover()
    nodes = {node.classification_id: node for node in catalog.nodes}
    root_target = adapter.compile(nodes["offertoday:118000"])[0]
    leaf_id = next(
        node.classification_id
        for node in catalog.nodes
        if node.parent_node_key == nodes["offertoday:118000"].node_key
        and node.classification_id is not None
    )
    leaf_target = adapter.compile(nodes[leaf_id])[0]
    monkeypatch.setattr(
        offertoday_spider_module,
        "load_published_query_plan",
        lambda _source, _ids: PublishedSourceQueryPlan(
            source_site="offertoday",
            revision_id="revision-1",
            revision_fingerprint="f" * 64,
            entries=(
                ResolvedSourceQueryTarget(nodes["offertoday:118000"], root_target),
                ResolvedSourceQueryTarget(nodes[leaf_id], leaf_target),
            ),
        ),
    )

    spider = OfferTodaySpider(category_ids="118000,118101", max_pages="1")
    requests = [spider._build_next_listing_request(), spider._build_next_listing_request()]
    payloads = [json.loads(request.body) for request in requests]

    assert [request.url for request in requests] == [
        "https://www.offertoday.com/wapi/geek/recommend/list",
        "https://www.offertoday.com/wapi/geek/recommend/list",
    ]
    assert [payload["jobFunctionCodes"] for payload in payloads] == [
        [118000],
        [int(leaf_target.payload["category_code"])],
    ]
    assert all(payload["keyword"] == "" for payload in payloads)

    monkeypatch.setattr(
        offertoday_crawl,
        "load_published_query_plan",
        offertoday_spider_module.load_published_query_plan,
    )
    standalone_conditions = offertoday_crawl._build_request_listing_conditions(
        "offertoday:118000",
        keywords=[],
    )
    assert [(item.category_id, item.keyword, item.endpoint, item.rcd_type) for item in standalone_conditions] == [
        (118000, "", "browse", 7),
        (int(leaf_target.payload["category_code"]), "", "browse", 7),
    ]
    explicit_keyword_conditions = offertoday_crawl._build_request_listing_conditions(
        "offertoday:118000",
        keywords=["python"],
    )
    assert [
        (item.category_id, item.keyword, item.search_family)
        for item in explicit_keyword_conditions
    ] == [(None, "python", "explicit_keyword")]
    with pytest.raises(ValueError, match="Invalid OfferToday"):
        OfferTodaySpider(category_ids="not-a-classification")

    def reject_unknown(_source, _ids):
        raise SourceCatalogError(
            "SOURCE_CLASSIFICATION_UNKNOWN", "Unknown Source Classification"
        )

    monkeypatch.setattr(
        offertoday_crawl, "load_published_query_plan", reject_unknown
    )
    monkeypatch.setattr(
        offertoday_spider_module, "load_published_query_plan", reject_unknown
    )
    with pytest.raises(SourceCatalogError):
        offertoday_crawl._build_request_listing_conditions(
            "offertoday:999",
            keywords=[],
        )
    with pytest.raises(SourceCatalogError):
        OfferTodaySpider(category_ids="offertoday:999")


def test_every_queryable_node_compiles_with_matching_deterministic_semantics():
    jobsdb = JobsDBSourceCatalogAdapter()
    ctgoodjobs = CTgoodjobsSourceCatalogAdapter(
        category_provider=get_static_ctgoodjobs_categories
    )
    offertoday = OfferTodaySourceCatalogAdapter()

    reports = [
        validate_compiled_catalog(adapter.discover(), adapter)
        for adapter in (jobsdb, ctgoodjobs, offertoday)
    ]

    assert [(report.source_site, report.target_count) for report in reports] == [
        ("jobsdb", 25),
        ("ctgoodjobs", 12),
        ("offertoday", 462),
    ]
