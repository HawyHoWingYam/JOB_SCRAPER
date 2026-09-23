from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import scrapy
from scrapy.http import HtmlResponse, TextResponse

from app.crawl_modes import resolve_crawl_mode
from app.crawl_control.contracts import (
    QueryTargetSnapshotV1,
    SelectedClassificationSnapshotV1,
)
from app.crawl_control.errors import ListingRunPageCapExceededError
from app.crawl_control.detail_runtime import (
    DetailRuntimePlan,
    DetailRuntimeTarget,
)
from app.crawl_control.listing_runtime import (
    ListingRuntimePlan,
    ListingRuntimeTarget,
)
from app.scraper.category_scraper import CategoryListScraper
from app.scraper.ctgoodjobs.category_registry import (
    get_static_ctgoodjobs_categories,
)
from app.services.crawl_job_runtime import ListingBatchPersistResult
from app.services.source_sites import build_source_sites
from app.source_classifications.adapters.ctgoodjobs import CTgoodjobsSourceClassificationAdapter
from app.source_classifications.adapters.jobsdb import JobsDBSourceClassificationAdapter
from app.source_classifications.adapters.offertoday import OfferTodaySourceClassificationAdapter
from app.sources.offertoday.listing_runner import (
    ListingConditionOutcome,
    ListingRetryPolicy,
    ListingRunResult,
    ListingStopPolicy,
    OfferTodayListingCondition,
    OfferTodayListingRunner,
    listing_observation_to_payload,
)
from app.sources.offertoday.listing_contract import (
    OfferTodayListingTransportResult,
    production_offertoday_listing_request_policy,
)
from app.sources.offertoday.response_policy import OfferTodayTransportError
from app.source_classifications.domain import SourceQueryTarget
from scripts import ctgoodjobs_standalone_crawl as ctgoodjobs_crawl
from scripts import jobsdb_standalone_crawl as jobsdb_crawl
from scripts import offertoday_standalone_crawl as offertoday_crawl


SCRAPY_PROJECT = Path(__file__).resolve().parents[1] / "scrapy_project"
if str(SCRAPY_PROJECT) not in sys.path:
    sys.path.insert(0, str(SCRAPY_PROJECT))

from job_scraper_spiders.spiders import ctgoodjobs as ctgoodjobs_spider_module  # noqa: E402
from job_scraper_spiders.spiders import jobsdb as jobsdb_spider_module  # noqa: E402
from job_scraper_spiders.spiders import offertoday as offertoday_spider_module  # noqa: E402


@pytest.mark.parametrize(
    "crawl_module",
    [jobsdb_crawl, ctgoodjobs_crawl, offertoday_crawl],
)
def test_standalone_listing_paths_always_enforce_skip_existing(crawl_module) -> None:
    args = crawl_module._build_argument_parser().parse_args([])
    assert args.skip_existing is True

    crawl_module._apply_request_payload_defaults(
        args,
        {"crawl_phase": "listing", "skip_existing": False},
    )
    assert args.skip_existing is True


def _runtime_plan(
    source_site: str,
    classification_ids: tuple[str, ...],
    *,
    page_depth: int = 2,
    run_page_cap: int | None = None,
) -> ListingRuntimePlan:
    if source_site == "jobsdb":
        adapter = JobsDBSourceClassificationAdapter()
        crawl_mode = "headless"
    elif source_site == "ctgoodjobs":
        adapter = CTgoodjobsSourceClassificationAdapter(
            category_provider=get_static_ctgoodjobs_categories
        )
        crawl_mode = "headed"
    else:
        adapter = OfferTodaySourceClassificationAdapter()
        crawl_mode = "headless"
    catalog = adapter.discover()
    nodes = {
        node.classification_id: node
        for node in catalog.nodes
        if node.classification_id is not None
    }
    targets = tuple(
        ListingRuntimeTarget(
            selected_classification=SelectedClassificationSnapshotV1(
                node_key=nodes[classification_id].node_key,
                classification_id=classification_id,
                native_label=nodes[classification_id].native_label,
                native_path=nodes[classification_id].native_path,
                query_semantics_hash=(
                    nodes[classification_id].query_semantics_hash or "b" * 64
                ),
            ),
            query_target=QueryTargetSnapshotV1.from_source_target(
                target
            ),
        )
        for classification_id in classification_ids
        for target in adapter.compile(nodes[classification_id])
    )
    estimated = len(targets) * page_depth
    return ListingRuntimePlan(
        crawl_job_id=uuid4(),
        dispatch_plan_id=uuid4(),
        dispatch_plan_fingerprint="a" * 64,
        source_site=source_site,
        crawl_mode=crawl_mode,
        page_depth=page_depth,
        run_page_cap=run_page_cap or estimated,
        targets=targets,
    )


def _offertoday_adaptive_runtime_plan(
    targets: tuple[tuple[str, str, str], ...],
    *,
    page_depth: int = 2,
) -> ListingRuntimePlan:
    adapter = OfferTodaySourceClassificationAdapter()
    nodes = {
        node.classification_id: node
        for node in adapter.discover().nodes
        if node.classification_id is not None
    }
    owner_id = "offertoday:118000"
    runtime_targets: list[ListingRuntimeTarget] = []
    for classification_id, target_kind, keyword in targets:
        node = nodes[classification_id]
        normalized_keyword = keyword.casefold() if keyword else None
        source_target = SourceQueryTarget(
            adapter="offertoday.category",
            classification_id=classification_id,
            payload={
                "category_code": int(classification_id.split(":", 1)[1]),
                "search_family": (
                    "classification_keyword_pack"
                    if target_kind == "keyword"
                    else "native_classification"
                ),
                "endpoint": "search",
                "keyword": keyword,
                "rcd_type": None,
                "target_kind": target_kind,
                "top_level_classification_id": owner_id,
                "normalized_keyword": normalized_keyword,
                "taxonomy_snapshot_fingerprint": "c" * 64,
                "keyword_catalog_fingerprint": "d" * 64,
                "keyword_catalog_updated_at": "2026-07-29T12:00:00+00:00",
            },
        )
        runtime_targets.append(
            ListingRuntimeTarget(
                selected_classification=SelectedClassificationSnapshotV1(
                    node_key=node.node_key,
                    classification_id=classification_id,
                    native_label=node.native_label,
                    native_path=node.native_path,
                    query_semantics_hash=node.query_semantics_hash or "b" * 64,
                ),
                query_target=QueryTargetSnapshotV1.from_source_target(source_target),
            )
        )
    return ListingRuntimePlan(
        crawl_job_id=uuid4(),
        dispatch_plan_id=uuid4(),
        dispatch_plan_fingerprint="a" * 64,
        source_site="offertoday",
        crawl_mode="headless",
        page_depth=page_depth,
        run_page_cap=len(runtime_targets) * page_depth,
        targets=tuple(runtime_targets),
    )


def _detail_runtime_plan(
    source_site: str,
    *,
    target_count: int,
) -> DetailRuntimePlan:
    targets = tuple(
        DetailRuntimeTarget(
            source_job_id=f"frozen-{index}",
            selection_order=index,
            listing_ids=(uuid4(),),
            eligibility_statuses=("pending",),
            eligibility_fingerprints=("1" * 64,),
            runtime_identity_fingerprints=("2" * 64,),
        )
        for index in range(target_count)
    )
    return DetailRuntimePlan(
        crawl_job_id=uuid4(),
        dispatch_plan_id=uuid4(),
        dispatch_plan_fingerprint="d" * 64,
        source_site=source_site,
        crawl_mode="headed" if source_site == "ctgoodjobs" else "headless",
        backlog_scope_kind="source_backlog",
        source_listing_crawl_job_id=None,
        classification_ids=(),
        snapshot_cutoff_at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
        eligible_target_count=target_count,
        selected_target_count=target_count,
        selected_row_count=target_count,
        complete_run_cap=max(target_count, 1),
        membership_fingerprint="e" * 64,
        targets=targets,
    )


