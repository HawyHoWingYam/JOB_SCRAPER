from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.offertoday_research_live_service import (
    OfferTodayResearchLiveService,
    detail_result_to_observation,
)
from app.services.offertoday_research_staging_service import (
    ResearchNoopListingStagingSink,
)
from app.sources.offertoday.detail_identity import (
    OfferTodayDetailFetchResult,
    OfferTodayDetailIdentity,
    OfferTodayEncryptedJobIdSource,
)
from app.sources.offertoday.listing_runner import (
    ListingPageObservation,
    ListingRetryPolicy,
    ListingRunResult,
    ListingStopPolicy,
    OfferTodayIdentityPair,
)
from app.sources.offertoday.research.live_contracts import DetailSmokeTarget
from app.sources.offertoday.research.smoke import build_runtime_smoke_condition
from app.sources.offertoday.response_policy import (
    OfferTodayResponseClassification,
    OfferTodayResponseKind,
)


def listing_result(
    count: int = 20,
    *,
    identity_source: OfferTodayEncryptedJobIdSource = "encryptJobId",
) -> ListingRunResult:
    identities = tuple(
        OfferTodayIdentityPair(
            job_id=f"j{index}",
            encrypted_job_id=(
                f"j{index}" if identity_source == "jobId_fallback" else f"e{index}"
            ),
            encrypted_job_id_source=identity_source,
        )
        for index in range(1, count + 1)
    )
    condition = build_runtime_smoke_condition()
    observation = ListingPageObservation(
        condition_id=condition.condition_id,
        search_family=condition.search_family,
        category_id=condition.category_id,
        keyword=condition.keyword,
        endpoint=condition.endpoint,
        rcd_type=condition.rcd_type,
        page=1,
        attempt=1,
        request_fingerprint="a" * 64,
        classification="success",
        api_code=0,
        reported_total=100,
        has_more=True,
        row_count=count,
        missing_job_id_count=0,
        missing_encrypted_job_id_count=0,
        job_id_fallback_count=(count if identity_source == "jobId_fallback" else 0),
        id_pairs=identities,
        rows=(),
        identity_issues=(),
        identity_conflicts=(),
        latency_ms=25,
        session_mode="fresh-headless",
        retry_reason=None,
        stop_reason=None,
    )
    return ListingRunResult(
        ordered_job_ids=tuple(item.job_id for item in identities),
        accepted_job_ids=tuple(item.job_id for item in identities),
        id_pairs=identities,
        observations=(observation,),
        condition_outcomes=(),
        identity_conflicts=(),
        identity_issues=(),
        gaps=(),
        stop_reason="page_cap",
        is_complete=False,
    )


def detail_result(
    job_id: str,
    encrypted_job_id: str,
    *,
    encrypted_job_id_source: OfferTodayEncryptedJobIdSource = "encryptJobId",
    kind: OfferTodayResponseKind = OfferTodayResponseKind.SUCCESS,
) -> OfferTodayDetailFetchResult:
    code_by_kind = {
        OfferTodayResponseKind.SUCCESS: 0,
        OfferTodayResponseKind.TERMINAL_UNAVAILABLE: 2520,
        OfferTodayResponseKind.AUTH_EXPIRED: 1002,
        OfferTodayResponseKind.IP_BLOCKED: -1000035,
    }
    stop_batch = kind not in {
        OfferTodayResponseKind.SUCCESS,
        OfferTodayResponseKind.TERMINAL_UNAVAILABLE,
    }
    classification = OfferTodayResponseClassification(
        kind=kind,
        code=code_by_kind.get(kind),
        message=None,
        data={"jobId": job_id} if kind is OfferTodayResponseKind.SUCCESS else None,
        raw_payload={"code": code_by_kind.get(kind)},
        retryable=kind is OfferTodayResponseKind.TRANSIENT_TRANSPORT,
        stop_batch=stop_batch,
    )
    succeeded = kind is OfferTodayResponseKind.SUCCESS
    return OfferTodayDetailFetchResult(
        identity=OfferTodayDetailIdentity(
            job_id=job_id,
            encrypted_job_id=encrypted_job_id,
            encrypted_job_id_source=encrypted_job_id_source,
        ),
        classification=classification,
        raw_response=classification.raw_payload,
        parsed_detail={"job_id": job_id} if succeeded else None,
        canonical_detail=(
            {
                "job_id": job_id,
                "encrypted_job_id": encrypted_job_id,
                "encrypted_job_id_source": encrypted_job_id_source,
                "title": f"Title {job_id}",
                "company_name": "Company",
                "description_text": "Description",
            }
            if succeeded
            else None
        ),
    )


