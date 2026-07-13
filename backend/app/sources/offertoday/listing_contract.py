"""Typed OfferToday listing pagination contracts.

The live site returns a response-derived cursor.  These contracts keep that
cursor in the listing runner instead of hiding mutable pagination state in the
browser runtime.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from app.sources.offertoday.detail_identity import (
    OfferTodayDetailIdentity,
    OfferTodayEncryptedJobIdSource,
)


PaginationMode = Literal["stateless-control", "response-cursor"]
BrowserLifecycle = Literal[
    "shared-variant-runtime",
    "condition-local-runtime",
    "restart-each-page",
]
EndpointKind = Literal["search", "browse"]
CursorCapability = Literal["search-response-cursor-v1", "unverified"]
TerminalCapability = Literal["has-more-empty-confirmation-v1", "unverified"]

OFFERTODAY_LISTING_SEARCH_CONTRACT_URL = (
    "https://www.offertoday.com/wapi/geek/recommend/search/list"
)
OFFERTODAY_LISTING_BROWSE_CONTRACT_URL = (
    "https://www.offertoday.com/wapi/geek/recommend/list"
)

_PAGINATION_MODES = {"stateless-control", "response-cursor"}
_BROWSER_LIFECYCLES = {
    "shared-variant-runtime",
    "condition-local-runtime",
    "restart-each-page",
}
_SHA256_LENGTH = 64


def _endpoint_nonblank_string(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise ValueError(f"{field_name} must be an exact nonblank string")
    return value


@dataclass(frozen=True, slots=True)
class OfferTodayListingEndpointContract:
    schema_version: int
    contract_id: str
    endpoint: EndpointKind
    url: str
    allowed_rcd_types: tuple[int | None, ...]
    result_rows_field: str
    supplemental_rows_field: str | None
    cursor_capability: CursorCapability
    terminal_capability: TerminalCapability

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("endpoint contract schema_version must equal 1")
        _endpoint_nonblank_string(self.contract_id, "contract_id")
        if self.endpoint not in {"search", "browse"}:
            raise ValueError("unsupported endpoint contract endpoint")
        _endpoint_nonblank_string(self.url, "url")
        if not isinstance(self.allowed_rcd_types, tuple) or not self.allowed_rcd_types:
            raise ValueError("allowed_rcd_types must be a nonempty tuple")
        if len(set(self.allowed_rcd_types)) != len(self.allowed_rcd_types):
            raise ValueError("allowed_rcd_types must be distinct")
        for value in self.allowed_rcd_types:
            if value is not None and type(value) is not int:
                raise ValueError("allowed rcdType values must be exact integers or None")
        _endpoint_nonblank_string(self.result_rows_field, "result_rows_field")
        if self.supplemental_rows_field is not None:
            _endpoint_nonblank_string(
                self.supplemental_rows_field,
                "supplemental_rows_field",
            )
        if self.cursor_capability not in {
            "search-response-cursor-v1",
            "unverified",
        }:
            raise ValueError("unsupported endpoint cursor capability")
        if self.terminal_capability not in {
            "has-more-empty-confirmation-v1",
            "unverified",
        }:
            raise ValueError("unsupported endpoint terminal capability")
        if self.endpoint == "browse" and (
            self.cursor_capability != "unverified"
            or self.terminal_capability != "unverified"
        ):
            raise ValueError("browse v1 capabilities must remain unverified")

    @property
    def contract_hash(self) -> str:
        return _canonical_hash(self.to_payload())

    @property
    def cursor_verified(self) -> bool:
        return self.cursor_capability != "unverified"

    @property
    def terminal_verified(self) -> bool:
        return self.terminal_capability != "unverified"

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_id": self.contract_id,
            "endpoint": self.endpoint,
            "url": self.url,
            "allowed_rcd_types": list(self.allowed_rcd_types),
            "result_rows_field": self.result_rows_field,
            "supplemental_rows_field": self.supplemental_rows_field,
            "cursor_capability": self.cursor_capability,
            "terminal_capability": self.terminal_capability,
        }


OFFERTODAY_SEARCH_ENDPOINT_CONTRACT = OfferTodayListingEndpointContract(
    schema_version=1,
    contract_id="recommend-search-list-v1",
    endpoint="search",
    url=OFFERTODAY_LISTING_SEARCH_CONTRACT_URL,
    allowed_rcd_types=(None,),
    result_rows_field="resultList",
    supplemental_rows_field="suppleRcdList",
    cursor_capability="search-response-cursor-v1",
    terminal_capability="has-more-empty-confirmation-v1",
)
OFFERTODAY_BROWSE_ENDPOINT_CONTRACT = OfferTodayListingEndpointContract(
    schema_version=1,
    contract_id="recommend-list-envelope-v1",
    endpoint="browse",
    url=OFFERTODAY_LISTING_BROWSE_CONTRACT_URL,
    allowed_rcd_types=(None,),
    result_rows_field="resultList",
    supplemental_rows_field=None,
    cursor_capability="unverified",
    terminal_capability="unverified",
)
OFFERTODAY_ENDPOINT_CONTRACTS = (
    OFFERTODAY_SEARCH_ENDPOINT_CONTRACT,
    OFFERTODAY_BROWSE_ENDPOINT_CONTRACT,
)
_ENDPOINT_CONTRACTS_BY_ID = {
    contract.contract_id: contract for contract in OFFERTODAY_ENDPOINT_CONTRACTS
}


def offertoday_endpoint_contract(
    contract_id: str,
) -> OfferTodayListingEndpointContract:
    try:
        return _ENDPOINT_CONTRACTS_BY_ID[contract_id]
    except KeyError as exc:
        raise ValueError(f"unknown OfferToday endpoint contract: {contract_id}") from exc


def validate_offertoday_endpoint_request(
    contract: OfferTodayListingEndpointContract,
    payload: Mapping[str, Any],
) -> None:
    if not isinstance(payload, Mapping):
        raise OfferTodayCursorContractError("invalid_request_payload")
    _exact_positive_int(payload.get("page"), "request_page")
    _exact_positive_int(payload.get("pageSize"), "request_page_size")
    rcd_type = payload.get("rcdType") if "rcdType" in payload else None
    if rcd_type is not None and type(rcd_type) is not int:
        raise OfferTodayCursorContractError("invalid_request_rcd_type")
    if rcd_type not in contract.allowed_rcd_types:
        raise OfferTodayCursorContractError("unsupported_request_rcd_type")
    cursor_fields = {"sessionId", "supplePage", "suppleAmount", "suppleType"}
    if not contract.cursor_verified and cursor_fields & set(payload):
        raise OfferTodayCursorContractError("unverified_cursor_contract")


def validate_offertoday_endpoint_response_url(
    contract: OfferTodayListingEndpointContract,
    response_url: str | None,
) -> None:
    if response_url is None:
        return
    if not isinstance(response_url, str) or not response_url.strip():
        raise OfferTodayCursorContractError("invalid_response_url")
    if response_url.split("?", 1)[0] != contract.url:
        raise OfferTodayCursorContractError("endpoint_response_url_mismatch")


class OfferTodayCursorContractError(ValueError):
    """Raised when a listing response cannot continue a valid cursor chain."""

    def __init__(self, reason: str) -> None:
        self.reason = str(reason)
        super().__init__(self.reason)


class OfferTodayBrowserContextLostError(ConnectionError):
    """Raised when a listing request loses its owning browser context."""


def _canonical_hash(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _exact_nonnegative_int(value: Any, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise OfferTodayCursorContractError(f"invalid_{field_name}")
    return value


def _exact_positive_int(value: Any, field_name: str) -> int:
    resolved = _exact_nonnegative_int(value, field_name)
    if resolved < 1:
        raise OfferTodayCursorContractError(f"invalid_{field_name}")
    return resolved


def _optional_sha256(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 or None")
    return value


def _required_sha256(value: Any, field_name: str) -> str:
    resolved = _optional_sha256(value, field_name)
    if resolved is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return resolved


def _exact_nonblank_string(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise ValueError(f"{field_name} must be an exact nonblank string")
    return value


@dataclass(frozen=True, slots=True)
class OfferTodayListingCursorFieldPresence:
    session_id: bool
    supple_page: bool
    supple_amount: bool
    supple_type: bool
    page_size: bool

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            if type(getattr(self, field_name)) is not bool:
                raise ValueError(f"{field_name} presence must be an exact boolean")

    @classmethod
    def from_payload(cls, payload: Any) -> "OfferTodayListingCursorFieldPresence":
        expected = set(cls.__dataclass_fields__)
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("cursor field presence payload fields do not match")
        return cls(**{field_name: payload[field_name] for field_name in expected})


def offertoday_listing_cursor_field_presence(
    response: Mapping[str, Any] | None,
) -> OfferTodayListingCursorFieldPresence:
    raw_data = response.get("data") if isinstance(response, Mapping) else None
    data = raw_data if isinstance(raw_data, Mapping) else {}
    return OfferTodayListingCursorFieldPresence(
        session_id="sessionId" in data and data.get("sessionId") is not None,
        supple_page="supplePage" in data and data.get("supplePage") is not None,
        supple_amount="suppleAmount" in data and data.get("suppleAmount") is not None,
        supple_type="suppleType" in data and data.get("suppleType") is not None,
        page_size="pageSize" in data and data.get("pageSize") is not None,
    )


@dataclass(frozen=True, slots=True)
class OfferTodayListingIdentityEvidenceV2:
    job_id: str
    encrypted_job_id: str
    encrypted_job_id_source: OfferTodayEncryptedJobIdSource

    def __post_init__(self) -> None:
        OfferTodayDetailIdentity(
            job_id=self.job_id,
            encrypted_job_id=self.encrypted_job_id,
            encrypted_job_id_source=self.encrypted_job_id_source,
        )

    @classmethod
    def from_payload(cls, payload: Any) -> "OfferTodayListingIdentityEvidenceV2":
        expected = set(cls.__dataclass_fields__)
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("listing identity evidence payload fields do not match")
        return cls(
            job_id=payload["job_id"],
            encrypted_job_id=payload["encrypted_job_id"],
            encrypted_job_id_source=payload["encrypted_job_id_source"],
        )


@dataclass(frozen=True, slots=True)
class OfferTodayListingCursorEvidence:
    cursor_hash: str
    session_id_hash: str
    supple_page: int
    supple_amount: int
    supple_type: int
    effective_page_size: int

    def __post_init__(self) -> None:
        _required_sha256(self.cursor_hash, "cursor_hash")
        _required_sha256(self.session_id_hash, "session_id_hash")
        for field_name, value in (
            ("supple_page", self.supple_page),
            ("supple_amount", self.supple_amount),
            ("supple_type", self.supple_type),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a nonnegative exact integer")
        if type(self.effective_page_size) is not int or self.effective_page_size < 1:
            raise ValueError("effective_page_size must be a positive exact integer")

    @classmethod
    def from_payload(cls, payload: Any) -> "OfferTodayListingCursorEvidence":
        expected = set(cls.__dataclass_fields__)
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("cursor evidence payload fields do not match")
        return cls(**{field_name: payload[field_name] for field_name in expected})


@dataclass(frozen=True, slots=True)
class OfferTodayListingCursor:
    session_id: str
    supple_page: int
    supple_amount: int
    supple_type: int
    effective_page_size: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.session_id, str)
            or not self.session_id
            or self.session_id != self.session_id.strip()
        ):
            raise OfferTodayCursorContractError("invalid_session_id")
        for field_name, value in (
            ("supple_page", self.supple_page),
            ("supple_amount", self.supple_amount),
            ("supple_type", self.supple_type),
        ):
            _exact_nonnegative_int(value, field_name)
        _exact_positive_int(self.effective_page_size, "effective_page_size")

    @property
    def cursor_hash(self) -> str:
        return _canonical_hash(self.to_request_fields())

    def to_request_fields(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "supplePage": self.supple_page,
            "suppleAmount": self.supple_amount,
            "suppleType": self.supple_type,
        }

    def to_evidence(self) -> OfferTodayListingCursorEvidence:
        return OfferTodayListingCursorEvidence(
            cursor_hash=self.cursor_hash,
            session_id_hash=hashlib.sha256(self.session_id.encode()).hexdigest(),
            supple_page=self.supple_page,
            supple_amount=self.supple_amount,
            supple_type=self.supple_type,
            effective_page_size=self.effective_page_size,
        )


@dataclass(frozen=True, slots=True)
class OfferTodayListingRequestPolicy:
    protocol_version: int
    pagination_mode: PaginationMode
    requested_page_size: int
    browser_lifecycle: BrowserLifecycle
    variant_id: str
    repeat_index: int
    condition_restart_index: int = 0
    endpoint_contract_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.protocol_version) is not int or self.protocol_version != 2:
            raise ValueError("protocol_version must equal 2")
        if self.pagination_mode not in _PAGINATION_MODES:
            raise ValueError("unsupported pagination_mode")
        if type(self.requested_page_size) is not int or self.requested_page_size < 1:
            raise ValueError("requested_page_size must be a positive exact integer")
        if self.browser_lifecycle not in _BROWSER_LIFECYCLES:
            raise ValueError("unsupported browser_lifecycle")
        if (
            not isinstance(self.variant_id, str)
            or not self.variant_id
            or self.variant_id != self.variant_id.strip()
        ):
            raise ValueError("variant_id must be nonblank")
        if type(self.repeat_index) is not int or self.repeat_index not in (1, 2):
            raise ValueError("repeat_index must be 1 or 2")
        if type(self.condition_restart_index) is not int or self.condition_restart_index < 0:
            raise ValueError("condition_restart_index must be a nonnegative exact integer")
        if self.endpoint_contract_id is not None:
            _exact_nonblank_string(
                self.endpoint_contract_id,
                "endpoint_contract_id",
            )
            contract = offertoday_endpoint_contract(self.endpoint_contract_id)
            if self.requires_cursor and not contract.cursor_verified:
                raise ValueError(
                    "response-cursor mode requires a verified endpoint cursor contract"
                )

    @property
    def endpoint_contract(self) -> OfferTodayListingEndpointContract | None:
        if self.endpoint_contract_id is None:
            return None
        return offertoday_endpoint_contract(self.endpoint_contract_id)

    @property
    def requires_cursor(self) -> bool:
        return self.pagination_mode == "response-cursor"

    def condition_execution_id(self, condition_id: str) -> str:
        payload = {
            "condition_id": condition_id,
            "condition_restart_index": self.condition_restart_index,
            "protocol_version": self.protocol_version,
            "repeat_index": self.repeat_index,
            "variant_id": self.variant_id,
        }
        if self.endpoint_contract_id is not None:
            payload["endpoint_contract_id"] = self.endpoint_contract_id
        return _canonical_hash(payload)

    def logical_request_id(self, condition_id: str, page: int) -> str:
        if type(page) is not int or page < 1:
            raise ValueError("page must be a positive exact integer")
        return _canonical_hash(
            {
                "condition_execution_id": self.condition_execution_id(condition_id),
                "page": page,
            }
        )

    def physical_attempt_id(self, condition_id: str, page: int, attempt: int) -> str:
        if type(attempt) is not int or attempt < 1:
            raise ValueError("attempt must be a positive exact integer")
        return _canonical_hash(
            {
                "attempt": attempt,
                "logical_request_id": self.logical_request_id(condition_id, page),
            }
        )


@dataclass(frozen=True, slots=True)
class OfferTodayListingTransportResult:
    payload: dict[str, Any] | None
    browser_context_hash: str | None = None
    http_status: int | None = None
    response_url: str | None = None

    def __post_init__(self) -> None:
        if self.payload is not None and not isinstance(self.payload, dict):
            raise TypeError("payload must be a dictionary or None")
        object.__setattr__(self, "payload", deepcopy(self.payload))
        _optional_sha256(self.browser_context_hash, "browser_context_hash")
        if (self.http_status is None) != (self.response_url is None):
            raise ValueError("http_status and response_url must be provided together")
        if self.http_status is not None and (
            type(self.http_status) is not int or not 200 <= self.http_status < 300
        ):
            raise ValueError("http_status must be a successful exact integer status")
        if self.response_url is not None and (
            not isinstance(self.response_url, str)
            or not self.response_url.strip()
            or self.response_url != self.response_url.strip()
        ):
            raise ValueError("response_url must be a nonblank trimmed string")


@dataclass(frozen=True, slots=True)
class OfferTodayListingPageResult:
    raw_payload: dict[str, Any]
    result_rows: tuple[dict[str, Any], ...]
    supplemental_rows: tuple[dict[str, Any], ...]
    cursor: OfferTodayListingCursor | None
    has_more: bool | None
    reported_total: int | None
    response_page_size: int | None
    cursor_field_presence: OfferTodayListingCursorFieldPresence

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_payload", deepcopy(self.raw_payload))
        object.__setattr__(
            self,
            "result_rows",
            tuple(deepcopy(row) for row in self.result_rows),
        )
        object.__setattr__(
            self,
            "supplemental_rows",
            tuple(deepcopy(row) for row in self.supplemental_rows),
        )


@dataclass(frozen=True, slots=True)
class OfferTodayListingPageEvidenceV2:
    protocol_version: int
    variant_id: str
    repeat_index: int
    condition_restart_index: int
    condition_execution_id: str
    logical_request_id: str
    physical_attempt_id: str
    browser_context_hash: str | None
    pagination_mode: PaginationMode
    browser_lifecycle: BrowserLifecycle
    requested_page_size: int
    response_page_size: int | None
    effective_page_size: int | None
    cursor_input: OfferTodayListingCursorEvidence | None
    cursor_output: OfferTodayListingCursorEvidence | None
    response_cursor_fields: OfferTodayListingCursorFieldPresence
    session_continuity: Literal[
        "not_applicable",
        "initial",
        "continued",
        "violation",
        "unavailable",
    ]
    result_row_count: int
    supplemental_row_count: int
    result_job_ids: tuple[str, ...]
    supplemental_job_ids: tuple[str, ...]
    result_identity_pairs: tuple[OfferTodayListingIdentityEvidenceV2, ...]
    supplemental_identity_pairs: tuple[OfferTodayListingIdentityEvidenceV2, ...]
    cohort_overlap_job_ids: tuple[str, ...]
    new_job_id_count: int
    duplicate_job_id_count: int
    zero_new_full_page: bool
    terminal_signal: bool
    awaiting_empty_confirmation: bool
    contract_error: str | None = None

    def __post_init__(self) -> None:
        if type(self.protocol_version) is not int or self.protocol_version != 2:
            raise ValueError("protocol_version must equal 2")
        _exact_nonblank_string(self.variant_id, "variant_id")
        if type(self.repeat_index) is not int or self.repeat_index not in (1, 2):
            raise ValueError("repeat_index must be 1 or 2")
        if type(self.condition_restart_index) is not int or self.condition_restart_index < 0:
            raise ValueError("condition_restart_index must be nonnegative")
        for field_name in (
            "condition_execution_id",
            "logical_request_id",
            "physical_attempt_id",
        ):
            _required_sha256(getattr(self, field_name), field_name)
        _optional_sha256(self.browser_context_hash, "browser_context_hash")
        if self.pagination_mode not in _PAGINATION_MODES:
            raise ValueError("unsupported pagination_mode")
        if self.browser_lifecycle not in _BROWSER_LIFECYCLES:
            raise ValueError("unsupported browser_lifecycle")
        _exact_positive_int(self.requested_page_size, "requested_page_size")
        if self.response_page_size is not None:
            _exact_positive_int(self.response_page_size, "response_page_size")
        if self.effective_page_size is not None:
            _exact_positive_int(self.effective_page_size, "effective_page_size")
        if self.session_continuity not in {
            "not_applicable",
            "initial",
            "continued",
            "violation",
            "unavailable",
        }:
            raise ValueError("unsupported session_continuity")
        for field_name in (
            "result_row_count",
            "supplemental_row_count",
            "new_job_id_count",
            "duplicate_job_id_count",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a nonnegative exact integer")
        for field_name in (
            "result_job_ids",
            "supplemental_job_ids",
            "cohort_overlap_job_ids",
        ):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or any(
                not isinstance(value, str)
                or not value
                or value != value.strip()
                for value in values
            ):
                raise ValueError(f"{field_name} must contain exact nonblank strings")
        for field_name in (
            "zero_new_full_page",
            "terminal_signal",
            "awaiting_empty_confirmation",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise ValueError(f"{field_name} must be an exact boolean")
        if self.contract_error is not None:
            _exact_nonblank_string(self.contract_error, "contract_error")
        if tuple(sorted(set(self.result_job_ids) & set(self.supplemental_job_ids))) != (
            self.cohort_overlap_job_ids
        ):
            raise ValueError("cohort_overlap_job_ids does not match the cohorts")
        for cohort_name, pairs, job_ids in (
            ("result", self.result_identity_pairs, self.result_job_ids),
            (
                "supplemental",
                self.supplemental_identity_pairs,
                self.supplemental_job_ids,
            ),
        ):
            pair_counts = Counter(item.job_id for item in pairs)
            job_id_counts = Counter(job_ids)
            if any(
                count > job_id_counts.get(job_id, 0)
                for job_id, count in pair_counts.items()
            ):
                raise ValueError(
                    f"{cohort_name} identity pairs are not owned by the ID cohort"
                )

    @classmethod
    def from_payload(cls, payload: Any) -> "OfferTodayListingPageEvidenceV2":
        expected = set(cls.__dataclass_fields__)
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("v2 page evidence payload fields do not match")
        values = dict(payload)
        for field_name in ("cursor_input", "cursor_output"):
            raw_value = values[field_name]
            values[field_name] = (
                None
                if raw_value is None
                else OfferTodayListingCursorEvidence.from_payload(raw_value)
            )
        values["response_cursor_fields"] = (
            OfferTodayListingCursorFieldPresence.from_payload(
                values["response_cursor_fields"]
            )
        )
        for field_name in ("result_identity_pairs", "supplemental_identity_pairs"):
            raw_items = values[field_name]
            if not isinstance(raw_items, list):
                raise ValueError(f"{field_name} must be a list")
            values[field_name] = tuple(
                OfferTodayListingIdentityEvidenceV2.from_payload(item)
                for item in raw_items
            )
        for field_name in (
            "result_job_ids",
            "supplemental_job_ids",
            "cohort_overlap_job_ids",
        ):
            raw_items = values[field_name]
            if not isinstance(raw_items, list):
                raise ValueError(f"{field_name} must be a list")
            values[field_name] = tuple(raw_items)
        return cls(**values)


def _row_cohort(data: Mapping[str, Any], field_name: str) -> tuple[dict[str, Any], ...]:
    raw_value = data.get(field_name)
    if raw_value is None and field_name == "suppleRcdList":
        return ()
    if not isinstance(raw_value, list) or any(
        not isinstance(row, Mapping) for row in raw_value
    ):
        raise OfferTodayCursorContractError(f"invalid_{field_name}")
    return tuple(dict(deepcopy(row)) for row in raw_value)


def parse_offertoday_listing_page_result(
    response: dict[str, Any],
    *,
    require_cursor: bool,
    expected_session_id: str | None = None,
    expected_effective_page_size: int | None = None,
    endpoint_contract_id: str | None = None,
) -> OfferTodayListingPageResult:
    """Parse and validate the response fields needed for a cursor chain."""

    if endpoint_contract_id is not None:
        contract = offertoday_endpoint_contract(endpoint_contract_id)
        if contract.endpoint == "browse":
            if require_cursor:
                raise OfferTodayCursorContractError("unverified_cursor_contract")
            raw_data = response.get("data")
            if not isinstance(raw_data, Mapping):
                raise OfferTodayCursorContractError("invalid_data")
            data = dict(raw_data)
            cursor_presence = offertoday_listing_cursor_field_presence(response)
            if any(
                (
                    cursor_presence.session_id,
                    cursor_presence.supple_page,
                    cursor_presence.supple_amount,
                    cursor_presence.supple_type,
                )
            ):
                raise OfferTodayCursorContractError(
                    "unexpected_search_cursor_fields"
                )
            if data.get("suppleRcdList") not in (None, []):
                raise OfferTodayCursorContractError(
                    "unexpected_search_supplemental_rows"
                )
            result_rows = _row_cohort(data, contract.result_rows_field)
            raw_page_size = data.get("pageSize")
            response_page_size = (
                None
                if raw_page_size is None
                else _exact_positive_int(raw_page_size, "page_size")
            )
            raw_has_more = data.get("hasMore")
            if raw_has_more is not None and type(raw_has_more) is not bool:
                raise OfferTodayCursorContractError("invalid_has_more")
            raw_total = data.get("total")
            reported_total = (
                None
                if raw_total is None
                else _exact_nonnegative_int(raw_total, "total")
            )
            return OfferTodayListingPageResult(
                raw_payload=response,
                result_rows=result_rows,
                supplemental_rows=(),
                cursor=None,
                has_more=raw_has_more,
                reported_total=reported_total,
                response_page_size=response_page_size,
                cursor_field_presence=cursor_presence,
            )

    raw_data = response.get("data")
    if not isinstance(raw_data, Mapping):
        raise OfferTodayCursorContractError("invalid_data")
    data = dict(raw_data)
    cursor_field_presence = offertoday_listing_cursor_field_presence(response)
    result_rows = _row_cohort(data, "resultList")
    supplemental_rows = _row_cohort(data, "suppleRcdList")

    raw_page_size = data.get("pageSize")
    if raw_page_size is None:
        response_page_size = None
    else:
        response_page_size = _exact_positive_int(raw_page_size, "page_size")
    if require_cursor and response_page_size is None:
        raise OfferTodayCursorContractError("missing_page_size")

    cursor_field_names = (
        "sessionId",
        "supplePage",
        "suppleAmount",
        "suppleType",
    )
    cursor_fields_present = [
        name in data and data.get(name) is not None for name in cursor_field_names
    ]
    cursor: OfferTodayListingCursor | None = None
    if require_cursor or any(cursor_fields_present):
        if not all(cursor_fields_present):
            raise OfferTodayCursorContractError("incomplete_cursor")
        session_id = data.get("sessionId")
        if not isinstance(session_id, str) or not session_id.strip():
            raise OfferTodayCursorContractError("invalid_session_id")
        if response_page_size is None:
            raise OfferTodayCursorContractError("missing_page_size")
        cursor = OfferTodayListingCursor(
            session_id=session_id,
            supple_page=_exact_nonnegative_int(data.get("supplePage"), "supple_page"),
            supple_amount=_exact_nonnegative_int(
                data.get("suppleAmount"),
                "supple_amount",
            ),
            supple_type=_exact_nonnegative_int(data.get("suppleType"), "supple_type"),
            effective_page_size=response_page_size,
        )
        if expected_session_id is not None and cursor.session_id != expected_session_id:
            raise OfferTodayCursorContractError("session_rollover")
        if (
            expected_effective_page_size is not None
            and cursor.effective_page_size != expected_effective_page_size
        ):
            raise OfferTodayCursorContractError("page_size_drift")

    raw_has_more = data.get("hasMore")
    if raw_has_more is not None and type(raw_has_more) is not bool:
        raise OfferTodayCursorContractError("invalid_has_more")
    has_more = raw_has_more
    raw_total = data.get("total")
    if raw_total is not None:
        reported_total = _exact_nonnegative_int(raw_total, "total")
    else:
        reported_total = None
    return OfferTodayListingPageResult(
        raw_payload=response,
        result_rows=result_rows,
        supplemental_rows=supplemental_rows,
        cursor=cursor,
        has_more=has_more,
        reported_total=reported_total,
        response_page_size=response_page_size,
        cursor_field_presence=cursor_field_presence,
    )
