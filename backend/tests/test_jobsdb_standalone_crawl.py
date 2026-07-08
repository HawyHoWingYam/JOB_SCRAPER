from __future__ import annotations

import importlib
from types import SimpleNamespace
from uuid import uuid4

import logging

import pytest


class _FakeCategoryListScraper:
    PAGE_SIZE = 32

    async def fetch_page(self, classification_id, page=1, client=None):
        return {
            "totalCount": 1,
            "data": [
                {
                    "id": "job-1",
                    "title": "Data Engineer",
                    "companyName": "Acme",
                    "locations": [{"label": "Hong Kong", "countryCode": "HK"}],
                    "classifications": [
                        {"classification": {"id": classification_id, "description": "Technology"}}
                    ],
                    "bulletPoints": ["Python"],
                    "teaser": "Build pipelines",
                    "workTypes": ["Full time"],
                }
            ],
        }

    async def scrape_category(self, classification_id, max_pages=None, on_progress=None):
        payload = await self.fetch_page(classification_id, page=1)
        return {
            "classification_id": classification_id,
            "job_ids": [row["id"] for row in payload.get("data", [])],
            "total_count": payload.get("totalCount", 0),
            "pages_scraped": 1,
        }


class _FakeDetailScraper:
    async def fetch_job_detail(self, job_id, client=None):
        return {
            "jobsdb_id": job_id,
            "title": "Data Engineer",
            "abstract": "Build pipelines",
            "description_html": "<p>Build pipelines</p>",
            "classification_id": 6281,
            "classification": "Technology",
            "subclassification_id": 100,
            "subclassification": "Engineering",
            "location": "Hong Kong",
            "work_type": "Full time",
            "salary": {"label": "HKD 30k"},
            "listing_date": "2026-07-09T00:00:00+00:00",
            "advertiser_id": "acme",
            "advertiser_name": "Acme",
            "status": "active",
            "scraped_at": "2026-07-09T00:00:00+00:00",
        }


class _FakeBrowserDetailScraper:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def fetch_job_detail(self, job_id, client=None):
        return None


class _FakeRuntime:
    instances: list["_FakeRuntime"] = []

    def __init__(self):
        self.started = []
        self.completed = []
        self.failed = []
        self.manual_actions = []
        self.detail_running = []
        self.detail_completed = []
        self.detail_failed = []
        self.detail_manual = []
        self.events = []
        self.staged = []
        _FakeRuntime.instances.append(self)

    def mark_started(self, **kwargs):
        self.started.append(kwargs)

    def stage_listing_batch(self, **kwargs):
        self.staged.append(kwargs)
        return SimpleNamespace(rows_staged=1, job_ids_seen=1, skipped_existing=0)

    def write_progress_event(self, **kwargs):
        self.events.append(kwargs)

    def load_detail_targets(self, **kwargs):
        return SimpleNamespace(
            target_rows=1,
            selected_rows=1,
            skipped_existing_rows=0,
            targets=[
                {
                    "listing_id": "listing-1",
                    "source_job_id": "job-1",
                    "source_url": "https://hk.jobsdb.com/job/job-1",
                }
            ],
        )

    def mark_detail_running(self, **kwargs):
        self.detail_running.append(kwargs)

    def mark_detail_completed(self, **kwargs):
        self.detail_completed.append(kwargs)

    def mark_detail_failed(self, **kwargs):
        self.detail_failed.append(kwargs)

    def mark_detail_manual_action_required(self, **kwargs):
        self.detail_manual.append(kwargs)

    def mark_manual_action_required(self, **kwargs):
        self.manual_actions.append(kwargs)

    def mark_completed(self, **kwargs):
        self.completed.append(kwargs)

    def mark_failed(self, **kwargs):
        self.failed.append(kwargs)


