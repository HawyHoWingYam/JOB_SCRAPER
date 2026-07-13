from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from itertools import permutations
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from app.sources.offertoday.constants import (
    OFFERTODAY_LISTING_BROWSE_URL,
    OFFERTODAY_LISTING_SEARCH_URL,
)
from app.sources.offertoday import listing_runner as runner_module
from app.sources.offertoday.listing_runner import (
    ListingRetryPolicy,
    ListingStopPolicy,
    OfferTodayIdentityPair,
    OfferTodayListingCondition,
    OfferTodayListingRunner,
    listing_observation_to_payload,
)
from app.sources.offertoday.listing_contract import (
    OfferTodayBrowserContextLostError,
    OfferTodayListingRequestPolicy,
    OfferTodayListingTransportResult,
)
from app.sources.offertoday.response_policy import (
    OfferTodayResponseKind,
    OfferTodayTransportError,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "offertoday"


def _listing_row(
    job_id: Any,
    encrypted_job_id: Any,
    *,
    title: str = "Platform Engineer",
    function_codes: tuple[str, ...] = ("118000", "118003", "118003"),
) -> dict[str, Any]:
    top_code = function_codes[0] if function_codes else None
    child_codes = function_codes[1:]
    return {
        "jobId": job_id,
        "encryptJobId": encrypted_job_id,
        "jobName": title,
        "companyName": "Example Technology Limited",
        "locationDesc": "Hong Kong",
        "level3LocDesc": "Central and Western",
        "salaryDesc": "HKD 40K-55K",
        "jobTypeDesc": "Full Time",
        "experience": "3 years",
        "educationDesc": "Degree",
        "skills": ["Python", "AWS"],
        "skillList": ["FastAPI"],
        "keywords": ["platform"],
        "benefits": ["Medical insurance"],
        "workingDays": "5 days",
        "jobPostTime": "2026-07-10T09:30:00+08:00",
        "jobFunctions": (
            [
                {
                    "code": top_code,
                    "name": "Information Technology",
                    "children": [
                        {"code": code, "name": "Software Development"}
                        for code in child_codes
                    ],
                }
            ]
            if top_code is not None
            else []
        ),
        "locations": {
            "code": "100000",
            "name": "Hong Kong",
            "children": [],
        },
        "jobType": 1,
        "activeStatus": "ACTIVE",
        "bossName": "Recruiter Lee",
        "bossTitle": "Talent Partner",
        "brandLogo": "https://cdn.offertoday.com/company/example.png",
    }


def _listing_response(
    rows: list[dict[str, Any]],
    *,
    has_more: bool,
    total: int = 1,
) -> dict[str, Any]:
    return {
        "code": 0,
        "msg": "Success",
        "data": {
            "pageSize": 50,
            "total": total,
            "hasMore": has_more,
            "resultList": rows,
            "recommendation": {"rcdType": 7},
        },
    }


def _cursor_response(
    rows: list[dict[str, Any]],
    *,
    session_id: str = "session-1",
    page_size: int = 10,
    has_more: bool = True,
    supplemental_rows: list[dict[str, Any]] | None = None,
    supple_page: int = 0,
    supple_amount: int = 0,
    supple_type: int = 0,
) -> dict[str, Any]:
    response = _listing_response(rows, has_more=has_more, total=len(rows))
    response["data"].update(
        {
            "pageSize": page_size,
            "sessionId": session_id,
            "supplePage": supple_page,
            "suppleAmount": supple_amount,
            "suppleType": supple_type,
            "suppleRcdList": list(supplemental_rows or []),
        }
    )
    return response


def _request_policy(**overrides) -> OfferTodayListingRequestPolicy:
    values = {
        "protocol_version": 2,
        "pagination_mode": "response-cursor",
        "requested_page_size": 10,
        "browser_lifecycle": "condition-local-runtime",
        "variant_id": "ui-cursor-same-browser",
        "repeat_index": 1,
    }
    values.update(overrides)
    return OfferTodayListingRequestPolicy(**values)


class ScriptedTransport:
    def __init__(self, *steps: object) -> None:
        self.steps = list(steps)
        self.requests: list[tuple[dict[str, Any], str | None]] = []

    async def fetch_listing_json(
        self,
        payload: dict[str, Any],
        *,
        listing_url: str | None = None,
    ) -> dict[str, Any] | None:
        self.requests.append((deepcopy(payload), listing_url))
        if not self.steps:
            raise AssertionError("scripted transport exhausted")
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return deepcopy(step)


class RestartableScriptedTransport:
    def __init__(self, *steps: object) -> None:
        self.steps = list(steps)
        self.requests: list[dict[str, Any]] = []
        self.restart_count = 0
        self._context_number = 1

    @property
    def browser_context_hash(self) -> str:
        return hashlib.sha256(
            f"restartable-context-{self._context_number}".encode()
        ).hexdigest()

    async def fetch_listing_page(
        self,
        payload: dict[str, Any],
        *,
        listing_url: str | None = None,
    ) -> OfferTodayListingTransportResult:
        self.requests.append(deepcopy(payload))
        if not self.steps:
            raise AssertionError("restartable transport exhausted")
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return OfferTodayListingTransportResult(
            payload=deepcopy(step),
            browser_context_hash=self.browser_context_hash,
        )

    async def restart_after_browser_loss(self) -> None:
        self.restart_count += 1
        self._context_number += 1


class ResponseUrlScriptedTransport:
    def __init__(self, payload: dict[str, Any], response_url: str) -> None:
        self.payload = deepcopy(payload)
        self.response_url = response_url
        self.requests: list[dict[str, Any]] = []

    async def fetch_listing_page(
        self,
        payload: dict[str, Any],
        *,
        listing_url: str | None = None,
    ) -> OfferTodayListingTransportResult:
        self.requests.append(deepcopy(payload))
        return OfferTodayListingTransportResult(
            payload=self.payload,
            http_status=200,
            response_url=self.response_url,
        )


class MemoryObservationSink:
    def __init__(self) -> None:
        self.observations: list[object] = []
        self.outcomes: list[object] = []

    async def record_page_attempt(self, observation: object) -> None:
        self.observations.append(observation)

    async def record_condition_outcome(self, outcome: object) -> None:
        self.outcomes.append(outcome)


class MemoryStagingSink:
    def __init__(self) -> None:
        self.staged_pages: list[dict[str, object]] = []
        self.deferrals: list[dict[str, object]] = []

    async def stage_page(
        self,
        *,
        condition: object,
        page: int,
        rows: list[dict[str, Any]],
    ) -> None:
        self.staged_pages.append(
            {
                "condition": condition,
                "page": page,
                "rows": deepcopy(rows),
            }
        )

    async def defer_identity_conflict(
        self,
        *,
        job_ids: tuple[str, ...],
        encrypted_job_ids: tuple[str, ...],
        reason: str,
    ) -> None:
        self.deferrals.append(
            {
                "job_ids": job_ids,
                "encrypted_job_ids": encrypted_job_ids,
                "reason": reason,
            }
        )


class NoWaitSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay_seconds: float) -> None:
        self.delays.append(delay_seconds)


class DeterministicClock:
    def __init__(self, step_seconds: float = 0.025) -> None:
        self.current = 0.0
        self.step_seconds = step_seconds

    def __call__(self) -> float:
        self.current += self.step_seconds
        return self.current


def _condition(*, keyword: str = "platform") -> OfferTodayListingCondition:
    return OfferTodayListingCondition(
        search_family="explicit_keyword",
        category_id=None,
        keyword=keyword,
        endpoint="search",
        rcd_type=7,
    )


async def _run(
    transport: ScriptedTransport,
    *,
    conditions: list[OfferTodayListingCondition] | None = None,
    max_pages: int = 10,
    max_attempts: int = 3,
    unique_job_cap: int | None = None,
    require_empty_confirmation: bool = True,
    request_policy: OfferTodayListingRequestPolicy | None = None,
):
    observation_sink = MemoryObservationSink()
    staging_sink = MemoryStagingSink()
    sleep = NoWaitSleep()
    runner = OfferTodayListingRunner(
        transport,
        sleep=sleep,
        clock=DeterministicClock(),
    )
    result = await runner.run(
        conditions=conditions or [_condition()],
        stop_policy=ListingStopPolicy(
            max_pages_per_condition=max_pages,
            unique_job_cap=unique_job_cap,
            require_empty_confirmation=require_empty_confirmation,
        ),
        retry_policy=ListingRetryPolicy(
            max_attempts_per_page=max_attempts,
            retry_delays_seconds=(0.1, 0.2),
            page_delay_seconds=0.0,
        ),
        observation_sink=observation_sink,
        staging_sink=staging_sink,
        session_mode="saved-session",
        request_policy=request_policy,
    )
    return result, observation_sink, staging_sink, sleep