def test_historical_offertoday_browse_target_snapshot_keeps_original_payload():
    snapshot = QueryTargetSnapshotV1.from_source_target(
        SourceQueryTarget(
            adapter="offertoday.category",
            classification_id="offertoday:118000",
            payload={
                "category_code": 118000,
                "endpoint": "browse",
                "keyword": "",
                "rcd_type": 7,
            },
        )
    )

    restored = QueryTargetSnapshotV1.model_validate(snapshot.model_dump(mode="json"))
    assert restored.parameter_payload == {
        "category_code": 118000,
        "endpoint": "browse",
        "keyword": "",
        "rcd_type": 7,
    }
    catalog = OfferTodaySourceClassificationAdapter().discover()
    node = next(
        item
        for item in catalog.nodes
        if item.classification_id == "offertoday:118000"
    )
    runtime_plan = ListingRuntimePlan(
        crawl_job_id=uuid4(),
        dispatch_plan_id=uuid4(),
        dispatch_plan_fingerprint="a" * 64,
        source_site="offertoday",
        crawl_mode="headless",
        page_depth=1,
        run_page_cap=1,
        targets=(
            ListingRuntimeTarget(
                selected_classification=SelectedClassificationSnapshotV1(
                    node_key=node.node_key,
                    classification_id="offertoday:118000",
                    native_label=node.native_label,
                    native_path=node.native_path,
                    query_semantics_hash=node.query_semantics_hash or "b" * 64,
                ),
                query_target=restored,
            ),
        ),
    )
    conditions = offertoday_crawl._build_request_listing_conditions(
        None,
        keywords=[],
        runtime_plan=runtime_plan,
    )
    assert [
        (item.category_id, item.keyword, item.endpoint, item.rcd_type)
        for item in conditions
    ] == [(118000, "", "browse", 7)]
def _detail_load_result(
    runtime_targets: tuple[DetailRuntimeTarget, ...],
    *,
    snapshot_target_count: int,
):
    source_job_ids = tuple(target.source_job_id for target in runtime_targets)
    return SimpleNamespace(
        selected_rows=len(runtime_targets),
        skipped_existing_rows=0,
        target_rows=len(runtime_targets),
        distinct_selected_ids=len(runtime_targets),
        reconciled_rows=0,
        duplicate_rows=0,
        fetch_cohort_source_job_ids=source_job_ids,
        fetch_cohort_hash="f" * 64,
        reconciled_source_job_ids=(),
        identity_conflict_ids=(),
        identity_conflict_evidence=(),
        targets=[
            {
                "source_job_id": target.source_job_id,
                "listing_id": target.listing_ids[0],
                "listing_ids": target.listing_ids,
            }
            for target in runtime_targets
        ],
        new_detail_targets=len(runtime_targets),
        repair_detail_targets=0,
        eligible_distinct_target_rows=len(runtime_targets),
        eligible_pending_rows=len(runtime_targets),
        eligible_failed_rows=0,
        eligible_manual_action_rows=0,
        snapshot_target_count=snapshot_target_count,
        snapshot_remaining_target_count=len(runtime_targets),
        live_future_eligible_target_count=1,
    )


class _Runtime:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def stage_listing_batch(self, *, payloads, **_kwargs):
        source_job_ids = tuple(
            dict.fromkeys(
                str(payload.get("source_job_id") or "")
                for payload in payloads
                if str(payload.get("source_job_id") or "")
            )
        )
        return ListingBatchPersistResult(
            rows_created=len(source_job_ids),
            created_source_job_ids=source_job_ids,
            preexisting_staged_source_job_ids=(),
            published_source_job_ids=(),
            job_ids_seen=len(source_job_ids),
            skipped_existing=0,
        )

    def write_progress_event(self, *, event_type, payload, **_kwargs) -> None:
        self.events.append((event_type, dict(payload)))

    def merge_metrics(self, **_kwargs) -> None:
        return None


def test_jobsdb_defaults_to_headless_across_runtime_capabilities() -> None:
    assert resolve_crawl_mode("jobsdb") == "headless"
    assert build_source_sites()["jobsdb"]["default_crawl_mode"] == "headless"


@pytest.mark.parametrize(
    ("crawl_mode", "is_resume", "resume_strategy"),
    [
        ("headless", False, "fresh_profile"),
        ("headless", True, "fresh_profile"),
        ("headless", True, "reuse_open_browser"),
        ("headed", False, "fresh_profile"),
        ("headed", True, "fresh_profile"),
    ],
)
@pytest.mark.asyncio
async def test_jobsdb_detail_always_uses_mode_aware_browser_transport(
    monkeypatch: pytest.MonkeyPatch,
    crawl_mode: str,
    is_resume: bool,
    resume_strategy: str,
) -> None:
    scraper_calls: list[dict[str, object]] = []

    class FakeBrowserDetailScraper:
        def __init__(self, **kwargs) -> None:
            scraper_calls.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(
        jobsdb_crawl,
        "JobsDBBrowserDetailScraper",
        FakeBrowserDetailScraper,
    )
    args = SimpleNamespace(
        crawl_job_id="jobsdb-detail-route",
        crawl_mode=crawl_mode,
        is_resume=is_resume,
        resume_strategy=resume_strategy,
        source_listing_crawl_job_id="listing-run",
        category_ids=[],
        detail_limit=10,
        detail_statuses=["pending", "manual_action_required"],
        skip_existing=False,
        manual_action_browser_channel="",
        manual_action_browser_profile_path="",
    )

    async with jobsdb_crawl._detail_scraper_context(args):
        pass

    assert len(scraper_calls) == 1
    request_payload = scraper_calls[0]["request_payload"]
    assert request_payload["crawl_mode"] == crawl_mode
    assert request_payload["is_resume"] is is_resume
    assert request_payload["resume_strategy"] == resume_strategy


def test_listing_request_budget_fails_before_exceeding_reviewed_cap() -> None:
    plan = _runtime_plan("jobsdb", ("jobsdb:1200",), run_page_cap=2)
    budget = plan.new_request_budget()

    assert budget.claim() == 1
    assert budget.claim() == 2
    with pytest.raises(ListingRunPageCapExceededError) as over_cap:
        budget.claim()

    assert over_cap.value.context["requested_pages"] == 3
    assert over_cap.value.context["run_page_cap"] == 2


@pytest.mark.asyncio
async def test_jobsdb_first_page_probe_is_reused_within_page_budget() -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    class Scraper(CategoryListScraper):
        def __init__(self) -> None:
            super().__init__(sleep=no_sleep)
            self.requested_pages: list[int] = []

        async def fetch_page(self, _classification_id, page=1, client=None):
            self.requested_pages.append(page)
            return {
                "totalCount": 64,
                "data": [{"id": f"job-{page}"}],
            }

    scraper = Scraper()
    scraper.reuse_first_page = True
    budget = _runtime_plan(
        "jobsdb",
        ("jobsdb:1200",),
        page_depth=2,
    ).new_request_budget()
    scraper.before_request = budget.claim
    staged_pages: list[int] = []

    async def stage_page(*, page, **_kwargs) -> None:
        staged_pages.append(page)

    await scraper.scrape_category(
        1200,
        max_pages=2,
        page_sink=stage_page,
    )

    assert scraper.requested_pages == [1, 2]
    assert budget.requested_pages == 2
    assert staged_pages == [2, 1]


