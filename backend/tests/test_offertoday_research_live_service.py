from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from app.scraper.offertoday.category_registry import (
    OFFERTODAY_CATEGORIES_L1,
    OFFERTODAY_CATEGORY_CATALOG_VERSION,
    offertoday_category_catalog_hash,
)
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
from app.sources.offertoday.listing_contract import (
    OfferTodayBrowserContextLostError,
    OfferTodayListingTransportResult,
    offertoday_endpoint_contract,
)
from app.sources.offertoday.listing_runner import (
    ListingConditionOutcome,
    ListingPageObservation,
    ListingRetryPolicy,
    ListingRunResult,
    ListingStopPolicy,
    OfferTodayIdentityPair,
)
from app.sources.offertoday.research.calibration import (
    build_calibration_conditions,
    build_pilot_conditions,
)
from app.sources.offertoday.research.live_contracts import (
    CensusCandidate,
    DetailSmokeTarget,
    DiscoveryPolicyCandidateV2,
)
from app.sources.offertoday.research.partition_research import (
    OFFERTODAY_PARTITION_CATALOG,
    build_endpoint_probe_plan,
    build_partition_probe_plan,
    offertoday_partition_catalog_hash,
    phase_c_request_policy_hash,
    top_level_partition,
)
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
    stop_reason = "target_cap" if count >= 20 else "page_cap"
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
        stop_reason=stop_reason,
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
        stop_reason=stop_reason,
        is_complete=False,
    )


def two_page_listing_result(count: int = 20) -> ListingRunResult:
    if count <= 10:
        raise ValueError("two-page fixture requires more than ten identities")

    result = listing_result(count=count)
    first_page_pairs = result.id_pairs[:10]
    second_page_pairs = result.id_pairs[10:]
    first_page = replace(
        result.observations[0],
        row_count=len(first_page_pairs),
        id_pairs=first_page_pairs,
        stop_reason=None,
    )
    second_page = replace(
        result.observations[0],
        page=2,
        request_fingerprint="b" * 64,
        row_count=len(second_page_pairs),
        id_pairs=second_page_pairs,
        stop_reason=result.stop_reason,
    )
    return replace(result, observations=(first_page, second_page))


def bounded_listing_result(
    condition,
    *,
    pages_observed: int = 3,
    stop_reason: str = "page_cap",
    classification: str = "success",
) -> ListingRunResult:
    base = listing_result()
    if classification == "success":
        observations = tuple(
            replace(
                base.observations[0],
                condition_id=condition.condition_id,
                search_family=condition.search_family,
                category_id=condition.category_id,
                keyword=condition.keyword,
                endpoint=condition.endpoint,
                rcd_type=condition.rcd_type,
                page=page,
                request_fingerprint=f"{page:064x}",
                stop_reason=(stop_reason if page == pages_observed else None),
            )
            for page in range(1, pages_observed + 1)
        )
    else:
        observations = (
            replace(
                base.observations[0],
                condition_id=condition.condition_id,
                search_family=condition.search_family,
                category_id=condition.category_id,
                keyword=condition.keyword,
                endpoint=condition.endpoint,
                rcd_type=condition.rcd_type,
                page=1,
                request_fingerprint="f" * 64,
                classification=classification,
                api_code=1002 if classification == "auth_expired" else None,
                row_count=0,
                id_pairs=(),
                stop_reason=stop_reason,
            ),
        )
    is_complete = stop_reason == "natural_exhaustion"
    return replace(
        base,
        observations=observations,
        condition_outcomes=(
            ListingConditionOutcome(
                condition=condition,
                pages_observed=pages_observed,
                stop_reason=stop_reason,
                is_complete=is_complete,
            ),
        ),
        stop_reason=stop_reason,
        is_complete=is_complete,
    )


def census_candidate() -> CensusCandidate:
    conditions = build_pilot_conditions("search", None)
    return CensusCandidate(
        endpoint="search",
        rcd_type=None,
        category_ids=tuple(condition.category_id for condition in conditions),
        page_size=50,
        max_pages_per_condition=500,
        require_empty_confirmation=True,
        max_attempts_per_page=3,
        retry_delays_seconds=(5.0, 15.0),
        page_delay_range_seconds=(3.0, 5.0),
        session_mode="fresh-headless",
        fixed_repeat_category_ids=(118000, 112000, 127000),
        source_artifact_hash="a" * 64,
        rejected_variants=(),
    )