class FakeRuntime:
    def __init__(self) -> None:
        self.session_checks = 0
        self.detail_json_calls: list[tuple[str, str | None]] = []

    async def fetch_detail_json(
        self,
        *,
        job_id: str,
        encrypted_job_id: str | None = None,
    ) -> dict:
        self.detail_json_calls.append((job_id, encrypted_job_id))
        return {}

    async def check_session(self):
        self.session_checks += 1
        raise AssertionError("run_smoke must not issue a separate session probe")

    async def require_healthy_session(self):
        self.session_checks += 1
        raise AssertionError("run_smoke must not issue a separate session probe")


class FakeRunner:
    def __init__(self, result: ListingRunResult) -> None:
        self.result = result
        self.calls: list[dict] = []

    async def run(self, **kwargs) -> ListingRunResult:
        self.calls.append(kwargs)
        return self.result


class RunnerFactory:
    def __init__(self, result: ListingRunResult) -> None:
        self.runner = FakeRunner(result)
        self.transports: list[object] = []

    def __call__(self, transport) -> FakeRunner:
        self.transports.append(transport)
        return self.runner


class FakeDetailScraper:
    def __init__(self, result_provider) -> None:
        self.result_provider = result_provider
        self.calls: list[
            tuple[str, str | None, OfferTodayEncryptedJobIdSource | None]
        ] = []

    async def fetch_job_detail(
        self,
        job_id: str,
        *,
        encrypted_job_id: str | None = None,
        encrypted_job_id_source: OfferTodayEncryptedJobIdSource | None = None,
    ) -> OfferTodayDetailFetchResult:
        self.calls.append((job_id, encrypted_job_id, encrypted_job_id_source))
        result = self.result_provider(
            job_id,
            encrypted_job_id,
            encrypted_job_id_source,
        )
        if isinstance(result, BaseException):
            raise result
        return result


class DetailScraperFactory:
    def __init__(self, result_provider=None) -> None:
        self.kwargs: list[dict] = []
        self.scraper = FakeDetailScraper(
            result_provider
            or (
                lambda job_id, encrypted_job_id, encrypted_job_id_source: detail_result(
                    job_id,
                    encrypted_job_id,
                    encrypted_job_id_source=(
                        encrypted_job_id_source or "encryptJobId"
                    ),
                )
            )
        )

    def __call__(self, **kwargs) -> FakeDetailScraper:
        self.kwargs.append(kwargs)
        return self.scraper


class FakeObservationService:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self.detail_attempts: list[dict] = []

    def record_event(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))

    def record_detail_attempt(self, payload: dict) -> None:
        self.detail_attempts.append(payload)


def deterministic_clocks():
    timestamps = iter(
        datetime(2026, 7, 11, tzinfo=UTC) + timedelta(seconds=index)
        for index in range(100)
    )
    clock_values = iter(float(index) for index in range(100))
    return lambda: next(timestamps), lambda: next(clock_values)


@pytest.mark.asyncio
async def test_run_smoke_uses_exact_listing_budget_and_no_session_preflight() -> None:
    runtime = FakeRuntime()
    runner_factory = RunnerFactory(listing_result())
    detail_factory = DetailScraperFactory()
    observation_service = FakeObservationService()
    now, clock = deterministic_clocks()

    service = OfferTodayResearchLiveService(
        runner_factory=runner_factory,
        detail_scraper_factory=detail_factory,
        sleep=lambda _seconds: _completed_awaitable(),
        now=now,
        clock=clock,
    )
    await service.run_smoke(
        runtime=runtime,
        observation_service=observation_service,
    )

    assert runner_factory.transports == [runtime]
    assert len(runner_factory.runner.calls) == 1
    call = runner_factory.runner.calls[0]
    assert call["conditions"] == (build_runtime_smoke_condition(),)
    assert call["stop_policy"] == ListingStopPolicy(
        max_pages_per_condition=1,
        unique_job_cap=None,
        require_empty_confirmation=False,
    )
    assert call["retry_policy"] == ListingRetryPolicy(
        max_attempts_per_page=1,
        retry_delays_seconds=(),
        page_delay_seconds=0.0,
    )
    assert call["observation_sink"] is observation_service
    assert isinstance(call["staging_sink"], ResearchNoopListingStagingSink)
    assert call["session_mode"] == "fresh-headless"
    assert runtime.session_checks == 0


