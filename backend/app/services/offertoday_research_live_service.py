from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AsyncExitStack
from datetime import datetime
from typing import Any

from app.scraper.offertoday_browser_detail_scraper import OfferTodayBrowserDetailScraper
from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime
from app.services.offertoday_research_observation_service import (
    OfferTodayResearchObservationService,
)
from app.services.offertoday_research_staging_service import (
    ResearchNoopListingStagingSink,
)
from app.sources.offertoday.detail_identity import (
    OfferTodayDetailFetchResult,
    OfferTodayDetailIdentity,
)
from app.sources.offertoday.listing_runner import (
    ListingRetryPolicy,
    ListingRunResult,
    ListingStopPolicy,
    OfferTodayListingCondition,
    OfferTodayListingRunner,
)
from app.sources.offertoday.listing_contract import OfferTodayListingTransportResult
from app.sources.offertoday.research.calibration import (
    BoundedConditionResult,
    build_pilot_conditions,
    evaluate_bounded_condition,
)
from app.sources.offertoday.research.live_contracts import (
    CensusCandidate,
    DetailSmokeObservation,
    DetailSmokeTarget,
    LiveSmokeExecution,
)
from app.sources.offertoday.research.pagination_bakeoff import (
    BAKEOFF_ENDPOINT,
    BAKEOFF_MAX_ATTEMPTS_PER_PAGE,
    BAKEOFF_MAX_LOGICAL_PAGES_PER_CONDITION,
    BAKEOFF_PAGE_DELAY_RANGE_SECONDS,
    BAKEOFF_RCD_TYPE,
    BAKEOFF_REQUIRE_EMPTY_CONFIRMATION,
    BAKEOFF_RETRY_DELAYS_SECONDS,
    BAKEOFF_SESSION_MODE,
    PaginationBakeoffRepeat,
    PaginationConditionExecution,
    bakeoff_variant,
    build_bakeoff_order,
    pagination_bakeoff_unexpected_failure_reason,
)
from app.sources.offertoday.research.partition_research import (
    ENDPOINT_PROBE_EXPERIMENT,
    PARTITION_PROBE_EXPERIMENT,
    PHASE_C_PAGE_DELAY_RANGE_SECONDS,
    PHASE_C_RETRY_DELAYS_SECONDS,
    PHASE_C_SESSION_MODE,
    EndpointProbePlan,
    PartitionProbePlan,
    PhaseCProbeExecution,
    condition_evidence_from_listing_result,
    offertoday_partition,
    request_policy_for_contract,
    top_level_partition,
)
from app.sources.offertoday.research.smoke import (
    SMOKE_DETAIL_TARGET_COUNT,
    SMOKE_LISTING_REQUEST_LIMIT,
    build_runtime_smoke_condition,
    evaluate_smoke,
    freeze_detail_smoke_cohort,
    listing_ready_for_detail_smoke,
)
from app.sources.offertoday.response_policy import OfferTodayResponseKind
from app.utils.time import utc_now


async def _typed_listing_fetch(runtime, payload, *, listing_url=None):
    typed_fetch = getattr(runtime, "fetch_listing_page", None)
    if callable(typed_fetch):
        return await typed_fetch(payload, listing_url=listing_url)
    raw_payload = await runtime.fetch_listing_json(
        payload,
        listing_url=listing_url,
    )
    return OfferTodayListingTransportResult(
        payload=raw_payload,
        browser_context_hash=getattr(runtime, "browser_context_hash", None),
    )