def census_listing_result(
    candidate: CensusCandidate,
    *,
    incomplete_index: int | None = None,
) -> ListingRunResult:
    conditions = build_pilot_conditions(candidate.endpoint, candidate.rcd_type)
    outcome_count = (
        len(conditions) if incomplete_index is None else incomplete_index + 1
    )
    outcomes = tuple(
        ListingConditionOutcome(
            condition=condition,
            pages_observed=2,
            stop_reason=(
                "page_cap"
                if incomplete_index is not None and index == incomplete_index
                else "natural_exhaustion"
            ),
            is_complete=not (
                incomplete_index is not None and index == incomplete_index
            ),
        )
        for index, condition in enumerate(conditions[:outcome_count])
    )
    base = listing_result()
    return replace(
        base,
        condition_outcomes=outcomes,
        stop_reason=(
            "page_cap" if incomplete_index is not None else "natural_exhaustion"
        ),
        is_complete=incomplete_index is None,
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


class SequenceRunnerFactory:
    def __init__(self, results: tuple[ListingRunResult, ...]) -> None:
        self.results = results
        self.runners: list[FakeRunner] = []
        self.transports: list[object] = []

    def __call__(self, transport) -> FakeRunner:
        index = len(self.runners)
        if index >= len(self.results):
            raise AssertionError("unexpected bounded runner construction")
        runner = FakeRunner(self.results[index])
        self.runners.append(runner)
        self.transports.append(transport)
        return runner


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
                    encrypted_job_id_source=(encrypted_job_id_source or "encryptJobId"),
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
        self.page_attempts: list[ListingPageObservation] = []
        self.condition_outcomes: list[ListingConditionOutcome] = []

    def record_event(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))

    def record_detail_attempt(self, payload: dict) -> None:
        self.detail_attempts.append(payload)

    async def record_page_attempt(self, observation) -> None:
        self.page_attempts.append(observation)

    async def record_condition_outcome(self, outcome) -> None:
        self.condition_outcomes.append(outcome)


def deterministic_clocks():
    timestamps = iter(
        datetime(2026, 7, 11, tzinfo=UTC) + timedelta(seconds=index)
        for index in range(100)
    )
    clock_values = iter(float(index) for index in range(100))
    return lambda: next(timestamps), lambda: next(clock_values)


class BakeoffRuntime:
    def __init__(self, factory, runtime_index: int) -> None:
        self.factory = factory
        self.runtime_index = runtime_index
        self.browser_context_hash = hashlib.sha256(
            f"bakeoff-context-{runtime_index}".encode()
        ).hexdigest()
        self.requests: list[dict] = []

    async def __aenter__(self):
        self.factory.entered.append(self)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.factory.exited.append(self)

    async def fetch_listing_page(self, payload, *, listing_url=None):
        self.requests.append(deepcopy(payload))
        category_id = payload["jobFunctionCodes"][0]
        page = payload["page"]
        session_id = payload.get("sessionId") or f"server-session-{category_id}"
        rows = (
            [
                {
                    "jobId": f"{category_id}-{payload['pageSize']}",
                    "encryptJobId": f"enc-{category_id}-{payload['pageSize']}",
                    "jobName": "Platform Engineer",
                    "companyName": "Example",
                }
            ]
            if page == 1
            else []
        )
        response = {
            "code": 0,
            "data": {
                "pageSize": 10,
                "sessionId": session_id,
                "supplePage": page,
                "suppleAmount": 0,
                "suppleType": 0,
                "hasMore": False,
                "total": 100,
                "resultList": rows,
                "suppleRcdList": [],
            },
        }
        return OfferTodayListingTransportResult(
            payload=response,
            browser_context_hash=self.browser_context_hash,
        )


class BakeoffRuntimeFactory:
    def __init__(self) -> None:
        self.created: list[BakeoffRuntime] = []
        self.entered: list[BakeoffRuntime] = []
        self.exited: list[BakeoffRuntime] = []

    def __call__(self, *, headed: bool):
        assert headed is False
        runtime = BakeoffRuntime(self, len(self.created) + 1)
        self.created.append(runtime)
        return runtime


class RetryOnceBakeoffRuntime(BakeoffRuntime):
    async def fetch_listing_page(self, payload, *, listing_url=None):
        if not self.factory.retry_emitted:
            self.factory.retry_emitted = True
            self.requests.append(deepcopy(payload))
            raise ConnectionError("transient listing failure")
        return await super().fetch_listing_page(payload, listing_url=listing_url)


class RetryOnceBakeoffRuntimeFactory(BakeoffRuntimeFactory):
    def __init__(self) -> None:
        super().__init__()
        self.retry_emitted = False

    def __call__(self, *, headed: bool):
        assert headed is False
        runtime = RetryOnceBakeoffRuntime(self, len(self.created) + 1)
        self.created.append(runtime)
        return runtime


class BrowserLossBakeoffRuntime(BakeoffRuntime):
    async def fetch_listing_page(self, payload, *, listing_url=None):
        if not self.factory.loss_emitted:
            self.factory.loss_emitted = True
            self.requests.append(deepcopy(payload))
            raise OfferTodayBrowserContextLostError("browser context lost")
        return await super().fetch_listing_page(payload, listing_url=listing_url)


class BrowserLossBakeoffRuntimeFactory(BakeoffRuntimeFactory):
    def __init__(self) -> None:
        super().__init__()
        self.loss_emitted = False

    def __call__(self, *, headed: bool):
        assert headed is False
        runtime = BrowserLossBakeoffRuntime(self, len(self.created) + 1)
        self.created.append(runtime)
        return runtime


class MissingCursorBakeoffRuntime(BakeoffRuntime):
    async def fetch_listing_page(self, payload, *, listing_url=None):
        result = await super().fetch_listing_page(payload, listing_url=listing_url)
        response = deepcopy(result.payload)
        if isinstance(response, dict) and isinstance(response.get("data"), dict):
            for field_name in (
                "sessionId",
                "supplePage",
                "suppleAmount",
                "suppleType",
            ):
                response["data"].pop(field_name, None)
        return OfferTodayListingTransportResult(
            payload=response,
            browser_context_hash=self.browser_context_hash,
        )


