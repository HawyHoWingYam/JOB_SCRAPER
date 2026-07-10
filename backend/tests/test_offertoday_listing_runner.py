from __future__ import annotations

import hashlib
import json
from copy import deepcopy
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
    OfferTodayListingCondition,
    OfferTodayListingRunner,
)
from app.sources.offertoday.response_policy import (
    OfferTodayResponseKind,
    OfferTodayTransportError,
)


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
    )
    return result, observation_sink, staging_sink, sleep


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
async def test_same_page_forward_identity_conflict_is_hard_and_stages_nothing() -> None:
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
    assert conflict.reason == "one_job_id_to_multiple_encrypted_ids"
    assert observations.observations[0].identity_conflicts == (conflict,)
    assert observations.observations[0].classification == "identity_conflict"
    assert observations.observations[0].stop_reason == "identity_conflict"
    assert [
        (pair.job_id, pair.encrypted_job_id)
        for pair in observations.observations[0].id_pairs
    ] == [
        ("j-conflict", "enc-first"),
        ("j-conflict", "enc-second"),
    ]
    assert staging.staged_pages == []
    assert staging.deferrals == [
        {
            "job_ids": ("j-conflict",),
            "encrypted_job_ids": ("enc-first", "enc-second"),
            "reason": "one_job_id_to_multiple_encrypted_ids",
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
            "reason": "one_job_id_to_multiple_encrypted_ids",
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
        (
            "j-unresolved",
            None,
            "j-unresolved",
            None,
            "missing_encrypted_job_id",
            "encrypted_job_id",
        ),
        (
            "j-blank",
            "  ",
            "j-blank",
            None,
            "missing_encrypted_job_id",
            "encrypted_job_id",
        ),
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
        ("jobId", ["bad"], "invalid_job_id"),
        ("jobId", {"bad": 1}, "invalid_job_id"),
        ("jobId", True, "invalid_job_id"),
        ("jobId", 101, "invalid_job_id"),
        ("encryptJobId", ["bad"], "invalid_encrypted_job_id"),
        ("encryptJobId", {"bad": 1}, "invalid_encrypted_job_id"),
        ("encryptJobId", False, "invalid_encrypted_job_id"),
        ("encryptJobId", 202, "invalid_encrypted_job_id"),
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


@pytest.mark.asyncio
async def test_known_canonical_missing_encrypted_id_is_deferred() -> None:
    transport = ScriptedTransport(
        _listing_response(
            [_listing_row("j-known", "enc-known")],
            has_more=True,
        ),
        _listing_response(
            [_listing_row("j-known", None)],
            has_more=True,
        ),
    )

    result, _observations, staging, _sleep = await _run(transport)

    assert [page["page"] for page in staging.staged_pages] == [1]
    assert staging.deferrals == [
        {
            "job_ids": ("j-known",),
            "encrypted_job_ids": ("enc-known",),
            "reason": "missing_encrypted_job_id",
        }
    ]
    assert result.ordered_job_ids == ("j-known",)
    assert result.accepted_job_ids == ()
    assert result.id_pairs == ()
    assert result.stop_reason == "identity_issue"


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
            "one_job_id_to_multiple_encrypted_ids",
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
        {"job_id": "j-en", "encrypted_job_id": "enc-en"},
        {"job_id": "j-zh", "encrypted_job_id": "enc-zh"},
        {"job_id": "j-mixed", "encrypted_job_id": "enc-mixed"},
        {"job_id": "j-other", "encrypted_job_id": "enc-other"},
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
