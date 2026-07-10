from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, Mapping, overload

from app.sources.offertoday.response_policy import OfferTodayResponseClassification


class OfferTodayIdentityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OfferTodayDetailIdentity:
    job_id: str
    encrypted_job_id: str


@dataclass(frozen=True, slots=True)
class OfferTodayDetailFetchResult:
    identity: OfferTodayDetailIdentity
    classification: OfferTodayResponseClassification
    raw_response: dict[str, Any] | None
    parsed_detail: dict[str, Any] | None
    canonical_detail: dict[str, Any] | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_response", deepcopy(self.raw_response))
        object.__setattr__(self, "parsed_detail", deepcopy(self.parsed_detail))
        object.__setattr__(self, "canonical_detail", deepcopy(self.canonical_detail))


@overload
def read_offertoday_identity_evidence(
    payload: Mapping[str, Any],
    *,
    field_names: tuple[str, ...],
    raw_field_name: str,
    evidence_name: str,
    required: Literal[True] = True,
) -> str: ...


@overload
def read_offertoday_identity_evidence(
    payload: Mapping[str, Any],
    *,
    field_names: tuple[str, ...],
    raw_field_name: str,
    evidence_name: str,
    required: Literal[False],
) -> str | None: ...


def read_offertoday_identity_evidence(
    payload: Mapping[str, Any],
    *,
    field_names: tuple[str, ...],
    raw_field_name: str,
    evidence_name: str,
    required: bool = True,
) -> str | None:
    evidence: list[tuple[str, Any]] = [
        (field_name, payload.get(field_name)) for field_name in field_names
    ]
    raw_data = payload.get("raw_data")
    if isinstance(raw_data, Mapping):
        evidence.append((f"raw_data.{raw_field_name}", raw_data.get(raw_field_name)))

    valid_values: list[tuple[str, str]] = []
    for name, value in evidence:
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if not isinstance(value, str):
            raise OfferTodayIdentityError(
                f"OfferToday identity alias {name} must be a nonblank string; "
                f"got {value!r}"
            )
        valid_values.append((name, value.strip()))

    if not valid_values:
        if not required:
            return None
        rendered = ", ".join(f"{name}={value!r}" for name, value in evidence)
        raise OfferTodayIdentityError(
            f"Missing nonblank string {evidence_name}; evidence: {rendered}"
        )

    distinct_values = {value for _name, value in valid_values}
    if len(distinct_values) > 1:
        rendered = ", ".join(f"{name}={value!r}" for name, value in valid_values)
        raise OfferTodayIdentityError(
            f"Conflicting {evidence_name} identity evidence: {rendered}"
        )
    return valid_values[0][1]


def _require_nonblank_string(value: Any, *, evidence_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfferTodayIdentityError(
            f"Missing nonblank string {evidence_name}; got {value!r}"
        )
    return value.strip()


def resolve_offertoday_detail_identity(
    *,
    source_job_id: Any,
    listing_payload: Mapping[str, Any],
) -> OfferTodayDetailIdentity:
    resolved_source_job_id = _require_nonblank_string(
        source_job_id,
        evidence_name="source_job_id",
    )
    if not isinstance(listing_payload, Mapping):
        raise OfferTodayIdentityError(
            f"Missing OfferToday listing identity payload; got {type(listing_payload).__name__}"
        )

    job_id = read_offertoday_identity_evidence(
        listing_payload,
        field_names=("job_id", "jobId"),
        raw_field_name="jobId",
        evidence_name="jobId",
    )
    encrypted_job_id = read_offertoday_identity_evidence(
        listing_payload,
        field_names=("encrypted_job_id", "encryptJobId"),
        raw_field_name="encryptJobId",
        evidence_name="encryptJobId",
    )
    if resolved_source_job_id != job_id:
        raise OfferTodayIdentityError(
            "OfferToday detail identity mismatch: "
            f"source_job_id={resolved_source_job_id!r}, listing jobId={job_id!r}"
        )
    return OfferTodayDetailIdentity(
        job_id=job_id,
        encrypted_job_id=encrypted_job_id,
    )


def validate_offertoday_detail_identity(
    identity: OfferTodayDetailIdentity,
    detail_payload: Mapping[str, Any],
) -> None:
    if not isinstance(detail_payload, Mapping):
        raise OfferTodayIdentityError(
            f"Missing OfferToday detail identity payload; got {type(detail_payload).__name__}"
        )
    response_job_id = read_offertoday_identity_evidence(
        detail_payload,
        field_names=("job_id", "jobId"),
        raw_field_name="jobId",
        evidence_name="jobId",
    )
    if response_job_id != identity.job_id:
        raise OfferTodayIdentityError(
            "OfferToday detail response identity mismatch: "
            f"requested jobId={identity.job_id!r}, response jobId={response_job_id!r}"
        )

    response_encrypted_job_id = read_offertoday_identity_evidence(
        detail_payload,
        field_names=("encrypted_job_id", "encryptJobId"),
        raw_field_name="encryptJobId",
        evidence_name="encryptJobId",
        required=False,
    )
    if (
        response_encrypted_job_id is not None
        and response_encrypted_job_id != identity.encrypted_job_id
    ):
        raise OfferTodayIdentityError(
            "OfferToday detail response identity mismatch: "
            f"requested encryptJobId={identity.encrypted_job_id!r}, "
            f"response encryptJobId={response_encrypted_job_id!r}"
        )
