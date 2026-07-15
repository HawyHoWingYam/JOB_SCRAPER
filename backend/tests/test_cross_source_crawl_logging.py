from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.logging_config import redact_url
from app.services.crawl_job_runtime import ListingBatchPersistResult
from app.services.offertoday_detail_pipeline import (
    OfferTodayDetailPipeline,
    OfferTodayDetailProcessResult,
    OfferTodayDetailTarget,
)
from app.scraper.manual_action import (
    ManualActionRequiredError,
    build_session_recovery_manual_action,
)
from app.sources.offertoday.listing_runner import (
    ListingConditionOutcome,
    ListingPageObservation,
    ListingRunResult,
)
from app.sources.offertoday.response_policy import (
    OfferTodayResponseKind,
    OfferTodayTransportError,
)
from scripts import ctgoodjobs_standalone_crawl as ctgoodjobs_crawl
from scripts import jobsdb_standalone_crawl as jobsdb_crawl
from scripts import offertoday_standalone_crawl as offertoday_crawl


class _EmptyTargets:
    selected_rows = 0
    skipped_existing_rows = 0
    target_rows = 0
    targets: list[dict] = []
    distinct_selected_ids = 0
    reconciled_rows = 0
    duplicate_rows = 0
    fetch_cohort_source_job_ids: tuple[str, ...] = ()
    fetch_cohort_hash = "empty"
    reconciled_source_job_ids: tuple[str, ...] = ()
    identity_conflict_ids: tuple[str, ...] = ()
    identity_conflict_evidence: tuple[dict, ...] = ()
    new_detail_targets = 0
    repair_detail_targets = 0


class _FakeRuntime:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self.staged_source_job_ids: set[str] = set()

    def load_detail_targets(self, **_kwargs):
        return _EmptyTargets()

    def write_progress_event(self, *, event_type, payload, **_kwargs):
        self.events.append((event_type, dict(payload)))

    def merge_metrics(self, **_kwargs):
        return None

    def mark_completed(self, **_kwargs):
        return None

    def transition_detail_running(self, *_args, **_kwargs):
        return None

    def transition_detail_outcome(self, *_args, **_kwargs):
        return None

    def stage_listing_batch(self, *, payloads, **_kwargs):
        source_job_ids = tuple(
            dict.fromkeys(
                str(payload.get("source_job_id") or "")
                for payload in payloads
                if str(payload.get("source_job_id") or "")
            )
        )
        created = tuple(
            source_job_id
            for source_job_id in source_job_ids
            if source_job_id not in self.staged_source_job_ids
        )
        preexisting = tuple(
            source_job_id
            for source_job_id in source_job_ids
            if source_job_id in self.staged_source_job_ids
        )
        self.staged_source_job_ids.update(source_job_ids)
        return ListingBatchPersistResult(
            rows_created=len(created),
            created_source_job_ids=created,
            preexisting_staged_source_job_ids=preexisting,
            published_source_job_ids=(),
            job_ids_seen=len(source_job_ids),
            skipped_existing=0,
        )


class _OneTargetRuntime(_FakeRuntime):
    def __init__(self, *, source_site: str) -> None:
        super().__init__()
        listing_payload = {
            "job_id": "job-1",
            "encrypted_job_id": "enc-job-1",
            "encrypted_job_id_source": "encryptJobId",
        }
        self.targets = _EmptyTargets()
        self.targets.selected_rows = 1
        self.targets.target_rows = 1
        self.targets.fetch_cohort_source_job_ids = ("job-1",)
        self.targets.fetch_cohort_hash = "one-target"
        self.targets.targets = [
            {
                "listing_id": "listing-1",
                "duplicate_listing_ids": [],
                "source_job_id": "job-1",
                "source_url": (
                    "https://jobs.ctgoodjobs.hk/job/job-1"
                    if source_site == "ctgoodjobs"
                    else "https://hk.jobsdb.com/job/job-1"
                ),
                "source_classification_id": "ct-it",
                "listing_payload": listing_payload,
            }
        ]
        self.detail_transitions: list[str] = []

    def load_detail_targets(self, **_kwargs):
        return self.targets

    def mark_detail_running(self, **_kwargs):
        self.detail_transitions.append("running")

    def mark_detail_completed(self, **_kwargs):
        self.detail_transitions.append("completed")

    def mark_detail_failed(self, **_kwargs):
        self.detail_transitions.append("failed")

    def mark_detail_manual_action_required(self, **_kwargs):
        self.detail_transitions.append("manual_action_required")

    def mark_manual_action_required(self, **_kwargs):
        self.detail_transitions.append("crawl_manual_action_required")

    def add_second_target(self) -> None:
        second = deepcopy(self.targets.targets[0])
        second.update(
            {
                "listing_id": "listing-2",
                "source_job_id": "job-2",
                "source_url": second["source_url"].replace("job-1", "job-2"),
                "listing_payload": {
                    "job_id": "job-2",
                    "encrypted_job_id": "enc-job-2",
                    "encrypted_job_id_source": "encryptJobId",
                },
            }
        )
        self.targets.targets.append(second)
        self.targets.selected_rows = 2
        self.targets.target_rows = 2
        self.targets.fetch_cohort_source_job_ids = ("job-1", "job-2")
        self.targets.fetch_cohort_hash = "two-targets"


