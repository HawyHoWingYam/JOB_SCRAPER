from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from app.scraper.offertoday_browser_detail_scraper import (
    OfferTodayBrowserDetailScraper,
)
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
    ListingStopPolicy,
    OfferTodayListingRunner,
)
from app.sources.offertoday.research.live_contracts import (
    DetailSmokeObservation,
    DetailSmokeTarget,
    LiveSmokeExecution,
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
                latency_ms = int(
                    round(max(0.0, self._clock() - started_at) * 1000)
                )
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
        has_description=bool(
            str(canonical.get("description_text") or "").strip()
        ),
        stop_batch=classification.stop_batch,
    )
