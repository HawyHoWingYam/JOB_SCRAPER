from __future__ import annotations

import importlib
import inspect
import logging
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.sources.offertoday.listing_runner import (
    ListingIdentityConflict,
    ListingIdentityIssue,
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
    is_partial=False,
    capped_condition_ids=(),
    supplemental_rows_observed=0,
    supplemental_job_ids=(),
    supplemental_identity_issue_count=0,
):
    return SimpleNamespace(
        stop_reason=stop_reason,
        is_complete=is_complete,
        is_partial=is_partial,
        is_partial_success=is_partial,
        can_proceed_to_detail=is_complete or is_partial,
        capped_condition_ids=tuple(capped_condition_ids),
        supplemental_rows_observed=supplemental_rows_observed,
        supplemental_job_ids=tuple(supplemental_job_ids),
        supplemental_identity_issue_count=supplemental_identity_issue_count,
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

    async def fetch_detail_json(self, *, job_id, encrypted_job_id):
        raise AssertionError("The injected fake detail pipeline owns this fetch")


class _FakeCrawlRuntime:
    def __init__(self, *, detail_load_result=None, trace=None, metrics=None):
        self.stage_calls = []
        self.defer_calls = []
        self.events = []
        self.load_detail_targets_calls = []
        self.manual_action_payload = None
        self.failed_payload = None
        self.completed_calls = []
        self.detail_load_result = detail_load_result
        self.trace = trace
        self.metrics = dict(metrics or {})
        self.metric_merges = []

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
            complete_existing_source_job_ids=(),
            terminal_unavailable_source_job_ids=(),
            new_source_job_ids=source_job_ids,
            repair_source_job_ids=(),
            duplicate_source_job_ids=(),
        )

    def defer_listing_identity_conflict(self, **kwargs):
        self.defer_calls.append(dict(kwargs))
        return len(kwargs["source_job_ids"])

    def write_progress_event(self, **kwargs):
        self.events.append(dict(kwargs))
        if self.trace is not None:
            self.trace.append(kwargs["event_type"])

    def load_detail_targets(self, **kwargs):
        self.load_detail_targets_calls.append(dict(kwargs))
        if self.trace is not None:
            self.trace.append("load_detail_targets")
        if self.detail_load_result is not None:
            return self.detail_load_result
        source_job_ids = list(kwargs["request_payload"].get("source_job_ids") or [])
        if not source_job_ids and kwargs["request_payload"].get(
            "source_listing_crawl_job_id"
        ):
            source_job_ids = list(
                dict.fromkeys(
                    payload["source_job_id"]
                    for call in self.stage_calls
                    for payload in call["payloads"]
                )
            )
        return SimpleNamespace(
            targets=[{"source_job_id": source_job_id} for source_job_id in source_job_ids],
            target_rows=len(source_job_ids),
            selected_rows=len(source_job_ids),
            skipped_existing_rows=0,
            distinct_selected_ids=len(source_job_ids),
            reconciled_rows=0,
            duplicate_rows=0,
            fetch_cohort_source_job_ids=tuple(source_job_ids),
            fetch_cohort_hash="empty-test-hash",
            reconciled_source_job_ids=(),
            identity_conflict_ids=(),
            identity_conflict_evidence=(),
        )

    def mark_manual_action_required(self, **kwargs):
        self.manual_action_payload = dict(kwargs["payload"])
        if self.trace is not None:
            self.trace.append("manual_action_required")

    def mark_failed(self, **kwargs):
        self.failed_payload = dict(kwargs["payload"])

    def mark_completed(self, **kwargs):
        self.completed_calls.append(dict(kwargs))
        self.metrics.update(dict(kwargs.get("metrics") or {}))
        if self.trace is not None:
            self.trace.append("completed")

    def merge_metrics(self, **kwargs):
        patch = dict(kwargs["metrics_patch"])
        self.metrics.update(patch)
        self.metric_merges.append(
            {
                "patch": patch,
                "snapshot": dict(self.metrics),
            }
        )
        if self.trace is not None:
            self.trace.append("merge_metrics")


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
    assert run_kwargs["stop_policy"].unique_job_cap is None
    assert run_kwargs["stop_policy"].require_empty_confirmation is True
    assert run_kwargs["stop_policy"].page_cap_behavior == "retain-and-continue"
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
    assert all(condition.endpoint == "search" for condition in run_kwargs["conditions"])
    assert all(condition.rcd_type is None for condition in run_kwargs["conditions"])
    assert run_kwargs["request_policy"].requested_page_size == 10
    assert run_kwargs["request_policy"].requires_cursor is True
    assert run_kwargs["request_policy"].endpoint_contract_id == (
        "recommend-search-list-v1"
    )
    assert run_kwargs["terminal_policy"] == "result-transition-confirmation-v1"


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
        "listing_partial": False,
        "capped_condition_ids": [],
    }
    assert crawl_runtime.load_detail_targets_calls == []
    assert crawl_runtime.completed_calls == []


