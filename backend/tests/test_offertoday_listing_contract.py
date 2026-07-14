from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from dataclasses import asdict

import pytest

from app.sources.offertoday.constants import build_offertoday_listing_payload
from app.sources.offertoday.listing_contract import (
    OFFERTODAY_BROWSE_ENDPOINT_CONTRACT,
    OFFERTODAY_SEARCH_ENDPOINT_CONTRACT,
    OfferTodayCursorContractError,
    OfferTodayListingCursor,
    OfferTodayListingCursorFieldPresence,
    OfferTodayListingIdentityEvidenceV2,
    OfferTodayListingPageEvidenceV2,
    OfferTodayListingRequestPolicy,
    OfferTodayListingTransportResult,
    offertoday_endpoint_contract,
    parse_offertoday_listing_page_result,
    production_offertoday_listing_request_policy,
    validate_offertoday_endpoint_request,
    validate_offertoday_endpoint_response_url,
)


def _response(**data_overrides):
    data = {
        "pageSize": 10,
        "sessionId": "session-secret-1",
        "supplePage": 0,
        "suppleAmount": 0,
        "suppleType": 0,
        "hasMore": True,
        "total": 321,
        "resultList": [{"jobId": "job-1"}],
        "suppleRcdList": [{"jobId": "supp-1"}],
    }
    data.update(data_overrides)
    return {"code": 0, "data": data}


def _policy(**overrides) -> OfferTodayListingRequestPolicy:
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


def test_endpoint_contracts_are_distinct_versioned_and_rcd_omitted() -> None:
    assert OFFERTODAY_SEARCH_ENDPOINT_CONTRACT.contract_id == (
        "recommend-search-list-v1"
    )
    assert OFFERTODAY_BROWSE_ENDPOINT_CONTRACT.contract_id == (
        "recommend-list-envelope-v1"
    )
    assert OFFERTODAY_SEARCH_ENDPOINT_CONTRACT.endpoint == "search"
    assert OFFERTODAY_BROWSE_ENDPOINT_CONTRACT.endpoint == "browse"
    assert OFFERTODAY_SEARCH_ENDPOINT_CONTRACT.contract_hash != (
        OFFERTODAY_BROWSE_ENDPOINT_CONTRACT.contract_hash
    )
    assert OFFERTODAY_SEARCH_ENDPOINT_CONTRACT.allowed_rcd_types == (None,)
    assert OFFERTODAY_BROWSE_ENDPOINT_CONTRACT.allowed_rcd_types == (None,)
    assert OFFERTODAY_SEARCH_ENDPOINT_CONTRACT.cursor_verified is True
    assert OFFERTODAY_BROWSE_ENDPOINT_CONTRACT.cursor_verified is False
    assert OFFERTODAY_BROWSE_ENDPOINT_CONTRACT.terminal_verified is False
    assert (
        offertoday_endpoint_contract("recommend-search-list-v1")
        is OFFERTODAY_SEARCH_ENDPOINT_CONTRACT
    )


def test_production_request_policy_hides_research_controls() -> None:
    policy = production_offertoday_listing_request_policy()

    assert policy.pagination_mode == "response-cursor"
    assert policy.requested_page_size == 10
    assert policy.browser_lifecycle == "condition-local-runtime"
    assert policy.variant_id == "production-it-cursor"
    assert policy.endpoint_contract is OFFERTODAY_SEARCH_ENDPOINT_CONTRACT
    assert policy.requires_cursor is True