class MissingCursorBakeoffRuntimeFactory(BakeoffRuntimeFactory):
    def __call__(self, *, headed: bool):
        assert headed is False
        runtime = MissingCursorBakeoffRuntime(self, len(self.created) + 1)
        self.created.append(runtime)
        return runtime


class UnexpectedBakeoffRuntime(BakeoffRuntime):
    async def fetch_listing_page(self, payload, *, listing_url=None):
        self.factory.request_count += 1
        if self.factory.request_count == self.factory.fail_on_request:
            raise RuntimeError("secret runtime failure details")
        return await super().fetch_listing_page(payload, listing_url=listing_url)


class UnexpectedBakeoffRuntimeFactory(BakeoffRuntimeFactory):
    def __init__(self, *, fail_on_request: int) -> None:
        super().__init__()
        self.fail_on_request = fail_on_request
        self.request_count = 0

    def __call__(self, *, headed: bool):
        assert headed is False
        runtime = UnexpectedBakeoffRuntime(self, len(self.created) + 1)
        self.created.append(runtime)
        return runtime


class ExitFailureBakeoffRuntime(BakeoffRuntime):
    async def __aexit__(self, exc_type, exc, tb):
        await super().__aexit__(exc_type, exc, tb)
        if len(self.requests) >= 6 and not self.factory.exit_failure_emitted:
            self.factory.exit_failure_emitted = True
            raise RuntimeError("secret runtime close failure details")


class ExitFailureBakeoffRuntimeFactory(BakeoffRuntimeFactory):
    def __init__(self) -> None:
        super().__init__()
        self.exit_failure_emitted = False

    def __call__(self, *, headed: bool):
        assert headed is False
        runtime = ExitFailureBakeoffRuntime(self, len(self.created) + 1)
        self.created.append(runtime)
        return runtime


class IncrementingClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 0.01
        return self.value


@pytest.mark.asyncio
async def test_run_pagination_bakeoff_honors_frozen_order_and_runtime_lifecycles() -> (
    None
):
    runtime_factory = BakeoffRuntimeFactory()
    observation_service = FakeObservationService()
    staging_sink = ResearchNoopListingStagingSink()

    async def no_sleep(_seconds: float) -> None:
        return None

    service = OfferTodayResearchLiveService(
        sleep=no_sleep,
        clock=IncrementingClock(),
    )
    execution = await service.run_pagination_bakeoff(
        runtime_factory=runtime_factory,
        observation_service=observation_service,
        repeat_index=1,
        order_seed=20260713,
        staging_sink=staging_sink,
    )

    assert len(execution.order) == 15
    assert len(execution.executions) == 15
    assert len(observation_service.page_attempts) == 30
    assert len(observation_service.condition_outcomes) == 15
    assert staging_sink.stage_calls == 15
    assert staging_sink.would_stage_rows == 15
    assert len(runtime_factory.created) == 12
    assert len(runtime_factory.exited) == len(runtime_factory.entered)
    assert {id(item) for item in runtime_factory.exited} == {
        id(item) for item in runtime_factory.entered
    }

    by_variant = {
        variant_id: [
            item for item in execution.executions if item.variant_id == variant_id
        ]
        for variant_id in {
            item.variant_id for item in execution.executions
        }
    }
    shared_hashes = {
        observation.cursor_evidence.browser_context_hash
        for item in by_variant["ui-cursor"]
        for observation in item.result.observations
    }
    condition_hashes = {
        observation.cursor_evidence.browser_context_hash
        for item in by_variant["ui-cursor-same-browser"]
        for observation in item.result.observations
    }
    assert len(shared_hashes) == 1
    assert len(condition_hashes) == 3
    for item in by_variant["ui-cursor-restart"]:
        assert len(
            {
                observation.cursor_evidence.browser_context_hash
                for observation in item.result.observations
            }
        ) == 2


@pytest.mark.asyncio
async def test_run_pagination_bakeoff_uses_cursor_payload_only_after_page_one() -> (
    None
):
    runtime_factory = BakeoffRuntimeFactory()

    async def no_sleep(_seconds: float) -> None:
        return None

    service = OfferTodayResearchLiveService(
        sleep=no_sleep,
        clock=IncrementingClock(),
    )
    execution = await service.run_pagination_bakeoff(
        runtime_factory=runtime_factory,
        observation_service=FakeObservationService(),
        repeat_index=2,
        order_seed=20260713,
    )

    for item in execution.executions:
        observations = item.result.observations
        assert observations[0].cursor_evidence.cursor_input is None
        if item.variant_id == "stateless-current":
            assert observations[1].cursor_evidence.cursor_input is None
        else:
            assert observations[1].cursor_evidence.cursor_input is not None
            assert (
                observations[0].cursor_evidence.cursor_output.cursor_hash
                == observations[1].cursor_evidence.cursor_input.cursor_hash
            )


@pytest.mark.asyncio
async def test_pagination_bakeoff_retries_same_logical_page_in_same_runtime() -> None:
    runtime_factory = RetryOnceBakeoffRuntimeFactory()
    observation_service = FakeObservationService()

    async def no_sleep(_seconds: float) -> None:
        return None

    service = OfferTodayResearchLiveService(
        sleep=no_sleep,
        clock=IncrementingClock(),
    )
    await service.run_pagination_bakeoff(
        runtime_factory=runtime_factory,
        observation_service=observation_service,
        repeat_index=1,
        order_seed=20260713,
    )

    retry, success = observation_service.page_attempts[:2]
    assert retry.classification == "transient_transport"
    assert retry.cursor_evidence.logical_request_id == (
        success.cursor_evidence.logical_request_id
    )
    assert retry.cursor_evidence.browser_context_hash == (
        success.cursor_evidence.browser_context_hash
    )
    assert retry.cursor_evidence.physical_attempt_id != (
        success.cursor_evidence.physical_attempt_id
    )
    assert len(runtime_factory.created) == 12
    assert len(runtime_factory.exited) == len(runtime_factory.entered)


