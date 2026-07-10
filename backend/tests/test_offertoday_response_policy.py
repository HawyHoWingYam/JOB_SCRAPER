from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.sources.offertoday.response_policy import (
    OfferTodayResponseClassification,
    OfferTodayResponseKind,
    OfferTodayTransportError,
    classify_offertoday_response,
)


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        (OfferTodayResponseKind.SUCCESS, "success"),
        (OfferTodayResponseKind.AUTH_EXPIRED, "auth_expired"),
        (OfferTodayResponseKind.WAF_CHALLENGE, "waf_challenge"),
        (OfferTodayResponseKind.IP_BLOCKED, "ip_blocked"),
        (OfferTodayResponseKind.TERMINAL_UNAVAILABLE, "terminal_unavailable"),
        (OfferTodayResponseKind.TRANSIENT_TRANSPORT, "transient_transport"),
        (OfferTodayResponseKind.INVALID_PAYLOAD, "invalid_payload"),
        (OfferTodayResponseKind.ID_MISMATCH, "id_mismatch"),
        (OfferTodayResponseKind.PERSIST_FAILURE, "persist_failure"),
    ],
)
def test_response_kind_values(kind: OfferTodayResponseKind, value: str):
    assert kind.value == value


@pytest.mark.parametrize(
    ("operation", "payload", "expected_job_id", "expected_data"),
    [
        (
            "listing",
            {"code": 0, "msg": " ok ", "data": {"resultList": [{"jobId": "123"}]}},
            None,
            {"resultList": [{"jobId": "123"}]},
        ),
        (
            "detail",
            {"code": 0, "msg": "ok", "data": {"jobId": " 123 ", "title": "Engineer"}},
            "123",
            {"jobId": " 123 ", "title": "Engineer"},
        ),
    ],
)
def test_classifies_valid_success_payloads(
    operation: str,
    payload: dict,
    expected_job_id: str | None,
    expected_data: dict,
):
    classification = classify_offertoday_response(
        payload,
        operation=operation,
        expected_job_id=expected_job_id,
    )

    assert classification == OfferTodayResponseClassification(
        kind=OfferTodayResponseKind.SUCCESS,
        code=0,
        message="ok",
        data=expected_data,
        raw_payload=payload,
        retryable=False,
        stop_batch=False,
    )


def test_waf_url_takes_precedence_over_nominal_success():
    classification = classify_offertoday_response(
        {"code": 0, "msg": "ok", "data": {"resultList": []}},
        operation="listing",
        current_url="https://www.offertoday.com/web/passport/cm/verify?from=search",
    )

    assert classification.kind is OfferTodayResponseKind.WAF_CHALLENGE
    assert classification.code is None
    assert classification.message == "OfferToday verification challenge"
    assert classification.data is None
    assert classification.retryable is False
    assert classification.stop_batch is True


@pytest.mark.parametrize(
    ("operation", "code", "kind", "stop_batch"),
    [
        ("listing", 1002, OfferTodayResponseKind.AUTH_EXPIRED, True),
        ("detail", 1002, OfferTodayResponseKind.AUTH_EXPIRED, True),
        ("listing", -1000035, OfferTodayResponseKind.IP_BLOCKED, True),
        ("detail", -1000035, OfferTodayResponseKind.IP_BLOCKED, True),
        ("detail", 2520, OfferTodayResponseKind.TERMINAL_UNAVAILABLE, False),
    ],
)
def test_classifies_known_api_failures(
    operation: str,
    code: int,
    kind: OfferTodayResponseKind,
    stop_batch: bool,
):
    classification = classify_offertoday_response(
        {"code": code, "msg": "OfferToday failure", "data": None},
        operation=operation,
    )

    assert classification.kind is kind
    assert classification.code == code
    assert classification.message == "OfferToday failure"
    assert classification.retryable is False
    assert classification.stop_batch is stop_batch