@pytest.mark.asyncio
async def test_page_delay_range_uses_uniform_for_each_successful_transition() -> None:
    transport = ScriptedTransport(
        _listing_response([_listing_row("j1", "e1")], has_more=True, total=3),
        _listing_response([_listing_row("j2", "e2")], has_more=True, total=3),
        _listing_response([_listing_row("j3", "e3")], has_more=False, total=3),
    )
    observation_sink = MemoryObservationSink()
    staging_sink = MemoryStagingSink()
    sleep = NoWaitSleep()
    uniform_calls: list[tuple[float, float]] = []

    def uniform(lower: float, upper: float) -> float:
        uniform_calls.append((lower, upper))
        return 4.25

    runner = OfferTodayListingRunner(
        transport,
        sleep=sleep,
        clock=DeterministicClock(),
        uniform=uniform,
    )

    result = await runner.run(
        conditions=[_condition()],
        stop_policy=ListingStopPolicy(
            max_pages_per_condition=3,
            require_empty_confirmation=False,
        ),
        retry_policy=ListingRetryPolicy(
            max_attempts_per_page=3,
            retry_delays_seconds=(5.0, 15.0),
            page_delay_seconds=0.0,
            page_delay_range_seconds=(3.0, 5.0),
        ),
        observation_sink=observation_sink,
        staging_sink=staging_sink,
        session_mode="saved-session",
    )

    assert result.is_complete is True
    assert [request[0]["page"] for request in transport.requests] == [1, 2, 3]
    assert uniform_calls == [(3.0, 5.0), (3.0, 5.0)]
    assert sleep.delays == [4.25, 4.25]


@pytest.mark.asyncio
async def test_page_delay_range_does_not_randomize_retry_delays() -> None:
    transport = ScriptedTransport(
        {"code": 7001, "msg": "Temporary upstream error", "data": {}},
        {"code": 7001, "msg": "Temporary upstream error", "data": {}},
        _listing_response([_listing_row("j1", "e1")], has_more=True, total=2),
        _listing_response([_listing_row("j2", "e2")], has_more=False, total=2),
    )
    observation_sink = MemoryObservationSink()
    staging_sink = MemoryStagingSink()
    sleep = NoWaitSleep()
    runner = OfferTodayListingRunner(
        transport,
        sleep=sleep,
        clock=DeterministicClock(),
        uniform=lambda lower, upper: 4.25,
    )

    result = await runner.run(
        conditions=[_condition()],
        stop_policy=ListingStopPolicy(
            max_pages_per_condition=2,
            require_empty_confirmation=False,
        ),
        retry_policy=ListingRetryPolicy(
            max_attempts_per_page=3,
            retry_delays_seconds=(5.0, 15.0),
            page_delay_seconds=0.0,
            page_delay_range_seconds=(3.0, 5.0),
        ),
        observation_sink=observation_sink,
        staging_sink=staging_sink,
        session_mode="saved-session",
    )

    assert result.is_complete is True
    assert [request[0]["page"] for request in transport.requests] == [1, 1, 1, 2]
    assert sleep.delays == [5.0, 15.0, 4.25]


@pytest.mark.asyncio
async def test_policy_without_page_delay_range_keeps_fixed_transition_delay() -> None:
    transport = ScriptedTransport(
        _listing_response([_listing_row("j1", "e1")], has_more=True, total=2),
        _listing_response([_listing_row("j2", "e2")], has_more=False, total=2),
    )
    observation_sink = MemoryObservationSink()
    staging_sink = MemoryStagingSink()
    sleep = NoWaitSleep()

    def unexpected_uniform(_lower: float, _upper: float) -> float:
        raise AssertionError("uniform must not run without a delay range")

    runner = OfferTodayListingRunner(
        transport,
        sleep=sleep,
        clock=DeterministicClock(),
        uniform=unexpected_uniform,
    )

    result = await runner.run(
        conditions=[_condition()],
        stop_policy=ListingStopPolicy(
            max_pages_per_condition=2,
            require_empty_confirmation=False,
        ),
        retry_policy=ListingRetryPolicy(page_delay_seconds=1.75),
        observation_sink=observation_sink,
        staging_sink=staging_sink,
        session_mode="saved-session",
    )

    assert result.is_complete is True
    assert sleep.delays == [1.75]


@pytest.mark.parametrize(
    "delay_range",
    (
        (-1.0, 3.0),
        (3.0, -1.0),
        (5.0, 3.0),
        (float("nan"), 3.0),
        (3.0, float("inf")),
    ),
)
def test_page_delay_range_rejects_negative_reversed_or_non_finite_values(
    delay_range: tuple[float, float],
) -> None:
    with pytest.raises(ValueError, match="page_delay_range_seconds"):
        ListingRetryPolicy(page_delay_range_seconds=delay_range)


@pytest.mark.parametrize(
    ("fixture_name", "endpoint", "expected_job_id"),
    [
        ("jobid_only_search_page.json", "search", "RbeDGc1VoBZwKIInWPjDCA=="),
        ("jobid_only_browse_page.json", "browse", "lxwa-xaLLtVD4diDhVRUjw=="),
    ],
)
@pytest.mark.asyncio
async def test_real_jobid_only_page_is_accepted_with_observation_and_fallback_counts(
    fixture_name: str,
    endpoint: str,
    expected_job_id: str,
) -> None:
    response = json.loads((FIXTURE_ROOT / fixture_name).read_text(encoding="utf-8"))
    raw_before = deepcopy(response["data"]["resultList"][0])
    condition = OfferTodayListingCondition(
        search_family="runtime_smoke",
        category_id=118000,
        keyword="",
        endpoint=endpoint,
        rcd_type=7,
    )

    result, observations, staging, _sleep = await _run(
        ScriptedTransport(response),
        conditions=[condition],
        max_pages=1,
        require_empty_confirmation=False,
    )

    assert result.stop_reason == "page_cap"
    assert result.identity_issues == ()
    assert result.identity_conflicts == ()
    assert result.accepted_job_ids == (expected_job_id,)
    assert result.id_pairs[0].job_id == expected_job_id
    assert result.id_pairs[0].encrypted_job_id == expected_job_id
    assert result.id_pairs[0].encrypted_job_id_source == "jobId_fallback"
    page = observations.observations[0]
    assert page.missing_encrypted_job_id_count == 1
    assert page.job_id_fallback_count == 1
    assert page.identity_issues == ()
    assert staging.staged_pages[0]["rows"][0]["raw_data"] == raw_before
    assert "encryptJobId" not in staging.staged_pages[0]["rows"][0]["raw_data"]


@pytest.mark.asyncio
async def test_single_explicit_mapping_promotes_prior_fallback_authority() -> None:
    fallback = _listing_row("j-promote", None)
    fallback.pop("encryptJobId")
    transport = ScriptedTransport(
        _listing_response([fallback], has_more=True),
        _listing_response([_listing_row("j-promote", "enc-promoted")], has_more=False),
    )

    result, observations, staging, _sleep = await _run(
        transport,
        max_pages=2,
        require_empty_confirmation=False,
    )

    assert result.identity_conflicts == ()
    assert result.accepted_job_ids == ("j-promote",)
    assert result.id_pairs[0].encrypted_job_id == "enc-promoted"
    assert result.id_pairs[0].encrypted_job_id_source == "encryptJobId"
    assert observations.observations[0].job_id_fallback_count == 1
    assert observations.observations[1].job_id_fallback_count == 0
    assert observations.observations[0].id_pairs == (
        OfferTodayIdentityPair("j-promote", "j-promote", "jobId_fallback"),
    )
    assert observations.observations[1].id_pairs == (
        OfferTodayIdentityPair("j-promote", "enc-promoted", "encryptJobId"),
    )
    assert len(staging.staged_pages) == 2
    assert [
        page["rows"][0]["encrypted_job_id_source"]
        for page in staging.staged_pages
    ] == ["jobId_fallback", "encryptJobId"]


