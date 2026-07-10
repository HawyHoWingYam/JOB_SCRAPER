from __future__ import annotations

import importlib
import inspect
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.offertoday_research_observation_service import (
    OfferTodayResearchObservationService,
)
from app.sources.offertoday.listing_runner import (
    ListingPageObservation,
    ListingRowEvidence,
    OfferTodayIdentityPair,
    OfferTodayListingRunner,
)


@pytest.mark.asyncio
async def test_run_runtime_probe_delegates_smoke_test_to_runtime(monkeypatch):
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    calls: dict[str, object] = {}

    class _FakeRuntime:
        def __init__(self, **kwargs) -> None:
            self.kwargs = dict(kwargs)
            self._page = SimpleNamespace(url="https://www.offertoday.com/hk/search")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def check_session(self, *, listing_payload):
            calls["check_payload"] = dict(listing_payload)
            return SimpleNamespace(
                current_url="https://www.offertoday.com/hk/search",
                is_waf_challenge=False,
                listing_probe_payload={"data": {"resultList": [{"jobId": "job-1", "encryptJobId": "enc-1"}]}},
                listing_result_count=1,
                healthy=True,
            )

        async def run_smoke_test(self, *, listing_payload, detail_limit=1):
            calls["smoke_payload"] = dict(listing_payload)
            calls["detail_limit"] = detail_limit
            return {
                "listing_ok": True,
                "listing_count": 1,
                "detail_results": [{"job_id": "job-1", "code": 0}],
                "current_url": "https://www.offertoday.com/hk/search",
                "is_waf_challenge": False,
            }

    monkeypatch.setattr(crawl_module, "OfferTodayBrowserRuntime", _FakeRuntime)

    exit_code = await crawl_module._run_runtime_probe(
        headed=False,
        auth_state="",
        resume_strategy="fresh_profile",
        category_ids=[],
        keywords=["data"],
        smoke_test=True,
    )

    assert exit_code == 0
    assert calls["smoke_payload"]["keyword"] == "data"
    assert calls["detail_limit"] == 1


@pytest.mark.asyncio
async def test_run_runtime_probe_fails_when_smoke_test_reports_no_detail_success(monkeypatch):
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")

    class _FakeRuntime:
        def __init__(self, **kwargs) -> None:
            self.kwargs = dict(kwargs)
            self._page = SimpleNamespace(url="https://www.offertoday.com/hk/search")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def check_session(self, *, listing_payload):
            return SimpleNamespace(
                current_url="https://www.offertoday.com/hk/search",
                is_waf_challenge=False,
                listing_probe_payload={"data": {"resultList": []}},
                listing_result_count=0,
                healthy=True,
            )

        async def run_smoke_test(self, *, listing_payload, detail_limit=1):
            return {
                "listing_ok": True,
                "listing_count": 1,
                "detail_results": [{"job_id": "job-1", "code": -1000035}],
                "current_url": "https://www.offertoday.com/hk/search",
                "is_waf_challenge": False,
            }

    monkeypatch.setattr(crawl_module, "OfferTodayBrowserRuntime", _FakeRuntime)

    exit_code = await crawl_module._run_runtime_probe(
        headed=False,
        auth_state="",
        resume_strategy="fresh_profile",
        category_ids=[],
        keywords=["data"],
        smoke_test=True,
    )

    assert exit_code == 1


@pytest.mark.asyncio
async def test_run_runtime_probe_check_fails_when_session_is_unhealthy(monkeypatch):
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")

    class _FakeRuntime:
        def __init__(self, **kwargs) -> None:
            self._page = SimpleNamespace(url="https://www.offertoday.com/hk/search")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def check_session(self, *, listing_payload):
            return SimpleNamespace(
                current_url="https://www.offertoday.com/hk/search",
                is_waf_challenge=False,
                listing_result_count=0,
                healthy=False,
            )

    monkeypatch.setattr(crawl_module, "OfferTodayBrowserRuntime", _FakeRuntime)

    exit_code = await crawl_module._run_runtime_probe(
        headed=False,
        auth_state="",
        resume_strategy="fresh_profile",
        category_ids=[],
        keywords=["data"],
        smoke_test=False,
    )

    assert exit_code == 1