def test_legacy_policy_identity_is_unchanged_without_endpoint_contract() -> None:
    policy = _policy()
    old_payload = {
        "condition_id": "condition",
        "condition_restart_index": 0,
        "protocol_version": 2,
        "repeat_index": 1,
        "variant_id": "ui-cursor-same-browser",
    }
    canonical = json.dumps(
        old_payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert policy.endpoint_contract is None
    assert policy.condition_execution_id("condition") == hashlib.sha256(
        canonical.encode()
    ).hexdigest()


def test_explicit_endpoint_contract_participates_in_policy_identity() -> None:
    legacy = _policy()
    explicit = _policy(endpoint_contract_id="recommend-search-list-v1")
    assert explicit.endpoint_contract is OFFERTODAY_SEARCH_ENDPOINT_CONTRACT
    assert explicit.condition_execution_id("condition") != (
        legacy.condition_execution_id("condition")
    )


def test_unverified_browse_contract_rejects_response_cursor_policy() -> None:
    with pytest.raises(ValueError, match="verified endpoint cursor contract"):
        _policy(endpoint_contract_id="recommend-list-envelope-v1")


def test_browse_contract_parses_envelope_without_claiming_cursor() -> None:
    response = {
        "code": 0,
        "data": {
            "pageSize": 10,
            "total": 12,
            "hasMore": False,
            "resultList": [{"jobId": "browse-job"}],
        },
    }
    result = parse_offertoday_listing_page_result(
        response,
        require_cursor=False,
        endpoint_contract_id="recommend-list-envelope-v1",
    )
    assert result.cursor is None
    assert result.result_rows == ({"jobId": "browse-job"},)
    assert result.supplemental_rows == ()
    assert result.has_more is False
    assert result.reported_total == 12


def test_browse_contract_rejects_search_cursor_or_supplemental_fields() -> None:
    with pytest.raises(
        OfferTodayCursorContractError,
        match="unexpected_search_cursor_fields",
    ):
        parse_offertoday_listing_page_result(
            _response(),
            require_cursor=False,
            endpoint_contract_id="recommend-list-envelope-v1",
        )


@pytest.mark.parametrize("rcd_type", [7, True, "7", 7.0])
def test_phase_c_endpoint_request_rejects_noncatalog_rcd_type(rcd_type) -> None:
    payload = {"page": 1, "pageSize": 10, "rcdType": rcd_type}
    with pytest.raises(OfferTodayCursorContractError):
        validate_offertoday_endpoint_request(
            OFFERTODAY_SEARCH_ENDPOINT_CONTRACT,
            payload,
        )


def test_phase_c_endpoint_request_accepts_omitted_rcd_type() -> None:
    validate_offertoday_endpoint_request(
        OFFERTODAY_SEARCH_ENDPOINT_CONTRACT,
        {"page": 1, "pageSize": 10},
    )


def test_endpoint_response_url_must_match_own_contract() -> None:
    with pytest.raises(
        OfferTodayCursorContractError,
        match="endpoint_response_url_mismatch",
    ):
        validate_offertoday_endpoint_response_url(
            OFFERTODAY_SEARCH_ENDPOINT_CONTRACT,
            OFFERTODAY_BROWSE_ENDPOINT_CONTRACT.url,
        )


def test_cursor_page_result_and_next_payload_preserve_exact_response_values() -> None:
    first = parse_offertoday_listing_page_result(
        _response(supplePage=2, suppleAmount=5, suppleType=7),
        require_cursor=True,
    )

    assert first.cursor == OfferTodayListingCursor(
        session_id="session-secret-1",
        supple_page=2,
        supple_amount=5,
        supple_type=7,
        effective_page_size=10,
    )
    payload = build_offertoday_listing_payload(
        category_id=118000,
        keyword="",
        page=2,
        rcd_type=None,
        page_size=10,
        cursor=first.cursor,
    )
    assert payload["page"] == 2
    assert payload["pageSize"] == 10
    assert "rcdType" not in payload
    assert {
        key: payload[key]
        for key in ("sessionId", "supplePage", "suppleAmount", "suppleType")
    } == {
        "sessionId": "session-secret-1",
        "supplePage": 2,
        "suppleAmount": 5,
        "suppleType": 7,
    }


@pytest.mark.parametrize(
    "missing_field",
    ("sessionId", "supplePage", "suppleAmount", "suppleType", "pageSize"),
)
def test_cursor_mode_rejects_missing_page_one_contract_fields(missing_field) -> None:
    response = _response()
    response["data"].pop(missing_field)

    with pytest.raises(OfferTodayCursorContractError):
        parse_offertoday_listing_page_result(response, require_cursor=True)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("sessionId", ""),
        ("sessionId", 123),
        ("supplePage", True),
        ("supplePage", -1),
        ("suppleAmount", 0.0),
        ("suppleType", "0"),
        ("pageSize", False),
        ("pageSize", 0),
    ),
)
def test_cursor_mode_rejects_weak_or_malformed_scalars(
    field_name,
    invalid_value,
) -> None:
    with pytest.raises(OfferTodayCursorContractError):
        parse_offertoday_listing_page_result(
            _response(**{field_name: invalid_value}),
            require_cursor=True,
        )


@pytest.mark.parametrize("session_id", (None, 123, "", " session-secret-1"))
def test_cursor_constructor_rejects_nonexact_session_id(session_id) -> None:
    with pytest.raises(OfferTodayCursorContractError, match="invalid_session_id"):
        OfferTodayListingCursor(session_id, 0, 0, 0, 10)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("hasMore", 1),
        ("hasMore", "true"),
        ("total", True),
        ("total", 1.0),
        ("total", -1),
        ("total", "1"),
    ),
)
def test_page_result_rejects_malformed_present_diagnostic_scalars(
    field_name,
    invalid_value,
) -> None:
    with pytest.raises(OfferTodayCursorContractError):
        parse_offertoday_listing_page_result(
            _response(**{field_name: invalid_value}),
            require_cursor=True,
        )