class _ManagedListingTransport:
    """Own a research runtime and preserve it for one logical page retry."""

    def __init__(self, runtime_factory, *, restart_each_page: bool) -> None:
        self._runtime_factory = runtime_factory
        self._restart_each_page = restart_each_page
        self._runtime_context = None
        self._runtime = None
        self._logical_page_key: str | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        await self._close_runtime(exc_type, exc, traceback)

    @property
    def browser_context_hash(self) -> str | None:
        value = getattr(self._runtime, "browser_context_hash", None)
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _page_key(payload, listing_url) -> str:
        canonical = json.dumps(
            {"listing_url": listing_url, "payload": payload},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    async def _open_runtime(self) -> None:
        runtime_context = self._runtime_factory(headed=False)
        runtime = await runtime_context.__aenter__()
        self._runtime_context = runtime_context
        self._runtime = runtime

    async def _close_runtime(
        self,
        exc_type=None,
        exc=None,
        traceback=None,
    ) -> None:
        runtime_context = self._runtime_context
        self._runtime_context = None
        self._runtime = None
        self._logical_page_key = None
        if runtime_context is not None:
            await runtime_context.__aexit__(exc_type, exc, traceback)

    async def fetch_listing_page(self, payload, *, listing_url=None):
        page_key = self._page_key(payload, listing_url)
        if (
            self._restart_each_page
            and self._runtime is not None
            and self._logical_page_key != page_key
        ):
            await self._close_runtime()
        if self._runtime is None:
            await self._open_runtime()
        self._logical_page_key = page_key
        return await _typed_listing_fetch(
            self._runtime,
            payload,
            listing_url=listing_url,
        )

    async def fetch_listing_json(self, payload, *, listing_url=None):
        result = await self.fetch_listing_page(payload, listing_url=listing_url)
        return result.payload

    async def restart_after_browser_loss(self) -> None:
        await self._close_runtime()


class OfferTodayResearchLiveService:
    def __init__(
        self,
        *,
        runner_factory=OfferTodayListingRunner,
        detail_scraper_factory=OfferTodayBrowserDetailScraper,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.perf_counter,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._runner_factory = runner_factory
        self._detail_scraper_factory = detail_scraper_factory
        self._sleep = sleep
        self._clock = clock
        self._now = now

    async def run_endpoint_probe(
        self,
        *,
        runtime_factory,
        observation_service: OfferTodayResearchObservationService,
        plan: EndpointProbePlan,
        staging_sink: Any | None = None,
    ) -> PhaseCProbeExecution:
        partition = top_level_partition(plan.category_code)
        targets = tuple(
            (partition.partition_id, contract_id)
            for contract_id in plan.contract_ids
        )
        return await self._run_phase_c_probe(
            experiment=ENDPOINT_PROBE_EXPERIMENT,
            plan=plan,
            targets=targets,
            runtime_factory=runtime_factory,
            observation_service=observation_service,
            staging_sink=staging_sink,
        )

    async def run_partition_probe(
        self,
        *,
        runtime_factory,
        observation_service: OfferTodayResearchObservationService,
        plan: PartitionProbePlan,
        staging_sink: Any | None = None,
    ) -> PhaseCProbeExecution:
        targets = tuple(
            (partition_id, plan.endpoint_contract_id)
            for partition_id in plan.partition_ids
        )
        return await self._run_phase_c_probe(
            experiment=PARTITION_PROBE_EXPERIMENT,
            plan=plan,
            targets=targets,
            runtime_factory=runtime_factory,
            observation_service=observation_service,
            staging_sink=staging_sink,
        )

    async def _run_phase_c_probe(
        self,
        *,
        experiment: str,
        plan: EndpointProbePlan | PartitionProbePlan,
        targets: Sequence[tuple[str, str]],
        runtime_factory,
        observation_service: OfferTodayResearchObservationService,
        staging_sink: Any | None,
    ) -> PhaseCProbeExecution:
        active_staging_sink = (
            ResearchNoopListingStagingSink() if staging_sink is None else staging_sink
        )
        if not isinstance(active_staging_sink, ResearchNoopListingStagingSink):
            raise ValueError("Phase C probes require ResearchNoopListingStagingSink")
        conditions = []
        failure_reason = None
        for partition_id, contract_id in targets:
            partition = offertoday_partition(partition_id)
            contract = request_policy_for_contract(contract_id).endpoint_contract
            if contract is None:  # pragma: no cover - explicit Phase C invariant
                raise AssertionError("Phase C request policy requires endpoint contract")
            condition = OfferTodayListingCondition(
                search_family=experiment,
                category_id=partition.category_code,
                keyword="",
                endpoint=contract.endpoint,
                rcd_type=None,
            )
            max_pages = (
                plan.max_pages_per_contract
                if isinstance(plan, EndpointProbePlan)
                else plan.max_pages_per_condition
            )
            try:
                async with _ManagedListingTransport(
                    runtime_factory,
                    restart_each_page=False,
                ) as transport:
                    result = await self._runner_factory(
                        transport,
                        sleep=self._sleep,
                        clock=self._clock,
                    ).run(
                        conditions=(condition,),
                        stop_policy=ListingStopPolicy(
                            max_pages_per_condition=max_pages,
                            unique_job_cap=None,
                            require_empty_confirmation=True,
                        ),
                        retry_policy=ListingRetryPolicy(
                            max_attempts_per_page=plan.max_attempts_per_page,
                            retry_delays_seconds=PHASE_C_RETRY_DELAYS_SECONDS,
                            page_delay_seconds=0.0,
                            page_delay_range_seconds=(
                                PHASE_C_PAGE_DELAY_RANGE_SECONDS
                            ),
                        ),
                        observation_sink=observation_service,
                        staging_sink=active_staging_sink,
                        session_mode=PHASE_C_SESSION_MODE,
                        request_policy=request_policy_for_contract(contract_id),
                    )
            except Exception as exc:
                failure_reason = f"unexpected_phase_c_probe_error:{type(exc).__name__}"
                break
            evidence = condition_evidence_from_listing_result(
                partition_id=partition_id,
                endpoint_contract_id=contract_id,
                result=result,
            )
            conditions.append(evidence)
            if result.stop_reason in {
                "auth_expired",
                "waf_challenge",
                "ip_blocked",
                "id_mismatch",
                "identity_conflict",
                "identity_issue",
                "unresolved_gap",
                "cursor_contract_violation",
                "endpoint_contract_violation",
                "page_contract_violation",
                "browser_context_lost",
            }:
                failure_reason = f"hard_stop:{result.stop_reason}"
                break
        return PhaseCProbeExecution(
            experiment=experiment,
            plan=plan,
            conditions=tuple(conditions),
            failure_reason=failure_reason,
        )

    async def run_pagination_bakeoff(
        self,
        *,
        runtime_factory,
        observation_service: OfferTodayResearchObservationService,
        repeat_index: int,
        order_seed: int,
        staging_sink: Any | None = None,
    ) -> PaginationBakeoffRepeat:
        active_staging_sink = (
            ResearchNoopListingStagingSink() if staging_sink is None else staging_sink
        )
        order = build_bakeoff_order(
            repeat_index=repeat_index,
            order_seed=order_seed,
        )
        executions: list[PaginationConditionExecution] = []
        failure_reason: str | None = None
        shared_stack = AsyncExitStack()
        await shared_stack.__aenter__()
        try:
            shared_transports: dict[str, _ManagedListingTransport] = {}
            for entry in order:
                variant = bakeoff_variant(entry.variant_id)
                policy = variant.request_policy(repeat_index=repeat_index)
                condition = OfferTodayListingCondition(
                    search_family="cursor_pagination_bakeoff_v2",
                    category_id=entry.category_id,
                    keyword="",
                    endpoint=BAKEOFF_ENDPOINT,
                    rcd_type=BAKEOFF_RCD_TYPE,
                )

                async def run_with_transport(transport) -> ListingRunResult:
                    runner = self._runner_factory(
                        transport,
                        sleep=self._sleep,
                        clock=self._clock,
                    )
                    return await runner.run(
                        conditions=(condition,),
                        stop_policy=ListingStopPolicy(
                            max_pages_per_condition=(
                                BAKEOFF_MAX_LOGICAL_PAGES_PER_CONDITION
                            ),
                            unique_job_cap=None,
                            require_empty_confirmation=(
                                BAKEOFF_REQUIRE_EMPTY_CONFIRMATION
                            ),
                        ),
                        retry_policy=ListingRetryPolicy(
                            max_attempts_per_page=BAKEOFF_MAX_ATTEMPTS_PER_PAGE,
                            retry_delays_seconds=BAKEOFF_RETRY_DELAYS_SECONDS,
                            page_delay_seconds=0.0,
                            page_delay_range_seconds=(
                                BAKEOFF_PAGE_DELAY_RANGE_SECONDS
                            ),
                        ),
                        observation_sink=observation_service,
                        staging_sink=active_staging_sink,
                        session_mode=BAKEOFF_SESSION_MODE,
                        request_policy=policy,
                    )

                try:
                    if variant.browser_lifecycle == "shared-variant-runtime":
                        transport = shared_transports.get(variant.variant_id)
                        if transport is None:
                            transport = await shared_stack.enter_async_context(
                                _ManagedListingTransport(
                                    runtime_factory,
                                    restart_each_page=False,
                                )
                            )
                            shared_transports[variant.variant_id] = transport
                        result = await run_with_transport(transport)
                    elif variant.browser_lifecycle == "condition-local-runtime":
                        async with _ManagedListingTransport(
                            runtime_factory,
                            restart_each_page=False,
                        ) as transport:
                            result = await run_with_transport(transport)
                    elif variant.browser_lifecycle == "restart-each-page":
                        async with _ManagedListingTransport(
                            runtime_factory,
                            restart_each_page=True,
                        ) as transport:
                            result = await run_with_transport(transport)
                    else:  # pragma: no cover - variant contract invariant
                        raise AssertionError(
                            "unsupported bake-off browser lifecycle"
                        )
                except Exception as exc:
                    failure_reason = pagination_bakeoff_unexpected_failure_reason(exc)
                    break

                executions.append(
                    PaginationConditionExecution(
                        repeat_index=repeat_index,
                        variant_id=entry.variant_id,
                        category_id=entry.category_id,
                        category_order=entry.category_order,
                        result=result,
                    )
                )
                if result.stop_reason in {
                    "auth_expired",
                    "waf_challenge",
                    "ip_blocked",
                    "id_mismatch",
                    "identity_conflict",
                    "identity_issue",
                    "unresolved_gap",
                    "cursor_contract_violation",
                }:
                    failure_reason = f"hard_stop:{result.stop_reason}"
                    break
        except Exception as exc:
            failure_reason = pagination_bakeoff_unexpected_failure_reason(exc)
        finally:
            try:
                await shared_stack.aclose()
            except Exception as exc:
                if failure_reason is None:
                    failure_reason = pagination_bakeoff_unexpected_failure_reason(exc)

        return PaginationBakeoffRepeat(
            repeat_index=repeat_index,
            order_seed=order_seed,
            order=order,
            executions=tuple(executions),
            failure_reason=failure_reason,
        )

    async def run_bounded_conditions(
        self,
        *,
        runtime: OfferTodayBrowserRuntime,
        observation_service: OfferTodayResearchObservationService,
        conditions: Sequence[OfferTodayListingCondition],
        staging_sink: Any | None = None,
    ) -> tuple[BoundedConditionResult, ...]:
        active_staging_sink = (
            ResearchNoopListingStagingSink() if staging_sink is None else staging_sink
        )
        results: list[BoundedConditionResult] = []
        for condition in conditions:
            runner = self._runner_factory(runtime)
            listing_result = await runner.run(
                conditions=(condition,),
                stop_policy=ListingStopPolicy(
                    max_pages_per_condition=3,
                    unique_job_cap=None,
                    require_empty_confirmation=False,
                ),
                retry_policy=ListingRetryPolicy(
                    max_attempts_per_page=3,
                    retry_delays_seconds=(5.0, 15.0),
                    page_delay_seconds=0.0,
                    page_delay_range_seconds=(3.0, 5.0),
                ),
                observation_sink=observation_service,
                staging_sink=active_staging_sink,
                session_mode="fresh-headless",
            )
            bounded_result = evaluate_bounded_condition(
                condition,
                listing_result,
                planned_page_limit=3,
            )
            results.append(bounded_result)
            if not bounded_result.accepted:
                break
        return tuple(results)

    async def run_census(
        self,
        *,
        runtime: OfferTodayBrowserRuntime,
        observation_service: OfferTodayResearchObservationService,
        candidate: CensusCandidate,
        staging_sink: Any,
    ) -> ListingRunResult:
        return await self._run_candidate_conditions(
            runtime=runtime,
            observation_service=observation_service,
            candidate=candidate,
            staging_sink=staging_sink,
            conditions=build_pilot_conditions(
                candidate.endpoint,
                candidate.rcd_type,
            ),
        )

    async def run_fixed_repeat(
        self,
        *,
        runtime: OfferTodayBrowserRuntime,
        observation_service: OfferTodayResearchObservationService,
        candidate: CensusCandidate,
        staging_sink: Any,
    ) -> ListingRunResult:
        conditions_by_category = {
            condition.category_id: condition
            for condition in build_pilot_conditions(
                candidate.endpoint,
                candidate.rcd_type,
            )
        }
        return await self._run_candidate_conditions(
            runtime=runtime,
            observation_service=observation_service,
            candidate=candidate,
            staging_sink=staging_sink,
            conditions=tuple(
                conditions_by_category[category_id]
                for category_id in candidate.fixed_repeat_category_ids
            ),
        )

    async def _run_candidate_conditions(
        self,
        *,
        runtime: OfferTodayBrowserRuntime,
        observation_service: OfferTodayResearchObservationService,
        candidate: CensusCandidate,
        staging_sink: Any,
        conditions: Sequence[OfferTodayListingCondition],
    ) -> ListingRunResult:
        runner = self._runner_factory(runtime)
        return await runner.run(
            conditions=conditions,
            stop_policy=ListingStopPolicy(
                max_pages_per_condition=candidate.max_pages_per_condition,
                unique_job_cap=None,
                require_empty_confirmation=candidate.require_empty_confirmation,
            ),
            retry_policy=ListingRetryPolicy(
                max_attempts_per_page=candidate.max_attempts_per_page,
                retry_delays_seconds=candidate.retry_delays_seconds,
                page_delay_seconds=0.0,
                page_delay_range_seconds=candidate.page_delay_range_seconds,
            ),
            observation_sink=observation_service,
            staging_sink=staging_sink,
            session_mode=candidate.session_mode,
        )

    async def run_smoke(
        self,
        *,
        runtime: OfferTodayBrowserRuntime,
        observation_service: OfferTodayResearchObservationService,
    ) -> LiveSmokeExecution:
        staging_sink = ResearchNoopListingStagingSink()
        runner = self._runner_factory(runtime)
        listing_result = await runner.run(
            conditions=(build_runtime_smoke_condition(),),
            stop_policy=ListingStopPolicy(
                max_pages_per_condition=SMOKE_LISTING_REQUEST_LIMIT,
                unique_job_cap=SMOKE_DETAIL_TARGET_COUNT,
                require_empty_confirmation=False,
            ),
            retry_policy=ListingRetryPolicy(
                max_attempts_per_page=1,
                retry_delays_seconds=(),
                page_delay_seconds=0.0,
            ),
            observation_sink=observation_service,
            staging_sink=staging_sink,
            session_mode="fresh-headless",
        )
        frozen_targets = freeze_detail_smoke_cohort(
            listing_result,
            limit=SMOKE_DETAIL_TARGET_COUNT,
        )
        observation_service.record_event(
            "research.detail_cohort_frozen",
            {
                "count": len(frozen_targets),
                "targets": [target.to_payload() for target in frozen_targets],
            },
        )
        observations: list[DetailSmokeObservation] = []
        if listing_ready_for_detail_smoke(listing_result, frozen_targets):
            detail_scraper = self._detail_scraper_factory(
                detail_json_fetcher=runtime.fetch_detail_json,
                headed=False,
            )
            for index, target in enumerate(frozen_targets):
                started_timestamp = self._now().isoformat()
                started_at = self._clock()
                detail_result = await detail_scraper.fetch_job_detail(
                    target.job_id,
                    encrypted_job_id=target.encrypted_job_id,
                    encrypted_job_id_source=target.encrypted_job_id_source,
                )
                latency_ms = int(round(max(0.0, self._clock() - started_at) * 1000))
                completed_timestamp = self._now().isoformat()
                observation = detail_result_to_observation(
                    target=target,
                    result=detail_result,
                    started_at=started_timestamp,
                    completed_at=completed_timestamp,
                    latency_ms=latency_ms,
                )
                observations.append(observation)
                observation_service.record_detail_attempt(observation.to_payload())
                if observation.stop_batch:
                    break
                if index + 1 < len(frozen_targets):
                    await self._sleep(3.0)
        decision = evaluate_smoke(
            listing_result=listing_result,
            frozen_targets=frozen_targets,
            observations=tuple(observations),
        )
        return LiveSmokeExecution(
            listing_result=listing_result,
            frozen_targets=frozen_targets,
            detail_observations=tuple(observations),
            decision=decision,
            would_stage_rows=staging_sink.would_stage_rows,
            stage_calls=staging_sink.stage_calls,
        )


def detail_result_to_observation(
    *,
    target: DetailSmokeTarget,
    result: OfferTodayDetailFetchResult,
    started_at: str,
    completed_at: str,
    latency_ms: int,
) -> DetailSmokeObservation:
    canonical: dict[str, Any] = result.canonical_detail or {}
    classification = result.classification
    expected_identity = OfferTodayDetailIdentity(
        job_id=target.job_id,
        encrypted_job_id=target.encrypted_job_id,
        encrypted_job_id_source=target.encrypted_job_id_source,
    )
    return DetailSmokeObservation(
        target=target,
        classification=classification.kind.value,
        api_code=classification.code,
        started_at=started_at,
        completed_at=completed_at,
        latency_ms=latency_ms,
        identity_valid=(
            classification.kind is OfferTodayResponseKind.SUCCESS
            and result.canonical_detail is not None
            and result.identity == expected_identity
        ),
        parsed=result.parsed_detail is not None,
        has_title=bool(str(canonical.get("title") or "").strip()),
        has_company=bool(str(canonical.get("company_name") or "").strip()),
        has_description=bool(str(canonical.get("description_text") or "").strip()),
        stop_batch=classification.stop_batch,
    )
