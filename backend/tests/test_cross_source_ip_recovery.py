from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.scraper.access_block import classify_public_access_evidence
from app.scraper.category_scraper import CategoryListScraper
from app.scraper.ctgoodjobs_browser_page_scraper import CTGoodJobsBrowserPageScraper
from app.scraper.job_detail_scraper import JobDetailScraper
from app.scraper.jobsdb_browser_detail_scraper import JobsDBBrowserDetailScraper
from app.scraper.manual_action import (
    ManualActionRequiredError,
    build_session_recovery_manual_action,
    normalize_manual_action_payload,
)
from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime
from app.services.crawl_job_runtime import ListingBatchPersistResult
from app.services.crawl_job_dispatch_service import resolve_resume_detail_statuses
from app.sources.offertoday.listing_contract import (
    production_offertoday_listing_request_policy,
)
from app.sources.offertoday.listing_runner import (
    ListingConditionOutcome,
    ListingPageObservation,
    ListingRetryPolicy,
    ListingRunResult,
    ListingStopPolicy,
    OfferTodayListingRunner,
    listing_observation_to_payload,
)
from app.sources.offertoday.response_policy import (
    OfferTodayResponseKind,
    OfferTodayTransportError,
    classify_offertoday_response,
)
from app.sources.offertoday.search_space import build_offertoday_listing_conditions
from scripts import ctgoodjobs_standalone_crawl as ctgoodjobs_crawl
from scripts import jobsdb_standalone_crawl as jobsdb_crawl
from scripts import offertoday_standalone_crawl as offertoday_crawl


class _RedirectingOfferTodayPage:
    def __init__(self, final_url: str) -> None:
        self.url = "https://www.offertoday.com/hk/search"
        self.final_url = final_url
        self.fetch_calls = 0

    async def evaluate(self, script, _argument=None):
        if "document.cookie" in script:
            return None
        self.fetch_calls += 1
        self.url = self.final_url
        raise RuntimeError("Page.evaluate: TypeError: Failed to fetch")


class _ProgrammingErrorOfferTodayPage:
    url = "https://www.offertoday.com/hk/search"

    async def evaluate(self, script, _argument=None):
        if "document.cookie" in script:
            return None
        raise RuntimeError("Execution context was destroyed")


class _DelayedRedirectingOfferTodayPage:
    def __init__(self, final_url: str) -> None:
        self.url = "https://www.offertoday.com/hk/search"
        self.final_url = final_url
        self.fetch_calls = 0

    async def evaluate(self, script, _argument=None):
        if "document.cookie" in script:
            return None
        self.fetch_calls += 1

        async def finish_redirect() -> None:
            await asyncio.sleep(0.01)
            self.url = self.final_url

        asyncio.create_task(finish_redirect())
        raise RuntimeError("Page.evaluate: TypeError: Failed to fetch")


class _IdempotentListingRuntime:
    def __init__(self) -> None:
        self.source_job_ids: set[str] = set()
        self.progress_events: list[tuple[str, dict]] = []
        self.manual_actions: list[dict] = []
        self.metrics: list[dict] = []

    def stage_listing_batch(self, *, payloads, **_kwargs):
        ordered_ids = tuple(
            dict.fromkeys(
                str(payload.get("source_job_id") or "")
                for payload in payloads
                if str(payload.get("source_job_id") or "")
            )
        )
        preexisting = tuple(
            source_job_id
            for source_job_id in ordered_ids
            if source_job_id in self.source_job_ids
        )
        created = tuple(
            source_job_id
            for source_job_id in ordered_ids
            if source_job_id not in self.source_job_ids
        )
        self.source_job_ids.update(ordered_ids)
        return ListingBatchPersistResult(
            rows_created=len(created),
            created_source_job_ids=created,
            preexisting_staged_source_job_ids=preexisting,
            published_source_job_ids=(),
            job_ids_seen=len(ordered_ids),
            skipped_existing=0,
        )

    def write_progress_event(self, *, event_type, payload, **_kwargs) -> None:
        self.progress_events.append((event_type, dict(payload)))

    def mark_manual_action_required(self, **kwargs) -> None:
        self.manual_actions.append(dict(kwargs))

    def merge_metrics(self, *, metrics_patch, **_kwargs) -> None:
        self.metrics.append(dict(metrics_patch))