@pytest.mark.asyncio
async def test_later_fallback_does_not_downgrade_explicit_authority() -> None:
    later_fallback = _listing_row("j-stable", None)
    later_fallback.pop("encryptJobId")
    transport = ScriptedTransport(
        _listing_response(
            [_listing_row("j-stable", "enc-stable")],
            has_more=True,
        ),
        _listing_response([later_fallback], has_more=False),
    )

    result, observations, _staging, _sleep = await _run(
        transport,
        max_pages=2,
        require_empty_confirmation=False,
    )

    assert observations.observations[0].id_pairs == (
        OfferTodayIdentityPair("j-stable", "enc-stable", "encryptJobId"),
    )
    assert observations.observations[1].rows[0].encrypted_job_id_source == (
        "jobId_fallback"
    )
    assert observations.observations[1].id_pairs == (
        OfferTodayIdentityPair("j-stable", "enc-stable", "encryptJobId"),
    )
    assert result.id_pairs == observations.observations[1].id_pairs


@pytest.mark.parametrize("encrypted_value", [None, "   "])
@pytest.mark.asyncio
async def test_valid_jobid_with_null_or_blank_encrypted_value_uses_fallback(
    encrypted_value,
) -> None:
    transport = ScriptedTransport(
        _listing_response(
            [_listing_row("j-fallback", encrypted_value)],
            has_more=True,
        )
    )

    result, observations, staging, _sleep = await _run(
        transport,
        max_pages=1,
        require_empty_confirmation=False,
    )

    assert result.identity_issues == ()
    assert result.id_pairs == (
        OfferTodayIdentityPair(
            "j-fallback",
            "j-fallback",
            "jobId_fallback",
        ),
    )
    assert observations.observations[0].missing_encrypted_job_id_count == 1
    assert observations.observations[0].job_id_fallback_count == 1
    assert len(staging.staged_pages) == 1


@pytest.mark.asyncio
async def test_retries_same_page_then_confirms_natural_exhaustion_and_stages_normalized_rows() -> (
    None
):
    raw_row = _listing_row("j-1", "enc-1")
    transport = ScriptedTransport(
        TimeoutError("listing request timed out"),
        _listing_response([raw_row], has_more=True),
        _listing_response([], has_more=False),
        _listing_response([], has_more=False),
    )

    result, observations, staging, sleep = await _run(transport)

    assert [request[0]["page"] for request in transport.requests] == [1, 1, 2, 3]
    assert {request[1] for request in transport.requests} == {
        OFFERTODAY_LISTING_SEARCH_URL
    }
    assert result.stop_reason == "natural_exhaustion"
    assert result.is_complete is True
    assert result.ordered_job_ids == ("j-1",)
    assert result.accepted_job_ids == ("j-1",)
    assert [(pair.job_id, pair.encrypted_job_id) for pair in result.id_pairs] == [
        ("j-1", "enc-1")
    ]
    assert result.gaps == ()
    assert result.identity_issues == ()
    assert result.identity_conflicts == ()
    assert result.condition_outcomes[0].pages_observed == 3
    assert result.condition_outcomes[0].stop_reason == "natural_exhaustion"
    assert result.condition_outcomes[0].is_complete is True

    assert [(item.page, item.attempt) for item in observations.observations] == [
        (1, 1),
        (1, 2),
        (2, 1),
        (3, 1),
    ]
    assert [item.classification for item in observations.observations] == [
        OfferTodayResponseKind.TRANSIENT_TRANSPORT.value,
        OfferTodayResponseKind.SUCCESS.value,
        OfferTodayResponseKind.SUCCESS.value,
        OfferTodayResponseKind.SUCCESS.value,
    ]
    assert observations.observations[0].retry_reason == "transient_transport"
    assert observations.observations[1].reported_total == 1
    assert observations.observations[1].has_more is True
    assert observations.observations[1].row_count == 1
    evidence = observations.observations[1].rows[0]
    assert evidence.job_id == "j-1"
    assert evidence.encrypted_job_id == "enc-1"
    assert evidence.job_function_codes == ("118000", "118003")
    assert evidence.title_language == "en"
    assert evidence.api_language == "zh_HK"
    assert all(item.latency_ms == 25 for item in observations.observations)
    assert all(
        item.session_mode == "saved-session" for item in observations.observations
    )

    assert len(staging.staged_pages) == 1
    staged_row = staging.staged_pages[0]["rows"][0]
    assert staged_row["job_id"] == "j-1"
    assert staged_row["encrypted_job_id"] == "enc-1"
    assert staged_row["raw_data"] == raw_row
    assert sleep.delays == [0.1]


@pytest.mark.asyncio
async def test_exhausted_confirmation_retries_create_gap_without_advancing() -> None:
    transport = ScriptedTransport(
        _listing_response([], has_more=False, total=0),
        TimeoutError("confirmation timeout 1"),
        TimeoutError("confirmation timeout 2"),
        TimeoutError("confirmation timeout 3"),
    )

    result, observations, staging, sleep = await _run(transport)

    assert [request[0]["page"] for request in transport.requests] == [1, 2, 2, 2]
    assert result.stop_reason == "unresolved_gap"
    assert result.is_complete is False
    assert len(result.gaps) == 1
    assert result.gaps[0].condition_id == _condition().condition_id
    assert result.gaps[0].page == 2
    assert result.gaps[0].attempts == 3
    assert result.gaps[0].last_kind is OfferTodayResponseKind.TRANSIENT_TRANSPORT
    assert result.condition_outcomes[0].pages_observed == 1
    assert result.condition_outcomes[0].stop_reason == "unresolved_gap"
    assert result.condition_outcomes[0].is_complete is False
    assert [
        observation.retry_reason for observation in observations.observations[1:]
    ] == ["transient_transport", "transient_transport", None]
    assert observations.observations[-1].stop_reason == "unresolved_gap"
    assert observations.outcomes == list(result.condition_outcomes)
    assert staging.staged_pages == []
    assert sleep.delays == [0.1, 0.2]


@pytest.mark.asyncio
async def test_nonempty_confirmation_is_contract_anomaly_and_restarts_empty_confirmation() -> (
    None
):
    transport = ScriptedTransport(
        _listing_response([], has_more=False, total=1),
        _listing_response(
            [_listing_row("j-anomaly", "enc-anomaly")],
            has_more=True,
        ),
        _listing_response([], has_more=False, total=1),
        _listing_response([], has_more=False, total=1),
    )

    result, observations, staging, _sleep = await _run(transport)

    assert [request[0]["page"] for request in transport.requests] == [1, 2, 3, 4]
    assert [item.classification for item in observations.observations] == [
        "success",
        "contract_anomaly",
        "success",
        "success",
    ]
    assert observations.observations[1].row_count == 1
    assert result.ordered_job_ids == ("j-anomaly",)
    assert result.accepted_job_ids == ("j-anomaly",)
    assert staging.staged_pages[0]["page"] == 2
    assert result.stop_reason == "natural_exhaustion"
    assert result.is_complete is True


@pytest.mark.asyncio
async def test_page_cap_preventing_confirmation_is_incomplete() -> None:
    transport = ScriptedTransport(_listing_response([], has_more=False, total=0))

    result, observations, _staging, _sleep = await _run(transport, max_pages=1)

    assert [request[0]["page"] for request in transport.requests] == [1]
    assert len(observations.observations) == 1
    assert result.condition_outcomes[0].stop_reason == "page_cap"
    assert result.condition_outcomes[0].is_complete is False
    assert result.stop_reason == "page_cap"
    assert result.is_complete is False


@pytest.mark.asyncio
async def test_unique_job_cap_is_an_explicit_incomplete_target_stop() -> None:
    transport = ScriptedTransport(
        _listing_response([_listing_row("j-cap", "enc-cap")], has_more=True)
    )

    result, observations, staging, _sleep = await _run(
        transport,
        unique_job_cap=1,
    )

    assert [request[0]["page"] for request in transport.requests] == [1]
    assert observations.observations[0].stop_reason == "target_cap"
    assert len(staging.staged_pages) == 1
    assert result.ordered_job_ids == ("j-cap",)
    assert result.accepted_job_ids == ("j-cap",)
    assert result.condition_outcomes[0].stop_reason == "target_cap"
    assert result.stop_reason == "target_cap"
    assert result.is_complete is False