class _FakeIngestWorkerService:
    def _build_company_data(self, canonical_job):
        return {"company_id": "company-1", "name": canonical_job.get("company_name"), "source_site": "jobsdb", "source_company_id": "acme"}

    def _build_job_data(self, canonical_job, company_id):
        return {
            "job_id": f"jobsdb:{canonical_job['source_job_id']}",
            "source_site": "jobsdb",
            "source_job_id": canonical_job["source_job_id"],
            "company_id": company_id,
            "title": canonical_job["title"],
            "description": canonical_job["description"],
            "location": canonical_job["location"],
            "employment_type": canonical_job["employment_type"],
            "source_classification_id": canonical_job["source_classification_id"],
            "source_classification_name": canonical_job["source_classification_name"],
            "source_subclassification_id": canonical_job["source_subclassification_id"],
            "source_subclassification_name": canonical_job["source_subclassification_name"],
            "posted_date": canonical_job["posted_date"],
            "salary_range": canonical_job["salary_range"],
            "raw_data": canonical_job["raw_data"],
        }


class _FakeCompanyRepository:
    def upsert_company(self, db, company_data, auto_commit=False):
        return SimpleNamespace(id="company-1"), "created"


class _FakeJobRepository:
    def upsert_source_job(self, db, job_data, skip_existing=False, auto_commit=False):
        return SimpleNamespace(id="job-row-1"), "created"


class _FakeDbSession:
    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


def test_jobsdb_apply_request_payload_defaults_preserves_requested_phase():
    crawl_module = importlib.import_module("backend.scripts.jobsdb_standalone_crawl")
    args = SimpleNamespace(
        category_ids=[],
        max_pages=1,
        detail_limit=100,
        crawl_mode="headless",
        crawl_phase="full",
        source_listing_crawl_job_id="",
        detail_statuses=["pending"],
        resume_strategy="fresh_profile",
        skip_existing=False,
        is_resume=False,
    )

    crawl_module._apply_request_payload_defaults(
        args,
        {
            "crawl_phase": "listing",
            "crawl_mode": "headed",
            "category_ids": [6281],
            "max_pages": 3,
            "detail_limit": 25,
            "detail_statuses": ["manual_action_required"],
            "source_listing_crawl_job_id": "listing-job-1",
            "skip_existing": True,
            "is_resume": True,
            "resume_strategy": "reuse_open_browser",
        },
    )

    assert args.crawl_phase == "listing"
    assert args.crawl_mode == "headed"
    assert args.category_ids == [6281]
    assert args.max_pages == 3
    assert args.detail_limit == 25
    assert args.detail_statuses == ["manual_action_required"]
    assert args.source_listing_crawl_job_id == "listing-job-1"
    assert args.skip_existing is True
    assert args.is_resume is True
    assert args.resume_strategy == "reuse_open_browser"


def _patch_common(monkeypatch, crawl_module, *, payload):
    _FakeRuntime.instances.clear()
    monkeypatch.setattr(crawl_module, "CategoryListScraper", _FakeCategoryListScraper)
    monkeypatch.setattr(crawl_module, "JobDetailScraper", _FakeDetailScraper)
    monkeypatch.setattr(crawl_module, "JobsDBBrowserDetailScraper", _FakeBrowserDetailScraper)
    monkeypatch.setattr(crawl_module, "CrawlJobRuntime", _FakeRuntime)
    monkeypatch.setattr(crawl_module, "IngestWorkerService", _FakeIngestWorkerService)
    monkeypatch.setattr(crawl_module, "CompanyRepository", _FakeCompanyRepository)
    monkeypatch.setattr(crawl_module, "JobRepository", _FakeJobRepository)
    monkeypatch.setattr(crawl_module, "_load_request_payload", lambda crawl_job_id: (dict(payload), "jobsdb"))
    monkeypatch.setattr(crawl_module, "SessionLocal", lambda: _FakeDbSession())