@pytest.mark.asyncio
async def test_fetch_detail_json_propagates_strict_identity_error_without_fallback(
    monkeypatch,
):
    crawl_module = importlib.import_module(
        "backend.scripts.offertoday_standalone_crawl"
    )
    identity_module = importlib.import_module("app.sources.offertoday.detail_identity")
    identity_error = identity_module.OfferTodayIdentityError("missing encryptJobId")
    calls: list[tuple[object, object]] = []
    legacy_calls = 0

    class _FakeRuntime:
        async def fetch_detail_json(self, *, job_id, encrypted_job_id=None):
            calls.append((job_id, encrypted_job_id))
            raise identity_error

    async def legacy_fallback(*args, **kwargs):
        nonlocal legacy_calls
        legacy_calls += 1
        return "{}"

    monkeypatch.setattr(crawl_module, "scrapling_fetch", legacy_fallback, raising=False)

    with pytest.raises(identity_module.OfferTodayIdentityError) as exc_info:
        await crawl_module._fetch_detail_json_with_identifiers(
            _FakeRuntime(),
            job_id="job-1",
            encrypted_job_id=None,
        )

    assert exc_info.value is identity_error
    assert calls == [("job-1", None)]
    assert legacy_calls == 0


def test_persist_listing_checkpoint_uses_shared_runtime_for_stage_and_progress(caplog):
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    runtime_calls: list[tuple[str, object]] = []

    class _FakeRuntime:
        def stage_listing_batch(self, **kwargs):
            runtime_calls.append(("stage", len(kwargs["payloads"])))
            return SimpleNamespace(job_ids_seen=1, rows_staged=1, skipped_existing=0)

        def write_progress_event(self, **kwargs):
            runtime_calls.append(("event", kwargs["event_type"]))

    with caplog.at_level(logging.INFO, logger="offertoday-crawl"):
        result = crawl_module._persist_listing_checkpoint(
            crawl_runtime=_FakeRuntime(),
            crawl_job_id=str(uuid4()),
            search_family="it_keyword",
            search_families=["it_keyword"],
            category_id=118000,
            keyword="python",
            current_page=1,
            total_pages=3,
            pending_listing_payloads=[
                {
                    "source_site": "offertoday",
                    "source_job_id": "job-1",
                    "source_url": "https://www.offertoday.com/hk/job/job-1",
                    "listing_payload": {"jobId": "job-1"},
                }
            ],
            jobs_skipped_existing=0,
            skip_existing=True,
        )

    assert ("stage", 1) in runtime_calls
    assert ("event", "crawl.page_processed") in runtime_calls
    assert result.rows_staged == 1
    assert "SCRAPE_LISTING_BATCH_STAGED" in caplog.text