@pytest.mark.asyncio
async def test_two_page_target_cap_collects_twenty_and_never_requests_page_three() -> (
    None
):
    def jobid_only_rows(start: int, stop: int) -> list[dict[str, Any]]:
        rows = []
        for number in range(start, stop):
            row = _listing_row(f"j{number:02d}", None)
            row.pop("encryptJobId")
            rows.append(row)
        return rows

    transport = ScriptedTransport(
        _listing_response(jobid_only_rows(1, 11), has_more=True, total=21),
        _listing_response(jobid_only_rows(11, 21), has_more=True, total=21),
        _listing_response(jobid_only_rows(21, 22), has_more=False, total=21),
    )

    result, observations, _staging, _sleep = await _run(
        transport,
        max_pages=2,
        max_attempts=1,
        unique_job_cap=20,
        require_empty_confirmation=False,
    )

    expected_ids = tuple(f"j{number:02d}" for number in range(1, 21))
    assert [request[0]["page"] for request in transport.requests] == [1, 2]
    assert len(transport.steps) == 1
    assert result.accepted_job_ids == expected_ids
    assert tuple(pair.encrypted_job_id_source for pair in result.id_pairs) == (
        "jobId_fallback",
    ) * 20
    assert [item.stop_reason for item in observations.observations] == [
        None,
        "target_cap",
    ]
    assert result.stop_reason == "target_cap"
    assert result.is_complete is False


@pytest.mark.asyncio
async def test_unique_job_cap_precedes_terminal_completion_when_confirmation_disabled() -> (
    None
):
    transport = ScriptedTransport(
        _listing_response(
            [_listing_row("j-terminal-cap", "enc-terminal-cap")],
            has_more=False,
        )
    )

    result, observations, staging, _sleep = await _run(
        transport,
        unique_job_cap=1,
        require_empty_confirmation=False,
    )

    assert len(transport.requests) == 1
    assert result.ordered_job_ids == ("j-terminal-cap",)
    assert result.accepted_job_ids == ("j-terminal-cap",)
    assert len(staging.staged_pages) == 1
    assert observations.observations[0].stop_reason == "target_cap"
    assert result.condition_outcomes[0].stop_reason == "target_cap"
    assert result.condition_outcomes[0].is_complete is False
    assert result.stop_reason == "target_cap"
    assert result.is_complete is False


@pytest.mark.asyncio
async def test_two_explicit_mappings_remain_a_forward_conflict() -> None:
    transport = ScriptedTransport(
        _listing_response(
            [
                _listing_row("j-conflict", "enc-first"),
                _listing_row("j-conflict", "enc-second"),
            ],
            has_more=True,
        )
    )

    result, observations, staging, _sleep = await _run(transport, max_pages=1)

    assert result.stop_reason == "identity_conflict"
    assert result.is_complete is False
    assert result.ordered_job_ids == ("j-conflict",)
    assert result.accepted_job_ids == ()
    assert result.id_pairs == ()
    assert len(result.identity_conflicts) == 1
    conflict = result.identity_conflicts[0]
    assert conflict.job_ids == ("j-conflict",)
    assert conflict.encrypted_job_ids == ("enc-first", "enc-second")
    assert conflict.reason == "multiple_explicit_encrypted_ids"
    assert observations.observations[0].identity_conflicts == (conflict,)
    assert observations.observations[0].classification == "identity_conflict"
    assert observations.observations[0].stop_reason == "identity_conflict"
    assert observations.observations[0].id_pairs == ()
    assert staging.staged_pages == []
    assert staging.deferrals == [
        {
            "job_ids": ("j-conflict",),
            "encrypted_job_ids": ("enc-first", "enc-second"),
            "reason": "multiple_explicit_encrypted_ids",
        }
    ]


@pytest.mark.asyncio
async def test_later_mapping_change_defers_earlier_staged_canonical_row() -> None:
    transport = ScriptedTransport(
        _listing_response(
            [_listing_row("j-later", "enc-original")],
            has_more=True,
        ),
        _listing_response(
            [_listing_row("j-later", "enc-changed")],
            has_more=True,
        ),
    )

    result, observations, staging, _sleep = await _run(transport)

    assert [request[0]["page"] for request in transport.requests] == [1, 2]
    assert [page["page"] for page in staging.staged_pages] == [1]
    assert staging.deferrals == [
        {
            "job_ids": ("j-later",),
            "encrypted_job_ids": ("enc-changed", "enc-original"),
            "reason": "multiple_explicit_encrypted_ids",
        }
    ]
    assert result.ordered_job_ids == ("j-later",)
    assert result.accepted_job_ids == ()
    assert result.id_pairs == ()
    assert result.stop_reason == "identity_conflict"
    assert observations.observations[1].stop_reason == "identity_conflict"


@pytest.mark.parametrize(
    (
        "job_id",
        "encrypted_job_id",
        "expected_job_id",
        "expected_encrypted_job_id",
        "reason",
        "missing_field",
    ),
    [
        (None, "enc-orphan", None, "enc-orphan", "missing_job_id", "job_id"),
        ("  ", "enc-blank", None, "enc-blank", "missing_job_id", "job_id"),
    ],
)
@pytest.mark.asyncio
async def test_missing_identity_fields_are_observed_and_never_staged(
    job_id: Any,
    encrypted_job_id: Any,
    expected_job_id: str | None,
    expected_encrypted_job_id: str | None,
    reason: str,
    missing_field: str,
) -> None:
    transport = ScriptedTransport(
        _listing_response(
            [_listing_row(job_id, encrypted_job_id)],
            has_more=True,
        )
    )

    result, observations, staging, _sleep = await _run(transport, max_pages=1)

    assert result.stop_reason == "identity_issue"
    assert result.is_complete is False
    assert len(result.identity_issues) == 1
    issue = result.identity_issues[0]
    assert issue.job_id == expected_job_id
    assert issue.encrypted_job_id == expected_encrypted_job_id
    assert issue.reason == reason
    observation = observations.observations[0]
    assert observation.identity_issues == (issue,)
    assert observation.classification == "identity_issue"
    assert observation.missing_job_id_count == (missing_field == "job_id")
    assert observation.missing_encrypted_job_id_count == (
        missing_field == "encrypted_job_id"
    )
    assert observation.stop_reason == "identity_issue"
    assert staging.staged_pages == []
    assert staging.deferrals == []
    assert result.accepted_job_ids == ()
    if expected_job_id is None:
        assert result.ordered_job_ids == ()
    else:
        assert result.ordered_job_ids == (expected_job_id,)


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "expected_reason"),
    [
        ("jobId", ["bad"], "invalid_job_id_evidence"),
        ("jobId", {"bad": 1}, "invalid_job_id_evidence"),
        ("jobId", True, "invalid_job_id_evidence"),
        ("jobId", 101, "invalid_job_id_evidence"),
        ("encryptJobId", ["bad"], "invalid_encrypted_job_id_evidence"),
        ("encryptJobId", {"bad": 1}, "invalid_encrypted_job_id_evidence"),
        ("encryptJobId", False, "invalid_encrypted_job_id_evidence"),
        ("encryptJobId", 202, "invalid_encrypted_job_id_evidence"),
    ],
)
@pytest.mark.asyncio
async def test_non_string_raw_identity_values_are_rejected_before_staging(
    field_name: str,
    invalid_value: object,
    expected_reason: str,
) -> None:
    raw_row = _listing_row("j-valid", "enc-valid")
    raw_row[field_name] = invalid_value
    transport = ScriptedTransport(
        _listing_response([raw_row], has_more=True),
    )

    result, observations, staging, _sleep = await _run(transport, max_pages=1)

    assert result.stop_reason == "identity_issue"
    assert result.is_complete is False
    assert result.accepted_job_ids == ()
    assert result.id_pairs == ()
    assert len(result.identity_issues) == 1
    assert result.identity_issues[0].reason == expected_reason
    assert observations.observations[0].classification == "identity_issue"
    assert observations.observations[0].identity_issues == result.identity_issues
    assert observations.observations[0].missing_job_id_count == 0
    assert observations.observations[0].missing_encrypted_job_id_count == 0
    assert staging.staged_pages == []

    evidence = observations.observations[0].rows[0]
    if field_name == "jobId":
        assert evidence.job_id is None
        assert evidence.encrypted_job_id == "enc-valid"
        assert result.ordered_job_ids == ()
    else:
        assert evidence.job_id == "j-valid"
        assert evidence.encrypted_job_id is None
        assert result.ordered_job_ids == ("j-valid",)