class _FakeDb:
    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


def _messages(caplog) -> str:
    return "\n".join(record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_jobsdb_listing_logs_page_stage_and_terminal_summary(
    monkeypatch,
    caplog,
) -> None:
    class FakeCategoryScraper:
        async def scrape_category(
            self,
            category_id,
            *,
            max_pages,
            page_sink,
            on_page_start,
        ):
            await on_page_start(
                category_id=category_id,
                category_name="Information Technology",
                page=1,
                total_pages=max_pages,
            )
            await page_sink(
                category_id=category_id,
                category_name="Information Technology",
                page=1,
                total_pages=max_pages,
                jobs=[{"id": "jobsdb-secret-listing-id"}],
            )
            return {"job_ids": ["jobsdb-secret-listing-id"]}

    monkeypatch.setattr(jobsdb_crawl, "CategoryListScraper", FakeCategoryScraper)
    args = SimpleNamespace(
        crawl_job_id="jobsdb-listing-task",
        crawl_mode="headless",
        category_ids=[1200],
        max_pages=1,
        skip_existing=False,
    )

    with caplog.at_level("INFO", logger="jobsdb-crawl"):
        result = await jobsdb_crawl.run_listing_phase(args, _FakeRuntime())

    messages = _messages(caplog)
    assert result.rows_created == 1
    assert messages.count("SCRAPE_LISTING_CATEGORY_START") == 1
    assert messages.count("SCRAPE_LISTING_PAGE_START") == 1
    assert messages.count("SCRAPE_LISTING_BATCH_STAGED") == 1
    assert messages.count("SCRAPE_LISTING_DONE") == 1
    assert "source=jobsdb" in messages
    assert "crawl_job_id=jobsdb-listing-task" in messages
    assert "crawl_phase=listing" in messages
    assert "crawl_mode=headless" in messages
    assert "job_ids=1" in messages
    assert "listings_staged=1" in messages
    assert "jobsdb-secret-listing-id" not in messages


@pytest.mark.asyncio
async def test_ctgoodjobs_listing_logs_page_stage_and_terminal_summary(
    monkeypatch,
    caplog,
) -> None:
    category = SimpleNamespace(
        source_classification_id="ct-it",
        ctgoodjobs_id="ct-it",
        url="https://jobs.ctgoodjobs.hk/jobs/information-technology",
        slug="information-technology",
        name="Information Technology",
    )
    monkeypatch.setattr(
        ctgoodjobs_crawl,
        "_categories_by_id",
        lambda: {"ct-it": category},
    )
    monkeypatch.setattr(
        ctgoodjobs_crawl,
        "parse_category_page",
        lambda *_args, **_kwargs: {
            "job_ids": ["ct-secret-listing-id"],
            "job_urls": [
                "https://jobs.ctgoodjobs.hk/job/ct-secret-listing-id"
            ],
        },
    )

    class FakeBrowser:
        async def fetch_page_html(self, *_args, **_kwargs):
            return "<html>secret listing body</html>"

    args = SimpleNamespace(
        crawl_job_id="ctgoodjobs-listing-task",
        crawl_mode="headed",
        category_ids=["ct-it"],
        max_pages=1,
        skip_existing=False,
    )

    with caplog.at_level("INFO", logger="ctgoodjobs-crawl"):
        result = await ctgoodjobs_crawl._run_listing_phase(
            args,
            _FakeRuntime(),
            FakeBrowser(),
        )

    messages = _messages(caplog)
    assert result["listings_staged"] == 1
    assert messages.count("SCRAPE_LISTING_CATEGORY_START") == 1
    assert messages.count("SCRAPE_LISTING_PAGE_START") == 1
    assert messages.count("SCRAPE_LISTING_BATCH_STAGED") == 1
    assert messages.count("SCRAPE_LISTING_DONE") == 1
    assert "source=ctgoodjobs" in messages
    assert "crawl_job_id=ctgoodjobs-listing-task" in messages
    assert "crawl_phase=listing" in messages
    assert "crawl_mode=headed" in messages
    assert "job_ids=1" in messages
    assert "listings_staged=1" in messages
    assert "ct-secret-listing-id" not in messages
    assert "secret listing body" not in messages


@pytest.mark.asyncio
async def test_offertoday_empty_listing_logs_start_stage_and_terminal_summary(
    caplog,
) -> None:
    class HealthyBrowser:
        async def require_healthy_session(self) -> None:
            return None

    class EmptyListingRunner:
        async def run(self, *, conditions, observation_sink, **_kwargs):
            condition = conditions[0]
            await observation_sink.record_page_start(
                condition=condition,
                page=1,
                attempt=1,
                max_attempts=3,
            )
            observation = ListingPageObservation(
                condition_id=condition.condition_id,
                search_family=condition.search_family,
                category_id=condition.category_id,
                keyword=condition.keyword,
                endpoint=condition.endpoint,
                rcd_type=condition.rcd_type,
                page=1,
                attempt=1,
                request_fingerprint="safe-fingerprint",
                classification="success",
                api_code=0,
                reported_total=0,
                has_more=False,
                row_count=0,
                missing_job_id_count=0,
                missing_encrypted_job_id_count=0,
                job_id_fallback_count=0,
                id_pairs=(),
                rows=(),
                identity_issues=(),
                identity_conflicts=(),
                latency_ms=4,
                session_mode="headless",
                retry_reason=None,
                stop_reason="natural_exhaustion",
                response_url=(
                    "https://www.offertoday.com/wapi/geek/recommend/search/list"
                ),
            )
            await observation_sink.record_page_attempt(observation)
            outcome = ListingConditionOutcome(
                condition=condition,
                pages_observed=1,
                stop_reason="natural_exhaustion",
                is_complete=True,
            )
            await observation_sink.record_condition_outcome(outcome)
            return ListingRunResult(
                ordered_job_ids=(),
                accepted_job_ids=(),
                id_pairs=(),
                observations=(observation,),
                condition_outcomes=(outcome,),
                identity_conflicts=(),
                identity_issues=(),
                gaps=(),
                stop_reason="natural_exhaustion",
                is_complete=True,
            )

    args = SimpleNamespace(
        crawl_job_id="offertoday-listing-task",
        crawl_phase="listing",
        headed=False,
        category_ids="118000",
        keywords="python",
        max_pages=1,
        detail_limit=10,
        detail_statuses="pending,manual_action_required",
        skip_existing=False,
        resume_strategy="fresh_profile",
    )

    with caplog.at_level("INFO", logger="offertoday-crawl"):
        result = await offertoday_crawl._run_listing_phase(
            args=args,
            browser_runtime=HealthyBrowser(),
            crawl_runtime=_FakeRuntime(),
            crawl_job_id="offertoday-listing-task",
            listing_runner=EmptyListingRunner(),
        )

    messages = _messages(caplog)
    assert result.is_complete is True
    assert messages.count("SCRAPE_LISTING_CATEGORY_START") == 1
    assert messages.count("SCRAPE_LISTING_PAGE_START") == 1
    assert messages.count("SCRAPE_LISTING_BATCH_STAGED") == 1
    assert messages.count("SCRAPE_LISTING_DONE") == 1
    assert "source=offertoday" in messages
    assert "crawl_job_id=offertoday-listing-task" in messages
    assert "crawl_phase=listing" in messages
    assert "crawl_mode=headless" in messages
    assert "job_ids=0" in messages
    assert "listings_staged=0" in messages


@pytest.mark.asyncio
async def test_offertoday_listing_ip_block_logs_manual_and_terminal_summary(
    caplog,
) -> None:
    blocked_url = (
        "https://www.offertoday.com/web/passport/cm/verify.html?"
        "code=-1000035&gateway=otd"
    )

    class BlockedBrowser:
        async def require_healthy_session(self) -> None:
            raise build_session_recovery_manual_action(
                source_site="offertoday",
                stage="browser_session",
                blocked_url=blocked_url,
                classification="ip_blocked",
                code=-1000035,
                evidence={"final_url": blocked_url, "reason": "session_preflight"},
            )

    args = SimpleNamespace(
        crawl_job_id="offertoday-blocked-listing",
        crawl_phase="listing",
        headed=False,
        category_ids="118000",
        keywords="python",
        max_pages=3,
        detail_limit=10,
        detail_statuses="pending,manual_action_required",
        skip_existing=False,
        resume_strategy="fresh_profile",
    )

    with caplog.at_level("INFO", logger="offertoday-crawl"):
        with pytest.raises(ManualActionRequiredError):
            await offertoday_crawl._run_listing_phase(
                args=args,
                browser_runtime=BlockedBrowser(),
                crawl_runtime=_FakeRuntime(),
                crawl_job_id="offertoday-blocked-listing",
            )

    messages = _messages(caplog)
    assert messages.count("SCRAPE_LISTING_MANUAL_ACTION") == 1
    assert messages.count("SCRAPE_LISTING_DONE") == 1
    assert "source=offertoday" in messages
    assert "crawl_job_id=offertoday-blocked-listing" in messages
    assert "crawl_phase=listing" in messages
    assert "crawl_mode=headless" in messages
    assert "classification=ip_blocked" in messages
    assert "code=-1000035" in messages
    assert "outcome=manual_action_required" in messages


@pytest.mark.asyncio
async def test_jobsdb_empty_detail_has_empty_and_terminal_summary(monkeypatch, caplog) -> None:
    monkeypatch.setattr(jobsdb_crawl, "SessionLocal", _FakeDb)
    args = SimpleNamespace(
        crawl_job_id="jobsdb-task",
        crawl_mode="headless",
        source_listing_crawl_job_id="listing-task",
        category_ids=[1200],
        detail_limit=10,
        detail_statuses=["pending", "manual_action_required"],
        skip_existing=False,
        is_resume=False,
        resume_strategy="fresh_profile",
    )

    with caplog.at_level("INFO", logger="jobsdb-crawl"):
        result = await jobsdb_crawl.run_detail_phase(args, _FakeRuntime())

    messages = _messages(caplog)
    assert result["target_rows"] == 0
    assert "SCRAPE_DETAIL_TARGETS_EMPTY" in messages
    assert "SCRAPE_DETAIL_DONE" in messages
    assert "crawl_job_id=jobsdb-task" in messages


@pytest.mark.asyncio
async def test_ctgoodjobs_empty_detail_has_empty_and_terminal_summary(caplog) -> None:
    args = SimpleNamespace(
        crawl_job_id="ctgoodjobs-task",
        crawl_mode="headed",
        source_listing_crawl_job_id="listing-task",
        category_ids=["10"],
        detail_limit=10,
        detail_statuses=["pending", "manual_action_required"],
        skip_existing=False,
    )

    with caplog.at_level("INFO", logger="ctgoodjobs-crawl"):
        result = await ctgoodjobs_crawl._run_detail_phase(
            args,
            _FakeRuntime(),
            browser_scraper=object(),
            source_listing_crawl_job_id="listing-task",
            detail_scope="listing_batch",
        )

    messages = _messages(caplog)
    assert result["target_rows"] == 0
    assert "SCRAPE_DETAIL_TARGETS_EMPTY" in messages
    assert "SCRAPE_DETAIL_DONE" in messages
    assert "crawl_job_id=ctgoodjobs-task" in messages


@pytest.mark.asyncio
async def test_offertoday_empty_detail_has_empty_and_terminal_summary(caplog) -> None:
    args = SimpleNamespace(
        crawl_job_id="offertoday-task",
        crawl_phase="full",
        headed=False,
        source_listing_crawl_job_id="listing-task",
        category_ids="118000",
        keywords="",
        max_pages=1,
        detail_limit=10,
        detail_statuses="pending,manual_action_required",
        skip_existing=False,
        resume_strategy="fresh_profile",
    )

    with caplog.at_level("INFO", logger="offertoday-crawl"):
        result = await offertoday_crawl._run_detail_phase(
            args=args,
            browser_runtime=object(),
            crawl_runtime=_FakeRuntime(),
            crawl_job_id="offertoday-task",
            detail_load_result=_EmptyTargets(),
        )

    messages = _messages(caplog)
    assert result.processed_targets == 0
    assert "SCRAPE_DETAIL_TARGETS_EMPTY" in messages
    assert "SCRAPE_DETAIL_DONE" in messages
    assert "crawl_job_id=offertoday-task" in messages


def test_new_log_contract_does_not_render_session_secrets() -> None:
    secret_values = (
        "cookie-secret",
        "csrf-secret",
        "storage-state-secret",
        "full-job-description-secret",
        "query-token-secret",
    )
    event = offertoday_crawl.build_scrape_log_event(
        "SCRAPE_DETAIL_ITEM_FAIL",
        source="offertoday",
        crawl_job_id="safe-task",
        source_job_id="safe-job",
        classification="ip_blocked",
        error_type="ManualActionRequiredError",
        blocked_url=(
            "https://www.offertoday.com/web/passport/cm/verify.html?"
            "code=-1000035&token=query-token-secret"
        ),
    )

    assert all(secret not in event for secret in secret_values)
    assert (
        "blocked_url=https://www.offertoday.com/web/passport/cm/verify.html"
        in event
    )
    assert (
        redact_url("postgresql://operator:db-secret@db/jobs?sslmode=require")
        == "postgresql://operator:***@db/jobs?sslmode=require"
    )


@pytest.mark.asyncio
async def test_offertoday_detail_retry_log_keeps_common_correlation_fields(
    caplog,
) -> None:
    runtime = _OneTargetRuntime(source_site="offertoday")
    target = OfferTodayDetailTarget.from_runtime_target(runtime.targets.targets[0])
    fetch_calls = 0

    async def fetch_detail(**_kwargs):
        nonlocal fetch_calls
        fetch_calls += 1
        raise OfferTodayTransportError(
            "temporary network failure",
            http_status=None,
            response_url=(
                "https://www.offertoday.com/wapi/geek/recommend/jobDetail"
            ),
            payload=None,
            error_kind="network",
        )

    async def no_sleep(_seconds: float) -> None:
        return None

    pipeline = OfferTodayDetailPipeline(
        session_factory=_FakeDb,
        crawl_runtime=runtime,
        company_repository=object(),
        job_repository=object(),
        sleep=no_sleep,
        max_attempts=2,
        retry_delays_seconds=(0.0,),
    )

    with caplog.at_level(
        "INFO",
        logger="app.services.offertoday_detail_pipeline",
    ):
        result = await pipeline.process_target(
            target=target,
            detail_crawl_job_id="offertoday-retry-task",
            fetch_detail=fetch_detail,
            crawl_mode="headless",
        )

    messages = _messages(caplog)
    assert fetch_calls == 2
    assert result.outcome is OfferTodayResponseKind.TRANSIENT_TRANSPORT
    assert messages.count("SCRAPE_DETAIL_RETRY") == 1
    assert "source=offertoday" in messages
    assert "crawl_job_id=offertoday-retry-task" in messages
    assert "crawl_phase=detail" in messages
    assert "crawl_mode=headless" in messages
    assert "source_job_id=job-1" in messages
    assert "attempt=1" in messages
    assert "max_attempts=2" in messages


@pytest.mark.asyncio
async def test_jobsdb_every_detail_target_has_start_result_and_done(
    monkeypatch,
    caplog,
) -> None:
    runtime = _OneTargetRuntime(source_site="jobsdb")

    class FakeDetailScraper:
        async def fetch_job_detail(self, _source_job_id):
            return {
                "title": "Engineer",
                "description": "full-job-description-secret",
                "cookie": "cookie-secret",
            }

    @asynccontextmanager
    async def fake_detail_context(_args):
        yield FakeDetailScraper()

    class FakeIngestService:
        def _build_company_data(self, _canonical):
            return {"name": "Example"}

        def _build_job_data(self, canonical, _company_id):
            return dict(canonical)

    class FakeCompanyRepository:
        def upsert_company(self, *_args, **_kwargs):
            return SimpleNamespace(id="company-1"), "created"

    class FakeJobRepository:
        def upsert_source_job(self, *_args, **_kwargs):
            return SimpleNamespace(id="published-1"), "created"

    monkeypatch.setattr(jobsdb_crawl, "SessionLocal", _FakeDb)
    monkeypatch.setattr(jobsdb_crawl, "_detail_scraper_context", fake_detail_context)
    monkeypatch.setattr(jobsdb_crawl, "IngestWorkerService", FakeIngestService)
    monkeypatch.setattr(jobsdb_crawl, "CompanyRepository", FakeCompanyRepository)
    monkeypatch.setattr(jobsdb_crawl, "JobRepository", FakeJobRepository)
    monkeypatch.setattr(
        jobsdb_crawl,
        "build_jobsdb_canonical_job",
        lambda detail, **_kwargs: SimpleNamespace(
            to_dict=lambda: {"raw_data": dict(detail)}
        ),
    )
    args = SimpleNamespace(
        crawl_job_id="jobsdb-detail-task",
        crawl_mode="headless",
        source_listing_crawl_job_id="listing-task",
        category_ids=[1200],
        detail_limit=10,
        detail_statuses=["pending", "manual_action_required"],
        skip_existing=False,
        is_resume=False,
        resume_strategy="fresh_profile",
    )

    with caplog.at_level("INFO", logger="jobsdb-crawl"):
        result = await jobsdb_crawl.run_detail_phase(args, runtime)

    messages = _messages(caplog)
    assert result["completed"] == 1
    assert messages.count("SCRAPE_DETAIL_ITEM_START") == 1
    assert messages.count("SCRAPE_DETAIL_ITEM_OK") == 1
    assert messages.count("SCRAPE_DETAIL_DONE") == 1
    assert "detail_index=1" in messages
    assert "detail_total=1" in messages
    assert "elapsed_ms=" in messages
    assert "cumulative_saved=1" in messages
    assert "cookie-secret" not in messages
    assert "full-job-description-secret" not in messages


@pytest.mark.asyncio
async def test_ctgoodjobs_every_detail_target_has_start_result_and_done(
    monkeypatch,
    caplog,
) -> None:
    runtime = _OneTargetRuntime(source_site="ctgoodjobs")
    category = SimpleNamespace(
        source_classification_id="ct-it",
        name="Information Technology",
        slug="information-technology",
    )
    monkeypatch.setattr(
        ctgoodjobs_crawl,
        "_categories_by_id",
        lambda: {"ct-it": category},
    )
    monkeypatch.setattr(
        ctgoodjobs_crawl,
        "parse_detail_page",
        lambda *_args, **_kwargs: {
            "description": "full-job-description-secret",
            "csrf": "csrf-secret",
        },
    )
    monkeypatch.setattr(
        ctgoodjobs_crawl,
        "merge_ctgoodjobs_job",
        lambda **_kwargs: {"title": "Engineer"},
    )
    monkeypatch.setattr(
        ctgoodjobs_crawl,
        "build_ctgoodjobs_canonical_job",
        lambda _merged: SimpleNamespace(
            to_dict=lambda: {
                "raw_data": {
                    "description": "full-job-description-secret",
                    "csrf": "csrf-secret",
                }
            }
        ),
    )

    async def fake_persist(**_kwargs):
        return "published-1"

    monkeypatch.setattr(
        ctgoodjobs_crawl,
        "_persist_ctgoodjobs_job",
        fake_persist,
    )

    class FakeBrowser:
        async def fetch_page_html(self, *_args, **_kwargs):
            return "<html>full-job-description-secret</html>"

    args = SimpleNamespace(
        crawl_job_id="ctgoodjobs-detail-task",
        crawl_mode="headed",
        category_ids=["ct-it"],
        detail_limit=10,
        detail_statuses=["pending", "manual_action_required"],
        skip_existing=False,
    )

    with caplog.at_level("INFO", logger="ctgoodjobs-crawl"):
        result = await ctgoodjobs_crawl._run_detail_phase(
            args,
            runtime,
            FakeBrowser(),
            source_listing_crawl_job_id="listing-task",
            detail_scope="listing_batch",
        )

    messages = _messages(caplog)
    assert result["completed"] == 1
    assert messages.count("SCRAPE_DETAIL_ITEM_START") == 1
    assert messages.count("SCRAPE_DETAIL_ITEM_OK") == 1
    assert messages.count("SCRAPE_DETAIL_DONE") == 1
    assert "elapsed_ms=" in messages
    assert "cumulative_saved=1" in messages
    assert "csrf-secret" not in messages
    assert "full-job-description-secret" not in messages


@pytest.mark.asyncio
async def test_offertoday_every_detail_target_has_start_result_and_done(caplog) -> None:
    runtime = _OneTargetRuntime(source_site="offertoday")

    class FakePipeline:
        async def process_target(self, *, target, **_kwargs):
            return OfferTodayDetailProcessResult(
                source_job_id=target.identity.job_id,
                outcome=OfferTodayResponseKind.SUCCESS,
                job_action="created",
                company_action="created",
            )

    args = SimpleNamespace(
        crawl_job_id="offertoday-detail-task",
        crawl_phase="full",
        headed=False,
        source_listing_crawl_job_id="listing-task",
        category_ids="118000",
        keywords="",
        max_pages=1,
        detail_limit=10,
        detail_statuses="pending,manual_action_required",
        skip_existing=False,
        resume_strategy="fresh_profile",
    )

    with caplog.at_level("INFO", logger="offertoday-crawl"):
        result = await offertoday_crawl._run_detail_phase(
            args=args,
            browser_runtime=object(),
            crawl_runtime=runtime,
            crawl_job_id="offertoday-detail-task",
            detail_load_result=runtime.targets,
            pipeline=FakePipeline(),
        )

    messages = _messages(caplog)
    assert result.jobs_saved == 1
    assert messages.count("SCRAPE_DETAIL_ITEM_START") == 1
    assert messages.count("SCRAPE_DETAIL_ITEM_OK") == 1
    assert messages.count("SCRAPE_DETAIL_DONE") == 1
    assert "detail_index=1" in messages
    assert "detail_total=1" in messages
    assert "elapsed_ms=" in messages
    assert "cumulative_saved=1" in messages


@pytest.mark.asyncio
async def test_jobsdb_detail_ip_block_stops_before_later_target(
    monkeypatch,
    caplog,
) -> None:
    runtime = _OneTargetRuntime(source_site="jobsdb")
    runtime.add_second_target()

    class BlockedScraper:
        def __init__(self) -> None:
            self.calls = 0

        async def fetch_job_detail(self, source_job_id):
            self.calls += 1
            raise build_session_recovery_manual_action(
                source_site="jobsdb",
                stage="detail_page",
                blocked_url=f"https://hk.jobsdb.com/job/{source_job_id}",
                classification="ip_blocked",
                evidence={"status_code": 429},
            )

    scraper = BlockedScraper()

    @asynccontextmanager
    async def fake_detail_context(_args):
        yield scraper

    monkeypatch.setattr(jobsdb_crawl, "SessionLocal", _FakeDb)
    monkeypatch.setattr(jobsdb_crawl, "_detail_scraper_context", fake_detail_context)
    args = SimpleNamespace(
        crawl_job_id="jobsdb-blocked-detail",
        crawl_mode="headless",
        source_listing_crawl_job_id="listing-task",
        category_ids=[1200],
        detail_limit=10,
        detail_statuses=["manual_action_required", "pending"],
        skip_existing=False,
        is_resume=True,
        resume_strategy="fresh_profile",
    )

    with caplog.at_level("INFO", logger="jobsdb-crawl"):
        with pytest.raises(Exception):
            await jobsdb_crawl.run_detail_phase(args, runtime)

    assert scraper.calls == 1
    assert runtime.detail_transitions == ["running", "manual_action_required"]
    messages = _messages(caplog)
    assert messages.count("SCRAPE_DETAIL_ITEM_START") == 1
    assert messages.count("SCRAPE_DETAIL_ITEM_MANUAL_ACTION") == 1
    assert "SCRAPE_DETAIL_DONE" in messages
    assert "outcome=manual_action_required" in messages


@pytest.mark.asyncio
async def test_ctgoodjobs_detail_ip_block_stops_before_later_target(
    monkeypatch,
    caplog,
) -> None:
    runtime = _OneTargetRuntime(source_site="ctgoodjobs")
    runtime.add_second_target()
    category = SimpleNamespace(
        source_classification_id="ct-it",
        name="Information Technology",
        slug="information-technology",
    )
    monkeypatch.setattr(
        ctgoodjobs_crawl,
        "_categories_by_id",
        lambda: {"ct-it": category},
    )

    class BlockedBrowser:
        def __init__(self) -> None:
            self.calls = 0

        async def fetch_page_html(self, url, **_kwargs):
            self.calls += 1
            raise build_session_recovery_manual_action(
                source_site="ctgoodjobs",
                stage="detail_page",
                blocked_url=url,
                classification="ip_blocked",
                evidence={"status_code": 403},
            )

    browser = BlockedBrowser()
    args = SimpleNamespace(
        crawl_job_id="ctgoodjobs-blocked-detail",
        crawl_mode="headed",
        category_ids=["ct-it"],
        detail_limit=10,
        detail_statuses=["manual_action_required", "pending"],
        skip_existing=False,
        resume_strategy="fresh_profile",
    )

    with caplog.at_level("INFO", logger="ctgoodjobs-crawl"):
        result = await ctgoodjobs_crawl._run_detail_phase(
            args,
            runtime,
            browser,
            source_listing_crawl_job_id="listing-task",
            detail_scope="listing_batch",
        )

    assert result["manual_action_required"] == 1
    assert browser.calls == 1
    assert runtime.detail_transitions == [
        "running",
        "manual_action_required",
        "crawl_manual_action_required",
    ]
    messages = _messages(caplog)
    assert messages.count("SCRAPE_DETAIL_ITEM_START") == 1
    assert messages.count("SCRAPE_DETAIL_ITEM_MANUAL_ACTION") == 1
    assert "SCRAPE_DETAIL_DONE" in messages


@pytest.mark.asyncio
async def test_offertoday_detail_ip_block_stops_before_later_target(caplog) -> None:
    runtime = _OneTargetRuntime(source_site="offertoday")
    runtime.add_second_target()

    class BlockedPipeline:
        def __init__(self) -> None:
            self.calls = 0

        async def process_target(self, *, target, **_kwargs):
            self.calls += 1
            return OfferTodayDetailProcessResult(
                source_job_id=target.identity.job_id,
                outcome=OfferTodayResponseKind.IP_BLOCKED,
                stop_batch=True,
            )

    pipeline = BlockedPipeline()
    args = SimpleNamespace(
        crawl_job_id="offertoday-blocked-detail",
        crawl_phase="full",
        headed=False,
        source_listing_crawl_job_id="listing-task",
        category_ids="118000",
        keywords="",
        max_pages=1,
        detail_limit=10,
        detail_statuses="manual_action_required,pending",
        skip_existing=False,
        resume_strategy="fresh_profile",
    )

    with caplog.at_level("INFO", logger="offertoday-crawl"):
        result = await offertoday_crawl._run_detail_phase(
            args=args,
            browser_runtime=object(),
            crawl_runtime=runtime,
            crawl_job_id="offertoday-blocked-detail",
            detail_load_result=runtime.targets,
            pipeline=pipeline,
        )

    assert result.stop_batch is True
    assert pipeline.calls == 1
    assert "crawl_manual_action_required" in runtime.detail_transitions
    messages = _messages(caplog)
    assert messages.count("SCRAPE_DETAIL_ITEM_START") == 1
    assert messages.count("SCRAPE_DETAIL_ITEM_MANUAL_ACTION") == 1
    assert "SCRAPE_DETAIL_DONE" in messages


def test_resume_payloads_exclude_completed_detail_targets() -> None:
    statuses = ["manual_action_required", "pending"]
    common_args = SimpleNamespace(
        crawl_job_id="detail-task",
        crawl_mode="headed",
        source_listing_crawl_job_id="listing-task",
        category_ids=[1200],
        detail_limit=10,
        detail_statuses=statuses,
        skip_existing=False,
        resume_strategy="fresh_profile",
        headed=True,
        keywords="",
        max_pages=1,
    )

    jobsdb_payload = jobsdb_crawl._build_detail_request_payload(common_args)
    ctgoodjobs_payload = ctgoodjobs_crawl._build_detail_request_payload(
        common_args,
        source_listing_crawl_job_id="listing-task",
    )
    offertoday_args = SimpleNamespace(
        **{
            **vars(common_args),
            "category_ids": "118000",
            "detail_statuses": "manual_action_required,pending",
        }
    )
    offertoday_payload = offertoday_crawl._build_runtime_request_payload(
        offertoday_args,
        crawl_phase="detail",
        source_listing_crawl_job_id="listing-task",
    )

    for payload in (jobsdb_payload, ctgoodjobs_payload, offertoday_payload):
        assert payload["detail_statuses"] == statuses
        assert "completed" not in payload["detail_statuses"]
        assert payload["source_listing_crawl_job_id"] == "listing-task"
