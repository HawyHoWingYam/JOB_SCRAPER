from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

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


def _read_identity_field(
    payload: Mapping[str, Any],
    *,
    field_names: tuple[str, ...],
    raw_field_name: str,
    evidence_name: str,
) -> str:
    evidence: list[tuple[str, Any]] = [
        (field_name, payload.get(field_name)) for field_name in field_names
    ]
    raw_data = payload.get("raw_data")
    if isinstance(raw_data, Mapping):
        evidence.append((f"raw_data.{raw_field_name}", raw_data.get(raw_field_name)))

    valid_values = [
        (name, value.strip())
        for name, value in evidence
        if isinstance(value, str) and value.strip()
    ]
    if not valid_values:
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

    job_id = _read_identity_field(
        listing_payload,
        field_names=("job_id", "jobId"),
        raw_field_name="jobId",
        evidence_name="jobId",
    )
    encrypted_job_id = _read_identity_field(
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
    response_job_id = _read_identity_field(
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