@pytest.mark.parametrize(
    (
        "job_id",
        "encrypted_job_id",
        "expected_issue_reason",
        "expected_missing_job_count",
        "expected_missing_encrypted_count",
    ),
    [
        (None, None, "missing_job_id", 1, 1),
        (["bad"], None, "invalid_job_id_evidence", 0, 1),
        (None, {"bad": 1}, "missing_job_id", 1, 0),
    ],
)
@pytest.mark.asyncio
async def test_combined_identity_fields_keep_independent_missing_counts(
    job_id: object,
    encrypted_job_id: object,
    expected_issue_reason: str,
    expected_missing_job_count: int,
    expected_missing_encrypted_count: int,
) -> None:
    transport = ScriptedTransport(
        _listing_response(
            [_listing_row(job_id, encrypted_job_id)],
            has_more=True,
        )
    )

    result, observations, staging, _sleep = await _run(transport, max_pages=1)

    assert result.stop_reason == "identity_issue"
    assert result.accepted_job_ids == ()
    assert result.id_pairs == ()
    assert len(result.identity_issues) == 1
    assert result.identity_issues[0].reason == expected_issue_reason
    observation = observations.observations[0]
    assert observation.missing_job_id_count == expected_missing_job_count
    assert (
        observation.missing_encrypted_job_id_count == expected_missing_encrypted_count
    )
    assert staging.staged_pages == []


@pytest.mark.asyncio
async def test_reverse_identity_conflict_defers_both_canonical_ids_and_stages_nothing() -> (
    None
):
    transport = ScriptedTransport(
        _listing_response(
            [
                _listing_row("j-first", "enc-shared"),
                _listing_row("j-second", "enc-shared"),
            ],
            has_more=True,
        )
    )

    result, observations, staging, _sleep = await _run(transport, max_pages=1)

    assert result.stop_reason == "identity_conflict"
    assert result.ordered_job_ids == ("j-first", "j-second")
    assert result.accepted_job_ids == ()
    assert result.id_pairs == ()
    assert len(result.identity_conflicts) == 1
    conflict = result.identity_conflicts[0]
    assert conflict.job_ids == ("j-first", "j-second")
    assert conflict.encrypted_job_ids == ("enc-shared",)
    assert conflict.reason == "one_encrypted_id_to_multiple_job_ids"
    assert observations.observations[0].identity_conflicts == (conflict,)
    assert observations.observations[0].classification == "identity_conflict"
    assert staging.staged_pages == []
    assert staging.deferrals == [
        {
            "job_ids": ("j-first", "j-second"),
            "encrypted_job_ids": ("enc-shared",),
            "reason": "one_encrypted_id_to_multiple_job_ids",
        }
    ]


@pytest.mark.parametrize(
    (
        "first_order",
        "second_order",
        "expected_job_ids",
        "expected_encrypted_job_ids",
        "expected_reason",
    ),
    [
        (
            (("j-forward", "enc-z"), ("j-forward", "enc-a")),
            (("j-forward", "enc-a"), ("j-forward", "enc-z")),
            ("j-forward",),
            ("enc-a", "enc-z"),
            "multiple_explicit_encrypted_ids",
        ),
        (
            (("j-z", "enc-reverse"), ("j-a", "enc-reverse")),
            (("j-a", "enc-reverse"), ("j-z", "enc-reverse")),
            ("j-a", "j-z"),
            ("enc-reverse",),
            "one_encrypted_id_to_multiple_job_ids",
        ),
    ],
)
@pytest.mark.asyncio
async def test_identity_conflict_and_deferral_evidence_is_permutation_stable(
    first_order: tuple[tuple[str, str], ...],
    second_order: tuple[tuple[str, str], ...],
    expected_job_ids: tuple[str, ...],
    expected_encrypted_job_ids: tuple[str, ...],
    expected_reason: str,
) -> None:
    async def run_order(
        identity_pairs: tuple[tuple[str, str], ...],
    ) -> tuple[object, MemoryStagingSink]:
        transport = ScriptedTransport(
            _listing_response(
                [
                    _listing_row(job_id, encrypted_id)
                    for job_id, encrypted_id in identity_pairs
                ],
                has_more=True,
            )
        )
        result, _observations, staging, _sleep = await _run(
            transport,
            max_pages=1,
        )
        return result, staging

    first_result, first_staging = await run_order(first_order)
    second_result, second_staging = await run_order(second_order)

    assert first_result.identity_conflicts == second_result.identity_conflicts
    assert first_staging.deferrals == second_staging.deferrals
    assert len(first_result.identity_conflicts) == 1
    conflict = first_result.identity_conflicts[0]
    assert conflict.job_ids == expected_job_ids
    assert conflict.encrypted_job_ids == expected_encrypted_job_ids
    assert conflict.reason == expected_reason


@pytest.mark.parametrize(
    (
        "history_pairs",
        "page_pairs",
        "expected_job_ids",
        "expected_encrypted_job_ids",
        "expected_reason",
    ),
    [
        (
            (),
            (
                ("j-forward", "enc-a"),
                ("j-forward", "enc-b"),
                ("j-forward", "enc-c"),
            ),
            ("j-forward",),
            ("enc-a", "enc-b", "enc-c"),
            "multiple_explicit_encrypted_ids",
        ),
        (
            (),
            (
                ("j-a", "enc-reverse"),
                ("j-b", "enc-reverse"),
                ("j-c", "enc-reverse"),
            ),
            ("j-a", "j-b", "j-c"),
            ("enc-reverse",),
            "one_encrypted_id_to_multiple_job_ids",
        ),
        (
            (("j-forward", "enc-a"),),
            (("j-forward", "enc-b"), ("j-forward", "enc-c")),
            ("j-forward",),
            ("enc-a", "enc-b", "enc-c"),
            "multiple_explicit_encrypted_ids",
        ),
        (
            (("j-a", "enc-reverse"),),
            (("j-b", "enc-reverse"), ("j-c", "enc-reverse")),
            ("j-a", "j-b", "j-c"),
            ("enc-reverse",),
            "one_encrypted_id_to_multiple_job_ids",
        ),
    ],
    ids=["forward", "reverse", "forward-with-history", "reverse-with-history"],
)
@pytest.mark.asyncio
async def test_three_way_conflict_evidence_is_complete_for_every_permutation(
    history_pairs: tuple[tuple[str, str], ...],
    page_pairs: tuple[tuple[str, str], ...],
    expected_job_ids: tuple[str, ...],
    expected_encrypted_job_ids: tuple[str, ...],
    expected_reason: str,
) -> None:
    expected_evidence = [
        (expected_job_ids, expected_encrypted_job_ids, expected_reason)
    ]
    expected_deferrals = [
        {
            "job_ids": expected_job_ids,
            "encrypted_job_ids": expected_encrypted_job_ids,
            "reason": expected_reason,
        }
    ]

    for page_order in permutations(page_pairs):
        steps = []
        if history_pairs:
            steps.append(
                _listing_response(
                    [
                        _listing_row(job_id, encrypted_id)
                        for job_id, encrypted_id in history_pairs
                    ],
                    has_more=True,
                )
            )
        steps.append(
            _listing_response(
                [
                    _listing_row(job_id, encrypted_id)
                    for job_id, encrypted_id in page_order
                ],
                has_more=True,
            )
        )
        transport = ScriptedTransport(*steps)

        result, observations, staging, _sleep = await _run(
            transport,
            max_pages=2,
        )

        conflict_evidence = [
            (conflict.job_ids, conflict.encrypted_job_ids, conflict.reason)
            for conflict in result.identity_conflicts
        ]
        observation_evidence = [
            (conflict.job_ids, conflict.encrypted_job_ids, conflict.reason)
            for conflict in observations.observations[-1].identity_conflicts
        ]
        assert conflict_evidence == expected_evidence, page_order
        assert observation_evidence == expected_evidence, page_order
        assert staging.deferrals == expected_deferrals, page_order
        assert result.stop_reason == "identity_conflict"
        assert result.accepted_job_ids == ()
        assert result.id_pairs == ()
        assert len(staging.staged_pages) == int(bool(history_pairs))


@pytest.mark.asyncio
async def test_identity_issue_blocks_other_valid_rows_on_the_same_page_from_staging() -> (
    None
):
    transport = ScriptedTransport(
        _listing_response(
            [
                _listing_row("j-valid", "enc-valid"),
                _listing_row(None, "enc-orphan"),
            ],
            has_more=True,
        )
    )

    result, observations, staging, _sleep = await _run(transport, max_pages=1)

    assert result.stop_reason == "identity_issue"
    assert result.ordered_job_ids == ("j-valid",)
    assert result.accepted_job_ids == ()
    assert result.id_pairs == ()
    assert [
        (pair.job_id, pair.encrypted_job_id)
        for pair in observations.observations[0].id_pairs
    ] == [("j-valid", "enc-valid")]
    assert staging.staged_pages == []