@pytest.mark.asyncio
async def test_offertoday_rejected_fetch_uses_post_redirect_url_for_ip_block() -> None:
    page = _RedirectingOfferTodayPage(
        "https://www.offertoday.com/web/passport/cm/verify.html?code=-1000035&gateway=otd"
    )
    runtime = OfferTodayBrowserRuntime(headed=False)
    runtime._page = page

    result = await runtime.check_session()

    assert result.classification is OfferTodayResponseKind.IP_BLOCKED
    assert result.api_code == -1000035
    assert result.current_url == page.final_url
    assert page.fetch_calls == 1

    with pytest.raises(ManualActionRequiredError) as raised:
        await runtime.require_healthy_session()

    assert raised.value.classification == "ip_blocked"
    assert raised.value.code == -1000035
    assert raised.value.blocked_url == page.final_url
    assert "public IP" in raised.value.message


@pytest.mark.asyncio
async def test_offertoday_rejected_fetch_waits_for_redirect_url_race() -> None:
    page = _DelayedRedirectingOfferTodayPage(
        "https://www.offertoday.com/web/passport/cm/verify.html?code=-1000035&gateway=otd"
    )
    runtime = OfferTodayBrowserRuntime(headed=False)
    runtime._page = page

    result = await runtime.check_session()

    assert result.classification is OfferTodayResponseKind.IP_BLOCKED
    assert result.current_url == page.final_url
    assert page.fetch_calls == 1


@pytest.mark.asyncio
async def test_offertoday_non_fetch_playwright_errors_still_propagate() -> None:
    runtime = OfferTodayBrowserRuntime(headed=False)
    runtime._page = _ProgrammingErrorOfferTodayPage()

    with pytest.raises(RuntimeError, match="Execution context was destroyed"):
        await runtime._fetch_json_response(
            "https://www.offertoday.com/wapi/geek/recommend/search/list",
            method="POST",
            payload={"page": 1},
        )


def test_offertoday_other_verify_url_is_waf_and_normal_network_error_is_transient() -> None:
    waf = classify_offertoday_response(
        None,
        operation="listing",
        current_url="https://www.offertoday.com/web/passport/cm/verify.html?code=123",
    )
    assert waf.kind is OfferTodayResponseKind.WAF_CHALLENGE

    transport_error = OfferTodayTransportError(
        "OfferToday browser fetch was interrupted",
        http_status=None,
        response_url="https://www.offertoday.com/hk/search",
        payload=None,
        error_kind="network",
    )
    transient = classify_offertoday_response(
        None,
        operation="listing",
        current_url=transport_error.response_url,
        transport_error=transport_error,
    )
    assert transient.kind is OfferTodayResponseKind.TRANSIENT_TRANSPORT
    assert transient.retryable is True


@pytest.mark.asyncio
async def test_offertoday_listing_ip_block_stops_without_retry_and_preserves_url() -> None:
    blocked_url = (
        "https://www.offertoday.com/web/passport/cm/verify.html?"
        "code=-1000035&gateway=otd"
    )

    class BlockingTransport:
        browser_context_hash = "a" * 64

        def __init__(self) -> None:
            self.calls = 0

        async def fetch_listing_page(self, _payload, *, listing_url=None):
            self.calls += 1
            raise OfferTodayTransportError(
                "OfferToday browser fetch was interrupted",
                http_status=None,
                response_url=blocked_url,
                payload=None,
                error_kind="network",
            )

    class ObservationSink:
        def __init__(self) -> None:
            self.observations = []

        async def record_page_start(self, **_kwargs) -> None:
            return None

        async def record_page_attempt(self, observation) -> None:
            self.observations.append(observation)

        async def record_condition_outcome(self, _outcome) -> None:
            return None

    class StagingSink:
        def __init__(self) -> None:
            self.stage_calls = 0

        async def stage_page(self, **_kwargs) -> None:
            self.stage_calls += 1

        async def defer_identity_conflict(self, **_kwargs) -> None:
            return None

    transport = BlockingTransport()
    observation_sink = ObservationSink()
    staging_sink = StagingSink()
    runner = OfferTodayListingRunner(transport)
    conditions = build_offertoday_listing_conditions(
        [118000],
        keywords=["python"],
        default_to_it=False,
        endpoint="search",
        category_endpoint="search",
        rcd_type=None,
    )

    result = await runner.run(
        conditions=conditions,
        stop_policy=ListingStopPolicy(
            max_pages_per_condition=3,
            unique_job_cap=None,
            require_empty_confirmation=True,
            page_cap_behavior="retain-and-continue",
        ),
        retry_policy=ListingRetryPolicy(
            max_attempts_per_page=3,
            retry_delays_seconds=(0.0, 0.0),
            page_delay_seconds=0.0,
        ),
        observation_sink=observation_sink,
        staging_sink=staging_sink,
        session_mode="headless",
        request_policy=production_offertoday_listing_request_policy(),
        terminal_policy="result-transition-confirmation-v1",
    )

    assert transport.calls == 1
    assert staging_sink.stage_calls == 0
    assert result.stop_reason == "ip_blocked"
    assert len(observation_sink.observations) == 1
    observation = observation_sink.observations[0]
    assert observation.response_url == blocked_url
    assert observation.api_code == -1000035
    assert observation.retry_reason is None
    assert "response_url" not in listing_observation_to_payload(observation)
    assert offertoday_crawl._production_listing_observation_payload(observation)[
        "response_url"
    ] == blocked_url

    evidence = offertoday_crawl._listing_result_evidence(result)
    assert evidence["blocked_url"] == blocked_url
    assert evidence["code"] == -1000035
    assert evidence["accepted_job_id_count"] == 0
    assert "accepted_job_ids" not in evidence

    manual_action = offertoday_crawl._build_result_manual_action_payload(
        crawl_phase="listing",
        classification=result.stop_reason,
        evidence=evidence,
        request_payload={
            "crawl_phase": "listing",
            "crawl_mode": "headless",
            "max_pages": 3,
        },
    )
    assert manual_action["classification"] == "ip_blocked"
    assert manual_action["stage"] == "listing"
    assert manual_action["blocked_url"] == blocked_url
    assert manual_action["code"] == -1000035
    assert manual_action["resume_supported"] is True