def _default_listing_args(**overrides):
    values = {
        "category_ids": [118000],
        "keywords": [],
        "max_pages": 50,
        "crawl_phase": "listing",
        "crawl_job_id": "crawl-1",
        "source_listing_crawl_job_id": "",
        "detail_limit": 100,
        "detail_statuses": "pending,failed,manual_action_required",
        "resume_strategy": "fresh_profile",
        "skip_existing": True,
        "headed": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _listing_result(
    *,
    stop_reason="natural_exhaustion",
    is_complete=True,
    accepted_job_ids=("job-1",),
    ordered_job_ids=None,
    gaps=(),
    identity_conflicts=(),
    identity_issues=(),
    observations=(),
    condition_outcomes=(),
):
    return SimpleNamespace(
        stop_reason=stop_reason,
        is_complete=is_complete,
        accepted_job_ids=tuple(accepted_job_ids),
        ordered_job_ids=tuple(ordered_job_ids or accepted_job_ids),
        gaps=tuple(gaps),
        identity_conflicts=tuple(identity_conflicts),
        identity_issues=tuple(identity_issues),
        observations=tuple(observations),
        condition_outcomes=tuple(condition_outcomes),
    )


class _FakeListingBrowserRuntime:
    def __init__(self, responses=None, trace=None):
        self.responses = list(responses or [])
        self.trace = trace
        self.preflight_calls = 0
        self.fetch_calls = []

    async def require_healthy_session(self):
        self.preflight_calls += 1
        if self.trace is not None:
            self.trace.append("preflight")
        return SimpleNamespace(healthy=True)

    async def fetch_listing_json(self, payload, *, listing_url=None):
        self.fetch_calls.append((dict(payload), listing_url))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class _FakeCrawlRuntime:
    def __init__(self):
        self.stage_calls = []
        self.defer_calls = []
        self.events = []
        self.load_detail_targets_calls = []
        self.manual_action_payload = None
        self.failed_payload = None
        self.completed_calls = []

    def stage_listing_batch(self, **kwargs):
        self.stage_calls.append(dict(kwargs))
        source_job_ids = tuple(
            payload["source_job_id"] for payload in kwargs["payloads"]
        )
        return SimpleNamespace(
            rows_staged=len(source_job_ids),
            rows_created=len(source_job_ids),
            skipped_existing=0,
            created_source_job_ids=source_job_ids,
            preexisting_staged_source_job_ids=(),
            published_source_job_ids=(),
            job_ids_seen=len(source_job_ids),
        )

    def defer_listing_identity_conflict(self, **kwargs):
        self.defer_calls.append(dict(kwargs))
        return len(kwargs["source_job_ids"])

    def write_progress_event(self, **kwargs):
        self.events.append(dict(kwargs))

    def load_detail_targets(self, **kwargs):
        self.load_detail_targets_calls.append(dict(kwargs))
        source_job_ids = list(kwargs["request_payload"].get("source_job_ids") or [])
        return SimpleNamespace(
            targets=[{"source_job_id": source_job_id} for source_job_id in source_job_ids],
            target_rows=len(source_job_ids),
            selected_rows=len(source_job_ids),
            skipped_existing_rows=0,
        )

    def mark_manual_action_required(self, **kwargs):
        self.manual_action_payload = dict(kwargs["payload"])

    def mark_failed(self, **kwargs):
        self.failed_payload = dict(kwargs["payload"])

    def mark_completed(self, **kwargs):
        self.completed_calls.append(dict(kwargs))


@pytest.mark.asyncio
async def test_run_listing_phase_preflights_once_and_uses_shared_default_it_policies():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    trace = []
    browser_runtime = _FakeListingBrowserRuntime(trace=trace)

    async def run(**kwargs):
        assert trace == ["preflight"]
        trace.append("runner")
        return _listing_result()

    runner = SimpleNamespace(run=AsyncMock(side_effect=run))

    result = await crawl_module._run_listing_phase(
        args=_default_listing_args(),
        browser_runtime=browser_runtime,
        crawl_runtime=_FakeCrawlRuntime(),
        crawl_job_id="crawl-1",
        listing_runner=runner,
    )

    assert result.is_complete is True
    assert browser_runtime.preflight_calls == 1
    assert trace == ["preflight", "runner"]
    run_kwargs = runner.run.await_args.kwargs
    assert run_kwargs["stop_policy"].max_pages_per_condition == 50
    assert (
        run_kwargs["stop_policy"].unique_job_cap
        == crawl_module.DEFAULT_IT_UNIQUE_JOB_TARGET
        == 5000
    )
    assert run_kwargs["stop_policy"].require_empty_confirmation is True
    assert run_kwargs["retry_policy"].max_attempts_per_page == 3
    assert run_kwargs["retry_policy"].retry_delays_seconds == (1.0, 2.0)
    assert run_kwargs["retry_policy"].page_delay_seconds == 1.5
    assert isinstance(
        run_kwargs["observation_sink"], crawl_module.CrawlJobListingObservationSink
    )
    assert isinstance(
        run_kwargs["staging_sink"], crawl_module.OfferTodayCrawlStagingSink
    )
    assert run_kwargs["session_mode"] == "headless"
    assert run_kwargs["conditions"][0].search_family == "it_category"


@pytest.mark.asyncio
async def test_non_default_listing_has_no_unique_cap():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    runner = SimpleNamespace(run=AsyncMock(return_value=_listing_result()))

    await crawl_module._run_listing_phase(
        args=_default_listing_args(category_ids=[], keywords=["python"]),
        browser_runtime=_FakeListingBrowserRuntime(),
        crawl_runtime=_FakeCrawlRuntime(),
        crawl_job_id="crawl-1",
        listing_runner=runner,
    )

    assert runner.run.await_args.kwargs["stop_policy"].unique_job_cap is None
    conditions = runner.run.await_args.kwargs["conditions"]
    assert [(condition.search_family, condition.keyword) for condition in conditions] == [
        ("explicit_keyword", "python")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stop_reason", "action_type"),
    [
        ("auth_expired", "session_recovery"),
        ("waf_challenge", "session_recovery"),
        ("ip_blocked", "session_recovery"),
        ("identity_issue", "identity_audit"),
        ("identity_conflict", "identity_audit"),
        ("id_mismatch", "identity_audit"),
    ],
)
async def test_listing_hard_stop_enters_resumable_manual_or_identity_audit_state(
    stop_reason,
    action_type,
):
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    crawl_runtime = _FakeCrawlRuntime()
    runner = SimpleNamespace(
        run=AsyncMock(
            return_value=_listing_result(
                stop_reason=stop_reason,
                is_complete=False,
                condition_outcomes=[SimpleNamespace(pages_observed=2)],
            )
        )
    )

    result = await crawl_module._run_listing_phase(
        args=_default_listing_args(crawl_phase="full"),
        browser_runtime=_FakeListingBrowserRuntime(),
        crawl_runtime=crawl_runtime,
        crawl_job_id="crawl-1",
        listing_runner=runner,
    )

    assert result.is_complete is False
    assert crawl_runtime.failed_payload is None
    assert crawl_runtime.manual_action_payload["classification"] == stop_reason
    assert crawl_runtime.manual_action_payload["action_type"] == action_type
    assert crawl_runtime.manual_action_payload["resume_context"]["crawl_phase"] == "listing"
    assert crawl_runtime.manual_action_payload["evidence"]["pages_observed"] == 2
    assert crawl_runtime.load_detail_targets_calls == []
    assert crawl_runtime.completed_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stop_reason",
    ["unresolved_gap", "page_cap", "target_cap", "unknown_incomplete"],
)
async def test_incomplete_listing_failure_records_stop_evidence_and_loads_no_details(
    stop_reason,
):
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    crawl_runtime = _FakeCrawlRuntime()
    runner = SimpleNamespace(
        run=AsyncMock(
            return_value=_listing_result(
                stop_reason=stop_reason,
                is_complete=False,
                gaps=[SimpleNamespace(page=3)],
                identity_conflicts=[SimpleNamespace(reason="conflict")],
                condition_outcomes=[SimpleNamespace(pages_observed=4)],
            )
        )
    )

    result = await crawl_module._run_listing_phase(
        args=_default_listing_args(crawl_phase="full"),
        browser_runtime=_FakeListingBrowserRuntime(),
        crawl_runtime=crawl_runtime,
        crawl_job_id="crawl-1",
        listing_runner=runner,
    )

    assert result.is_complete is False
    assert crawl_runtime.manual_action_payload is None
    assert crawl_runtime.failed_payload == {
        "stop_reason": stop_reason,
        "gap_count": 1,
        "conflict_count": 1,
        "identity_issue_count": 0,
        "pages_observed": 4,
        "accepted_job_ids": ["job-1"],
    }
    assert crawl_runtime.load_detail_targets_calls == []
    assert crawl_runtime.completed_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted_job_ids", [("old-1", "new-1"), ()])