@pytest.mark.asyncio
async def test_first_seen_canonical_order_dedupes_staging_across_conditions() -> None:
    conditions = [
        _condition(keyword="first"),
        OfferTodayListingCondition(
            search_family="explicit_keyword",
            category_id=None,
            keyword="second",
            endpoint="browse",
            rcd_type=None,
        ),
    ]
    transport = ScriptedTransport(
        _listing_response(
            [
                _listing_row("j-2", "enc-2"),
                _listing_row("j-1", "enc-1"),
            ],
            has_more=False,
            total=3,
        ),
        _listing_response([], has_more=False, total=3),
        _listing_response(
            [
                _listing_row("j-1", "enc-1"),
                _listing_row("j-3", "enc-3"),
            ],
            has_more=False,
            total=3,
        ),
        _listing_response([], has_more=False, total=3),
    )

    result, observations, staging, _sleep = await _run(
        transport,
        conditions=conditions,
    )

    assert [(request[0]["page"], request[1]) for request in transport.requests] == [
        (1, OFFERTODAY_LISTING_SEARCH_URL),
        (2, OFFERTODAY_LISTING_SEARCH_URL),
        (1, OFFERTODAY_LISTING_BROWSE_URL),
        (2, OFFERTODAY_LISTING_BROWSE_URL),
    ]
    assert result.ordered_job_ids == ("j-2", "j-1", "j-3")
    assert result.accepted_job_ids == ("j-2", "j-1", "j-3")
    assert [(pair.job_id, pair.encrypted_job_id) for pair in result.id_pairs] == [
        ("j-2", "enc-2"),
        ("j-1", "enc-1"),
        ("j-3", "enc-3"),
    ]
    assert [outcome.condition for outcome in result.condition_outcomes] == conditions
    assert all(outcome.is_complete for outcome in result.condition_outcomes)
    assert result.is_complete is True
    assert len(observations.observations) == 4
    staged_job_ids = [
        row["job_id"]
        for staged_page in staging.staged_pages
        for row in staged_page["rows"]
    ]
    assert staged_job_ids == ["j-2", "j-1", "j-3"]


@pytest.mark.asyncio
async def test_title_language_evidence_is_deterministic_and_serializer_is_json_safe() -> (
    None
):
    transport = ScriptedTransport(
        _listing_response(
            [
                _listing_row("j-en", "enc-en", title="Platform Engineer"),
                _listing_row(
                    "j-zh",
                    "enc-zh",
                    title="\u8edf\u4ef6\u5de5\u7a0b\u5e2b",
                ),
                _listing_row(
                    "j-mixed",
                    "enc-mixed",
                    title="Platform \u8edf\u4ef6\u5de5\u7a0b\u5e2b",
                ),
                _listing_row("j-other", "enc-other", title="2026 / +++"),
            ],
            has_more=False,
            total=4,
        ),
        _listing_response([], has_more=False, total=4),
    )

    result, observations, _staging, _sleep = await _run(transport)

    observation = observations.observations[0]
    assert [row.title_language for row in observation.rows] == [
        "en",
        "zh",
        "mixed",
        "other",
    ]
    canonical_request = json.dumps(
        {
            "payload": transport.requests[0][0],
            "url": OFFERTODAY_LISTING_SEARCH_URL,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert (
        observation.request_fingerprint
        == hashlib.sha256(canonical_request.encode()).hexdigest()
    )

    assert hasattr(runner_module, "listing_observation_to_payload")
    serializer = runner_module.listing_observation_to_payload
    envelope = {
        "observation": observation,
        "kind": OfferTodayResponseKind.SUCCESS,
        "run_id": UUID("12345678-1234-5678-1234-567812345678"),
        "markers": ("saved", 2),
    }
    serialized = serializer(envelope)

    assert serialized["kind"] == "success"
    assert serialized["run_id"] == "12345678-1234-5678-1234-567812345678"
    assert serialized["markers"] == ["saved", 2]
    assert serialized["observation"]["id_pairs"] == [
        {
            "job_id": "j-en",
            "encrypted_job_id": "enc-en",
            "encrypted_job_id_source": "encryptJobId",
        },
        {
            "job_id": "j-zh",
            "encrypted_job_id": "enc-zh",
            "encrypted_job_id_source": "encryptJobId",
        },
        {
            "job_id": "j-mixed",
            "encrypted_job_id": "enc-mixed",
            "encrypted_job_id_source": "encryptJobId",
        },
        {
            "job_id": "j-other",
            "encrypted_job_id": "enc-other",
            "encrypted_job_id_source": "encryptJobId",
        },
    ]
    assert "raw_data" not in serialized["observation"]["rows"][0]
    assert json.dumps(serialized, sort_keys=True) == json.dumps(
        serializer(envelope),
        sort_keys=True,
    )
    assert result.is_complete is True


@pytest.mark.parametrize(
    ("failure", "expected_kind"),
    [
        (
            {"code": 1002, "msg": "Login expired", "data": None},
            OfferTodayResponseKind.AUTH_EXPIRED,
        ),
        (
            {"code": -1000035, "msg": "Request blocked", "data": None},
            OfferTodayResponseKind.IP_BLOCKED,
        ),
        (
            OfferTodayTransportError(
                "verification challenge",
                http_status=403,
                response_url=(
                    "https://www.offertoday.com/web/passport/cm/verify?from=search"
                ),
                payload=None,
                error_kind="http",
            ),
            OfferTodayResponseKind.WAF_CHALLENGE,
        ),
    ],
)
@pytest.mark.asyncio
async def test_stop_batch_classifications_stop_before_later_conditions(
    failure: object,
    expected_kind: OfferTodayResponseKind,
) -> None:
    transport = ScriptedTransport(failure)

    result, observations, staging, _sleep = await _run(
        transport,
        conditions=[_condition(keyword="first"), _condition(keyword="never-run")],
    )

    assert len(transport.requests) == 1
    assert len(result.condition_outcomes) == 1
    assert result.condition_outcomes[0].stop_reason == expected_kind.value
    assert result.condition_outcomes[0].is_complete is False
    assert result.stop_reason == expected_kind.value
    assert result.is_complete is False
    assert result.gaps == ()
    assert observations.observations[0].classification == expected_kind.value
    assert observations.observations[0].retry_reason is None
    assert observations.observations[0].stop_reason == expected_kind.value
    assert staging.staged_pages == []


@pytest.mark.asyncio
async def test_programmer_exception_propagates_without_retry_or_network_observation() -> (
    None
):
    transport = ScriptedTransport(AssertionError("programmer contract failed"))
    observation_sink = MemoryObservationSink()
    staging_sink = MemoryStagingSink()
    sleep = NoWaitSleep()
    runner = OfferTodayListingRunner(
        transport,
        sleep=sleep,
        clock=DeterministicClock(),
    )

    with pytest.raises(AssertionError, match="programmer contract failed"):
        await runner.run(
            conditions=[_condition()],
            stop_policy=ListingStopPolicy(max_pages_per_condition=3),
            retry_policy=ListingRetryPolicy(
                max_attempts_per_page=3,
                retry_delays_seconds=(0.1, 0.2),
            ),
            observation_sink=observation_sink,
            staging_sink=staging_sink,
            session_mode="saved-session",
        )

    assert len(transport.requests) == 1
    assert observation_sink.observations == []
    assert observation_sink.outcomes == []
    assert staging_sink.staged_pages == []
    assert staging_sink.deferrals == []
    assert sleep.delays == []


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("missing browser fixture"),
        PermissionError("browser profile permission denied"),
    ],
    ids=["file-not-found", "permission-denied"],
)
@pytest.mark.asyncio
async def test_non_network_os_errors_propagate_without_retry_or_observation(
    failure: OSError,
) -> None:
    transport = ScriptedTransport(failure, failure, failure)
    observation_sink = MemoryObservationSink()
    staging_sink = MemoryStagingSink()
    sleep = NoWaitSleep()
    runner = OfferTodayListingRunner(
        transport,
        sleep=sleep,
        clock=DeterministicClock(),
    )
    result = None

    with pytest.raises(type(failure), match=str(failure)):
        result = await runner.run(
            conditions=[_condition()],
            stop_policy=ListingStopPolicy(max_pages_per_condition=3),
            retry_policy=ListingRetryPolicy(
                max_attempts_per_page=3,
                retry_delays_seconds=(0.1, 0.2),
            ),
            observation_sink=observation_sink,
            staging_sink=staging_sink,
            session_mode="saved-session",
        )

    assert result is None
    assert len(transport.requests) == 1
    assert observation_sink.observations == []
    assert observation_sink.outcomes == []
    assert staging_sink.staged_pages == []
    assert staging_sink.deferrals == []
    assert sleep.delays == []