def test_planned_scrapy_requests_use_frozen_order_and_do_not_chain_detail(
    monkeypatch,
) -> None:
    jobsdb_plan = _runtime_plan(
        "jobsdb",
        ("jobsdb:1200", "jobsdb:6281"),
    )
    monkeypatch.setattr(
        jobsdb_spider_module,
        "load_listing_runtime_plan_for_worker",
        lambda *_args, **_kwargs: jobsdb_plan,
    )
    jobsdb = jobsdb_spider_module.JobsdbSpider(crawl_job_id=str(uuid4()))
    jobsdb_requests = list(jobsdb.start_requests())
    jobsdb_params = [parse_qs(urlsplit(request.url).query) for request in jobsdb_requests]
    assert [item["classification"][0] for item in jobsdb_params] == [
        "1200",
        "1200",
        "6281",
        "6281",
    ]
    assert [item["page"][0] for item in jobsdb_params] == ["1", "2", "1", "2"]
    assert all(request.meta["dont_retry"] is True for request in jobsdb_requests)
    monkeypatch.setattr(
        jobsdb_spider_module,
        "parse_listing_search",
        lambda _data: {
            "jobs": [{"external_id": "job-1", "title": "Engineer"}]
        },
    )
    jobsdb_items = list(
        jobsdb._parse_listing(
            TextResponse(
                url=jobsdb_requests[-1].url,
                body=b"{}",
                encoding="utf-8",
            ),
            category_id="jobsdb:6281",
            page=2,
        )
    )
    assert not any(isinstance(item, scrapy.Request) for item in jobsdb_items)

    ctgoodjobs_plan = _runtime_plan(
        "ctgoodjobs",
        ("ctgoodjobs:021", "ctgoodjobs:001"),
    )
    monkeypatch.setattr(
        ctgoodjobs_spider_module,
        "load_listing_runtime_plan_for_worker",
        lambda *_args, **_kwargs: ctgoodjobs_plan,
    )
    ctgoodjobs = ctgoodjobs_spider_module.CtgoodjobsSpider(
        crawl_job_id=str(uuid4())
    )
    ctgoodjobs_requests = list(ctgoodjobs.start_requests())
    assert [request.url for request in ctgoodjobs_requests] == [
        "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology",
        "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology?page=2",
        "https://jobs.ctgoodjobs.hk/jobs/jobs-in-accounting-auditing",
        "https://jobs.ctgoodjobs.hk/jobs/jobs-in-accounting-auditing?page=2",
    ]
    assert all(
        request.meta["dont_retry"] is True
        for request in ctgoodjobs_requests
    )
    monkeypatch.setattr(
        ctgoodjobs_spider_module,
        "parse_category",
        lambda *_args, **_kwargs: {
            "job_ids": ["job-1"],
            "job_urls": ["https://jobs.ctgoodjobs.hk/job/job-1"],
            "errors": [],
        },
    )
    ctgoodjobs_items = list(
        ctgoodjobs._parse_listing_page(
            HtmlResponse(
                url=ctgoodjobs_requests[-1].url,
                body=b"<html></html>",
                encoding="utf-8",
            ),
            **ctgoodjobs_requests[-1].cb_kwargs,
        )
    )
    assert not any(isinstance(item, scrapy.Request) for item in ctgoodjobs_items)

    offertoday_adapter = OfferTodaySourceClassificationAdapter()
    offertoday_catalog = offertoday_adapter.discover()
    root_node = next(
        node
        for node in offertoday_catalog.nodes
        if node.classification_id == "offertoday:118000"
    )
    child_id = next(
        node.classification_id
        for node in offertoday_catalog.nodes
        if node.parent_node_key == root_node.node_key
        and node.classification_id is not None
    )
    offertoday_plan = _offertoday_adaptive_runtime_plan(
        (
            ("offertoday:118000", "native_top_level", ""),
            (child_id, "native_child", ""),
            ("offertoday:118000", "keyword", "Java"),
            ("offertoday:118000", "keyword", "Python"),
        ),
    )
    monkeypatch.setattr(
        offertoday_spider_module,
        "load_listing_runtime_plan_for_worker",
        lambda *_args, **_kwargs: offertoday_plan,
    )
    offertoday = offertoday_spider_module.OfferTodaySpider(
        crawl_job_id=str(uuid4()),
        keywords="tampered",
        max_pages="999",
    )
    offertoday_requests = [
        offertoday._build_next_listing_request() for _ in range(8)
    ]
    payloads = [json.loads(request.body) for request in offertoday_requests]
    assert all(request.url.endswith("/recommend/search/list") for request in offertoday_requests)
    assert [payload["page"] for payload in payloads] == [1, 2] * 4
    assert [payload["keyword"] for payload in payloads] == [
        "",
        "",
        "",
        "",
        "Java",
        "Java",
        "Python",
        "Python",
    ]
    assert all("rcdType" not in payload for payload in payloads)
    assert all(
        request.meta["dont_retry"] is True
        for request in offertoday_requests
    )
    assert len(offertoday._listing_tasks) == 0
    offertoday._listing_tasks.clear()
    assert list(offertoday._next_listing_or_detail()) == []


@pytest.mark.asyncio
async def test_planned_standalone_targets_ignore_payload_and_stop_empty_target(
    monkeypatch,
) -> None:
    jobsdb_plan = _runtime_plan(
        "jobsdb",
        ("jobsdb:1200", "jobsdb:6281"),
    )
    jobsdb_calls: list[tuple[int, int]] = []

    class JobsdbScraper:
        before_request = None
        sleep = None

        async def scrape_category(
            self,
            category_id,
            *,
            max_pages,
            page_sink,
            on_page_start,
        ):
            jobsdb_calls.append((category_id, max_pages))
            for page in range(1, max_pages + 1):
                self.before_request()
                await on_page_start(
                    category_id=category_id,
                    category_name="Category",
                    page=page,
                    total_pages=max_pages,
                )
                await page_sink(
                    category_id=category_id,
                    category_name="Category",
                    page=page,
                    total_pages=max_pages,
                    jobs=[],
                )

    monkeypatch.setattr(jobsdb_crawl, "CategoryListScraper", JobsdbScraper)
    monkeypatch.setattr(
        jobsdb_crawl,
        "load_source_query_plan",
        lambda *_args, **_kwargs: pytest.fail(
            "frozen JobsDB plan re-resolved classifications"
        ),
    )
    jobsdb_args = SimpleNamespace(
        crawl_job_id="jobsdb-planned",
        crawl_mode="headless",
        category_ids=["tampered"],
        max_pages=999,
        skip_existing=True,
    )
    jobsdb_crawl._apply_listing_runtime_plan(jobsdb_args, jobsdb_plan)
    assert jobsdb_args.skip_existing is True
    await jobsdb_crawl.run_listing_phase(jobsdb_args, _Runtime())
    assert jobsdb_calls == [(1200, 2), (6281, 2)]

    ctgoodjobs_plan = _runtime_plan(
        "ctgoodjobs",
        ("ctgoodjobs:021", "ctgoodjobs:001"),
    )
    fetched_urls: list[str] = []

    class Browser:
        async def fetch_page_html(self, url, **_kwargs):
            fetched_urls.append(url)
            return "<html></html>"

    monkeypatch.setattr(
        ctgoodjobs_crawl,
        "load_source_scope_query_plan",
        lambda *_args, **_kwargs: pytest.fail(
            "frozen CTGoodJobs plan re-resolved classifications"
        ),
    )
    monkeypatch.setattr(
        ctgoodjobs_crawl,
        "parse_category_page",
        lambda *_args, **kwargs: (
            {"job_ids": [], "job_urls": []}
            if "information-technology" in kwargs["url"]
            else {
                "job_ids": [f"job-{kwargs['page']}"],
                "job_urls": [
                    f"https://jobs.ctgoodjobs.hk/job/job-{kwargs['page']}"
                ],
            }
        ),
    )
    ctgoodjobs_args = SimpleNamespace(
        crawl_job_id="ctgoodjobs-planned",
        crawl_mode="headed",
        category_ids=["tampered"],
        max_pages=999,
        skip_existing=True,
    )
    ctgoodjobs_crawl._apply_listing_runtime_plan(
        ctgoodjobs_args,
        ctgoodjobs_plan,
    )
    assert ctgoodjobs_args.skip_existing is True
    await ctgoodjobs_crawl._run_listing_phase(
        ctgoodjobs_args,
        _Runtime(),
        Browser(),
    )
    assert fetched_urls == [
        "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology",
        "https://jobs.ctgoodjobs.hk/jobs/jobs-in-accounting-auditing",
        "https://jobs.ctgoodjobs.hk/jobs/jobs-in-accounting-auditing?page=2",
    ]