async def test_complete_full_listing_loads_only_accepted_global_cohort(accepted_job_ids):
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    crawl_runtime = _FakeCrawlRuntime()
    runner = SimpleNamespace(
        run=AsyncMock(return_value=_listing_result(accepted_job_ids=accepted_job_ids))
    )

    result = await crawl_module._run_listing_phase(
        args=_default_listing_args(crawl_phase="full"),
        browser_runtime=_FakeListingBrowserRuntime(),
        crawl_runtime=crawl_runtime,
        crawl_job_id="crawl-1",
        listing_runner=runner,
    )

    assert result.is_complete is True
    assert len(crawl_runtime.load_detail_targets_calls) == 1
    detail_call = crawl_runtime.load_detail_targets_calls[0]
    assert detail_call["request_payload"]["source_job_ids"] == list(
        accepted_job_ids
    )
    assert detail_call["request_payload"]["detail_limit"] == len(accepted_job_ids)
    assert "source_listing_crawl_job_id" not in detail_call["request_payload"]
    assert [target["source_job_id"] for target in result.detail_targets] == list(
        accepted_job_ids
    )


def test_build_listing_staging_payload_uses_canonical_id_and_encrypted_public_url():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    condition = SimpleNamespace(
        search_family="it_category",
        category_id=118001,
        keyword="python",
    )
    raw_data = {"jobId": "canonical-1", "encryptJobId": "encrypted-1"}

    payload = crawl_module._build_listing_staging_payload(
        {
            "job_id": "canonical-1",
            "encrypted_job_id": "encrypted-1",
            "title": "Data Engineer",
            "raw_data": raw_data,
        },
        condition=condition,
        page=3,
        rank=7,
    )

    assert payload["source_job_id"] == "canonical-1"
    assert payload["source_url"] == "https://www.offertoday.com/hk/job/encrypted-1"
    assert payload["source_classification_id"] == "118001"
    assert payload["source_classification_name"] == "it_category"
    assert payload["listing_page"] == 3
    assert payload["listing_rank"] == 7
    assert payload["listing_payload"]["raw_data"] == raw_data
    assert payload["search_family"] == "it_category"
    assert payload["keyword"] == "python"

    with pytest.raises(ValueError, match="encrypted_job_id"):
        crawl_module._build_listing_staging_payload(
            {"job_id": "canonical-1", "encrypted_job_id": "", "raw_data": {}},
            condition=condition,
            page=1,
            rank=1,
        )


