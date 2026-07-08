from __future__ import annotations

import importlib
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest


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