@pytest.mark.asyncio
async def test_jobsdb_listing_summary_counts_historical_skips(
    monkeypatch,
) -> None:
    class JobsdbScraper:
        before_request = None
        sleep = None

        async def scrape_category(
            self,
            category_id,
            *,
            max_pages,
            page_sink,
            on_page_start,
        ):
            self.before_request()
            await on_page_start(
                category_id=category_id,
                category_name="Category",
                page=1,
                total_pages=1,
            )
            await page_sink(
                category_id=category_id,
                category_name="Category",
                page=1,
                total_pages=1,
                jobs=[{"id": "historical"}, {"id": "new"}],
            )

    class Runtime(_Runtime):
        def stage_listing_batch(self, **_kwargs):
            return ListingBatchPersistResult(
                rows_created=1,
                created_source_job_ids=("new",),
                preexisting_staged_source_job_ids=(),
                published_source_job_ids=(),
                historical_source_job_ids=("historical",),
                job_ids_seen=2,
                skipped_existing=1,
                raw_job_ids_seen=2,
            )

    monkeypatch.setattr(jobsdb_crawl, "CategoryListScraper", JobsdbScraper)
    runtime = Runtime()
    args = SimpleNamespace(
        crawl_job_id="jobsdb-historical-skip",
        crawl_mode="headless",
        category_ids=[1200],
        max_pages=1,
        skip_existing=True,
    )
    jobsdb_crawl._apply_listing_runtime_plan(
        args,
        _runtime_plan("jobsdb", ("jobsdb:1200",), page_depth=1),
    )

    result = await jobsdb_crawl.run_listing_phase(args, runtime)

    assert result.historical_source_job_ids == ("historical",)
    assert result.skipped_existing == 1
    assert runtime.events[-1][0] == "crawl.page_processed"
    assert runtime.events[-1][1]["jobs_skipped_existing"] == 1


@pytest.mark.asyncio
async def test_offertoday_runner_counts_retries_against_aggregate_cap() -> None:
    class RetryingTransport:
        browser_context_hash = "c" * 64

        def __init__(self) -> None:
            self.calls = 0

        async def fetch_listing_json(self, _payload, *, listing_url=None):
            self.calls += 1
            raise OfferTodayTransportError(
                "temporary transport failure",
                http_status=None,
                response_url=listing_url,
                payload=None,
                error_kind="network",
            )

    class ObservationSink:
        async def record_page_start(self, **_kwargs) -> None:
            return None

        async def record_page_attempt(self, _observation) -> None:
            return None

        async def record_condition_outcome(self, _outcome) -> None:
            return None

    class StagingSink:
        async def stage_page(self, **_kwargs) -> None:
            return None

        async def defer_identity_conflict(self, **_kwargs) -> None:
            return None

    transport = RetryingTransport()
    result = await OfferTodayListingRunner(transport).run(
        conditions=(
            OfferTodayListingCondition(
                search_family="catalog_category",
                category_id=118000,
                keyword="",
                endpoint="browse",
                rcd_type=7,
            ),
        ),
        stop_policy=ListingStopPolicy(
            max_pages_per_condition=3,
            run_page_cap=1,
            page_cap_behavior="retain-and-continue",
        ),
        retry_policy=ListingRetryPolicy(
            max_attempts_per_page=3,
            retry_delays_seconds=(0.0, 0.0),
        ),
        observation_sink=ObservationSink(),
        staging_sink=StagingSink(),
        session_mode="headless",
        request_policy=None,
        terminal_policy="cursor-terminal-empty-confirmation-v1",
    )

    assert transport.calls == 1
    assert result.stop_reason == "run_page_cap"
    assert result.can_proceed_to_detail is False


@pytest.mark.asyncio
async def test_offertoday_runner_ignores_explicit_banner_cards_before_identity():
    class Transport:
        async def fetch_listing_json(self, _payload, *, listing_url=None):
            return {
                "code": 0,
                "data": {
                    "resultList": [
                        {
                            "cardType": 1,
                            "bannerType": 2,
                            "bannerCode": 20001,
                            "title": "Create a subscription",
                        },
                        {
                            "cardType": 0,
                            "jobId": "job-1",
                            "jobName": "AI Engineer",
                            "jobFunctions": [],
                        },
                    ],
                    "hasMore": True,
                    "total": 1,
                },
            }

    class ObservationSink:
        def __init__(self):
            self.observations = []

        async def record_page_start(self, **_kwargs):
            return None

        async def record_page_attempt(self, observation):
            self.observations.append(observation)

        async def record_condition_outcome(self, _outcome):
            return None

    class StagingSink:
        def __init__(self):
            self.rows = []

        async def stage_page(self, *, rows, **_kwargs):
            self.rows.extend(rows)

        async def defer_identity_conflict(self, **_kwargs):
            return None

    observation_sink = ObservationSink()
    staging_sink = StagingSink()
    result = await OfferTodayListingRunner(Transport()).run(
        conditions=(
            OfferTodayListingCondition(
                search_family="classification_keyword_sweep",
                category_id=118000,
                keyword="A",
                endpoint="search",
                rcd_type=None,
            ),
        ),
        stop_policy=ListingStopPolicy(
            max_pages_per_condition=1,
            page_cap_behavior="retain-and-continue",
        ),
        retry_policy=ListingRetryPolicy(max_attempts_per_page=1),
        observation_sink=observation_sink,
        staging_sink=staging_sink,
        session_mode="headless",
        request_policy=None,
        terminal_policy="cursor-terminal-empty-confirmation-v1",
    )

    observation = observation_sink.observations[0]
    assert observation.row_count == 2
    assert observation.non_job_cards_observed == 1
    assert observation.identity_issues == ()
    assert result.non_job_cards_observed == 1
    assert result.accepted_job_ids == ("job-1",)
    assert len(staging_sink.rows) == 1
    assert "non_job_cards_observed" not in listing_observation_to_payload(
        observation
    )
    assert offertoday_crawl._production_listing_observation_payload(
        observation
    )["non_job_cards_observed"] == 1