@pytest.mark.asyncio
async def test_staging_sink_uses_rows_created_and_defers_global_identity_conflict():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    crawl_runtime = _FakeCrawlRuntime()
    sink = crawl_module.OfferTodayCrawlStagingSink(
        crawl_runtime=crawl_runtime,
        crawl_job_id="crawl-1",
        skip_existing=False,
    )
    condition = SimpleNamespace(
        search_family="explicit_keyword",
        category_id=None,
        keyword="python",
    )

    await sink.stage_page(
        condition=condition,
        page=1,
        rows=[
            {
                "job_id": "canonical-1",
                "encrypted_job_id": "encrypted-1",
                "raw_data": {
                    "jobId": "canonical-1",
                    "encryptJobId": "encrypted-1",
                },
            }
        ],
    )
    await sink.defer_identity_conflict(
        job_ids=("canonical-1",),
        encrypted_job_ids=("encrypted-1",),
        reason="id_mismatch",
    )

    assert sink.rows_created == sink.rows_staged == 1
    assert sink.created_source_job_ids == ["canonical-1"]
    assert crawl_runtime.defer_calls == [
        {
            "crawl_job_id": "crawl-1",
            "source_job_ids": ("canonical-1",),
            "encrypted_job_ids": ("encrypted-1",),
            "reason": "id_mismatch",
        }
    ]


def _sample_listing_observation():
    pair = OfferTodayIdentityPair("job-1", "enc-1")
    row = ListingRowEvidence(
        job_id="job-1",
        encrypted_job_id="enc-1",
        title="Data Engineer",
        job_function_codes=("118001",),
        title_language="en",
        api_language="zh_HK",
    )
    return ListingPageObservation(
        condition_id="condition-1",
        search_family="it_category",
        category_id=118001,
        keyword="",
        endpoint="browse",
        rcd_type=7,
        page=1,
        attempt=1,
        request_fingerprint="fingerprint",
        classification="success",
        api_code=0,
        reported_total=1,
        has_more=False,
        row_count=1,
        missing_job_id_count=0,
        missing_encrypted_job_id_count=0,
        id_pairs=(pair,),
        rows=(row,),
        identity_issues=(),
        identity_conflicts=(),
        latency_ms=1,
        session_mode="headless",
        retry_reason=None,
        stop_reason=None,
    )


@pytest.mark.asyncio
async def test_production_and_research_sinks_serialize_identical_page_payload():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    observation = _sample_listing_observation()
    crawl_runtime = _FakeCrawlRuntime()
    production_sink = crawl_module.CrawlJobListingObservationSink(
        crawl_runtime=crawl_runtime,
        crawl_job_id="crawl-1",
    )

    class _ResearchRepository:
        def __init__(self):
            self.events = []

        def append_event(self, _db, **kwargs):
            self.events.append(dict(kwargs))

    repository = _ResearchRepository()
    research_sink = OfferTodayResearchObservationService(
        db=object(),
        crawl_job_repository=repository,
        crawl_job_id="research-1",
    )

    await production_sink.record_page_attempt(observation)
    await research_sink.record_page_attempt(observation)

    assert crawl_runtime.events[-1]["payload"] == repository.events[-1]["payload"]