@pytest.mark.asyncio
async def test_pagination_bakeoff_restarts_page_one_after_browser_loss() -> None:
    runtime_factory = BrowserLossBakeoffRuntimeFactory()
    observation_service = FakeObservationService()

    async def no_sleep(_seconds: float) -> None:
        return None

    service = OfferTodayResearchLiveService(
        sleep=no_sleep,
        clock=IncrementingClock(),
    )
    await service.run_pagination_bakeoff(
        runtime_factory=runtime_factory,
        observation_service=observation_service,
        repeat_index=1,
        order_seed=20260713,
    )

    lost, restarted = observation_service.page_attempts[:2]
    assert lost.retry_reason == "browser_context_lost_restart"
    assert lost.page == restarted.page == 1
    assert lost.cursor_evidence.condition_restart_index == 0
    assert restarted.cursor_evidence.condition_restart_index == 1
    assert lost.cursor_evidence.browser_context_hash != (
        restarted.cursor_evidence.browser_context_hash
    )
    assert len(runtime_factory.created) == 13
    assert len(runtime_factory.exited) == len(runtime_factory.entered)


@pytest.mark.asyncio
async def test_pagination_bakeoff_cursor_violation_hard_stops_and_closes() -> None:
    runtime_factory = MissingCursorBakeoffRuntimeFactory()

    async def no_sleep(_seconds: float) -> None:
        return None

    service = OfferTodayResearchLiveService(
        sleep=no_sleep,
        clock=IncrementingClock(),
    )

    execution = await service.run_pagination_bakeoff(
        runtime_factory=runtime_factory,
        observation_service=FakeObservationService(),
        repeat_index=1,
        order_seed=20260713,
    )

    assert execution.failure_reason == "hard_stop:cursor_contract_violation"
    assert len(execution.executions) < len(execution.order)
    assert runtime_factory.entered
    assert len(runtime_factory.exited) == len(runtime_factory.entered)


@pytest.mark.asyncio
async def test_pagination_bakeoff_unexpected_error_returns_type_only_prefix() -> None:
    runtime_factory = UnexpectedBakeoffRuntimeFactory(fail_on_request=5)

    async def no_sleep(_seconds: float) -> None:
        return None

    service = OfferTodayResearchLiveService(
        sleep=no_sleep,
        clock=IncrementingClock(),
    )

    execution = await service.run_pagination_bakeoff(
        runtime_factory=runtime_factory,
        observation_service=FakeObservationService(),
        repeat_index=1,
        order_seed=20260713,
    )

    assert execution.failure_reason == (
        "unexpected_pagination_bakeoff_error:RuntimeError"
    )
    assert "secret runtime failure details" not in execution.failure_reason
    assert 0 < len(execution.executions) < len(execution.order)
    assert len(runtime_factory.exited) == len(runtime_factory.entered)


@pytest.mark.asyncio
async def test_pagination_bakeoff_shared_close_error_returns_type_only_evidence() -> (
    None
):
    runtime_factory = ExitFailureBakeoffRuntimeFactory()

    async def no_sleep(_seconds: float) -> None:
        return None

    service = OfferTodayResearchLiveService(
        sleep=no_sleep,
        clock=IncrementingClock(),
    )

    execution = await service.run_pagination_bakeoff(
        runtime_factory=runtime_factory,
        observation_service=FakeObservationService(),
        repeat_index=1,
        order_seed=20260713,
    )

    assert execution.failure_reason == (
        "unexpected_pagination_bakeoff_error:RuntimeError"
    )
    assert "secret runtime close failure details" not in execution.failure_reason
    assert len(execution.executions) == len(execution.order)
    assert len(runtime_factory.exited) == len(runtime_factory.entered)


@pytest.mark.asyncio
async def test_run_bounded_conditions_uses_exact_policy_once_per_condition() -> None:
    conditions = build_calibration_conditions()
    runner_factory = SequenceRunnerFactory(
        tuple(bounded_listing_result(condition) for condition in conditions)
    )
    detail_factory = DetailScraperFactory()
    service = OfferTodayResearchLiveService(
        runner_factory=runner_factory,
        detail_scraper_factory=detail_factory,
    )
    runtime = FakeRuntime()
    observation_service = FakeObservationService()

    results = await service.run_bounded_conditions(
        runtime=runtime,
        observation_service=observation_service,
        conditions=conditions,
    )

    assert len(results) == 8
    assert all(result.accepted for result in results)
    assert runner_factory.transports == [runtime] * 8
    assert len(runner_factory.runners) == 8
    for condition, runner in zip(conditions, runner_factory.runners, strict=True):
        assert runner.calls == [
            {
                "conditions": (condition,),
                "stop_policy": ListingStopPolicy(
                    max_pages_per_condition=3,
                    unique_job_cap=None,
                    require_empty_confirmation=False,
                ),
                "retry_policy": ListingRetryPolicy(
                    max_attempts_per_page=3,
                    retry_delays_seconds=(5.0, 15.0),
                    page_delay_seconds=0.0,
                    page_delay_range_seconds=(3.0, 5.0),
                ),
                "observation_sink": observation_service,
                "staging_sink": runner.calls[0]["staging_sink"],
                "session_mode": "fresh-headless",
            }
        ]
        assert isinstance(
            runner.calls[0]["staging_sink"],
            ResearchNoopListingStagingSink,
        )
    assert detail_factory.kwargs == []
    assert runtime.detail_json_calls == []