@pytest.mark.asyncio
async def test_offertoday_runner_isolates_empty_state_and_recommendation_cohort():
    class Transport:
        browser_context_hash = "e" * 64

        def __init__(self):
            self.calls = 0

        async def fetch_listing_page(self, _payload, *, listing_url):
            self.calls += 1
            if self.calls == 1:
                result_list = [
                    {
                        "cardType": 2,
                        "emptyCardType": 2,
                        "imageUrl": "https://img.offertodayhk.com/empty.png",
                        "desc": None,
                        "buttonText": None,
                        "jumpUrl": None,
                    },
                    {
                        "cardType": 0,
                        "jobId": "job-in-scope",
                        "jobName": "Enterprise Architect",
                        "jobFunctions": [],
                    },
                    {
                        "cardType": 3,
                        "separateLineCode": 0,
                        "separateDesc": "暫無更多結果\n為您推薦以下崗位",
                        "actionList": [],
                    },
                    {
                        "cardType": 0,
                        "jobId": "job-recommended-1",
                        "jobName": "Oil Painter",
                        "jobFunctions": [],
                    },
                ]
            else:
                result_list = [
                    {
                        "cardType": 0,
                        "jobId": f"job-recommended-{self.calls}",
                        "jobName": "Unrelated recommendation",
                        "jobFunctions": [],
                    }
                ]
            return OfferTodayListingTransportResult(
                payload={
                    "code": 0,
                    "data": {
                        "resultList": result_list,
                        "suppleRcdList": [],
                        "hasMore": True,
                        "total": 1,
                        "pageSize": 10,
                        "sessionId": "separator-session",
                        "supplePage": self.calls - 1,
                        "suppleAmount": 0,
                        "suppleType": 0,
                    },
                },
                response_url=listing_url,
                http_status=200,
                browser_context_hash=self.browser_context_hash,
            )

    class Sink:
        def __init__(self):
            self.observations = []
            self.rows = []

        async def record_page_start(self, **_kwargs):
            return None

        async def record_page_attempt(self, observation):
            self.observations.append(observation)

        async def record_condition_outcome(self, _outcome):
            return None

        async def stage_page(self, *, rows, **_kwargs):
            self.rows.extend(rows)

        async def defer_identity_conflict(self, **_kwargs):
            return None

    sink = Sink()
    transport = Transport()
    result = await OfferTodayListingRunner(transport).run(
        conditions=(
            OfferTodayListingCondition(
                search_family="classification_keyword_sweep",
                category_id=118000,
                keyword="A",
                endpoint="search",
                rcd_type=None,
            ),
        ),
        stop_policy=ListingStopPolicy(
            max_pages_per_condition=3,
            run_page_cap=3,
            page_cap_behavior="retain-and-continue",
            stall_no_growth_page_count=3,
        ),
        retry_policy=ListingRetryPolicy(max_attempts_per_page=1),
        observation_sink=sink,
        staging_sink=sink,
        session_mode="headless",
        request_policy=production_offertoday_listing_request_policy(),
        terminal_policy="result-transition-confirmation-v1",
    )

    assert result.is_complete is True
    assert result.accepted_job_ids == ("job-in-scope",)
    assert result.supplemental_job_ids == (
        "job-recommended-1",
        "job-recommended-2",
        "job-recommended-3",
    )
    assert result.identity_issues == ()
    assert result.non_job_cards_observed == 2
    assert transport.calls == 3
    assert sink.observations[0].row_count == 4
    assert sink.observations[0].non_job_cards_observed == 2
    assert [item.terminal_empty_count for item in sink.observations] == [0, 1, 2]
    assert len(sink.rows) == 1


@pytest.mark.asyncio
async def test_offertoday_stall_restarts_once_then_marks_only_target_partial():
    first_keyword = "Java"

    class Transport:
        def __init__(self) -> None:
            self.first_calls = 0
            self.restart_calls = 0

        async def fetch_listing_json(self, payload, *, listing_url=None):
            if payload["keyword"] == first_keyword:
                self.first_calls += 1
                return {
                    "code": 0,
                    "data": {
                        "resultList": [
                            {
                                "cardType": 0,
                                "jobId": "job-1",
                                "jobName": "Engineer",
                                "jobFunctions": [],
                            }
                        ],
                        "hasMore": True,
                        "total": 100,
                    },
                }
            return {
                "code": 0,
                "data": {"resultList": [], "hasMore": False, "total": 0},
            }

        async def restart_after_stalled_query(self) -> None:
            self.restart_calls += 1

    class Sink:
        def __init__(self) -> None:
            self.staged_rows = []

        async def record_page_start(self, **_kwargs):
            return None

        async def record_page_attempt(self, _observation):
            return None

        async def record_condition_outcome(self, _outcome):
            return None

        async def stage_page(self, *, rows, **_kwargs):
            self.staged_rows.extend(rows)

        async def defer_identity_conflict(self, **_kwargs):
            return None

    transport = Transport()
    sink = Sink()
    conditions = (
        OfferTodayListingCondition(
            search_family="classification_keyword_pack",
            category_id=118000,
            keyword=first_keyword,
            endpoint="search",
            rcd_type=None,
        ),
        OfferTodayListingCondition(
            search_family="classification_keyword_pack",
            category_id=118000,
            keyword="Python",
            endpoint="search",
            rcd_type=None,
        ),
    )

    result = await OfferTodayListingRunner(transport).run(
        conditions=conditions,
        stop_policy=ListingStopPolicy(
            max_pages_per_condition=10,
            run_page_cap=20,
            page_cap_behavior="retain-and-continue",
            stall_no_growth_page_count=3,
            max_stall_restarts_per_condition=1,
        ),
        retry_policy=ListingRetryPolicy(max_attempts_per_page=1),
        observation_sink=sink,
        staging_sink=sink,
        session_mode="headless",
    )

    assert transport.first_calls == 7
    assert transport.restart_calls == 1
    assert len(sink.staged_rows) == 1
    assert result.accepted_job_ids == ("job-1",)
    assert [outcome.stop_reason for outcome in result.condition_outcomes] == [
        "stalled_after_session_recovery",
        "natural_exhaustion",
    ]
    assert result.condition_outcomes[0].stall_recovery_count == 1
    assert result.condition_outcomes[0].is_partial is True
    assert result.condition_outcomes[1].is_complete is True
    assert result.stop_reason == "partial_coverage"
    assert result.is_partial is True
    assert result.capped_condition_ids == ()


@pytest.mark.asyncio
async def test_offertoday_two_empty_pages_complete_before_stall_detection():
    class Transport:
        def __init__(self) -> None:
            self.calls = 0

        async def fetch_listing_json(self, _payload, *, listing_url=None):
            self.calls += 1
            return {
                "code": 0,
                "data": {"resultList": [], "hasMore": True, "total": 100},
            }

    class Sink:
        async def record_page_start(self, **_kwargs):
            return None

        async def record_page_attempt(self, _observation):
            return None

        async def record_condition_outcome(self, _outcome):
            return None

        async def stage_page(self, **_kwargs):
            return None

        async def defer_identity_conflict(self, **_kwargs):
            return None

    transport = Transport()
    result = await OfferTodayListingRunner(transport).run(
        conditions=(
            OfferTodayListingCondition(
                search_family="classification_keyword_pack",
                category_id=118000,
                keyword="Java",
                endpoint="search",
                rcd_type=None,
            ),
        ),
        stop_policy=ListingStopPolicy(
            max_pages_per_condition=10,
            stall_no_growth_page_count=2,
        ),
        retry_policy=ListingRetryPolicy(max_attempts_per_page=1),
        observation_sink=Sink(),
        staging_sink=Sink(),
        session_mode="headless",
    )

    assert transport.calls == 2
    assert result.is_complete is True
    assert result.condition_outcomes[0].stop_reason == "natural_exhaustion"


