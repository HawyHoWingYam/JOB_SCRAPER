from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Mapping


class OfferTodayResponseKind(StrEnum):
    SUCCESS = "success"
    AUTH_EXPIRED = "auth_expired"
    WAF_CHALLENGE = "waf_challenge"
    IP_BLOCKED = "ip_blocked"
    TERMINAL_UNAVAILABLE = "terminal_unavailable"
    TRANSIENT_TRANSPORT = "transient_transport"
    INVALID_PAYLOAD = "invalid_payload"
    ID_MISMATCH = "id_mismatch"
    PERSIST_FAILURE = "persist_failure"


@dataclass(frozen=True, slots=True)
class OfferTodayResponseClassification:
    kind: OfferTodayResponseKind
    code: int | None
    message: str | None
    data: dict[str, Any] | None
    raw_payload: dict[str, Any] | None
    retryable: bool
    stop_batch: bool


class OfferTodayTransportError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        http_status: int | None,
        response_url: str | None,
        payload: Mapping[str, Any] | None,
        error_kind: Literal["http", "invalid_json"],
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.response_url = response_url
        self.payload = dict(payload) if isinstance(payload, Mapping) else None
        self.error_kind = error_kind


def _result(
    kind: OfferTodayResponseKind,
    *,
    payload: Mapping[str, Any] | None,
    code: int | None,
    message: str | None,
    data: dict[str, Any] | None,
    retryable: bool,
    stop_batch: bool,
) -> OfferTodayResponseClassification:
    return OfferTodayResponseClassification(
        kind=kind,
        code=code,
        message=message,
        data=data,
        raw_payload=dict(payload) if isinstance(payload, Mapping) else None,
        retryable=retryable,
        stop_batch=stop_batch,
    )


def classify_offertoday_response(
    payload: Mapping[str, Any] | None,
    *,
    operation: Literal["listing", "detail"],
    current_url: str | None = None,
    expected_job_id: str | None = None,
    transport_error: BaseException | None = None,
    http_status: int | None = None,
) -> OfferTodayResponseClassification:
    if "/web/passport/cm/verify" in str(current_url or ""):
        return _result(
            OfferTodayResponseKind.WAF_CHALLENGE,
            payload=payload,
            code=None,
            message="OfferToday verification challenge",
            data=None,
            retryable=False,
            stop_batch=True,
        )

    if http_status == 429 or (http_status or 0) >= 500:
        return _result(
            OfferTodayResponseKind.TRANSIENT_TRANSPORT,
            payload=payload,
            code=None,
            message=str(transport_error or f"HTTP {http_status}"),
            data=None,
            retryable=True,
            stop_batch=False,
        )

    if (
        isinstance(transport_error, OfferTodayTransportError)
        and transport_error.error_kind == "invalid_json"
    ):
        return _result(
            OfferTodayResponseKind.INVALID_PAYLOAD,
            payload=payload,
            code=None,
            message=str(transport_error),
            data=None,
            retryable=operation == "listing",
            stop_batch=False,
        )

    if http_status is not None and http_status >= 400:
        return _result(
            OfferTodayResponseKind.INVALID_PAYLOAD,
            payload=payload,
            code=None,
            message=str(transport_error or f"HTTP {http_status}"),
            data=None,
            retryable=operation == "listing",
            stop_batch=False,
        )

    if transport_error is not None:
        return _result(
            OfferTodayResponseKind.TRANSIENT_TRANSPORT,
            payload=payload,
            code=None,
            message=str(transport_error),
            data=None,
            retryable=True,
            stop_batch=False,
        )

    if not isinstance(payload, Mapping):
        return _result(
            OfferTodayResponseKind.INVALID_PAYLOAD,
            payload=None,
            code=None,
            message="Response is not a JSON object",
            data=None,
            retryable=operation == "listing",
            stop_batch=False,
        )

    raw_code = payload.get("code")
    code = raw_code if isinstance(raw_code, int) else None
    message = str(payload.get("msg") or payload.get("message") or "").strip() or None
    raw_data = payload.get("data")
    data = dict(raw_data) if isinstance(raw_data, Mapping) else None

    if code == 1002:
        return _result(
            OfferTodayResponseKind.AUTH_EXPIRED,
            payload=payload,
            code=code,
            message=message,
            data=data,
            retryable=False,
            stop_batch=True,
        )

    if code == -1000035:
        return _result(
            OfferTodayResponseKind.IP_BLOCKED,
            payload=payload,
            code=code,
            message=message,
            data=data,
            retryable=False,
            stop_batch=True,
        )

    if code == 2520 and operation == "detail":
        return _result(
            OfferTodayResponseKind.TERMINAL_UNAVAILABLE,
            payload=payload,
            code=code,
            message=message,
            data=data,
            retryable=False,
            stop_batch=False,
        )

    if code != 0:
        return _result(
            OfferTodayResponseKind.INVALID_PAYLOAD,
            payload=payload,
            code=code,
            message=message or "Non-success API code",
            data=data,
            retryable=operation == "listing",
            stop_batch=False,
        )

    valid_shape = isinstance(raw_data, Mapping) and (
        (
            isinstance(raw_data.get("resultList"), list)
            and all(isinstance(row, Mapping) for row in raw_data.get("resultList"))
        )
        if operation == "listing"
        else bool(str(raw_data.get("jobId") or "").strip())
    )
    if not valid_shape:
        return _result(
            OfferTodayResponseKind.INVALID_PAYLOAD,
            payload=payload,
            code=code,
            message="Success payload has invalid data shape",
            data=data,
            retryable=operation == "listing",
            stop_batch=False,
        )

    if operation == "detail" and expected_job_id is not None:
        response_job_id = str(raw_data.get("jobId") or "").strip()
        if response_job_id != str(expected_job_id).strip():
            return _result(
                OfferTodayResponseKind.ID_MISMATCH,
                payload=payload,
                code=code,
                message=(
                    f"Expected jobId={expected_job_id}, got jobId={response_job_id}"
                ),
                data=data,
                retryable=False,
                stop_batch=True,
            )

    return _result(
        OfferTodayResponseKind.SUCCESS,
        payload=payload,
        code=code,
        message=message,
        data=data,
        retryable=False,
        stop_batch=False,
    )
