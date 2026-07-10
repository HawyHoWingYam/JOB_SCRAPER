from __future__ import annotations

import importlib
import inspect
from types import SimpleNamespace

import pytest

from app.sources.offertoday.listing_runner import OfferTodayListingRunner


class _SavedBrowserRuntime:
    def __init__(self, responses):
        self.responses = list(responses)
        self.preflight_calls = 0
        self.fetch_calls = []
        self.entered = 0
        self.exited = 0

    async def __aenter__(self):
        self.entered += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exited += 1

    async def require_healthy_session(self):
        self.preflight_calls += 1
        return SimpleNamespace(healthy=True)

    async def fetch_listing_json(self, payload, *, listing_url=None):
        self.fetch_calls.append((dict(payload), listing_url))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class _ProductionCrawlRuntime:
    def __init__(self):
        self.stage_calls = []
        self.defer_calls = []
        self.events = []
        self.failed = None
        self.manual = None

    def stage_listing_batch(self, **kwargs):
        self.stage_calls.append(dict(kwargs))
        ids = tuple(payload["source_job_id"] for payload in kwargs["payloads"])
        return SimpleNamespace(
            rows_staged=len(ids),
            rows_created=len(ids),
            skipped_existing=0,
            created_source_job_ids=ids,
            preexisting_staged_source_job_ids=(),
            published_source_job_ids=(),
        )

    def defer_listing_identity_conflict(self, **kwargs):
        self.defer_calls.append(dict(kwargs))

    def write_progress_event(self, **kwargs):
        self.events.append(dict(kwargs))

    def mark_failed(self, **kwargs):
        self.failed = dict(kwargs)

    def mark_manual_action_required(self, **kwargs):
        self.manual = dict(kwargs)

    def load_detail_targets(self, **kwargs):
        raise AssertionError("listing-only saved-response helper must not load details")


def _listing_row(job_id: str, encrypted_job_id: str):
    return {
        "jobId": job_id,
        "encryptJobId": encrypted_job_id,
        "jobName": f"Role {job_id}",
    }


def _success_page(rows, *, has_more):
    return {
        "code": 0,
        "data": {
            "resultList": list(rows),
            "hasMore": has_more,
            "total": len(rows),
        },
    }


async def _no_sleep(_seconds):
    return None


async def _run_production_saved_responses(responses):
    production = importlib.import_module(
        "backend.scripts.offertoday_standalone_crawl"
    )
    browser_runtime = _SavedBrowserRuntime(responses)
    runner = OfferTodayListingRunner(browser_runtime, sleep=_no_sleep)
    result = await production._run_listing_phase(
        args=SimpleNamespace(
            category_ids=[],
            keywords=["python"],
            max_pages=3,
            crawl_phase="listing",
            crawl_job_id="crawl-1",
            source_listing_crawl_job_id="",
            detail_limit=100,
            detail_statuses="pending,failed,manual_action_required",
            resume_strategy="fresh_profile",
            skip_existing=False,
            headed=False,
        ),
        browser_runtime=browser_runtime,
        crawl_runtime=_ProductionCrawlRuntime(),
        crawl_job_id="crawl-1",
        listing_runner=runner,
    )
    return result, browser_runtime


async def _run_audit_saved_responses(responses, *, target=5000):
    audit = importlib.import_module("backend.scripts.offertoday_coverage_audit")
    browser_runtime = _SavedBrowserRuntime(responses)
    runner = OfferTodayListingRunner(browser_runtime, sleep=_no_sleep)
    result = await audit.run_offertoday_coverage_audit(
        category_ids=[],
        keywords="python",
        max_pages_per_query=3,
        target_unique_job_ids=target,
        browser_runtime=browser_runtime,
        listing_runner=runner,
    )
    return result, browser_runtime


@pytest.mark.asyncio
async def test_audit_and_production_return_same_ids_and_completion_from_saved_responses():
    responses = [
        _success_page(
            [_listing_row("j-1", "enc-1"), _listing_row("j-2", "enc-2")],
            has_more=False,
        ),
        _success_page([], has_more=False),
    ]

    production, production_browser = await _run_production_saved_responses(
        list(responses)
    )
    audit, audit_browser = await _run_audit_saved_responses(list(responses))

    assert production.ordered_job_ids == audit.ordered_job_ids == ("j-1", "j-2")
    assert production.is_complete is audit.is_complete is True
    assert production_browser.preflight_calls == audit_browser.preflight_calls == 1


@pytest.mark.asyncio
async def test_audit_and_production_both_reject_three_attempt_page_gap():
    responses = [TimeoutError("a"), TimeoutError("b"), TimeoutError("c")]

    production, _ = await _run_production_saved_responses(list(responses))
    audit, _ = await _run_audit_saved_responses(list(responses))

    assert production.stop_reason == audit.stop_reason == "unresolved_gap"
    assert production.is_complete is audit.is_complete is False