def test_response_page_size_overrides_requested_size_for_contract_evidence() -> None:
    page = parse_offertoday_listing_page_result(
        _response(pageSize=10),
        require_cursor=True,
    )

    assert page.response_page_size == 10
    assert page.cursor is not None
    assert page.cursor.effective_page_size == 10


def test_cursor_chain_rejects_session_rollover_and_page_size_drift() -> None:
    with pytest.raises(OfferTodayCursorContractError, match="session_rollover"):
        parse_offertoday_listing_page_result(
            _response(sessionId="new-session"),
            require_cursor=True,
            expected_session_id="session-secret-1",
            expected_effective_page_size=10,
        )

    with pytest.raises(OfferTodayCursorContractError, match="page_size_drift"):
        parse_offertoday_listing_page_result(
            _response(pageSize=9),
            require_cursor=True,
            expected_session_id="session-secret-1",
            expected_effective_page_size=10,
        )


def test_result_and_supplemental_rows_are_separate_frozen_copies() -> None:
    response = _response()
    original = deepcopy(response)
    page = parse_offertoday_listing_page_result(response, require_cursor=True)

    response["data"]["resultList"][0]["jobId"] = "changed"
    response["data"]["suppleRcdList"].append({"jobId": "supp-2"})

    assert page.result_rows == ({"jobId": "job-1"},)
    assert page.supplemental_rows == ({"jobId": "supp-1"},)
    assert original != response


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (("resultList", {}), ("suppleRcdList", "invalid")),
)
def test_page_result_rejects_non_array_row_cohorts(field_name, invalid_value) -> None:
    with pytest.raises(OfferTodayCursorContractError, match=field_name):
        parse_offertoday_listing_page_result(
            _response(**{field_name: invalid_value}),
            require_cursor=True,
        )


def test_stateless_control_allows_absent_cursor_but_records_page_size() -> None:
    response = _response()
    for field_name in ("sessionId", "supplePage", "suppleAmount", "suppleType"):
        response["data"].pop(field_name)

    page = parse_offertoday_listing_page_result(response, require_cursor=False)

    assert page.cursor is None
    assert page.response_page_size == 10
    assert page.cursor_field_presence == OfferTodayListingCursorFieldPresence(
        session_id=False,
        supple_page=False,
        supple_amount=False,
        supple_type=False,
        page_size=True,
    )


def test_cursor_evidence_hashes_session_and_never_serializes_raw_value() -> None:
    cursor = OfferTodayListingCursor(
        session_id="session-secret-1",
        supple_page=0,
        supple_amount=0,
        supple_type=0,
        effective_page_size=10,
    )

    serialized = json.dumps(cursor.to_evidence().__dict__ if hasattr(cursor.to_evidence(), "__dict__") else {
        "cursor_hash": cursor.to_evidence().cursor_hash,
        "session_id_hash": cursor.to_evidence().session_id_hash,
        "supple_page": cursor.to_evidence().supple_page,
        "supple_amount": cursor.to_evidence().supple_amount,
        "supple_type": cursor.to_evidence().supple_type,
        "effective_page_size": cursor.to_evidence().effective_page_size,
    })

    assert "session-secret-1" not in serialized
    assert len(cursor.to_evidence().session_id_hash) == 64


def test_payload_builder_does_not_mutate_cursor_or_previous_payload() -> None:
    cursor = OfferTodayListingCursor("session-secret-1", 0, 0, 0, 10)
    first = build_offertoday_listing_payload(
        category_id=118000,
        keyword="",
        page=2,
        rcd_type=None,
        page_size=10,
        cursor=cursor,
    )
    second = build_offertoday_listing_payload(
        category_id=112000,
        keyword="",
        page=3,
        rcd_type=None,
        page_size=10,
        cursor=cursor,
    )

    second["sessionId"] = "changed"
    assert first["sessionId"] == "session-secret-1"
    assert first["jobFunctionCodes"] == [118000]
    assert second["jobFunctionCodes"] == [112000]


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("protocol_version", 1),
        ("pagination_mode", "invalid"),
        ("requested_page_size", 10.0),
        ("browser_lifecycle", "invalid"),
        ("variant_id", ""),
        ("repeat_index", 3),
        ("condition_restart_index", -1),
    ),
)
def test_request_policy_rejects_unfrozen_controls(field_name, invalid_value) -> None:
    with pytest.raises(ValueError):
        _policy(**{field_name: invalid_value})


def test_request_policy_ids_are_stable_and_attempt_specific() -> None:
    policy = _policy()

    assert policy.condition_execution_id("condition") == policy.condition_execution_id(
        "condition"
    )
    assert policy.logical_request_id("condition", 2) != policy.logical_request_id(
        "condition",
        1,
    )
    assert policy.physical_attempt_id(
        "condition",
        2,
        1,
    ) != policy.physical_attempt_id("condition", 2, 2)
    assert policy.condition_execution_id("condition") != _policy(
        condition_restart_index=1
    ).condition_execution_id("condition")