def _success_page(rows, *, has_more):
    return {
        "code": 0,
        "data": {
            "resultList": rows,
            "hasMore": has_more,
            "totalCount": len(rows),
        },
    }


@pytest.mark.asyncio
async def test_saved_response_production_orchestration_uses_authenticated_runner_only():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    browser_runtime = _FakeListingBrowserRuntime(
        responses=[
            _success_page(
                [
                    {
                        "jobId": "job-1",
                        "encryptJobId": "enc-1",
                        "jobName": "Data Engineer",
                    },
                    {
                        "jobId": "job-2",
                        "encryptJobId": "enc-2",
                        "jobName": "Platform Engineer",
                    },
                ],
                has_more=False,
            ),
            _success_page([], has_more=False),
        ]
    )

    async def no_sleep(_seconds):
        return None

    runner = OfferTodayListingRunner(browser_runtime, sleep=no_sleep)
    crawl_runtime = _FakeCrawlRuntime()
    result = await crawl_module._run_listing_phase(
        args=_default_listing_args(
            category_ids=[],
            keywords=["python"],
            max_pages=3,
            crawl_phase="listing",
        ),
        browser_runtime=browser_runtime,
        crawl_runtime=crawl_runtime,
        crawl_job_id="crawl-1",
        listing_runner=runner,
    )

    assert result.ordered_job_ids == ("job-1", "job-2")
    assert result.is_complete is True
    assert browser_runtime.preflight_calls == 1
    assert len(browser_runtime.fetch_calls) == 2
    assert [
        payload["source_job_id"]
        for call in crawl_runtime.stage_calls
        for payload in call["payloads"]
    ] == ["job-1", "job-2"]
    assert not hasattr(crawl_module, "_fetch_listing_json")
    assert "scrapling" not in inspect.getsource(crawl_module._run_listing_phase).lower()


def test_apply_request_payload_defaults_hydrates_launcher_only_invocation():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    args = SimpleNamespace(
        category_ids="",
        keywords="",
        max_pages=100,
        crawl_phase="full",
        source_listing_crawl_job_id="",
        detail_limit=100,
        detail_statuses="pending,manual_action_required",
        resume_strategy="fresh_profile",
        skip_existing=False,
        headed=False,
    )

    crawl_module._apply_request_payload_defaults(
        args,
        {
            "category_ids": [118000],
            "keywords": "python,data",
            "max_pages": 5,
            "crawl_phase": "detail",
            "source_listing_crawl_job_id": "listing-job-1",
            "detail_limit": 25,
            "detail_statuses": ["manual_action_required"],
            "resume_strategy": "reuse_open_browser",
            "skip_existing": True,
            "crawl_mode": "headed",
        },
    )

    assert args.category_ids == "118000"
    assert args.keywords == "python,data"
    assert args.max_pages == 5
    assert args.crawl_phase == "detail"
    assert args.source_listing_crawl_job_id == "listing-job-1"
    assert args.detail_limit == 25
    assert args.detail_statuses == "manual_action_required"
    assert args.resume_strategy == "reuse_open_browser"
    assert args.skip_existing is True
    assert args.headed is True


def test_batch_scoped_it_detail_does_not_exact_filter_root_category():
    search_space = importlib.import_module("app.sources.offertoday.search_space")
    resolver = getattr(search_space, "resolve_offertoday_detail_category_ids", None)

    assert callable(resolver)
    assert resolver(
        [118000],
        source_listing_crawl_job_id="listing-run-1",
    ) == []


def test_unbatched_it_detail_expands_root_to_full_it_tree():
    search_space = importlib.import_module("app.sources.offertoday.search_space")
    resolver = getattr(search_space, "resolve_offertoday_detail_category_ids", None)

    assert callable(resolver)
    assert resolver(
        [118000],
        source_listing_crawl_job_id=None,
    ) == list(search_space.OFFERTODAY_IT_CATEGORY_CODES)
