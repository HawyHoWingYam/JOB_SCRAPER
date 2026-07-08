from __future__ import annotations

import importlib
from types import SimpleNamespace
from uuid import uuid4

import logging

import pytest


class _FakeBrowserPageScraper:
    instances: list["_FakeBrowserPageScraper"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = dict(kwargs)
        self.calls: list[dict[str, object]] = []
        type(self).instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def fetch_page_html(self, url: str, *, stage: str, referer: str | None = None) -> str:
        self.calls.append(
            {
                "url": url,
                "stage": stage,
                "referer": referer,
            }
        )
        return f"<html data-stage='{stage}'></html>"


class _FakeCrawlJobRuntime:
    last_instance: "_FakeCrawlJobRuntime | None" = None

    def __init__(self, *args, **kwargs) -> None:
        type(self).last_instance = self
        self.started = False
        self.completed = False
        self.failed = False
        self.events: list[dict[str, object]] = []
        self.staged_batches: list[dict[str, object]] = []
        self.detail_running: list[dict[str, object]] = []
        self.detail_completed: list[dict[str, object]] = []
        self.detail_failed: list[dict[str, object]] = []
        self.manual_action_payload: dict[str, object] | None = None

    def mark_started(self, **kwargs) -> None:
        self.started = True

    def write_progress_event(self, **kwargs) -> None:
        self.events.append(dict(kwargs))

    def stage_listing_batch(self, **kwargs):
        self.staged_batches.append(dict(kwargs))
        payloads = list(kwargs["payloads"])
        return SimpleNamespace(
            rows_staged=len(payloads),
            job_ids_seen=len(payloads),
            skipped_existing=0,
        )

    def load_detail_targets(self, **kwargs):
        return SimpleNamespace(
            target_rows=1,
            selected_rows=1,
            skipped_existing_rows=0,
            targets=[
                {
                    "listing_id": "listing-1",
                    "crawl_job_id": kwargs["detail_crawl_job_id"],
                    "source_site": "ctgoodjobs",
                    "source_job_id": "job-1",
                    "source_url": "https://jobs.ctgoodjobs.hk/job/job-1",
                    "source_classification_id": "ctgoodjobs:021",
                    "source_classification_name": "Information Technology",
                    "listing_payload": {
                        "job_id": "job-1",
                        "url": "https://jobs.ctgoodjobs.hk/job/job-1",
                        "source_classification_id": "ctgoodjobs:021",
                        "source_classification_name": "Information Technology",
                        "source_classification_slug": "information-technology",
                    },
                    "detail_payload": {},
                }
            ],
        )

    def mark_detail_running(self, **kwargs) -> None:
        self.detail_running.append(dict(kwargs))

    def mark_detail_completed(self, **kwargs) -> None:
        self.detail_completed.append(dict(kwargs))

    def mark_detail_failed(self, **kwargs) -> None:
        self.detail_failed.append(dict(kwargs))

    def mark_manual_action_required(self, **kwargs) -> None:
        self.manual_action_payload = dict(kwargs)

    def mark_completed(self, **kwargs) -> None:
        self.completed = True

    def mark_failed(self, **kwargs) -> None:
        self.failed = True


class _FakeSession:
    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


class _FakeCompanyRepository:
    def upsert_company(self, db, company_data, auto_commit=False):
        return SimpleNamespace(id="company-1"), "created"


class _FakeJobRepository:
    def upsert_source_job(self, db, job_data, skip_existing=False, auto_commit=False):
        return SimpleNamespace(id="job-row-1"), "created"


class _FakeIngestWorkerService:
    def _build_company_data(self, canonical_job):
        return {
            "source_site": canonical_job["source_site"],
            "source_company_id": "company-source-1",
            "company_id": "company-source-1",
            "name": canonical_job["company_name"],
        }

    def _build_job_data(self, canonical_job, company_id):
        return {
            "source_site": canonical_job["source_site"],
            "source_job_id": canonical_job["source_job_id"],
            "job_id": canonical_job["source_job_id"],
            "company_id": company_id,
            "title": canonical_job["title"],
            "description": canonical_job["description"],
            "raw_data": canonical_job["raw_data"],
        }


def _fake_categories():
    return [
        SimpleNamespace(
            source_classification_id="ctgoodjobs:021",
            ctgoodjobs_id="021",
            name="Information Technology",
            slug="information-technology",
            url="https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology",
        )
    ]


def _fake_parse_category_page(
    _page_html: str,
    *,
    category_slug: str,
    source_classification_id: str,
    source_classification_name: str,
    page: int,
    url: str,
):
    return {
        "job_ids": ["job-1"],
        "job_urls": ["https://jobs.ctgoodjobs.hk/job/job-1"],
        "source_classification_id": source_classification_id,
        "source_classification_name": source_classification_name,
        "source_classification_slug": category_slug,
        "page": page,
        "url": url,
    }


def _fake_parse_detail_page(
    _page_html: str,
    *,
    source_classification_id: str,
    source_classification_name: str,
    source_classification_slug: str,
    url: str,
):
    return {
        "job_id": "job-1",
        "url": url,
        "title": "Platform Engineer",
        "company_name": "CTGoodJobs",
        "description_html": "<p>Build things</p>",
        "description_text": "Build things",
        "location": "Hong Kong",
        "employment_type": "Full Time",
        "salary_range": "HK$30,000 - HK$40,000",
        "source_classification_id": source_classification_id,
        "source_classification_name": source_classification_name,
        "source_classification_slug": source_classification_slug,
    }


def _fake_merge_ctgoodjobs_job(*, category, list_job, detail_job):
    return {
        "job_id": "ctgoodjobs:job-1",
        "url": detail_job["url"],
        "title": detail_job["title"],
        "company_name": detail_job["company_name"],
        "description_html": detail_job["description_html"],
        "description_text": detail_job["description_text"],
        "location": detail_job["location"],
        "employment_type": detail_job["employment_type"],
        "salary_range": detail_job["salary_range"],
        "source_classification_id": category["source_classification_id"],
        "source_classification_name": category["name"],
        "source_classification_slug": category["slug"],
    }


class _FakeCanonicalJob:
    def __init__(self, payload) -> None:
        self._payload = dict(payload)

    def to_dict(self):
        return {
            "source_site": "ctgoodjobs",
            "source_job_id": "job-1",
            "source_url": self._payload["url"],
            "title": self._payload["title"],
            "description": self._payload["description_html"],
            "company_name": self._payload["company_name"],
            "location": self._payload["location"],
            "salary_range": self._payload["salary_range"],
            "employment_type": self._payload["employment_type"],
            "source_classification_id": self._payload["source_classification_id"],
            "source_classification_name": self._payload["source_classification_name"],
            "raw_data": dict(self._payload),
        }


def _load_module():
    return importlib.import_module("backend.scripts.ctgoodjobs_standalone_crawl")


def _patch_happy_path_dependencies(monkeypatch, crawl_module) -> None:
    _FakeBrowserPageScraper.instances.clear()
    _FakeCrawlJobRuntime.last_instance = None
    monkeypatch.setattr(crawl_module, "CTGoodJobsBrowserPageScraper", _FakeBrowserPageScraper)
    monkeypatch.setattr(crawl_module, "CrawlJobRuntime", _FakeCrawlJobRuntime)
    monkeypatch.setattr(crawl_module, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(crawl_module, "CompanyRepository", _FakeCompanyRepository)
    monkeypatch.setattr(crawl_module, "JobRepository", _FakeJobRepository)
    monkeypatch.setattr(crawl_module, "IngestWorkerService", _FakeIngestWorkerService)
    monkeypatch.setattr(crawl_module, "get_static_ctgoodjobs_categories", _fake_categories)
    monkeypatch.setattr(crawl_module, "parse_category_page", _fake_parse_category_page)
    monkeypatch.setattr(crawl_module, "parse_detail_page", _fake_parse_detail_page)
    monkeypatch.setattr(crawl_module, "merge_ctgoodjobs_job", _fake_merge_ctgoodjobs_job)
    monkeypatch.setattr(crawl_module, "build_ctgoodjobs_canonical_job", _FakeCanonicalJob)
    monkeypatch.setattr(crawl_module, "_load_request_payload", lambda crawl_job_id: ({}, "ctgoodjobs"))


def test_ctgoodjobs_apply_request_payload_defaults_preserves_requested_phase():
    crawl_module = _load_module()
    args = SimpleNamespace(
        category_ids=[],
        max_pages=1,
        detail_limit=100,
        crawl_mode="headed",
        crawl_phase="full",
        source_listing_crawl_job_id="",
        detail_statuses=["pending"],
        skip_existing=False,
        is_resume=False,
        resume_strategy="fresh_profile",
    )

    crawl_module._apply_request_payload_defaults(
        args,
        {
            "crawl_phase": "detail",
            "crawl_mode": "headless",
            "category_ids": ["ctgoodjobs:021"],
            "max_pages": 2,
            "detail_limit": 50,
            "detail_statuses": ["manual_action_required"],
            "source_listing_crawl_job_id": "listing-job-1",
            "skip_existing": True,
            "is_resume": True,
            "resume_strategy": "reuse_open_browser",
        },
    )

    assert args.crawl_phase == "detail"
    assert args.crawl_mode == "headless"
    assert args.category_ids == ["ctgoodjobs:021"]
    assert args.max_pages == 2
    assert args.detail_limit == 50
    assert args.detail_statuses == ["manual_action_required"]
    assert args.source_listing_crawl_job_id == "listing-job-1"
    assert args.skip_existing is True
    assert args.is_resume is True
    assert args.resume_strategy == "reuse_open_browser"


@pytest.mark.asyncio
async def test_ctgoodjobs_executor_uses_browser_page_scraper_for_listing_and_detail(monkeypatch, caplog):
    crawl_module = _load_module()
    _patch_happy_path_dependencies(monkeypatch, crawl_module)

    with caplog.at_level(logging.INFO, logger="ctgoodjobs-crawl"):
        exit_code = await crawl_module.main(
            [
                "--crawl-job-id",
                str(uuid4()),
                "--category-ids",
                "ctgoodjobs:021",
                "--max-pages",
                "1",
            ]
        )

    runtime = _FakeCrawlJobRuntime.last_instance
    assert exit_code == 0
    assert runtime is not None
    assert runtime.completed is True
    assert len(_FakeBrowserPageScraper.instances) == 1
    assert _FakeBrowserPageScraper.instances[0].calls[0]["stage"] == "category_page"
    assert _FakeBrowserPageScraper.instances[0].calls[-1]["stage"] == "detail_page"
    assert runtime.detail_running[0]["listing_id"] == "listing-1"
    assert runtime.detail_completed[0]["listing_id"] == "listing-1"
    assert "SCRAPE_LISTING_BATCH_STAGED" in caplog.text
    assert "SCRAPE_DETAIL_TARGETS_LOADED" in caplog.text
    assert "SCRAPE_DETAIL_ITEM_OK" in caplog.text


@pytest.mark.asyncio
async def test_ctgoodjobs_executor_marks_manual_action_required_after_final_challenge(monkeypatch, caplog):
    crawl_module = _load_module()
    _patch_happy_path_dependencies(monkeypatch, crawl_module)

    async def _raise_manual_action(self, url: str, *, stage: str, referer: str | None = None) -> str:
        raise crawl_module.ManualActionRequiredError(
            source_site="ctgoodjobs",
            stage=stage,
            blocked_url=url,
            referer=referer,
            message=f"blocked during {stage}",
        )

    monkeypatch.setattr(_FakeBrowserPageScraper, "fetch_page_html", _raise_manual_action)

    with caplog.at_level(logging.INFO, logger="ctgoodjobs-crawl"):
        exit_code = await crawl_module.main(
            [
                "--crawl-job-id",
                str(uuid4()),
                "--category-ids",
                "ctgoodjobs:021",
                "--max-pages",
                "1",
            ]
        )

    runtime = _FakeCrawlJobRuntime.last_instance
    assert exit_code == 1
    assert runtime is not None
    assert runtime.manual_action_payload is not None
    assert runtime.manual_action_payload["source_site"] == "ctgoodjobs"
    assert runtime.manual_action_payload["payload"]["stage"] == "category_page"
    assert runtime.manual_action_payload["payload"]["resume_context"]["crawl_phase"] == "listing"
    assert "SCRAPE_EXECUTOR_START" in caplog.text