@pytest.mark.asyncio
async def test_audit_report_summarizes_retry_attempts_as_terminal_logical_pages():
    audit_module = importlib.import_module("backend.scripts.offertoday_coverage_audit")
    result, _ = await _run_audit_saved_responses(
        [
            TimeoutError("retry page 1"),
            _success_page([_listing_row("j-1", "enc-1")], has_more=False),
            _success_page([], has_more=False),
        ]
    )

    observations = result.listing_result.observations
    assert [observation.classification for observation in observations] == [
        "transient_transport",
        "success",
        "success",
    ]
    assert (observations[0].condition_id, observations[0].page) == (
        observations[1].condition_id,
        observations[1].page,
    )
    assert observations[0].attempt == 1
    assert observations[1].attempt == 2

    assert result.processed_tasks == 2
    assert result.global_sample_unique_job_ids == 1
    assert result.global_reported_total == 1
    family_stats = next(iter(result.families.values()))
    assert family_stats.pages_fetched == 2
    assert family_stats.listing_rows == 1
    assert family_stats.sample_unique_job_ids == 1
    assert family_stats.duplicate_job_ids == 0
    assert family_stats.reported_total == 1
    assert family_stats.failed_pages == 0

    report = audit_module.render_coverage_audit_report(result)
    assert "Processed tasks: 2" in report
    assert (
        f"{family_stats.search_family:<20} {2:>5} {1:>6} "
        f"{1:>7} {1:>7} {0:>7} {0:>6}"
    ) in report


@pytest.mark.asyncio
async def test_audit_and_production_report_same_shared_encrypted_id_conflict():
    responses = [
        _success_page(
            [_listing_row("j-1", "enc-shared"), _listing_row("j-2", "enc-shared")],
            has_more=True,
        )
    ]

    production, _ = await _run_production_saved_responses(list(responses))
    audit, _ = await _run_audit_saved_responses(list(responses))

    assert production.identity_conflicts == audit.identity_conflicts
    assert production.identity_conflicts[0].job_ids == ("j-1", "j-2")
    assert production.is_complete is audit.is_complete is False


@pytest.mark.asyncio
async def test_target_threshold_is_diagnostic_only_and_never_caps_runner():
    audit_module = importlib.import_module("backend.scripts.offertoday_coverage_audit")
    result, browser_runtime = await _run_audit_saved_responses(
        [
            _success_page([_listing_row("j-1", "enc-1")], has_more=False),
            _success_page([], has_more=False),
        ],
        target=1,
    )

    assert result.ordered_job_ids == ("j-1",)
    assert result.stop_reason == "natural_exhaustion"
    assert result.is_complete is True
    assert len(browser_runtime.fetch_calls) == 2
    report = audit_module.render_coverage_audit_report(result)
    assert "Threshold reached: yes" in report
    assert "PASS" not in report


@pytest.mark.asyncio
@pytest.mark.parametrize(("is_complete", "exit_code"), [(False, 3), (True, 0)])
async def test_main_exit_code_depends_on_runner_completion(
    monkeypatch,
    capsys,
    is_complete,
    exit_code,
):
    audit_module = importlib.import_module("backend.scripts.offertoday_coverage_audit")

    async def fake_run(**_kwargs):
        return SimpleNamespace(is_complete=is_complete)

    monkeypatch.setattr(audit_module, "run_offertoday_coverage_audit", fake_run)
    monkeypatch.setattr(
        audit_module,
        "render_coverage_audit_report",
        lambda _result: "report",
    )

    actual = await audit_module.main(
        ["--keywords", "python", "--target-unique-job-ids", "1"]
    )

    assert actual == exit_code
    assert capsys.readouterr().out.strip() == "report"


@pytest.mark.asyncio
async def test_default_live_audit_uses_headless_browser_runtime_and_preflights(
    monkeypatch,
):
    audit_module = importlib.import_module("backend.scripts.offertoday_coverage_audit")
    created_kwargs = []
    runtime = _SavedBrowserRuntime(
        [
            _success_page([_listing_row("j-1", "enc-1")], has_more=False),
            _success_page([], has_more=False),
        ]
    )

    def fake_browser_runtime(**kwargs):
        created_kwargs.append(dict(kwargs))
        return runtime

    monkeypatch.setattr(
        audit_module,
        "OfferTodayBrowserRuntime",
        fake_browser_runtime,
    )
    runner = OfferTodayListingRunner(runtime, sleep=_no_sleep)

    result = await audit_module.run_offertoday_coverage_audit(
        category_ids=[],
        keywords="python",
        max_pages_per_query=3,
        target_unique_job_ids=1,
        listing_runner=runner,
    )

    assert result.is_complete is True
    assert created_kwargs == [{"headed": False}]
    assert runtime.entered == runtime.exited == 1
    assert runtime.preflight_calls == 1


def test_audit_source_has_no_anonymous_playwright_or_direct_listing_loop():
    audit_module = importlib.import_module("backend.scripts.offertoday_coverage_audit")
    source = inspect.getsource(audit_module)

    assert "async_playwright" not in source
    assert "PlaywrightPageTransport" not in source
    assert "build_offertoday_listing_queries" not in source
    assert "fetch_listing(" not in source
    assert "fetch_listing_json(" not in source


@pytest.mark.asyncio
async def test_report_deprecates_live_audit_in_favor_of_future_research_census():
    audit_module = importlib.import_module("backend.scripts.offertoday_coverage_audit")
    result, _ = await _run_audit_saved_responses(
        [
            _success_page([], has_more=False),
            _success_page([], has_more=False),
        ]
    )

    report = audit_module.render_coverage_audit_report(result)

    assert "Deprecated for future live research" in report
    assert "offertoday_research.py" in report
    assert "Plan 2 census commands" in report