@pytest.mark.asyncio
async def test_offertoday_terminal_empty_pages_may_reuse_last_response_cursor():
    class Transport:
        browser_context_hash = "e" * 64

        def __init__(self) -> None:
            self.payloads = []

        async def fetch_listing_page(self, payload, *, listing_url):
            self.payloads.append(dict(payload))
            if len(self.payloads) == 1:
                data = {
                    "resultList": [
                        {
                            "cardType": 0,
                            "jobId": "job-terminal",
                            "jobName": "Terminal page job",
                            "jobFunctions": [],
                        }
                    ],
                    "suppleRcdList": [],
                    "hasMore": False,
                    "total": 1,
                    "pageSize": 10,
                    "sessionId": "terminal-session",
                    "supplePage": 0,
                    "suppleAmount": 0,
                    "suppleType": 0,
                }
            else:
                data = {
                    "resultList": [],
                    "suppleRcdList": [],
                    "hasMore": False,
                    "total": 0,
                    "pageSize": 10,
                }
            return OfferTodayListingTransportResult(
                payload={"code": 0, "data": data},
                response_url=listing_url,
                http_status=200,
                browser_context_hash=self.browser_context_hash,
            )

    class Sink:
        def __init__(self) -> None:
            self.observations = []

        async def record_page_start(self, **_kwargs):
            return None

        async def record_page_attempt(self, observation):
            self.observations.append(observation)

        async def record_condition_outcome(self, _outcome):
            return None

        async def stage_page(self, **_kwargs):
            return None

        async def defer_identity_conflict(self, **_kwargs):
            return None

    transport = Transport()
    sink = Sink()
    result = await OfferTodayListingRunner(transport).run(
        conditions=(
            OfferTodayListingCondition(
                search_family="native_classification",
                category_id=118000,
                keyword="",
                endpoint="search",
                rcd_type=None,
            ),
        ),
        stop_policy=ListingStopPolicy(
            max_pages_per_condition=10,
            run_page_cap=10,
            page_cap_behavior="retain-and-continue",
            stall_no_growth_page_count=3,
        ),
        retry_policy=ListingRetryPolicy(max_attempts_per_page=1),
        observation_sink=sink,
        staging_sink=sink,
        session_mode="headless",
        request_policy=production_offertoday_listing_request_policy(),
        terminal_policy="result-transition-confirmation-v1",
    )

    assert result.is_complete is True
    assert result.condition_outcomes[0].terminal_empty_count == 2
    assert len(transport.payloads) == 3
    assert [payload["page"] for payload in transport.payloads] == [1, 2, 3]
    assert transport.payloads[1]["sessionId"] == "terminal-session"
    assert transport.payloads[2]["sessionId"] == "terminal-session"
    assert [
        observation.terminal_empty_count for observation in sink.observations
    ] == [0, 1, 2]
    assert sink.observations[1].cursor_evidence.cursor_output is None
    assert (
        sink.observations[1].cursor_evidence.response_cursor_fields.session_id
        is False
    )
    assert [observation.stop_reason for observation in sink.observations] == [
        None,
        None,
        "result_cohort_exhaustion",
    ]


@pytest.mark.asyncio
async def test_offertoday_terminal_empty_page_rejects_partial_response_cursor():
    class Transport:
        browser_context_hash = "e" * 64

        def __init__(self) -> None:
            self.payloads = []

        async def fetch_listing_page(self, payload, *, listing_url):
            self.payloads.append(dict(payload))
            data = {
                "resultList": [
                    {
                        "cardType": 0,
                        "jobId": "job-terminal",
                        "jobName": "Terminal page job",
                        "jobFunctions": [],
                    }
                ],
                "suppleRcdList": [],
                "hasMore": False,
                "total": 1,
                "pageSize": 10,
                "sessionId": "terminal-session",
                "supplePage": 0,
                "suppleAmount": 0,
                "suppleType": 0,
            }
            if len(self.payloads) == 2:
                data = {
                    "resultList": [],
                    "suppleRcdList": [],
                    "hasMore": False,
                    "total": 0,
                    "pageSize": 10,
                    "sessionId": "terminal-session",
                }
            return OfferTodayListingTransportResult(
                payload={"code": 0, "data": data},
                response_url=listing_url,
                http_status=200,
                browser_context_hash=self.browser_context_hash,
            )

    class Sink:
        def __init__(self) -> None:
            self.observations = []

        async def record_page_start(self, **_kwargs):
            return None

        async def record_page_attempt(self, observation):
            self.observations.append(observation)

        async def record_condition_outcome(self, _outcome):
            return None

        async def stage_page(self, **_kwargs):
            return None

        async def defer_identity_conflict(self, **_kwargs):
            return None

    transport = Transport()
    sink = Sink()
    result = await OfferTodayListingRunner(transport).run(
        conditions=(
            OfferTodayListingCondition(
                search_family="native_classification",
                category_id=118000,
                keyword="",
                endpoint="search",
                rcd_type=None,
            ),
        ),
        stop_policy=ListingStopPolicy(
            max_pages_per_condition=10,
            run_page_cap=10,
            page_cap_behavior="retain-and-continue",
            stall_no_growth_page_count=3,
        ),
        retry_policy=ListingRetryPolicy(max_attempts_per_page=1),
        observation_sink=sink,
        staging_sink=sink,
        session_mode="headless",
        request_policy=production_offertoday_listing_request_policy(),
        terminal_policy="result-transition-confirmation-v1",
    )

    assert result.stop_reason == "cursor_contract_violation"
    assert result.is_complete is False
    assert len(transport.payloads) == 2
    assert sink.observations[1].cursor_evidence.contract_error == "incomplete_cursor"