@pytest.mark.asyncio
async def test_run_bounded_conditions_uses_injected_reconciled_staging_sink() -> None:
    conditions = build_calibration_conditions()[:2]
    runner_factory = SequenceRunnerFactory(
        tuple(bounded_listing_result(condition) for condition in conditions)
    )
    service = OfferTodayResearchLiveService(runner_factory=runner_factory)
    staging_sink = object()

    results = await service.run_bounded_conditions(
        runtime=FakeRuntime(),
        observation_service=FakeObservationService(),
        conditions=conditions,
        staging_sink=staging_sink,
    )

    assert len(results) == 2
    assert all(
        runner.calls[0]["staging_sink"] is staging_sink
        for runner in runner_factory.runners
    )


@pytest.mark.asyncio
async def test_run_bounded_conditions_stops_after_first_rejected_result() -> None:
    conditions = build_calibration_conditions()[:3]
    runner_factory = SequenceRunnerFactory(
        (
            bounded_listing_result(conditions[0]),
            bounded_listing_result(
                conditions[1],
                pages_observed=0,
                stop_reason="auth_expired",
                classification="auth_expired",
            ),
            bounded_listing_result(conditions[2]),
        )
    )
    service = OfferTodayResearchLiveService(runner_factory=runner_factory)

    results = await service.run_bounded_conditions(
        runtime=FakeRuntime(),
        observation_service=FakeObservationService(),
        conditions=conditions,
    )

    assert len(results) == 2
    assert results[0].accepted is True
    assert results[1].accepted is False
    assert len(runner_factory.runners) == 2


@pytest.mark.asyncio
async def test_run_census_uses_one_shared_runner_with_frozen_controls() -> None:
    candidate = census_candidate()
    expected_conditions = build_pilot_conditions(
        candidate.endpoint,
        candidate.rcd_type,
    )
    expected_result = census_listing_result(candidate)
    runner_factory = RunnerFactory(expected_result)
    service = OfferTodayResearchLiveService(runner_factory=runner_factory)
    runtime = FakeRuntime()
    observation_service = FakeObservationService()
    staging_sink = object()

    result = await service.run_census(
        runtime=runtime,
        observation_service=observation_service,
        candidate=candidate,
        staging_sink=staging_sink,
    )

    assert result is expected_result
    assert runner_factory.transports == [runtime]
    assert runner_factory.runner.calls == [
        {
            "conditions": expected_conditions,
            "stop_policy": ListingStopPolicy(
                max_pages_per_condition=500,
                unique_job_cap=None,
                require_empty_confirmation=True,
            ),
            "retry_policy": ListingRetryPolicy(
                max_attempts_per_page=3,
                retry_delays_seconds=(5.0, 15.0),
                page_delay_seconds=0.0,
                page_delay_range_seconds=(3.0, 5.0),
            ),
            "observation_sink": observation_service,
            "staging_sink": staging_sink,
            "session_mode": "fresh-headless",
        }
    ]
    assert runtime.detail_json_calls == []


@pytest.mark.asyncio
async def test_run_census_preserves_first_incomplete_page_cap_as_failure() -> None:
    candidate = census_candidate()
    partial_result = census_listing_result(candidate, incomplete_index=1)
    runner_factory = RunnerFactory(partial_result)
    service = OfferTodayResearchLiveService(runner_factory=runner_factory)

    result = await service.run_census(
        runtime=FakeRuntime(),
        observation_service=FakeObservationService(),
        candidate=candidate,
        staging_sink=object(),
    )

    assert len(result.condition_outcomes) == 2
    assert result.condition_outcomes[-1].stop_reason == "page_cap"
    assert result.condition_outcomes[-1].is_complete is False
    assert result.stop_reason == "page_cap"
    assert result.is_complete is False
    assert len(runner_factory.runner.calls) == 1


@pytest.mark.asyncio
async def test_run_fixed_repeat_uses_only_frozen_three_category_cohort() -> None:
    candidate = census_candidate()
    conditions_by_category = {
        condition.category_id: condition
        for condition in build_pilot_conditions(
            candidate.endpoint,
            candidate.rcd_type,
        )
    }
    expected_conditions = tuple(
        conditions_by_category[category_id]
        for category_id in candidate.fixed_repeat_category_ids
    )
    expected_result = census_listing_result(candidate)
    runner_factory = RunnerFactory(expected_result)
    service = OfferTodayResearchLiveService(runner_factory=runner_factory)
    observation_service = FakeObservationService()
    staging_sink = object()

    result = await service.run_fixed_repeat(
        runtime=FakeRuntime(),
        observation_service=observation_service,
        candidate=candidate,
        staging_sink=staging_sink,
    )

    assert result is expected_result
    assert runner_factory.runner.calls == [
        {
            "conditions": expected_conditions,
            "stop_policy": ListingStopPolicy(
                max_pages_per_condition=500,
                unique_job_cap=None,
                require_empty_confirmation=True,
            ),
            "retry_policy": ListingRetryPolicy(
                max_attempts_per_page=3,
                retry_delays_seconds=(5.0, 15.0),
                page_delay_seconds=0.0,
                page_delay_range_seconds=(3.0, 5.0),
            ),
            "observation_sink": observation_service,
            "staging_sink": staging_sink,
            "session_mode": "fresh-headless",
        }
    ]


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
        max_pages_per_condition=2,
        unique_job_cap=20,
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
        (f"j{index}", f"e{index}", "encryptJobId") for index in range(1, 21)
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
    assert (
        factory_kwargs["detail_json_fetcher"].__func__ is FakeRuntime.fetch_detail_json
    )