@pytest.mark.asyncio
async def test_connection_errors_retry_same_page_then_record_gap() -> None:
    transport = ScriptedTransport(
        ConnectionError("connection reset 1"),
        ConnectionError("connection reset 2"),
        ConnectionError("connection reset 3"),
    )

    result, observations, staging, sleep = await _run(transport)

    assert [request[0]["page"] for request in transport.requests] == [1, 1, 1]
    assert result.stop_reason == "unresolved_gap"
    assert result.is_complete is False
    assert len(result.gaps) == 1
    assert result.gaps[0].attempts == 3
    assert result.gaps[0].last_kind is OfferTodayResponseKind.TRANSIENT_TRANSPORT
    assert [item.classification for item in observations.observations] == [
        "transient_transport",
        "transient_transport",
        "transient_transport",
    ]
    assert [item.retry_reason for item in observations.observations] == [
        "transient_transport",
        "transient_transport",
        None,
    ]
    assert observations.observations[-1].stop_reason == "unresolved_gap"
    assert staging.staged_pages == []
    assert staging.deferrals == []
    assert sleep.delays == [0.1, 0.2]


@pytest.mark.asyncio
async def test_nonzero_and_malformed_attempts_retry_same_page_and_parse_success_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parse_calls: list[dict[str, Any]] = []
    real_parse = runner_module.parse_offertoday_listing_response

    def parse_spy(payload: dict[str, Any]) -> list[dict[str, Any]]:
        parse_calls.append(payload)
        return real_parse(payload)

    monkeypatch.setattr(runner_module, "parse_offertoday_listing_response", parse_spy)
    first_success = _listing_response([], has_more=False, total=0)
    confirmation = _listing_response([], has_more=False, total=0)
    transport = ScriptedTransport(
        {"code": 7001, "msg": "Temporary upstream error", "data": {}},
        {"code": 0, "msg": "Success", "data": {"resultList": "invalid"}},
        first_success,
        confirmation,
    )

    result, observations, _staging, sleep = await _run(transport)

    assert [request[0]["page"] for request in transport.requests] == [1, 1, 1, 2]
    assert [item.classification for item in observations.observations] == [
        "invalid_payload",
        "invalid_payload",
        "success",
        "success",
    ]
    assert [item.retry_reason for item in observations.observations] == [
        "invalid_payload",
        "invalid_payload",
        None,
        None,
    ]
    assert parse_calls == [first_success, confirmation]
    assert sleep.delays == [0.1, 0.2]
    assert result.is_complete is True


@pytest.mark.asyncio
async def test_reported_total_and_has_more_require_real_json_scalar_types() -> None:
    weakly_typed_response = _listing_response([], has_more=False, total=0)
    weakly_typed_response["data"]["total"] = True
    weakly_typed_response["data"]["hasMore"] = 1
    transport = ScriptedTransport(
        weakly_typed_response,
        _listing_response([], has_more=False, total=0),
    )

    result, observations, _staging, _sleep = await _run(transport)

    assert observations.observations[0].reported_total is None
    assert observations.observations[0].has_more is None
    assert result.is_complete is True


@pytest.mark.asyncio
async def test_cursor_mode_carries_exact_prior_response_cursor_to_next_page() -> None:
    transport = ScriptedTransport(
        _cursor_response(
            [_listing_row("j1", "e1")],
            supple_page=1,
            supple_amount=2,
            supple_type=3,
        ),
        _cursor_response(
            [],
            has_more=False,
            supple_page=4,
            supple_amount=5,
            supple_type=6,
        ),
        _cursor_response(
            [],
            has_more=False,
            supple_page=7,
            supple_amount=8,
            supple_type=9,
        ),
    )

    result, observations, staging, _sleep = await _run(
        transport,
        max_pages=3,
        request_policy=_request_policy(),
    )

    first, second, third = [request[0] for request in transport.requests]
    assert "sessionId" not in first
    assert first["pageSize"] == 10
    assert {
        key: second[key]
        for key in ("sessionId", "supplePage", "suppleAmount", "suppleType")
    } == {
        "sessionId": "session-1",
        "supplePage": 1,
        "suppleAmount": 2,
        "suppleType": 3,
    }
    assert {
        key: third[key]
        for key in ("sessionId", "supplePage", "suppleAmount", "suppleType")
    } == {
        "sessionId": "session-1",
        "supplePage": 4,
        "suppleAmount": 5,
        "suppleType": 6,
    }
    assert result.is_complete is True
    assert [item.cursor_evidence.session_continuity for item in observations.observations] == [
        "initial",
        "continued",
        "continued",
    ]
    assert [item["page"] for item in staging.staged_pages] == [1]


@pytest.mark.asyncio
async def test_cursor_isolation_resets_page_one_for_each_condition() -> None:
    conditions = [_condition(keyword="one"), _condition(keyword="two")]
    transport = ScriptedTransport(
        _cursor_response([_listing_row("j1", "e1")], session_id="session-one"),
        _cursor_response([], session_id="session-one", has_more=False),
        _cursor_response([_listing_row("j2", "e2")], session_id="session-two"),
        _cursor_response([], session_id="session-two", has_more=False),
    )

    result, _observations, _staging, _sleep = await _run(
        transport,
        conditions=conditions,
        max_pages=2,
        require_empty_confirmation=False,
        request_policy=_request_policy(),
    )

    requests = [request[0] for request in transport.requests]
    assert "sessionId" not in requests[0]
    assert requests[1]["sessionId"] == "session-one"
    assert "sessionId" not in requests[2]
    assert requests[3]["sessionId"] == "session-two"
    assert result.is_complete is True


@pytest.mark.asyncio
async def test_cursor_retry_replays_same_input_and_logical_request() -> None:
    transport = ScriptedTransport(
        _cursor_response([_listing_row("j1", "e1")]),
        ConnectionError("transient"),
        _cursor_response([], has_more=False),
    )

    result, observations, _staging, _sleep = await _run(
        transport,
        max_pages=2,
        max_attempts=2,
        require_empty_confirmation=False,
        request_policy=_request_policy(),
    )

    page_two_requests = [request[0] for request in transport.requests[1:]]
    assert page_two_requests[0] == page_two_requests[1]
    retry_observation, success_observation = observations.observations[1:]
    assert (
        retry_observation.cursor_evidence.logical_request_id
        == success_observation.cursor_evidence.logical_request_id
    )
    assert (
        retry_observation.cursor_evidence.physical_attempt_id
        != success_observation.cursor_evidence.physical_attempt_id
    )
    assert result.is_complete is True


@pytest.mark.asyncio
async def test_browser_context_loss_restarts_condition_at_page_one_and_dedupes() -> None:
    transport = RestartableScriptedTransport(
        _cursor_response(
            [_listing_row("j1", "e1")],
            session_id="session-before-loss",
            has_more=False,
        ),
        OfferTodayBrowserContextLostError("browser context lost"),
        _cursor_response(
            [_listing_row("j1", "e1")],
            session_id="session-after-loss",
            has_more=False,
        ),
        _cursor_response(
            [],
            session_id="session-after-loss",
            has_more=False,
        ),
    )

    result, observations, staging, _sleep = await _run(
        transport,
        max_pages=5,
        max_attempts=2,
        request_policy=_request_policy(),
    )

    assert [request["page"] for request in transport.requests] == [1, 2, 1, 2]
    assert transport.restart_count == 1
    assert result.is_complete is True
    assert result.accepted_job_ids == ("j1",)
    assert [item["page"] for item in staging.staged_pages] == [1]
    assert [
        item.cursor_evidence.condition_restart_index
        for item in observations.observations
    ] == [0, 0, 1, 1]
    assert observations.observations[1].retry_reason == (
        "browser_context_lost_restart"
    )
    assert (
        observations.observations[0].cursor_evidence.condition_execution_id
        != observations.observations[2].cursor_evidence.condition_execution_id
    )
    assert len(
        {
            item.cursor_evidence.physical_attempt_id
            for item in observations.observations
        }
    ) == 4


@pytest.mark.asyncio
async def test_cursor_contract_failure_never_flushes_condition_staging() -> None:
    transport = ScriptedTransport(
        _cursor_response([_listing_row("j1", "e1")]),
        _cursor_response([], session_id="rolled-over", has_more=False),
    )

    result, observations, staging, _sleep = await _run(
        transport,
        max_pages=2,
        require_empty_confirmation=False,
        request_policy=_request_policy(),
    )

    assert result.stop_reason == "cursor_contract_violation"
    assert result.is_complete is False
    assert observations.observations[-1].cursor_evidence.contract_error == "session_rollover"
    assert staging.staged_pages == []
    assert result.accepted_job_ids == ()