@pytest.mark.asyncio
async def test_offertoday_source_collection_window_is_partial_and_continues():
    class Transport:
        browser_context_hash = "e" * 64

        def __init__(self) -> None:
            self.pages_by_keyword: dict[str, list[int]] = {}

        async def fetch_listing_page(self, payload, *, listing_url):
            keyword = str(payload["keyword"])
            page = int(payload["page"])
            self.pages_by_keyword.setdefault(keyword, []).append(page)
            if keyword == "middle" and page == 46:
                data = {
                    "resultList": [],
                    "hasMore": True,
                    "total": 500,
                    "pageSize": 10,
                }
            elif keyword == "middle":
                data = {
                    "resultList": [
                        {
                            "cardType": 0,
                            "jobId": f"middle-{page}",
                            "jobName": f"Middle job {page}",
                            "jobFunctions": [],
                        }
                    ],
                    "suppleRcdList": [],
                    "hasMore": True,
                    "total": 500,
                    "pageSize": 10,
                    "sessionId": "middle-session",
                    "supplePage": page,
                    "suppleAmount": 0,
                    "suppleType": 0,
                }
            else:
                call_count = len(self.pages_by_keyword[keyword])
                data = {
                    "resultList": (
                        [
                            {
                                "cardType": 0,
                                "jobId": f"{keyword}-job",
                                "jobName": f"{keyword.title()} job",
                                "jobFunctions": [],
                            }
                        ]
                        if call_count == 1
                        else []
                    ),
                    "suppleRcdList": [],
                    "hasMore": False,
                    "total": 1 if call_count == 1 else 0,
                    "pageSize": 10,
                    **(
                        {
                            "sessionId": f"{keyword}-session",
                            "supplePage": page,
                            "suppleAmount": 0,
                            "suppleType": 0,
                        }
                        if call_count == 1
                        else {}
                    ),
                }
            return OfferTodayListingTransportResult(
                payload={"code": 0, "data": data},
                response_url=listing_url,
                http_status=200,
                browser_context_hash=self.browser_context_hash,
            )

    class Sink:
        def __init__(self) -> None:
            self.observations = []
            self.staged_rows = []

        async def record_page_start(self, **_kwargs):
            return None

        async def record_page_attempt(self, observation):
            self.observations.append(observation)

        async def record_condition_outcome(self, _outcome):
            return None

        async def stage_page(self, *, rows, **_kwargs):
            self.staged_rows.extend(rows)

        async def defer_identity_conflict(self, **_kwargs):
            return None

    conditions = tuple(
        OfferTodayListingCondition(
            search_family="classification_keyword_pack",
            category_id=118000,
            keyword=keyword,
            endpoint="search",
            rcd_type=None,
        )
        for keyword in ("first", "middle", "third")
    )
    transport = Transport()
    sink = Sink()

    result = await OfferTodayListingRunner(transport).run(
        conditions=conditions,
        stop_policy=ListingStopPolicy(
            max_pages_per_condition=50,
            run_page_cap=60,
            page_cap_behavior="retain-and-continue",
            stall_no_growth_page_count=None,
        ),
        retry_policy=ListingRetryPolicy(max_attempts_per_page=1),
        observation_sink=sink,
        staging_sink=sink,
        session_mode="headless",
        request_policy=production_offertoday_listing_request_policy(),
        terminal_policy="result-transition-confirmation-v1",
    )

    assert transport.pages_by_keyword["middle"][-1] == 46
    assert transport.pages_by_keyword["third"] == [1, 2, 3]
    assert [outcome.stop_reason for outcome in result.condition_outcomes] == [
        "result_cohort_exhaustion",
        "source_collection_window",
        "result_cohort_exhaustion",
    ]
    assert result.condition_outcomes[1].is_partial is True
    assert result.stop_reason == "partial_coverage"
    assert result.is_complete is False
    assert "middle-45" in result.accepted_job_ids
    assert "third-job" in result.accepted_job_ids
    window = next(
        observation
        for observation in sink.observations
        if observation.stop_reason == "source_collection_window"
    )
    assert window.cursor_evidence.contract_error == "incomplete_cursor"


@pytest.mark.asyncio
async def test_offertoday_cursorless_empty_before_source_window_remains_fatal():
    class Transport:
        browser_context_hash = "e" * 64

        async def fetch_listing_page(self, payload, *, listing_url):
            page = int(payload["page"])
            data = {
                "resultList": (
                    [
                        {
                            "cardType": 0,
                            "jobId": "job-1",
                            "jobName": "Job 1",
                            "jobFunctions": [],
                        }
                    ]
                    if page == 1
                    else []
                ),
                "suppleRcdList": [],
                "hasMore": True,
                "total": 500,
                "pageSize": 10,
                **(
                    {
                        "sessionId": "session-1",
                        "supplePage": 1,
                        "suppleAmount": 0,
                        "suppleType": 0,
                    }
                    if page == 1
                    else {}
                ),
            }
            return OfferTodayListingTransportResult(
                payload={"code": 0, "data": data},
                response_url=listing_url,
                http_status=200,
                browser_context_hash=self.browser_context_hash,
            )

    class Sink:
        async def record_page_start(self, **_kwargs):
            return None

        async def record_page_attempt(self, _observation):
            return None

        async def record_condition_outcome(self, _outcome):
            return None

        async def stage_page(self, **_kwargs):
            return None

        async def defer_identity_conflict(self, **_kwargs):
            return None

    result = await OfferTodayListingRunner(Transport()).run(
        conditions=(
            OfferTodayListingCondition(
                search_family="classification_keyword_pack",
                category_id=118000,
                keyword="early",
                endpoint="search",
                rcd_type=None,
            ),
        ),
        stop_policy=ListingStopPolicy(max_pages_per_condition=50),
        retry_policy=ListingRetryPolicy(max_attempts_per_page=1),
        observation_sink=Sink(),
        staging_sink=Sink(),
        session_mode="headless",
        request_policy=production_offertoday_listing_request_policy(),
        terminal_policy="result-transition-confirmation-v1",
    )

    assert result.stop_reason == "cursor_contract_violation"
    assert result.condition_outcomes[0].is_partial is False


@pytest.mark.asyncio
async def test_offertoday_job_shaped_missing_identity_remains_fatal():
    class Transport:
        async def fetch_listing_json(self, _payload, *, listing_url=None):
            return {
                "code": 0,
                "data": {
                    "resultList": [
                        {
                            "cardType": 0,
                            "jobName": "Missing identity job",
                            "jobFunctions": [],
                        }
                    ],
                    "hasMore": False,
                    "total": 1,
                },
            }

    class Sink:
        async def record_page_start(self, **_kwargs):
            return None

        async def record_page_attempt(self, _observation):
            return None

        async def record_condition_outcome(self, _outcome):
            return None

        async def stage_page(self, **_kwargs):
            raise AssertionError("invalid identity page must not stage")

        async def defer_identity_conflict(self, **_kwargs):
            return None

    result = await OfferTodayListingRunner(Transport()).run(
        conditions=(
            OfferTodayListingCondition(
                search_family="classification_keyword_sweep",
                category_id=118000,
                keyword="A",
                endpoint="search",
                rcd_type=None,
            ),
        ),
        stop_policy=ListingStopPolicy(max_pages_per_condition=1),
        retry_policy=ListingRetryPolicy(max_attempts_per_page=1),
        observation_sink=Sink(),
        staging_sink=Sink(),
        session_mode="headless",
        request_policy=None,
        terminal_policy="cursor-terminal-empty-confirmation-v1",
    )

    assert result.stop_reason == "identity_issue"
    assert len(result.identity_issues) == 1
    assert result.non_job_cards_observed == 0


@pytest.mark.asyncio
async def test_offertoday_standalone_uses_keyword_plan_without_hidden_defaults(
    monkeypatch,
) -> None:
    plan = _offertoday_adaptive_runtime_plan(
        (
            ("offertoday:118000", "native_top_level", ""),
            ("offertoday:118000", "keyword", "Java"),
            ("offertoday:118000", "keyword", "Python"),
        )
    )
    captured: dict[str, object] = {}

    class Browser:
        async def require_healthy_session(self) -> None:
            return None

    class Runner:
        async def run(
            self,
            *,
            conditions,
            stop_policy,
            request_policy,
            terminal_policy,
            **_kwargs,
        ):
            captured.update(
                conditions=conditions,
                stop_policy=stop_policy,
                request_policy=request_policy,
                terminal_policy=terminal_policy,
            )
            outcome = ListingConditionOutcome(
                condition=conditions[0],
                pages_observed=1,
                stop_reason="natural_exhaustion",
                is_complete=True,
            )
            return ListingRunResult(
                ordered_job_ids=(),
                accepted_job_ids=(),
                id_pairs=(),
                observations=(),
                condition_outcomes=(outcome,),
                identity_conflicts=(),
                identity_issues=(),
                gaps=(),
                stop_reason="natural_exhaustion",
                is_complete=True,
            )

    monkeypatch.setattr(
        offertoday_crawl,
        "load_source_query_plan",
        lambda *_args, **_kwargs: pytest.fail(
            "frozen OfferToday plan re-resolved classifications"
        ),
    )
    args = SimpleNamespace(
        crawl_job_id="offertoday-planned",
        crawl_phase="listing",
        headed=False,
        category_ids="tampered",
        keywords="tampered",
        max_pages=999,
        detail_limit=10,
        detail_statuses="pending",
        skip_existing=True,
        resume_strategy="fresh_profile",
    )
    offertoday_crawl._apply_listing_runtime_plan(args, plan)
    assert args.skip_existing is True

    await offertoday_crawl._run_listing_phase(
        args=args,
        browser_runtime=Browser(),
        crawl_runtime=_Runtime(),
        crawl_job_id=args.crawl_job_id,
        listing_runner=Runner(),
    )

    conditions = captured["conditions"]
    assert [
        (condition.category_id, condition.keyword, condition.endpoint)
        for condition in conditions
    ] == [
        (118000, "", "search"),
        (118000, "Java", "search"),
        (118000, "Python", "search"),
    ]
    stop_policy = captured["stop_policy"]
    assert stop_policy.max_pages_per_condition == 2
    assert stop_policy.run_page_cap == 6
    assert stop_policy.require_empty_confirmation is True
    assert stop_policy.stall_no_growth_page_count == 3
    assert stop_policy.max_stall_restarts_per_condition == 1
    assert captured["request_policy"] is not None
    assert captured["terminal_policy"] == "result-transition-confirmation-v1"