@pytest.mark.parametrize(
    ("operation", "retryable"),
    [("listing", True), ("detail", False)],
)
def test_unknown_api_failure_is_invalid_payload(operation: str, retryable: bool):
    classification = classify_offertoday_response(
        {"code": 7001, "msg": "Unexpected response", "data": {}},
        operation=operation,
    )

    assert classification.kind is OfferTodayResponseKind.INVALID_PAYLOAD
    assert classification.code == 7001
    assert classification.retryable is retryable
    assert classification.stop_batch is False


def test_listing_code_2520_is_an_unknown_api_failure():
    classification = classify_offertoday_response(
        {"code": 2520, "msg": "Position unavailable", "data": None},
        operation="listing",
    )

    assert classification.kind is OfferTodayResponseKind.INVALID_PAYLOAD
    assert classification.retryable is True
    assert classification.stop_batch is False


@pytest.mark.parametrize("raw_code", [False, True, 0.0, "0", [], {}])
def test_boolean_and_malformed_codes_are_invalid(raw_code: object):
    classification = classify_offertoday_response(
        {"code": raw_code, "data": {"resultList": []}},
        operation="listing",
    )

    assert classification.kind is OfferTodayResponseKind.INVALID_PAYLOAD
    assert classification.code is None
    assert classification.retryable is True
    assert classification.stop_batch is False


def test_detail_job_id_mismatch_stops_the_batch():
    classification = classify_offertoday_response(
        {"code": 0, "msg": "ok", "data": {"jobId": "actual-id"}},
        operation="detail",
        expected_job_id=" expected-id ",
    )

    assert classification.kind is OfferTodayResponseKind.ID_MISMATCH
    assert classification.message == "Expected jobId= expected-id , got jobId=actual-id"
    assert classification.retryable is False
    assert classification.stop_batch is True


@pytest.mark.parametrize(
    "job_id",
    [123, True, ["job-123"], {"id": "job-123"}],
)
def test_detail_success_requires_string_job_id(job_id: object):
    classification = classify_offertoday_response(
        {"code": 0, "data": {"jobId": job_id}},
        operation="detail",
    )

    assert classification.kind is OfferTodayResponseKind.INVALID_PAYLOAD
    assert classification.retryable is False
    assert classification.stop_batch is False


@pytest.mark.parametrize("http_status", [429, 500, 502, 503, 504])
def test_rate_limit_and_server_errors_are_transient(http_status: int):
    error = OfferTodayTransportError(
        f"HTTP {http_status}",
        http_status=http_status,
        response_url="https://www.offertoday.com/wapi/zpgeek/search/joblist.json",
        payload={"error": "upstream"},
        error_kind="http",
    )

    classification = classify_offertoday_response(
        error.payload,
        operation="detail",
        current_url=error.response_url,
        transport_error=error,
        http_status=error.http_status,
    )

    assert classification.kind is OfferTodayResponseKind.TRANSIENT_TRANSPORT
    assert classification.code is None
    assert classification.data is None
    assert classification.retryable is True
    assert classification.stop_batch is False
    assert classification.raw_payload == {"error": "upstream"}


def test_timeout_is_transient_transport_failure():
    classification = classify_offertoday_response(
        None,
        operation="listing",
        transport_error=TimeoutError("request timed out"),
    )

    assert classification.kind is OfferTodayResponseKind.TRANSIENT_TRANSPORT
    assert classification.message == "request timed out"
    assert classification.retryable is True
    assert classification.stop_batch is False


@pytest.mark.parametrize(
    "payload",
    [
        {"code": 0, "msg": "ok", "data": None},
        {"code": 0, "msg": "ok", "data": {}},
        {"code": 0, "msg": "ok", "data": {"resultList": {}}},
        {"code": 0, "msg": "ok", "data": {"resultList": ["not-a-row"]}},
    ],
)
def test_malformed_listing_success_data_is_retryable(payload: dict):
    classification = classify_offertoday_response(payload, operation="listing")

    assert classification.kind is OfferTodayResponseKind.INVALID_PAYLOAD
    assert classification.message == "Success payload has invalid data shape"
    assert classification.retryable is True
    assert classification.stop_batch is False