@pytest.mark.asyncio
async def test_cursor_mode_rejects_missing_page_one_cursor_without_staging() -> None:
    transport = ScriptedTransport(
        _listing_response([_listing_row("j1", "e1")], has_more=True)
    )

    result, observations, staging, _sleep = await _run(
        transport,
        max_pages=1,
        request_policy=_request_policy(),
    )

    assert result.stop_reason == "cursor_contract_violation"
    assert observations.observations[0].cursor_evidence.contract_error == "incomplete_cursor"
    assert staging.staged_pages == []


@pytest.mark.asyncio
async def test_search_endpoint_contract_preserves_cursor_execution() -> None:
    condition = OfferTodayListingCondition(
        search_family="phase_c_endpoint_probe",
        category_id=118000,
        keyword="",
        endpoint="search",
        rcd_type=None,
    )
    transport = ScriptedTransport(
        _cursor_response([], has_more=False),
    )
    result, observations, staging, _sleep = await _run(
        transport,
        conditions=[condition],
        max_pages=1,
        require_empty_confirmation=False,
        request_policy=_request_policy(
            endpoint_contract_id="recommend-search-list-v1"
        ),
    )
    assert result.stop_reason == "natural_exhaustion"
    assert observations.observations[0].cursor_evidence.contract_error is None
    assert staging.staged_pages == []


@pytest.mark.asyncio
async def test_browse_unverified_terminal_cannot_claim_exhaustion_or_stage() -> None:
    condition = OfferTodayListingCondition(
        search_family="phase_c_endpoint_probe",
        category_id=118000,
        keyword="",
        endpoint="browse",
        rcd_type=None,
    )
    result, observations, staging, _sleep = await _run(
        ScriptedTransport(
            _listing_response([_listing_row("browse-1", "browse-enc-1")], has_more=False)
        ),
        conditions=[condition],
        max_pages=1,
        request_policy=_request_policy(
            pagination_mode="stateless-control",
            variant_id="phase-c-browse-envelope",
            endpoint_contract_id="recommend-list-envelope-v1",
        ),
    )
    assert result.stop_reason == "page_cap"
    assert result.accepted_job_ids == ()
    assert observations.observations[0].cursor_evidence.result_job_ids == (
        "browse-1",
    )
    assert observations.observations[0].cursor_evidence.terminal_signal is False
    assert staging.staged_pages == []


@pytest.mark.asyncio
async def test_endpoint_contract_mismatch_rejects_before_transport_or_staging() -> None:
    condition = OfferTodayListingCondition(
        search_family="phase_c_endpoint_probe",
        category_id=118000,
        keyword="",
        endpoint="browse",
        rcd_type=None,
    )
    transport = ScriptedTransport(
        _listing_response([], has_more=False),
    )
    with pytest.raises(ValueError, match="does not match listing condition endpoint"):
        await _run(
            transport,
            conditions=[condition],
            max_pages=1,
            request_policy=_request_policy(
                endpoint_contract_id="recommend-search-list-v1"
            ),
        )
    assert transport.requests == []


@pytest.mark.asyncio
async def test_endpoint_response_url_mismatch_rejects_before_staging() -> None:
    condition = OfferTodayListingCondition(
        search_family="phase_c_endpoint_probe",
        category_id=118000,
        keyword="",
        endpoint="search",
        rcd_type=None,
    )
    transport = ResponseUrlScriptedTransport(
        _cursor_response([_listing_row("j1", "e1")]),
        OFFERTODAY_LISTING_BROWSE_URL,
    )
    result, observations, staging, _sleep = await _run(
        transport,
        conditions=[condition],
        max_pages=1,
        request_policy=_request_policy(
            endpoint_contract_id="recommend-search-list-v1"
        ),
    )
    assert result.stop_reason == "endpoint_contract_violation"
    assert observations.observations[0].cursor_evidence.contract_error == (
        "endpoint_response_url_mismatch"
    )
    assert staging.staged_pages == []


@pytest.mark.asyncio
async def test_cursor_mode_rejects_effective_page_size_drift() -> None:
    transport = ScriptedTransport(
        _cursor_response([_listing_row("j1", "e1")], page_size=10),
        _cursor_response([], page_size=9, has_more=False),
    )

    result, observations, staging, _sleep = await _run(
        transport,
        max_pages=2,
        require_empty_confirmation=False,
        request_policy=_request_policy(),
    )

    assert result.stop_reason == "cursor_contract_violation"
    assert observations.observations[-1].cursor_evidence.contract_error == "page_size_drift"
    assert staging.staged_pages == []


@pytest.mark.asyncio
async def test_supplemental_rows_are_evidence_only_and_not_product_staged() -> None:
    transport = ScriptedTransport(
        _cursor_response(
            [_listing_row("j-result", "e-result")],
            supplemental_rows=[_listing_row("j-supp", "e-supp")],
            has_more=False,
        )
    )

    result, observations, staging, _sleep = await _run(
        transport,
        max_pages=1,
        require_empty_confirmation=False,
        request_policy=_request_policy(),
    )

    evidence = observations.observations[0].cursor_evidence
    assert evidence.result_job_ids == ("j-result",)
    assert evidence.supplemental_job_ids == ("j-supp",)
    assert result.accepted_job_ids == ("j-result",)
    assert [row["job_id"] for row in staging.staged_pages[0]["rows"]] == [
        "j-result"
    ]
    assert [item.job_id for item in evidence.result_identity_pairs] == [
        "j-result"
    ]
    assert [item.job_id for item in evidence.supplemental_identity_pairs] == [
        "j-supp"
    ]


@pytest.mark.asyncio
async def test_supplemental_identity_conflict_rejects_before_result_staging() -> None:
    transport = ScriptedTransport(
        _cursor_response(
            [_listing_row("j-result", "shared-route")],
            supplemental_rows=[_listing_row("j-supp", "shared-route")],
            has_more=False,
        )
    )

    result, observations, staging, _sleep = await _run(
        transport,
        max_pages=1,
        require_empty_confirmation=False,
        request_policy=_request_policy(),
    )

    assert result.stop_reason == "identity_conflict"
    assert result.accepted_job_ids == ()
    assert observations.observations[0].identity_conflicts
    assert staging.staged_pages == []


@pytest.mark.asyncio
async def test_nonempty_cursor_confirmation_is_terminal_contract_violation() -> None:
    transport = ScriptedTransport(
        _cursor_response(
            [_listing_row("j1", "e1")],
            has_more=False,
        ),
        _cursor_response(
            [_listing_row("j2", "e2")],
            has_more=False,
        ),
    )

    result, observations, staging, _sleep = await _run(
        transport,
        max_pages=2,
        request_policy=_request_policy(),
    )

    assert result.stop_reason == "cursor_contract_violation"
    assert observations.observations[-1].classification == "contract_anomaly"
    assert (
        observations.observations[-1].cursor_evidence.contract_error
        == "nonempty_confirmation"
    )
    assert staging.staged_pages == []


@pytest.mark.asyncio
async def test_v2_observation_serialization_hashes_cursor_session() -> None:
    transport = ScriptedTransport(
        _cursor_response([], session_id="raw-session-secret", has_more=False)
    )

    _result, observations, _staging, _sleep = await _run(
        transport,
        max_pages=1,
        require_empty_confirmation=False,
        request_policy=_request_policy(),
    )

    payload = listing_observation_to_payload(observations.observations[0])
    serialized = json.dumps(payload, sort_keys=True)
    assert "raw-session-secret" not in serialized
    assert len(payload["cursor_evidence"]["cursor_output"]["session_id_hash"]) == 64


@pytest.mark.asyncio
async def test_v1_observation_payload_omits_v2_cursor_evidence_key() -> None:
    transport = ScriptedTransport(
        _listing_response([], has_more=False),
        _listing_response([], has_more=False),
    )

    _result, observations, _staging, _sleep = await _run(transport)

    payload = listing_observation_to_payload(observations.observations[0])
    assert "cursor_evidence" not in payload


@pytest.mark.parametrize(
    ("policy_name", "kwargs", "message"),
    [
        (
            ListingStopPolicy,
            {"max_pages_per_condition": 0},
            "max_pages_per_condition must be >= 1",
        ),
        (
            ListingRetryPolicy,
            {"max_attempts_per_page": 0},
            "max_attempts_per_page must be >= 1",
        ),
    ],
)
def test_policies_reject_non_positive_limits(
    policy_name: type,
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        policy_name(**kwargs)