@pytest.mark.parametrize(
    "listing_factory",
    (listing_result, two_page_listing_result),
    ids=("one-page", "two-page"),
)
@pytest.mark.asyncio
async def test_naturally_exhausted_target_cap_makes_zero_detail_attempts(
    listing_factory,
) -> None:
    listing = listing_factory()
    observations = (
        *listing.observations[:-1],
        replace(listing.observations[-1], has_more=False),
    )
    exhausted_listing = replace(listing, observations=observations)
    detail_factory = DetailScraperFactory()
    observation_service = FakeObservationService()
    now, clock = deterministic_clocks()
    service = OfferTodayResearchLiveService(
        runner_factory=RunnerFactory(exhausted_listing),
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
    assert execution.detail_observations == ()
    assert execution.decision.stop_reason == "listing_target_cap"
    assert execution.decision.expected_truncation is False
    assert execution.decision.attempted_count == 0


@pytest.mark.asyncio
async def test_run_smoke_passes_jobid_fallback_provenance_to_detail_scraper() -> None:
    detail_factory = DetailScraperFactory()
    now, clock = deterministic_clocks()
    service = OfferTodayResearchLiveService(
        runner_factory=RunnerFactory(listing_result(identity_source="jobId_fallback")),
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
async def test_impossible_one_page_page_cap_makes_zero_detail_calls() -> None:
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
    assert execution.detail_observations == ()
    assert execution.decision.stop_reason == "listing_page_cap"
    assert execution.decision.expected_truncation is False
    assert execution.decision.attempted_count == 0


@pytest.mark.parametrize(
    "observation_changes",
    (
        ({}, {"has_more": False}),
        ({}, {"row_count": 0, "id_pairs": ()}),
        ({"has_more": False}, {}),
    ),
    ids=(
        "final-has-more-false",
        "final-page-empty",
        "page-one-has-more-false",
    ),
)
@pytest.mark.asyncio
async def test_page_cap_terminal_signal_makes_zero_detail_attempts(
    observation_changes: tuple[dict[str, object], dict[str, object]],
) -> None:
    listing = two_page_listing_result(count=19)
    observations = tuple(
        replace(observation, **changes)
        for observation, changes in zip(listing.observations, observation_changes)
    )
    invalid_listing = replace(listing, observations=observations)
    detail_factory = DetailScraperFactory()
    observation_service = FakeObservationService()
    now, clock = deterministic_clocks()
    service = OfferTodayResearchLiveService(
        runner_factory=RunnerFactory(invalid_listing),
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
    assert execution.detail_observations == ()
    assert execution.decision.stop_reason == "listing_page_cap"
    assert execution.decision.expected_truncation is False
    assert execution.decision.attempted_count == 0


@pytest.mark.asyncio
async def test_clean_two_page_short_cohort_makes_zero_detail_attempts() -> None:
    detail_factory = DetailScraperFactory()
    observation_service = FakeObservationService()
    now, clock = deterministic_clocks()
    service = OfferTodayResearchLiveService(
        runner_factory=RunnerFactory(two_page_listing_result(count=19)),
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
    assert execution.detail_observations == ()
    assert execution.decision.stop_reason == "insufficient_valid_detail_targets"
    assert execution.decision.attempted_count == 0


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


class PhaseCRuntime:
    def __init__(self, factory, runtime_index: int) -> None:
        self.factory = factory
        self.runtime_index = runtime_index
        self.browser_context_hash = hashlib.sha256(
            f"phase-c-context-{runtime_index}".encode()
        ).hexdigest()
        self.requests: list[tuple[dict, str]] = []

    async def __aenter__(self):
        self.factory.entered.append(self)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.factory.exited.append(self)

    async def fetch_listing_page(self, payload, *, listing_url=None):
        assert isinstance(listing_url, str)
        self.requests.append((deepcopy(payload), listing_url))
        if self.factory.fail_runtime_index == self.runtime_index:
            raise RuntimeError("secret Phase C runtime details")
        category_id = payload["jobFunctionCodes"][0]
        page = payload["page"]
        rows = (
            [
                {
                    "jobId": f"{category_id}-{self.runtime_index}",
                    "encryptJobId": f"enc-{category_id}-{self.runtime_index}",
                    "jobName": "Phase C Engineer",
                    "companyName": "Example",
                }
            ]
            if page == 1
            else []
        )
        data = {
            "pageSize": 10,
            "hasMore": False,
            "total": 999_999,
            "resultList": rows,
        }
        if listing_url.endswith("/recommend/search/list"):
            data.update(
                {
                    "sessionId": payload.get("sessionId")
                    or f"phase-c-session-{category_id}",
                    "supplePage": page,
                    "suppleAmount": 0,
                    "suppleType": 0,
                    "suppleRcdList": [],
                }
            )
        return OfferTodayListingTransportResult(
            payload={"code": 0, "data": data},
            browser_context_hash=self.browser_context_hash,
            http_status=200,
            response_url=listing_url,
        )


class PhaseCRuntimeFactory:
    def __init__(self, *, fail_runtime_index: int | None = None) -> None:
        self.fail_runtime_index = fail_runtime_index
        self.created: list[PhaseCRuntime] = []
        self.entered: list[PhaseCRuntime] = []
        self.exited: list[PhaseCRuntime] = []

    def __call__(self, *, headed: bool):
        assert headed is False
        runtime = PhaseCRuntime(self, len(self.created) + 1)
        self.created.append(runtime)
        return runtime


async def _phase_c_no_sleep(_seconds: float) -> None:
    return None


@pytest.mark.asyncio
async def test_run_endpoint_probe_separates_contracts_and_never_stages_product_data() -> (
    None
):
    runtime_factory = PhaseCRuntimeFactory()
    staging_sink = ResearchNoopListingStagingSink()

    execution = await OfferTodayResearchLiveService(
        sleep=_phase_c_no_sleep,
        clock=IncrementingClock(),
    ).run_endpoint_probe(
        runtime_factory=runtime_factory,
        observation_service=FakeObservationService(),
        plan=build_endpoint_probe_plan(),
        staging_sink=staging_sink,
    )

    assert execution.failure_reason is None
    assert len(execution.conditions) == 2
    assert execution.conditions[0].endpoint_contract_id == "recommend-search-list-v1"
    assert execution.conditions[0].terminal_confirmed is True
    assert execution.conditions[1].endpoint_contract_id == "recommend-list-envelope-v1"
    assert execution.conditions[1].contract_verified is False
    assert execution.conditions[1].terminal_confirmed is False
    assert execution.accepted is False
    assert len(runtime_factory.created) == len(runtime_factory.exited) == 2
    assert [len(runtime.requests) for runtime in runtime_factory.created] == [2, 3]
    assert all(
        "rcdType" not in payload
        for runtime in runtime_factory.created
        for payload, _ in runtime.requests
    )
    assert staging_sink.stage_calls == 1
    assert staging_sink.would_stage_rows == 1
    assert len(staging_sink.staged_pages) == 1
    assert staging_sink.deferred_conflicts == ()


@pytest.mark.asyncio
async def test_run_partition_probe_honors_explicit_catalog_order_and_exact_budget() -> (
    None
):
    runtime_factory = PhaseCRuntimeFactory()
    staging_sink = ResearchNoopListingStagingSink()
    partition_ids = tuple(
        partition.partition_id for partition in OFFERTODAY_PARTITION_CATALOG[:2]
    )
    plan = build_partition_probe_plan(
        endpoint_contract_id="recommend-search-list-v1",
        partition_ids=partition_ids,
        max_pages_per_condition=3,
    )

    execution = await OfferTodayResearchLiveService(
        sleep=_phase_c_no_sleep,
        clock=IncrementingClock(),
    ).run_partition_probe(
        runtime_factory=runtime_factory,
        observation_service=FakeObservationService(),
        plan=plan,
        staging_sink=staging_sink,
    )

    assert execution.failure_reason is None
    assert execution.accepted is True
    assert tuple(item.partition_id for item in execution.conditions) == partition_ids
    assert execution.logical_requests == execution.physical_attempts == 4
    assert execution.logical_requests <= plan.budget.listing_logical
    assert execution.physical_attempts <= plan.budget.listing_attempt_max
    assert len(runtime_factory.created) == len(runtime_factory.exited) == 2
    assert staging_sink.stage_calls == 2
    assert staging_sink.would_stage_rows == 2
    assert len(staging_sink.staged_pages) == 2


@pytest.mark.asyncio
async def test_phase_c_probe_preserves_completed_prefix_and_type_only_failure() -> None:
    runtime_factory = PhaseCRuntimeFactory(fail_runtime_index=2)
    partition_ids = tuple(
        partition.partition_id for partition in OFFERTODAY_PARTITION_CATALOG[:3]
    )
    plan = build_partition_probe_plan(
        endpoint_contract_id="recommend-search-list-v1",
        partition_ids=partition_ids,
        max_pages_per_condition=3,
    )

    execution = await OfferTodayResearchLiveService(
        sleep=_phase_c_no_sleep,
        clock=IncrementingClock(),
    ).run_partition_probe(
        runtime_factory=runtime_factory,
        observation_service=FakeObservationService(),
        plan=plan,
        staging_sink=ResearchNoopListingStagingSink(),
    )

    assert tuple(item.partition_id for item in execution.conditions) == partition_ids[:1]
    assert execution.failure_reason == "unexpected_phase_c_probe_error:RuntimeError"
    assert "secret" not in execution.failure_reason
    assert len(runtime_factory.created) == len(runtime_factory.exited) == 2


@pytest.mark.asyncio
async def test_phase_c_probe_rejects_any_non_noop_staging_sink_before_runtime() -> None:
    runtime_factory = PhaseCRuntimeFactory()

    with pytest.raises(ValueError, match="ResearchNoopListingStagingSink"):
        await OfferTodayResearchLiveService().run_endpoint_probe(
            runtime_factory=runtime_factory,
            observation_service=FakeObservationService(),
            plan=build_endpoint_probe_plan(),
            staging_sink=object(),
        )

    assert runtime_factory.created == []


def _phase_d_candidate() -> DiscoveryPolicyCandidateV2:
    contract = offertoday_endpoint_contract("recommend-search-list-v1")
    partitions = tuple(
        top_level_partition(category.code)
        for category in OFFERTODAY_CATEGORIES_L1
    )
    return DiscoveryPolicyCandidateV2(
        candidate_version=2,
        endpoint_contract_id=contract.contract_id,
        endpoint_contract_hash=contract.contract_hash,
        endpoint=contract.endpoint,
        rcd_type=None,
        category_catalog_version=OFFERTODAY_CATEGORY_CATALOG_VERSION,
        category_catalog_hash=offertoday_category_catalog_hash(),
        partition_catalog_hash=offertoday_partition_catalog_hash(),
        phase_d_partitions=partitions,
        retained_partition_ids=(partitions[0].partition_id,),
        retained_condition_hashes=("a" * 64,),
        pagination_mode="response-cursor",
        requested_page_size=10,
        browser_lifecycle="condition-local-runtime",
        request_policy_hash=phase_c_request_policy_hash(contract.contract_id),
        terminal_policy="cursor-terminal-empty-confirmation-v1",
        max_pages_per_condition=500,
        require_empty_confirmation=True,
        max_attempts_per_page=3,
        retry_delays_seconds=(5.0, 15.0),
        page_delay_range_seconds=(3.0, 5.0),
        session_mode="saved-session",
        fixed_repeat_category_ids=(118000, 112000, 127000),
        phase_b_comparison_artifact_hash="b" * 64,
        phase_c_comparison_artifact_hash="c" * 64,
        source_artifact_hash="d" * 64,
        deferred_issue_ids=(4, 5),
    )


@pytest.mark.asyncio
async def test_phase_d_fixed_repeat_uses_one_condition_local_cursor_chain_each() -> (
    None
):
    runtime_factory = PhaseCRuntimeFactory()
    observation_service = FakeObservationService()
    staging_sink = ResearchNoopListingStagingSink()

    execution = await OfferTodayResearchLiveService(
        sleep=_phase_c_no_sleep,
        clock=IncrementingClock(),
    ).run_fixed_repeat_v2(
        runtime_factory=runtime_factory,
        observation_service=observation_service,
        candidate=_phase_d_candidate(),
        staging_sink=staging_sink,
    )

    assert execution.failure_reason is None
    assert execution.completed_condition_count == 3
    assert len(execution.results) == 3
    assert len(runtime_factory.created) == len(runtime_factory.exited) == 3
    assert [len(runtime.requests) for runtime in runtime_factory.created] == [2, 2, 2]
    assert [
        runtime.requests[0][0]["jobFunctionCodes"][0]
        for runtime in runtime_factory.created
    ] == [118000, 112000, 127000]
    assert all(
        "sessionId" not in runtime.requests[0][0]
        and "sessionId" in runtime.requests[1][0]
        for runtime in runtime_factory.created
    )
    assert staging_sink.stage_calls == 3
    assert staging_sink.would_stage_rows == 3
    assert observation_service.detail_attempts == []


@pytest.mark.asyncio
async def test_phase_d_census_runs_all_31_catalog_conditions() -> None:
    runtime_factory = PhaseCRuntimeFactory()

    execution = await OfferTodayResearchLiveService(
        sleep=_phase_c_no_sleep,
        clock=IncrementingClock(),
    ).run_census_v2(
        runtime_factory=runtime_factory,
        observation_service=FakeObservationService(),
        candidate=_phase_d_candidate(),
        staging_sink=ResearchNoopListingStagingSink(),
    )

    assert execution.failure_reason is None
    assert execution.completed_condition_count == 31
    assert len(runtime_factory.created) == len(runtime_factory.exited) == 31


@pytest.mark.asyncio
async def test_phase_d_census_preserves_prefix_and_sanitizes_runtime_failure() -> None:
    runtime_factory = PhaseCRuntimeFactory(fail_runtime_index=2)

    execution = await OfferTodayResearchLiveService(
        sleep=_phase_c_no_sleep,
        clock=IncrementingClock(),
    ).run_census_v2(
        runtime_factory=runtime_factory,
        observation_service=FakeObservationService(),
        candidate=_phase_d_candidate(),
        staging_sink=ResearchNoopListingStagingSink(),
    )

    assert execution.completed_condition_count == 1
    assert execution.failure_reason == "unexpected_phase_d_census_error:RuntimeError"
    assert "secret" not in execution.failure_reason
    assert len(runtime_factory.created) == len(runtime_factory.exited) == 2


@pytest.mark.asyncio
async def test_phase_d_rejects_unknown_staging_sink_before_runtime() -> None:
    runtime_factory = PhaseCRuntimeFactory()

    with pytest.raises(ValueError, match="no-op or reconciled"):
        await OfferTodayResearchLiveService().run_fixed_repeat_v2(
            runtime_factory=runtime_factory,
            observation_service=FakeObservationService(),
            candidate=_phase_d_candidate(),
            staging_sink=object(),
        )

    assert runtime_factory.created == []