async def _completed_awaitable() -> None:
    return None


@pytest.mark.asyncio
async def test_run_smoke_fetches_twenty_in_order_with_nineteen_delays() -> None:
    runtime = FakeRuntime()
    runner_factory = RunnerFactory(listing_result())
    detail_factory = DetailScraperFactory()
    observation_service = FakeObservationService()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    now, clock = deterministic_clocks()
    service = OfferTodayResearchLiveService(
        runner_factory=runner_factory,
        detail_scraper_factory=detail_factory,
        sleep=fake_sleep,
        now=now,
        clock=clock,
    )

    execution = await service.run_smoke(
        runtime=runtime,
        observation_service=observation_service,
    )

    expected_calls = [
        (f"j{index}", f"e{index}", "encryptJobId")
        for index in range(1, 21)
    ]
    assert detail_factory.scraper.calls == expected_calls
    assert sleeps == [3.0] * 19
    assert execution.decision.smoke_passed is True
    assert execution.would_stage_rows == 0
    assert execution.stage_calls == 0
    assert len(execution.detail_observations) == 20
    assert len(observation_service.detail_attempts) == 20
    assert observation_service.events[0][0] == "research.detail_cohort_frozen"
    assert observation_service.events[0][1]["count"] == 20
    first = observation_service.detail_attempts[0]
    assert first["target"]["position"] == 1
    assert first["target"]["job_id"] == "j1"
    assert first["target"]["encrypted_job_id"] == "e1"
    assert first["target"]["encrypted_job_id_source"] == "encryptJobId"
    assert len(first["target"]["job_id_hash"]) == 64
    assert len(first["target"]["encrypted_job_id_hash"]) == 64
    assert len(first["target"]["identity_resolution_hash"]) == 64
    assert first["started_at"].endswith("+00:00")
    assert first["completed_at"].endswith("+00:00")
    assert first["latency_ms"] == 1000

    assert len(detail_factory.kwargs) == 1
    factory_kwargs = detail_factory.kwargs[0]
    assert factory_kwargs["headed"] is False
    assert factory_kwargs["detail_json_fetcher"].__self__ is runtime
    assert factory_kwargs["detail_json_fetcher"].__func__ is FakeRuntime.fetch_detail_json


@pytest.mark.asyncio
async def test_run_smoke_passes_jobid_fallback_provenance_to_detail_scraper() -> None:
    detail_factory = DetailScraperFactory()
    now, clock = deterministic_clocks()
    service = OfferTodayResearchLiveService(
        runner_factory=RunnerFactory(
            listing_result(identity_source="jobId_fallback")
        ),
        detail_scraper_factory=detail_factory,
        sleep=lambda _seconds: _completed_awaitable(),
        now=now,
        clock=clock,
    )

    execution = await service.run_smoke(
        runtime=FakeRuntime(),
        observation_service=FakeObservationService(),
    )

    assert detail_factory.scraper.calls[0] == (
        "j1",
        "j1",
        "jobId_fallback",
    )
    assert execution.decision.smoke_passed is True


@pytest.mark.asyncio
async def test_terminal_unavailable_continues_without_retry_or_replacement() -> None:
    def result_provider(
        job_id: str,
        encrypted_job_id: str,
        encrypted_job_id_source: OfferTodayEncryptedJobIdSource,
    ):
        return detail_result(
            job_id,
            encrypted_job_id,
            encrypted_job_id_source=encrypted_job_id_source,
            kind=(
                OfferTodayResponseKind.TERMINAL_UNAVAILABLE
                if job_id == "j7"
                else OfferTodayResponseKind.SUCCESS
            ),
        )

    runner_factory = RunnerFactory(listing_result())
    detail_factory = DetailScraperFactory(result_provider)
    now, clock = deterministic_clocks()
    service = OfferTodayResearchLiveService(
        runner_factory=runner_factory,
        detail_scraper_factory=detail_factory,
        sleep=lambda _seconds: _completed_awaitable(),
        now=now,
        clock=clock,
    )

    execution = await service.run_smoke(
        runtime=FakeRuntime(),
        observation_service=FakeObservationService(),
    )

    assert len(detail_factory.scraper.calls) == 20
    assert detail_factory.scraper.calls.count(("j7", "e7", "encryptJobId")) == 1
    assert execution.decision.smoke_passed is True
    assert execution.decision.terminal_count == 1
    assert execution.decision.success_count == 19