@pytest.mark.asyncio
async def test_jobsdb_executor_stages_listings_and_persists_details(monkeypatch, caplog):
    crawl_module = importlib.import_module("backend.scripts.jobsdb_standalone_crawl")
    _patch_common(
        monkeypatch,
        crawl_module,
        payload={
            "crawl_phase": "full",
            "crawl_mode": "headless",
            "category_ids": [6281],
            "max_pages": 1,
            "detail_limit": 10,
            "detail_statuses": ["pending"],
            "skip_existing": False,
        },
    )

    with caplog.at_level(logging.INFO, logger="jobsdb-crawl"):
        exit_code = await crawl_module.main(["--crawl-job-id", str(uuid4())])

    runtime = _FakeRuntime.instances[0]
    assert exit_code == 0
    assert runtime.staged
    assert runtime.detail_running
    assert runtime.detail_completed
    assert runtime.completed
    assert "SCRAPE_LISTING_BATCH_STAGED" in caplog.text
    assert "SCRAPE_DETAIL_TARGETS_LOADED" in caplog.text
    assert "SCRAPE_DETAIL_ITEM_OK" in caplog.text


@pytest.mark.asyncio
async def test_jobsdb_executor_marks_manual_action_required_when_listing_interstitial_detected(monkeypatch, caplog):
    crawl_module = importlib.import_module("backend.scripts.jobsdb_standalone_crawl")
    _patch_common(
        monkeypatch,
        crawl_module,
        payload={
            "crawl_phase": "listing",
            "crawl_mode": "headed",
            "category_ids": [6281],
            "max_pages": 1,
            "detail_limit": 10,
            "detail_statuses": ["pending"],
            "skip_existing": False,
        },
    )

    async def raise_manual_action(self, classification_id, page=1, client=None):
        raise crawl_module.ManualActionRequiredError(
            source_site="jobsdb",
            stage="category_page",
            blocked_url="https://hk.jobsdb.com/jobs-in-information-technology",
            message="JobsDB listing fetch blocked by human verification",
        )

    monkeypatch.setattr(_FakeCategoryListScraper, "fetch_page", raise_manual_action)

    with caplog.at_level(logging.INFO, logger="jobsdb-crawl"):
        exit_code = await crawl_module.main(["--crawl-job-id", str(uuid4())])

    runtime = _FakeRuntime.instances[0]
    assert exit_code == 1
    assert runtime.manual_actions
    assert runtime.manual_actions[0]["payload"]["stage"] == "category_page"
    assert runtime.manual_actions[0]["payload"]["resume_context"]["crawl_phase"] == "listing"
    assert "SCRAPE_EXECUTOR_START" in caplog.text


@pytest.mark.asyncio
async def test_jobsdb_executor_persists_detail_resume_context_on_manual_action(monkeypatch, caplog):
    crawl_module = importlib.import_module("backend.scripts.jobsdb_standalone_crawl")
    _patch_common(
        monkeypatch,
        crawl_module,
        payload={
            "crawl_phase": "detail",
            "crawl_mode": "headed",
            "category_ids": [6281],
            "max_pages": 1,
            "detail_limit": 10,
            "detail_statuses": ["pending"],
            "source_listing_crawl_job_id": "listing-job-1",
            "skip_existing": False,
        },
    )

    async def raise_manual_action(self, job_id, client=None):
        raise crawl_module.ManualActionRequiredError(
            source_site="jobsdb",
            stage="detail_page",
            blocked_url=f"https://hk.jobsdb.com/job/{job_id}",
            message="JobsDB detail fetch blocked by human verification",
        )

    monkeypatch.setattr(_FakeBrowserDetailScraper, "fetch_job_detail", raise_manual_action)

    with caplog.at_level(logging.INFO, logger="jobsdb-crawl"):
        exit_code = await crawl_module.main(["--crawl-job-id", str(uuid4())])

    runtime = _FakeRuntime.instances[0]
    assert exit_code == 1
    assert runtime.manual_actions
    assert runtime.manual_actions[0]["payload"]["resume_context"]["crawl_phase"] == "detail"
    assert (
        runtime.manual_actions[0]["payload"]["resume_context"]["source_listing_crawl_job_id"]
        == "listing-job-1"
    )
    assert "SCRAPE_DETAIL_ITEM_MANUAL_ACTION" in caplog.text