@pytest.mark.asyncio
async def test_offertoday_listing_resumes_same_task_after_preflight_ip_stop() -> None:
    blocked_url = (
        "https://www.offertoday.com/web/passport/cm/verify.html?"
        "code=-1000035&gateway=otd"
    )

    class HealthyBrowser:
        def __init__(self) -> None:
            self.preflight_calls = 0

        async def require_healthy_session(self) -> None:
            self.preflight_calls += 1

    class BlockThenCompleteRunner:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, *, conditions, observation_sink, **_kwargs):
            self.calls += 1
            condition = conditions[0]
            blocked = self.calls == 1
            classification = "ip_blocked" if blocked else "success"
            stop_reason = "ip_blocked" if blocked else "natural_exhaustion"
            response_url = (
                blocked_url
                if blocked
                else "https://www.offertoday.com/wapi/geek/recommend/search/list"
            )
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
                request_fingerprint=f"attempt-{self.calls}",
                classification=classification,
                api_code=-1000035 if blocked else 0,
                reported_total=0 if not blocked else None,
                has_more=False if not blocked else None,
                row_count=0,
                missing_job_id_count=0,
                missing_encrypted_job_id_count=0,
                job_id_fallback_count=0,
                id_pairs=(),
                rows=(),
                identity_issues=(),
                identity_conflicts=(),
                latency_ms=3,
                session_mode="headless",
                retry_reason=None,
                stop_reason=stop_reason,
                response_url=response_url,
            )
            await observation_sink.record_page_attempt(observation)
            outcome = ListingConditionOutcome(
                condition=condition,
                pages_observed=0 if blocked else 1,
                stop_reason=stop_reason,
                is_complete=not blocked,
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
                stop_reason=stop_reason,
                is_complete=not blocked,
            )

    args = SimpleNamespace(
        crawl_job_id="offertoday-same-task",
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
    browser = HealthyBrowser()
    runner = BlockThenCompleteRunner()
    runtime = _IdempotentListingRuntime()

    blocked = await offertoday_crawl._run_listing_phase(
        args=args,
        browser_runtime=browser,
        crawl_runtime=runtime,
        crawl_job_id="offertoday-same-task",
        listing_runner=runner,
    )

    assert blocked.can_proceed_to_detail is False
    assert len(runtime.manual_actions) == 1
    stored_manual_action = runtime.manual_actions[0]
    assert stored_manual_action["crawl_job_id"] == "offertoday-same-task"
    assert stored_manual_action["payload"]["classification"] == "ip_blocked"
    assert stored_manual_action["payload"]["blocked_url"] == blocked_url
    assert stored_manual_action["payload"]["code"] == -1000035

    resumed = await offertoday_crawl._run_listing_phase(
        args=args,
        browser_runtime=browser,
        crawl_runtime=runtime,
        crawl_job_id="offertoday-same-task",
        listing_runner=runner,
    )

    assert resumed.is_complete is True
    assert resumed.can_proceed_to_detail is True
    assert browser.preflight_calls == 2
    assert runner.calls == 2
    assert len(runtime.manual_actions) == 1
    assert all(
        event_payload.get("response_url")
        for event_type, event_payload in runtime.progress_events
        if event_type == "crawl.listing_page_attempt"
    )


@pytest.mark.parametrize("source_site", ["ctgoodjobs", "jobsdb", "offertoday"])
def test_ip_manual_action_normalization_is_source_aware(source_site: str) -> None:
    error = build_session_recovery_manual_action(
        source_site=source_site,
        stage="category_page",
        blocked_url=f"https://example.test/{source_site}",
        classification="ip_blocked",
        evidence={"status_code": 429, "final_url": f"https://example.test/{source_site}"},
    )
    payload = normalize_manual_action_payload(
        error.to_payload(
            crawl_mode="headless",
            browser_channel="msedge",
            browser_profile_path="C:/profiles/test",
        ),
        source_site=source_site,
        request_payload={"crawl_phase": "listing"},
    )

    display_name = {
        "ctgoodjobs": "CTGoodJobs",
        "jobsdb": "JobsDB",
        "offertoday": "OfferToday",
    }[source_site]
    assert payload["classification"] == "ip_blocked"
    assert payload["resume_supported"] is True
    assert display_name in payload["message"]
    assert "Change" in " ".join(payload["instructions"])
    assert payload["resume_context"]["classification"] == "ip_blocked"
    if source_site == "offertoday":
        assert payload["code"] == -1000035
    else:
        assert payload.get("code") is None


@pytest.mark.parametrize("status_code", [403, 429])
def test_public_403_and_429_are_positive_ip_evidence(status_code: int) -> None:
    evidence = classify_public_access_evidence(
        status_code=status_code,
        final_url="https://hk.jobsdb.com/jobs",
    )
    assert evidence is not None
    assert evidence.classification == "ip_blocked"
    assert evidence.status_code == status_code


def test_generic_cloudflare_challenge_is_not_relabelled_as_ip_block() -> None:
    evidence = classify_public_access_evidence(
        status_code=200,
        final_url="https://hk.jobsdb.com/jobs",
        text="Just a moment... cf-challenge",
    )
    assert evidence is not None
    assert evidence.classification == "waf_challenge"
    assert classify_public_access_evidence(
        final_url="https://hk.jobsdb.com/jobs",
        text="ordinary job listing",
    ) is None


def test_content_anomaly_is_resumable_without_ip_guidance() -> None:
    error = build_session_recovery_manual_action(
        source_site="ctgoodjobs",
        stage="detail_page",
        blocked_url="https://jobs.ctgoodjobs.hk/job/job-2",
        classification="content_anomaly",
        evidence={"reason": "missing_company_identity", "consecutive_count": 2},
    )

    payload = error.to_payload(
        crawl_mode="headed",
        browser_channel="msedge",
        browser_profile_path="C:/profiles/ctgoodjobs",
    )
    assert payload["classification"] == "content_anomaly"
    assert payload["resume_supported"] is True
    assert "IP" not in payload["message"]
    assert "structure" in payload["message"].lower()
    assert resolve_resume_detail_statuses(payload["classification"]) == [
        "failed",
        "manual_action_required",
        "pending",
    ]
    assert "completed" not in resolve_resume_detail_statuses(payload["classification"])
    assert "terminal_unavailable" not in resolve_resume_detail_statuses(
        payload["classification"]
    )
    assert resolve_resume_detail_statuses("waf_challenge") == [
        "manual_action_required",
        "pending",
    ]


@pytest.mark.asyncio
async def test_ctgoodjobs_explicit_ip_marker_stops_without_challenge_retries() -> None:
    calls = 0

    async def fetcher(_url: str) -> str:
        nonlocal calls
        calls += 1
        return "Access denied: your IP address has been blocked"

    scraper = CTGoodJobsBrowserPageScraper(
        page_content_fetcher=fetcher,
        max_attempts=3,
    )
    with pytest.raises(ManualActionRequiredError) as raised:
        await scraper.fetch_page_html(
            "https://jobs.ctgoodjobs.hk/jobs",
            stage="category_page",
        )

    assert raised.value.classification == "ip_blocked"
    assert calls == 1


@pytest.mark.asyncio
async def test_ctgoodjobs_waf_evidence_wins_over_unavailable_page_text() -> None:
    async def fetcher(_url: str) -> str:
        return "Just a moment... cf-challenge. Job not found."

    scraper = CTGoodJobsBrowserPageScraper(
        page_content_fetcher=fetcher,
        max_attempts=1,
    )
    with pytest.raises(ManualActionRequiredError) as raised:
        await scraper.fetch_page_html(
            "https://jobs.ctgoodjobs.hk/job/job-1",
            stage="detail_page",
        )

    assert raised.value.classification == "waf_challenge"


@pytest.mark.asyncio
async def test_jobsdb_listing_and_detail_classify_ip_and_waf() -> None:
    async def status_429(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Too many requests")

    async with httpx.AsyncClient(transport=httpx.MockTransport(status_429)) as client:
        with pytest.raises(ManualActionRequiredError) as listing_error:
            await CategoryListScraper().fetch_page(1200, client=client)
    assert listing_error.value.classification == "ip_blocked"

    async def status_403(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Access denied")

    async with httpx.AsyncClient(transport=httpx.MockTransport(status_403)) as client:
        with pytest.raises(ManualActionRequiredError) as detail_error:
            await JobDetailScraper().fetch_job_detail("123456", client=client)
    assert detail_error.value.classification == "ip_blocked"

    async def browser_fetcher(_url: str) -> str:
        return "Just a moment... cf-challenge"

    browser = JobsDBBrowserDetailScraper(page_content_fetcher=browser_fetcher)
    with pytest.raises(ManualActionRequiredError) as browser_error:
        await browser.fetch_job_detail("123456")
    assert browser_error.value.classification == "waf_challenge"


@pytest.mark.asyncio
async def test_jobsdb_auth_status_is_not_relabelled_as_ip() -> None:
    async def status_401(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Authentication required")

    async with httpx.AsyncClient(transport=httpx.MockTransport(status_401)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await CategoryListScraper().fetch_page(1200, client=client)


@pytest.mark.asyncio
async def test_jobsdb_page_sink_commits_prefix_before_later_ip_stop() -> None:
    class FakeCategoryScraper(CategoryListScraper):
        def __init__(self) -> None:
            super().__init__()
            self.min_delay = 0
            self.max_delay = 0
            self.fetch_count = 0

        async def fetch_page(self, classification_id, page=1, client=None):
            self.fetch_count += 1
            if self.fetch_count == 1:
                return {"totalCount": 64, "data": []}
            if page == 2:
                return {"totalCount": 64, "data": [{"id": "job-1"}, {"id": "job-2"}]}
            raise build_session_recovery_manual_action(
                source_site="jobsdb",
                stage="category_page",
                blocked_url="https://hk.jobsdb.com/jobs?page=1",
                classification="ip_blocked",
                evidence={"status_code": 429},
            )

    staged_pages: list[tuple[int, tuple[str, ...]]] = []

    async def page_sink(*, category_id, category_name, page, total_pages, jobs):
        del category_id, category_name, total_pages
        staged_pages.append((page, tuple(str(job["id"]) for job in jobs)))

    with pytest.raises(ManualActionRequiredError):
        await FakeCategoryScraper().scrape_category(
            1200,
            max_pages=2,
            page_sink=page_sink,
        )

    assert staged_pages == [(2, ("job-1", "job-2"))]


@pytest.mark.asyncio
async def test_jobsdb_standalone_resume_replays_committed_pages_idempotently(
    monkeypatch,
    caplog,
) -> None:
    state = {"block": True, "page_starts": []}

    class FakeCategoryScraper:
        async def scrape_category(
            self,
            category_id,
            *,
            max_pages,
            page_sink,
            on_page_start,
        ):
            del max_pages
            state["page_starts"].append((state["block"], 2))
            await on_page_start(
                category_id=category_id,
                category_name="Information Technology",
                page=2,
                total_pages=2,
            )
            await page_sink(
                category_id=category_id,
                category_name="Information Technology",
                page=2,
                total_pages=2,
                jobs=[{"id": "job-1"}, {"id": "job-2"}],
            )
            if state["block"]:
                raise build_session_recovery_manual_action(
                    source_site="jobsdb",
                    stage="category_page",
                    blocked_url="https://hk.jobsdb.com/jobs?page=1",
                    classification="ip_blocked",
                    evidence={"status_code": 429},
                )
            state["page_starts"].append((state["block"], 1))
            await on_page_start(
                category_id=category_id,
                category_name="Information Technology",
                page=1,
                total_pages=2,
            )
            await page_sink(
                category_id=category_id,
                category_name="Information Technology",
                page=1,
                total_pages=2,
                jobs=[{"id": "job-2"}, {"id": "job-3"}],
            )
            return {"job_ids": ["job-1", "job-2", "job-3"]}

    monkeypatch.setattr(jobsdb_crawl, "CategoryListScraper", FakeCategoryScraper)
    runtime = _IdempotentListingRuntime()
    args = SimpleNamespace(
        crawl_job_id="jobsdb-resume-task",
        crawl_mode="headless",
        category_ids=[1200],
        max_pages=2,
        skip_existing=False,
    )

    with caplog.at_level("INFO", logger="jobsdb-crawl"):
        with pytest.raises(ManualActionRequiredError):
            await jobsdb_crawl.run_listing_phase(args, runtime)
        assert runtime.source_job_ids == {"job-1", "job-2"}
        assert state["page_starts"] == [(True, 2)]

        state["block"] = False
        result = await jobsdb_crawl.run_listing_phase(args, runtime)

    assert runtime.source_job_ids == {"job-1", "job-2", "job-3"}
    assert result.job_ids_seen == 3
    assert result.rows_created == 1
    assert state["page_starts"][-2:] == [(False, 2), (False, 1)]
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert messages.count("SCRAPE_LISTING_MANUAL_ACTION") == 1
    assert messages.count("SCRAPE_LISTING_DONE") == 2
    assert "classification=ip_blocked" in messages
    assert "outcome=manual_action_required" in messages
    assert "outcome=completed" in messages


@pytest.mark.asyncio
async def test_ctgoodjobs_standalone_preserves_page_prefix_and_stops_later_requests(
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
        lambda _html, *, page, **_kwargs: {
            "job_ids": [f"ct-job-{page}"],
            "job_urls": [f"https://jobs.ctgoodjobs.hk/job/ct-job-{page}"],
        },
    )

    class FakeBrowser:
        def __init__(self, *, block_on_second_page: bool) -> None:
            self.block_on_second_page = block_on_second_page
            self.calls = 0

        async def fetch_page_html(self, url, **_kwargs):
            self.calls += 1
            if self.block_on_second_page and self.calls == 2:
                raise build_session_recovery_manual_action(
                    source_site="ctgoodjobs",
                    stage="category_page",
                    blocked_url=url,
                    classification="ip_blocked",
                    evidence={"status_code": 403},
                )
            return f"page-{self.calls}"

    args = SimpleNamespace(
        crawl_job_id="ctgoodjobs-resume-task",
        crawl_mode="headed",
        category_ids=["ct-it"],
        max_pages=2,
        skip_existing=False,
    )
    runtime = _IdempotentListingRuntime()
    blocked_browser = FakeBrowser(block_on_second_page=True)

    with caplog.at_level("INFO", logger="ctgoodjobs-crawl"):
        with pytest.raises(ManualActionRequiredError):
            await ctgoodjobs_crawl._run_listing_phase(
                args,
                runtime,
                blocked_browser,
            )
        assert blocked_browser.calls == 2
        assert runtime.source_job_ids == {"ct-job-1"}

        resumed_browser = FakeBrowser(block_on_second_page=False)
        result = await ctgoodjobs_crawl._run_listing_phase(
            args,
            runtime,
            resumed_browser,
        )

    assert result["pages_processed"] == 2
    assert runtime.source_job_ids == {"ct-job-1", "ct-job-2"}
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert messages.count("SCRAPE_LISTING_MANUAL_ACTION") == 1
    assert messages.count("SCRAPE_LISTING_DONE") == 2
    assert "classification=ip_blocked" in messages
    assert "outcome=manual_action_required" in messages
    assert "outcome=completed" in messages


@pytest.mark.asyncio
async def test_generic_network_failures_remain_non_ip() -> None:
    async def broken_ct_fetcher(_url: str) -> str:
        raise OSError("temporary DNS failure")

    ct_scraper = CTGoodJobsBrowserPageScraper(
        page_content_fetcher=broken_ct_fetcher,
        max_attempts=1,
    )
    with pytest.raises(Exception) as ct_error:
        await ct_scraper.fetch_page_html(
            "https://jobs.ctgoodjobs.hk/jobs",
            stage="category_page",
        )
    assert not isinstance(ct_error.value, ManualActionRequiredError)

    async def connect_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("temporary DNS failure", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(connect_error)
    ) as client:
        result = await JobDetailScraper().fetch_job_detail(
            "123456",
            client=client,
        )
    assert result is None