@pytest.mark.asyncio
async def test_complete_full_listing_freezes_current_crawl_targets():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    crawl_runtime = _FakeCrawlRuntime()
    runner = SimpleNamespace(
        run=AsyncMock(return_value=_listing_result(accepted_job_ids=("seen-1",)))
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
    assert "source_job_ids" not in detail_call["request_payload"]
    assert detail_call["request_payload"]["source_listing_crawl_job_id"] == (
        "crawl-1"
    )
    assert detail_call["request_payload"]["detail_limit"] is None
    assert result.detail_targets == []


@pytest.mark.asyncio
async def test_partial_listing_completes_event_before_detail_target_freeze():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    trace: list[str] = []
    condition = SimpleNamespace(
        condition=SimpleNamespace(condition_id="capped-condition"),
        pages_observed=100,
        is_complete=False,
        is_partial=True,
    )
    runner = SimpleNamespace(
        run=AsyncMock(
            return_value=_listing_result(
                stop_reason="page_cap",
                is_complete=False,
                is_partial=True,
                accepted_job_ids=("new-1",),
                condition_outcomes=(condition,),
                capped_condition_ids=("capped-condition",),
            )
        )
    )
    crawl_runtime = _FakeCrawlRuntime(trace=trace)

    result = await crawl_module._run_listing_phase(
        args=_default_listing_args(crawl_phase="full"),
        browser_runtime=_FakeListingBrowserRuntime(trace=trace),
        crawl_runtime=crawl_runtime,
        crawl_job_id="crawl-1",
        listing_runner=runner,
    )

    assert result.is_partial_success is True
    assert crawl_runtime.failed_payload is None
    assert trace.index("listing_completed") < trace.index("load_detail_targets")
    assert crawl_runtime.metrics["listing_partial"] is True
    assert crawl_runtime.metrics["listing_capped_condition_count"] == 1
    assert crawl_runtime.load_detail_targets_calls[0]["request_payload"][
        "source_listing_crawl_job_id"
    ] == "crawl-1"


@pytest.mark.asyncio
async def test_partial_full_crawl_finishes_completed_after_detail_phase():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    trace: list[str] = []
    condition = SimpleNamespace(
        condition=SimpleNamespace(condition_id="capped-condition"),
        pages_observed=100,
        is_complete=False,
        is_partial=True,
    )
    runner = SimpleNamespace(
        run=AsyncMock(
            return_value=_listing_result(
                stop_reason="page_cap",
                is_complete=False,
                is_partial=True,
                accepted_job_ids=("new-1",),
                condition_outcomes=(condition,),
                capped_condition_ids=("capped-condition",),
            )
        )
    )
    crawl_runtime = _FakeCrawlRuntime(
        detail_load_result=_detail_load_result(
            [_detail_runtime_target("new-1")],
            fetch_cohort_hash="partial-hash",
        ),
        trace=trace,
    )

    listing_execution = await crawl_module._run_listing_phase(
        args=_default_listing_args(crawl_phase="full"),
        browser_runtime=_FakeListingBrowserRuntime(trace=trace),
        crawl_runtime=crawl_runtime,
        crawl_job_id="crawl-1",
        listing_runner=runner,
    )
    listing_metrics = crawl_module._listing_metrics(
        listing_execution.listing_result,
        listing_execution.staging_sink,
    )
    detail_result = await crawl_module._run_detail_phase(
        args=_default_listing_args(crawl_phase="full"),
        browser_runtime=_FakeListingBrowserRuntime(trace=trace),
        crawl_runtime=crawl_runtime,
        crawl_job_id="crawl-1",
        detail_load_result=listing_execution.detail_load_result,
        pipeline=_FakeDetailPipeline(
            [
                _detail_process_result(
                    "success",
                    job_action="created",
                    company_action="created",
                )
            ],
            trace=trace,
        ),
        completion_metrics=listing_metrics,
    )

    assert detail_result.stop_batch is False
    assert crawl_runtime.failed_payload is None
    assert len(crawl_runtime.completed_calls) == 1
    completed_metrics = crawl_runtime.completed_calls[0]["metrics"]
    assert completed_metrics["listing_partial"] is True
    assert completed_metrics["listing_capped_condition_count"] == 1
    assert completed_metrics["detail_success"] == 1
    assert completed_metrics["detail_failure"] == 0
    assert trace.index("listing_completed") < trace.index("load_detail_targets")
    assert trace.index("load_detail_targets") < trace.index(
        "crawl.detail_cohort_frozen"
    )
    assert trace.index("crawl.detail_cohort_frozen") < trace.index("completed")


def test_listing_metrics_report_exact_partial_and_incremental_cohorts():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    sink = crawl_module.OfferTodayCrawlStagingSink(
        crawl_runtime=_FakeCrawlRuntime(),
        crawl_job_id="crawl-1",
    )
    sink.complete_existing_source_job_ids.extend(["complete-1", "complete-1"])
    sink.terminal_unavailable_source_job_ids.append("terminal-1")
    sink.new_source_job_ids.extend(["new-1", "new-1"])
    sink.repair_source_job_ids.append("repair-1")
    outcomes = (
        SimpleNamespace(is_complete=True, is_partial=False),
        SimpleNamespace(is_complete=False, is_partial=True),
    )
    result = _listing_result(
        stop_reason="page_cap",
        is_complete=False,
        is_partial=True,
        accepted_job_ids=("new-1", "repair-1", "overlap-1"),
        condition_outcomes=outcomes,
        capped_condition_ids=("capped-1",),
        supplemental_rows_observed=4,
        supplemental_job_ids=("supp-1", "overlap-1"),
        supplemental_identity_issue_count=2,
    )

    assert crawl_module._listing_metrics(result, sink) == {
        "listing_partial": True,
        "listing_condition_count": 2,
        "listing_natural_condition_count": 1,
        "listing_capped_condition_count": 1,
        "listing_capped_condition_ids": ["capped-1"],
        "distinct_it_result_ids": 3,
        "supplemental_rows_observed": 4,
        "distinct_supplemental_ids": 2,
        "supplemental_result_overlap_count": 1,
        "supplemental_identity_issue_count": 2,
        "complete_existing_skipped": 1,
        "terminal_unavailable_skipped": 1,
        "new_detail_targets": 1,
        "repair_detail_targets": 1,
        "detail_success": 0,
        "detail_failure": 0,
    }


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
    assert payload["listing_payload"]["encrypted_job_id_source"] == "encryptJobId"
    assert payload["listing_payload"]["raw_data"] == raw_data
    assert payload["search_family"] == "it_category"
    assert payload["keyword"] == "python"


def test_listing_staging_payload_accepts_jobid_fallback_without_raw_fabrication():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    parsed = {
        "job_id": "j-fallback",
        "encrypted_job_id": "j-fallback",
        "encrypted_job_id_source": "jobId_fallback",
        "title": "Fallback fixture",
        "raw_data": {"jobId": "j-fallback"},
    }

    payload = crawl_module._build_listing_staging_payload(
        parsed,
        condition=SimpleNamespace(
            category_id=118000,
            search_family="it_category",
            keyword="",
        ),
        page=1,
        rank=1,
    )

    assert payload["source_job_id"] == "j-fallback"
    assert payload["source_url"].endswith("/j-fallback")
    assert payload["listing_payload"]["encrypted_job_id_source"] == (
        "jobId_fallback"
    )
    assert payload["listing_payload"]["raw_data"] == {"jobId": "j-fallback"}


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
    pair = OfferTodayIdentityPair("job-1", "enc-1", "encryptJobId")
    row = ListingRowEvidence(
        job_id="job-1",
        encrypted_job_id="enc-1",
        encrypted_job_id_source="encryptJobId",
        observed_encrypted_job_id="enc-1",
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
        job_id_fallback_count=0,
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
async def test_production_observation_sink_keeps_supplemental_identity_evidence():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    observation = replace(
        _sample_listing_observation(),
        supplemental_identity_issues=(
            ListingIdentityIssue(
                job_id="supplemental-1",
                encrypted_job_id=None,
                reason="missing_encrypted_job_id",
            ),
        ),
        supplemental_identity_conflicts=(
            ListingIdentityConflict(
                job_ids=("supplemental-2",),
                encrypted_job_ids=("enc-a", "enc-b"),
                reason="supplemental_job_id_to_multiple_encrypted_ids",
            ),
        ),
    )
    crawl_runtime = _FakeCrawlRuntime()
    sink = crawl_module.CrawlJobListingObservationSink(
        crawl_runtime=crawl_runtime,
        crawl_job_id="crawl-1",
    )

    await sink.record_page_attempt(observation)

    payload = crawl_runtime.events[-1]["payload"]
    assert payload["supplemental_identity_issues"] == [
        {
            "job_id": "supplemental-1",
            "encrypted_job_id": None,
            "reason": "missing_encrypted_job_id",
        }
    ]
    assert payload["supplemental_identity_conflicts"] == [
        {
            "job_ids": ["supplemental-2"],
            "encrypted_job_ids": ["enc-a", "enc-b"],
            "reason": "supplemental_job_id_to_multiple_encrypted_ids",
        }
    ]


def _success_page(rows, *, has_more, supple_page=0):
    return {
        "code": 0,
        "data": {
            "pageSize": 10,
            "sessionId": "production-session",
            "supplePage": supple_page,
            "suppleAmount": 0,
            "suppleType": 0,
            "suppleRcdList": [],
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
                _success_page([], has_more=False, supple_page=1),
                _success_page([], has_more=False, supple_page=2),
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


def test_resolve_detail_scope_defaults_to_category_backlog_for_detail_only_runs():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")

    source_listing_crawl_job_id, detail_scope = crawl_module._resolve_detail_scope(
        SimpleNamespace(
            crawl_job_id="detail-job-1",
            source_listing_crawl_job_id="",
        ),
        listing_phase_completed=False,
    )

    assert source_listing_crawl_job_id is None
    assert detail_scope == "category_backlog"


def test_resolve_detail_scope_uses_current_listing_batch_after_listing_phase():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")

    source_listing_crawl_job_id, detail_scope = crawl_module._resolve_detail_scope(
        SimpleNamespace(
            crawl_job_id="listing-job-1",
            source_listing_crawl_job_id="",
        ),
        listing_phase_completed=True,
    )

    assert source_listing_crawl_job_id == "listing-job-1"
    assert detail_scope == "current_run_listing_batch"


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


def _detail_runtime_target(
    source_job_id: str,
    *,
    listing_id: str | None = None,
    duplicate_listing_ids=(),
):
    encrypted_job_id = f"enc-{source_job_id}"
    return {
        "listing_id": listing_id or f"listing-{source_job_id}",
        "duplicate_listing_ids": tuple(duplicate_listing_ids),
        "source_job_id": source_job_id,
        "listing_payload": {
            "job_id": source_job_id,
            "encrypted_job_id": encrypted_job_id,
            "raw_data": {
                "jobId": source_job_id,
                "encryptJobId": encrypted_job_id,
            },
        },
    }


def _detail_load_result(
    targets=(),
    *,
    fetch_cohort_hash="cohort-hash",
    reconciled_source_job_ids=(),
    identity_conflict_ids=(),
    identity_conflict_evidence=(),
    selected_rows=None,
    duplicate_rows=0,
):
    targets = list(targets)
    fetch_ids = tuple(target["source_job_id"] for target in targets)
    selected_rows = (
        len(targets) + len(reconciled_source_job_ids) + duplicate_rows
        if selected_rows is None
        else selected_rows
    )
    return SimpleNamespace(
        targets=targets,
        target_rows=len(targets),
        selected_rows=selected_rows,
        skipped_existing_rows=len(reconciled_source_job_ids),
        distinct_selected_ids=len(fetch_ids) + len(reconciled_source_job_ids),
        reconciled_rows=len(reconciled_source_job_ids),
        duplicate_rows=duplicate_rows,
        fetch_cohort_source_job_ids=fetch_ids,
        fetch_cohort_hash=fetch_cohort_hash,
        reconciled_source_job_ids=tuple(reconciled_source_job_ids),
        identity_conflict_ids=tuple(identity_conflict_ids),
        identity_conflict_evidence=tuple(identity_conflict_evidence),
    )


class _FakeDetailPipeline:
    def __init__(self, outcomes=(), *, trace=None):
        self.outcomes = list(outcomes)
        self.trace = trace
        self.targets = []
        self.fetchers = []

    async def process_target(
        self,
        *,
        target,
        detail_crawl_job_id,
        fetch_detail,
    ):
        self.targets.append(target)
        self.fetchers.append(fetch_detail)
        if self.trace is not None:
            self.trace.append(f"fetch:{target.identity.job_id}")
        return self.outcomes.pop(0)


def _detail_process_result(
    kind,
    *,
    job_action=None,
    company_action=None,
    stop_batch=False,
):
    pipeline_module = importlib.import_module(
        "app.services.offertoday_detail_pipeline"
    )
    response_module = importlib.import_module(
        "app.sources.offertoday.response_policy"
    )
    return pipeline_module.OfferTodayDetailProcessResult(
        source_job_id="unused-by-fake",
        outcome=response_module.OfferTodayResponseKind(kind),
        job_action=job_action,
        company_action=company_action,
        stop_batch=stop_batch,
    )


@pytest.mark.asyncio
async def test_detail_only_preflights_then_freezes_cohort_before_first_fetch():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    trace = []
    load_result = _detail_load_result(
        [_detail_runtime_target("job-1")],
        fetch_cohort_hash="exact-hash",
        reconciled_source_job_ids=("reconciled-1",),
    )
    crawl_runtime = _FakeCrawlRuntime(
        detail_load_result=load_result,
        trace=trace,
    )
    pipeline = _FakeDetailPipeline(
        [
            _detail_process_result(
                "success",
                job_action="created",
                company_action="created",
            )
        ],
        trace=trace,
    )

    result = await crawl_module._run_detail_phase(
        args=_default_listing_args(crawl_phase="detail", category_ids=[118000]),
        browser_runtime=_FakeListingBrowserRuntime(trace=trace),
        crawl_runtime=crawl_runtime,
        crawl_job_id="detail-run",
        pipeline=pipeline,
    )

    assert trace[:4] == [
        "preflight",
        "load_detail_targets",
        "crawl.detail_cohort_frozen",
        "fetch:job-1",
    ]
    assert len(crawl_runtime.load_detail_targets_calls) == 1
    request_payload = crawl_runtime.load_detail_targets_calls[0]["request_payload"]
    assert request_payload["category_ids"] == [118000]
    assert "source_listing_crawl_job_id" not in request_payload
    cohort = next(
        event["payload"]
        for event in crawl_runtime.events
        if event["event_type"] == "crawl.detail_cohort_frozen"
    )
    assert cohort == {
        "fetch_cohort_source_job_ids": ["job-1"],
        "fetch_cohort_hash": "exact-hash",
        "reconciled_source_job_ids": ["reconciled-1"],
        "identity_conflict_ids": [],
        "identity_conflict_evidence": [],
        "fetch_cohort_distinct": 1,
    }
    assert result.stop_batch is False
    assert len(crawl_runtime.completed_calls) == 1


@pytest.mark.asyncio
async def test_load_time_identity_conflict_enters_identity_audit_without_fetch_or_completion():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    trace = []
    evidence = {
        "source_job_id": "conflict-1",
        "encrypted_job_ids": ["enc-a", "enc-b"],
        "reason": "job_id_to_multiple_encrypted_ids",
    }
    load_result = _detail_load_result(
        [],
        fetch_cohort_hash="conflict-hash",
        identity_conflict_ids=("conflict-1",),
        identity_conflict_evidence=(evidence,),
        selected_rows=2,
        duplicate_rows=1,
    )
    crawl_runtime = _FakeCrawlRuntime(
        detail_load_result=load_result,
        trace=trace,
        metrics={
            "detail_selected_rows": 2,
            "detail_duplicate_rows": 1,
        },
    )
    pipeline = _FakeDetailPipeline(trace=trace)

    result = await crawl_module._run_detail_phase(
        args=_default_listing_args(crawl_phase="detail"),
        browser_runtime=_FakeListingBrowserRuntime(trace=trace),
        crawl_runtime=crawl_runtime,
        crawl_job_id="detail-run",
        pipeline=pipeline,
    )

    assert trace == [
        "preflight",
        "load_detail_targets",
        "crawl.detail_cohort_frozen",
        "merge_metrics",
        "manual_action_required",
    ]
    assert pipeline.targets == []
    assert crawl_runtime.completed_calls == []
    assert crawl_runtime.manual_action_payload["action_type"] == "identity_audit"
    assert crawl_runtime.manual_action_payload["classification"] == "identity_conflict"
    assert crawl_runtime.manual_action_payload["evidence"] == {
        "identity_conflict_ids": ["conflict-1"],
        "identity_conflict_evidence": [evidence],
    }
    assert result.stop_batch is True
    paused_metrics = crawl_runtime.metric_merges[-1]["snapshot"]
    assert paused_metrics["detail_selected_rows"] == 2
    assert paused_metrics["detail_duplicate_rows"] == 1
    assert paused_metrics["detail_processed_targets"] == 0
    assert paused_metrics["detail_outcomes"] == {}
    assert paused_metrics["jobs_created"] == 0
    assert paused_metrics["jobs_updated"] == 0
    assert paused_metrics["jobs_reconciled"] == 0
    assert paused_metrics["jobs_saved"] == 0


@pytest.mark.asyncio
async def test_stopped_detail_result_leaves_later_target_unprocessed_and_never_completes_run():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    trace = []
    load_result = _detail_load_result(
        [_detail_runtime_target("blocked"), _detail_runtime_target("later")]
    )
    crawl_runtime = _FakeCrawlRuntime(trace=trace)
    pipeline = _FakeDetailPipeline(
        [_detail_process_result("ip_blocked", stop_batch=True)],
        trace=trace,
    )

    result = await crawl_module._run_detail_phase(
        args=_default_listing_args(crawl_phase="full"),
        browser_runtime=_FakeListingBrowserRuntime(trace=trace),
        crawl_runtime=crawl_runtime,
        crawl_job_id="detail-run",
        detail_load_result=load_result,
        pipeline=pipeline,
    )

    assert [target.identity.job_id for target in pipeline.targets] == ["blocked"]
    assert "fetch:later" not in trace
    assert crawl_runtime.completed_calls == []
    assert crawl_runtime.manual_action_payload["classification"] == "ip_blocked"
    assert crawl_runtime.manual_action_payload["action_type"] == "session_recovery"
    assert result.stop_batch is True


@pytest.mark.asyncio
async def test_detail_phase_passes_duplicate_listing_ids_and_preserves_task7_metrics_after_ten_targets():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    targets = [
        _detail_runtime_target(
            f"job-{index}",
            duplicate_listing_ids=(f"duplicate-{index}",) if index == 0 else (),
        )
        for index in range(11)
    ]
    load_result = _detail_load_result(
        targets,
        reconciled_source_job_ids=("reconciled-1", "reconciled-2"),
        selected_rows=14,
        duplicate_rows=1,
    )
    task7_metrics = {
        "detail_selected_rows": 14,
        "detail_reconciled_rows": 2,
        "detail_duplicate_rows": 1,
        "detail_distinct_selected_ids": 13,
    }
    crawl_runtime = _FakeCrawlRuntime(metrics=task7_metrics)
    outcomes = [
        _detail_process_result(
            "success",
            job_action="created" if index < 4 else "updated",
            company_action="created" if index == 0 else "updated",
        )
        for index in range(11)
    ]
    pipeline = _FakeDetailPipeline(outcomes)

    result = await crawl_module._run_detail_phase(
        args=_default_listing_args(crawl_phase="full"),
        browser_runtime=_FakeListingBrowserRuntime(),
        crawl_runtime=crawl_runtime,
        crawl_job_id="detail-run",
        detail_load_result=load_result,
        pipeline=pipeline,
    )

    assert pipeline.targets[0].listing_ids == (
        "listing-job-0",
        "duplicate-0",
    )
    assert any(
        event["event_type"] == "crawl.detail_progress"
        for event in crawl_runtime.events
    )
    for metric_name, value in task7_metrics.items():
        assert crawl_runtime.metrics[metric_name] == value
    assert crawl_runtime.metrics["jobs_created"] == 4
    assert crawl_runtime.metrics["jobs_updated"] == 7
    assert crawl_runtime.metrics["jobs_reconciled"] == 2
    assert crawl_runtime.metrics["terminal_unavailable"] == 0
    assert crawl_runtime.metrics["persist_failure"] == 0
    assert crawl_runtime.metrics["jobs_saved"] == 11
    assert result.jobs_created == 4
    assert result.jobs_updated == 7
    assert result.jobs_reconciled == 2


@pytest.mark.asyncio
async def test_detail_checkpoint_and_later_stop_merge_current_metrics_without_erasing_task7():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    trace = []
    targets = [
        _detail_runtime_target(f"job-{index}")
        for index in range(11)
    ]
    load_result = _detail_load_result(
        targets,
        reconciled_source_job_ids=("reconciled-1", "reconciled-2"),
        selected_rows=14,
        duplicate_rows=1,
    )
    task7_metrics = {
        "detail_selected_rows": 14,
        "detail_reconciled_rows": 2,
        "detail_duplicate_rows": 1,
        "detail_distinct_selected_ids": 13,
    }
    crawl_runtime = _FakeCrawlRuntime(metrics=task7_metrics, trace=trace)
    outcomes = [
        _detail_process_result(
            "success",
            job_action="created" if index < 6 else "updated",
            company_action="created" if index < 2 else "updated",
        )
        for index in range(10)
    ] + [_detail_process_result("ip_blocked", stop_batch=True)]
    pipeline = _FakeDetailPipeline(outcomes, trace=trace)

    result = await crawl_module._run_detail_phase(
        args=_default_listing_args(crawl_phase="full"),
        browser_runtime=_FakeListingBrowserRuntime(),
        crawl_runtime=crawl_runtime,
        crawl_job_id="detail-run",
        detail_load_result=load_result,
        pipeline=pipeline,
    )

    assert result.stop_batch is True
    assert crawl_runtime.completed_calls == []
    assert len(crawl_runtime.metric_merges) == 2
    checkpoint_metrics = crawl_runtime.metric_merges[0]["snapshot"]
    stopped_metrics = crawl_runtime.metric_merges[1]["snapshot"]
    for metric_name, value in task7_metrics.items():
        assert checkpoint_metrics[metric_name] == value
        assert stopped_metrics[metric_name] == value
    assert checkpoint_metrics["jobs_created"] == 6
    assert checkpoint_metrics["jobs_updated"] == 4
    assert checkpoint_metrics["jobs_reconciled"] == 2
    assert checkpoint_metrics["companies_created"] == 2
    assert checkpoint_metrics["companies_updated"] == 8
    assert checkpoint_metrics["terminal_unavailable"] == 0
    assert checkpoint_metrics["persist_failure"] == 0
    assert checkpoint_metrics["jobs_saved"] == 10
    assert checkpoint_metrics["items_emitted"] == 10
    assert checkpoint_metrics["detail_processed_targets"] == 10
    assert checkpoint_metrics["detail_outcomes"] == {"success": 10}
    assert stopped_metrics["detail_processed_targets"] == 11
    assert stopped_metrics["detail_outcomes"] == {
        "success": 10,
        "ip_blocked": 1,
    }
    assert stopped_metrics["jobs_saved"] == 10
    assert trace.index("merge_metrics") < trace.index("crawl.detail_progress")
    assert trace[-2:] == ["merge_metrics", "manual_action_required"]