@pytest.mark.parametrize(
    "kind",
    [
        OfferTodayResponseKind.AUTH_EXPIRED,
        OfferTodayResponseKind.WAF_CHALLENGE,
        OfferTodayResponseKind.IP_BLOCKED,
        OfferTodayResponseKind.ID_MISMATCH,
    ],
)
@pytest.mark.asyncio
async def test_batch_stop_stops_after_first_target_and_accounts_unattempted(
    kind: OfferTodayResponseKind,
) -> None:
    def result_provider(
        job_id: str,
        encrypted_job_id: str,
        encrypted_job_id_source: OfferTodayEncryptedJobIdSource,
    ):
        return detail_result(
            job_id,
            encrypted_job_id,
            encrypted_job_id_source=encrypted_job_id_source,
            kind=kind,
        )

    detail_factory = DetailScraperFactory(result_provider)
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    now, clock = deterministic_clocks()
    service = OfferTodayResearchLiveService(
        runner_factory=RunnerFactory(listing_result()),
        detail_scraper_factory=detail_factory,
        sleep=fake_sleep,
        now=now,
        clock=clock,
    )

    execution = await service.run_smoke(
        runtime=FakeRuntime(),
        observation_service=FakeObservationService(),
    )

    assert detail_factory.scraper.calls == [("j1", "e1", "encryptJobId")]
    assert sleeps == []
    assert execution.decision.smoke_passed is False
    assert execution.decision.stop_reason == kind.value
    assert execution.decision.attempted_count == 1
    assert execution.decision.unattempted_count == 19


@pytest.mark.asyncio
async def test_fewer_than_twenty_targets_makes_zero_detail_calls() -> None:
    detail_factory = DetailScraperFactory()
    observation_service = FakeObservationService()
    now, clock = deterministic_clocks()
    service = OfferTodayResearchLiveService(
        runner_factory=RunnerFactory(listing_result(count=19)),
        detail_scraper_factory=detail_factory,
        sleep=lambda _seconds: _completed_awaitable(),
        now=now,
        clock=clock,
    )

    execution = await service.run_smoke(
        runtime=FakeRuntime(),
        observation_service=observation_service,
    )

    assert detail_factory.kwargs == []
    assert detail_factory.scraper.calls == []
    assert observation_service.detail_attempts == []
    assert execution.decision.stop_reason == "insufficient_valid_detail_targets"


@pytest.mark.asyncio
async def test_unexpected_detail_exception_propagates_without_retry() -> None:
    error = TypeError("sensitive detail failure")
    detail_factory = DetailScraperFactory(
        lambda _job_id, _encrypted_job_id, _encrypted_job_id_source: error
    )
    now, clock = deterministic_clocks()
    service = OfferTodayResearchLiveService(
        runner_factory=RunnerFactory(listing_result()),
        detail_scraper_factory=detail_factory,
        sleep=lambda _seconds: _completed_awaitable(),
        now=now,
        clock=clock,
    )

    with pytest.raises(TypeError) as exc_info:
        await service.run_smoke(
            runtime=FakeRuntime(),
            observation_service=FakeObservationService(),
        )

    assert exc_info.value is error
    assert detail_factory.scraper.calls == [("j1", "e1", "encryptJobId")]


def test_detail_result_conversion_preserves_classification_and_content_flags() -> None:
    item = DetailSmokeTarget(position=1, job_id="j1", encrypted_job_id="e1")

    observation = detail_result_to_observation(
        target=item,
        result=detail_result("j1", "e1"),
        started_at="2026-07-11T00:00:00+00:00",
        completed_at="2026-07-11T00:00:01+00:00",
        latency_ms=1000,
    )

    assert observation.target is item
    assert observation.classification == "success"
    assert observation.api_code == 0
    assert observation.identity_valid is True
    assert observation.parsed is True
    assert observation.has_title is True
    assert observation.has_company is True
    assert observation.has_description is True
    assert observation.stop_batch is False


def test_detail_result_conversion_rejects_same_ids_with_different_provenance() -> None:
    item = DetailSmokeTarget(
        position=1,
        job_id="j1",
        encrypted_job_id="j1",
        encrypted_job_id_source="jobId_fallback",
    )

    observation = detail_result_to_observation(
        target=item,
        result=detail_result(
            "j1",
            "j1",
            encrypted_job_id_source="encryptJobId",
        ),
        started_at="2026-07-11T00:00:00+00:00",
        completed_at="2026-07-11T00:00:01+00:00",
        latency_ms=1000,
    )

    assert observation.identity_valid is False