@pytest.mark.asyncio
async def test_jobsdb_and_ctgoodjobs_detail_loops_receive_frozen_runtime_plan(
    caplog,
) -> None:
    class Runtime:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def load_detail_targets(self, **kwargs):
            self.calls.append(kwargs)
            plan = kwargs["detail_runtime_plan"]
            return _detail_load_result(
                (),
                snapshot_target_count=plan.selected_target_count,
            )

    jobsdb_plan = _detail_runtime_plan("jobsdb", target_count=0)
    jobsdb_args = SimpleNamespace(
        crawl_job_id=str(jobsdb_plan.crawl_job_id),
        category_ids=["tampered"],
        crawl_mode="headless",
        crawl_phase="listing",
        detail_limit=999,
        detail_statuses=["pending"],
        source_listing_crawl_job_id="tampered",
        skip_existing=True,
        is_resume=False,
        resume_strategy="fresh_profile",
        detail_pacing=None,
        cancellation_token=SimpleNamespace(
            raise_if_cancelled=lambda: None
        ),
    )
    jobsdb_crawl._apply_detail_runtime_plan(jobsdb_args, jobsdb_plan)
    assert jobsdb_args.skip_existing is True
    jobsdb_runtime = Runtime()
    await jobsdb_crawl.run_detail_phase(jobsdb_args, jobsdb_runtime)
    assert jobsdb_runtime.calls[0]["detail_runtime_plan"] is jobsdb_plan
    assert "catalog_revision_id" not in jobsdb_runtime.calls[0]["request_payload"]
    assert "catalog_revision_fingerprint" not in jobsdb_runtime.calls[0][
        "request_payload"
    ]

    ctgoodjobs_plan = _detail_runtime_plan("ctgoodjobs", target_count=0)
    ctgoodjobs_args = SimpleNamespace(
        crawl_job_id=str(ctgoodjobs_plan.crawl_job_id),
        category_ids=["tampered"],
        crawl_mode="headed",
        crawl_phase="listing",
        detail_limit=999,
        detail_statuses=["pending"],
        source_listing_crawl_job_id="tampered",
        skip_existing=True,
        is_resume=False,
        resume_strategy="fresh_profile",
        detail_pacing=None,
        cancellation_token=SimpleNamespace(
            raise_if_cancelled=lambda: None
        ),
    )
    ctgoodjobs_crawl._apply_detail_runtime_plan(
        ctgoodjobs_args,
        ctgoodjobs_plan,
    )
    assert ctgoodjobs_args.skip_existing is True
    ctgoodjobs_runtime = Runtime()
    await ctgoodjobs_crawl._run_detail_phase(
        ctgoodjobs_args,
        ctgoodjobs_runtime,
        browser_scraper=SimpleNamespace(),
        source_listing_crawl_job_id=None,
        detail_scope="source_backlog",
    )
    assert ctgoodjobs_runtime.calls[0][
        "detail_runtime_plan"
    ] is ctgoodjobs_plan
    assert "tampered" not in str(
        ctgoodjobs_runtime.calls[0]["request_payload"]
    )


@pytest.mark.asyncio
async def test_offertoday_recovery_segments_only_frozen_complete_run_membership(
    monkeypatch,
) -> None:
    plan = _detail_runtime_plan("offertoday", target_count=3)
    args = SimpleNamespace(
        crawl_job_id=str(plan.crawl_job_id),
        crawl_phase="listing",
        category_ids="tampered",
        keywords="tampered",
        max_pages=999,
        headed=False,
        source_listing_crawl_job_id="tampered",
        detail_scope="global",
        detail_limit=999,
        detail_statuses="pending",
        skip_existing=True,
        resume_strategy="fresh_profile",
        detail_pacing=None,
    )
    offertoday_crawl._apply_detail_runtime_plan(args, plan)
    assert args.skip_existing is True

    class Runtime:
        def __init__(self) -> None:
            self.loaded_segments: list[tuple[str, ...]] = []
            self.completed: list[dict] = []

        def load_detail_targets(self, **kwargs):
            assert kwargs["detail_runtime_plan"] is plan
            runtime_targets = tuple(kwargs.get("runtime_targets") or ())
            self.loaded_segments.append(
                tuple(target.source_job_id for target in runtime_targets)
            )
            return _detail_load_result(
                runtime_targets,
                snapshot_target_count=plan.selected_target_count,
            )

        def merge_metrics(self, **_kwargs) -> None:
            return None

        def write_progress_event(self, **_kwargs) -> None:
            return None

        def mark_completed(self, **kwargs) -> None:
            self.completed.append(kwargs)

        def mark_failed(self, **_kwargs) -> None:
            pytest.fail("frozen successful segments must not fail")

    async def fake_detail_phase(**kwargs):
        loaded = kwargs["detail_load_result"]
        return offertoday_crawl.OfferTodayDetailPhaseResult(
            detail_load_result=loaded,
            processed_targets=loaded.target_rows,
            outcome_counts={"success": loaded.target_rows},
            jobs_created=loaded.target_rows,
            jobs_updated=0,
            jobs_reconciled=0,
            companies_created=0,
            companies_updated=0,
            terminal_unavailable=0,
            persist_failure=0,
            stop_batch=False,
            total_target_rows=loaded.target_rows,
        )

    monkeypatch.setattr(
        offertoday_crawl,
        "DEFAULT_DETAIL_RECOVERY_SEGMENT_SIZE",
        2,
    )
    monkeypatch.setattr(
        offertoday_crawl,
        "_run_detail_phase",
        fake_detail_phase,
    )
    runtime = Runtime()

    result = await offertoday_crawl._run_detail_recovery(
        args=args,
        browser_runtime=SimpleNamespace(),
        crawl_runtime=runtime,
        crawl_job_id=args.crawl_job_id,
    )

    assert runtime.loaded_segments == [
        ("frozen-0", "frozen-1"),
        ("frozen-2",),
        (),
    ]
    assert result.total_target_rows == 3
    assert result.segments_completed == 2
    assert result.stop_batch is False
    assert runtime.completed[0]["metrics"][
        "detail_live_future_eligible_count"
    ] == 1