def test_transport_result_copies_payload_and_validates_context_hash() -> None:
    payload = _response()
    result = OfferTodayListingTransportResult(
        payload=payload,
        browser_context_hash="a" * 64,
        http_status=200,
        response_url="https://www.offertoday.com/wapi/geek/recommend/search/list",
    )
    payload["data"]["resultList"].clear()

    assert result.payload is not None
    assert result.payload["data"]["resultList"] == [{"jobId": "job-1"}]
    assert result.http_status == 200
    assert result.response_url.endswith("/wapi/geek/recommend/search/list")
    with pytest.raises(ValueError, match="browser_context_hash"):
        OfferTodayListingTransportResult(payload={}, browser_context_hash="invalid")
    with pytest.raises(ValueError, match="provided together"):
        OfferTodayListingTransportResult(payload={}, http_status=200)
    with pytest.raises(ValueError, match="successful exact integer"):
        OfferTodayListingTransportResult(
            payload={},
            http_status=302,
            response_url="https://www.offertoday.com/redirect",
        )
    with pytest.raises(ValueError, match="nonblank trimmed"):
        OfferTodayListingTransportResult(
            payload={},
            http_status=200,
            response_url=" ",
        )


def test_v2_page_evidence_round_trips_typed_cohorts_without_raw_session() -> None:
    cursor = OfferTodayListingCursor("session-secret-1", 0, 0, 0, 10)
    result_identity = OfferTodayListingIdentityEvidenceV2(
        job_id="job-1",
        encrypted_job_id="enc-1",
        encrypted_job_id_source="encryptJobId",
    )
    supplemental_identity = OfferTodayListingIdentityEvidenceV2(
        job_id="supp-1",
        encrypted_job_id="supp-1",
        encrypted_job_id_source="jobId_fallback",
    )
    evidence = OfferTodayListingPageEvidenceV2(
        protocol_version=2,
        variant_id="ui-cursor-same-browser",
        repeat_index=1,
        condition_restart_index=0,
        condition_execution_id="a" * 64,
        logical_request_id="b" * 64,
        physical_attempt_id="c" * 64,
        browser_context_hash="d" * 64,
        pagination_mode="response-cursor",
        browser_lifecycle="condition-local-runtime",
        requested_page_size=10,
        response_page_size=10,
        effective_page_size=10,
        cursor_input=None,
        cursor_output=cursor.to_evidence(),
        response_cursor_fields=OfferTodayListingCursorFieldPresence(
            session_id=True,
            supple_page=True,
            supple_amount=True,
            supple_type=True,
            page_size=True,
        ),
        session_continuity="initial",
        result_row_count=1,
        supplemental_row_count=1,
        result_job_ids=("job-1",),
        supplemental_job_ids=("supp-1",),
        result_identity_pairs=(result_identity,),
        supplemental_identity_pairs=(supplemental_identity,),
        cohort_overlap_job_ids=(),
        new_job_id_count=2,
        duplicate_job_id_count=0,
        zero_new_full_page=False,
        terminal_signal=False,
        awaiting_empty_confirmation=False,
        contract_error=None,
    )

    payload = json.loads(json.dumps(asdict(evidence), sort_keys=True))
    restored = OfferTodayListingPageEvidenceV2.from_payload(payload)

    assert restored == evidence
    assert "session-secret-1" not in json.dumps(payload, sort_keys=True)


def test_v2_page_evidence_rejects_identity_pair_outside_owning_cohort() -> None:
    with pytest.raises(ValueError, match="not owned"):
        OfferTodayListingPageEvidenceV2(
            protocol_version=2,
            variant_id="ui-cursor",
            repeat_index=1,
            condition_restart_index=0,
            condition_execution_id="a" * 64,
            logical_request_id="b" * 64,
            physical_attempt_id="c" * 64,
            browser_context_hash="d" * 64,
            pagination_mode="response-cursor",
            browser_lifecycle="shared-variant-runtime",
            requested_page_size=10,
            response_page_size=10,
            effective_page_size=10,
            cursor_input=None,
            cursor_output=None,
            response_cursor_fields=OfferTodayListingCursorFieldPresence(
                True, True, True, True, True
            ),
            session_continuity="unavailable",
            result_row_count=1,
            supplemental_row_count=0,
            result_job_ids=("job-1",),
            supplemental_job_ids=(),
            result_identity_pairs=(
                OfferTodayListingIdentityEvidenceV2(
                    "other-job",
                    "other-job",
                    "jobId_fallback",
                ),
            ),
            supplemental_identity_pairs=(),
            cohort_overlap_job_ids=(),
            new_job_id_count=1,
            duplicate_job_id_count=0,
            zero_new_full_page=False,
            terminal_signal=False,
            awaiting_empty_confirmation=False,
        )