def test_non_json_http_200_detail_is_nonretryable_invalid_payload():
    error = OfferTodayTransportError(
        "OfferToday returned HTML",
        http_status=200,
        response_url="https://www.offertoday.com/wapi/geek/recommend/jobDetail?id=123",
        payload=None,
        error_kind="invalid_json",
    )

    classification = classify_offertoday_response(
        None,
        operation="detail",
        current_url=error.response_url,
        transport_error=error,
        http_status=error.http_status,
    )

    assert classification.kind is OfferTodayResponseKind.INVALID_PAYLOAD
    assert classification.message == "OfferToday returned HTML"
    assert classification.retryable is False
    assert classification.stop_batch is False


@pytest.mark.parametrize(
    ("operation", "payload", "retryable"),
    [
        ("listing", ["not", "a", "mapping"], True),
        ("detail", "not a mapping", False),
        ("detail", {"code": 0, "data": {"jobId": "   "}}, False),
    ],
)
def test_invalid_payload_shapes_follow_operation_retry_policy(
    operation: str,
    payload: object,
    retryable: bool,
):
    classification = classify_offertoday_response(payload, operation=operation)

    assert classification.kind is OfferTodayResponseKind.INVALID_PAYLOAD
    if not isinstance(payload, dict):
        assert classification.message == "Response is not a JSON object"
    assert classification.retryable is retryable
    assert classification.stop_batch is False


def test_other_http_client_error_follows_operation_retry_policy():
    error = OfferTodayTransportError(
        "HTTP 403",
        http_status=403,
        response_url="https://www.offertoday.com/wapi/geek/recommend/jobDetail?id=123",
        payload={"error": "forbidden"},
        error_kind="http",
    )

    classification = classify_offertoday_response(
        error.payload,
        operation="detail",
        current_url=error.response_url,
        transport_error=error,
        http_status=error.http_status,
    )

    assert classification.kind is OfferTodayResponseKind.INVALID_PAYLOAD
    assert classification.retryable is False
    assert classification.raw_payload == {"error": "forbidden"}


def test_transport_error_copies_context_and_response_payloads_are_copied():
    error_payload = {"code": 403}
    error = OfferTodayTransportError(
        "forbidden",
        http_status=403,
        response_url="https://www.offertoday.com/failure",
        payload=error_payload,
        error_kind="http",
    )
    error_payload["code"] = 500

    assert str(error) == "forbidden"
    assert error.http_status == 403
    assert error.response_url == "https://www.offertoday.com/failure"
    assert error.payload == {"code": 403}
    assert error.error_kind == "http"

    payload = {"code": 0, "data": {"resultList": []}}
    classification = classify_offertoday_response(payload, operation="listing")
    payload["code"] = 1002

    assert classification.raw_payload == {"code": 0, "data": {"resultList": []}}
    with pytest.raises(FrozenInstanceError):
        classification.retryable = True


def test_transport_error_deep_copies_nested_payload_evidence():
    payload = {"context": {"attempts": [1]}}
    error = OfferTodayTransportError(
        "request failed",
        http_status=503,
        response_url="https://www.offertoday.com/failure",
        payload=payload,
        error_kind="http",
    )

    payload["context"]["attempts"].append(2)

    assert error.payload == {"context": {"attempts": [1]}}


def test_classification_deep_copies_nested_raw_and_data_evidence():
    payload = {
        "code": 0,
        "data": {
            "resultList": [{"jobId": "job-123", "metadata": {"tags": ["python"]}}]
        },
    }
    classification = classify_offertoday_response(payload, operation="listing")

    payload["data"]["resultList"][0]["metadata"]["tags"].append("sql")

    expected_data = {
        "resultList": [{"jobId": "job-123", "metadata": {"tags": ["python"]}}]
    }
    assert classification.raw_payload == {"code": 0, "data": expected_data}
    assert classification.data == expected_data
