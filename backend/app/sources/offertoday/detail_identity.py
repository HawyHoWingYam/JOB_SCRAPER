from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, overload

from app.sources.offertoday.response_policy import OfferTodayResponseClassification


OfferTodayEncryptedJobIdSource = Literal["encryptJobId", "jobId_fallback"]


class OfferTodayIdentityError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        classification: str = "invalid_identity",
    ) -> None:
        super().__init__(message)
        self.classification = classification


@dataclass(frozen=True, slots=True)
class OfferTodayDetailIdentity:
    job_id: str
    encrypted_job_id: str
    encrypted_job_id_source: OfferTodayEncryptedJobIdSource = "encryptJobId"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.job_id, str)
            or not self.job_id.strip()
            or self.job_id != self.job_id.strip()
        ):
            raise OfferTodayIdentityError(
                "OfferToday job_id must be a nonblank string",
                classification="missing_job_id",
            )
        if (
            not isinstance(self.encrypted_job_id, str)
            or not self.encrypted_job_id.strip()
            or self.encrypted_job_id != self.encrypted_job_id.strip()
        ):
            raise OfferTodayIdentityError(
                "OfferToday encrypted_job_id must be a nonblank string",
                classification="missing_encrypted_job_id",
            )
        if self.encrypted_job_id_source not in (
            "encryptJobId",
            "jobId_fallback",
        ):
            raise OfferTodayIdentityError(
                "Invalid encrypted_job_id_source",
                classification="invalid_encrypted_job_id_source",
            )
        if (
            self.encrypted_job_id_source == "jobId_fallback"
            and self.encrypted_job_id != self.job_id
        ):
            raise OfferTodayIdentityError(
                "jobId_fallback route must equal canonical jobId",
                classification="encrypted_job_id_source_conflict",
            )


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
    is_job_id = evidence_name == "jobId"
    prefix = "job_id" if is_job_id else "encrypted_job_id"
    return _read_entries(
        _alias_entries(
            payload,
            field_names=field_names,
            raw_field_name=raw_field_name,
        ),
        evidence_name=evidence_name,
        required=required,
        missing_classification=f"missing_{prefix}",
        invalid_classification=f"invalid_{prefix}_evidence",
        conflict_classification=f"{prefix}_alias_conflict",
    )


def _alias_entries(
    payload: Mapping[str, Any],
    *,
    field_names: tuple[str, ...],
    raw_field_name: str,
    include_raw: bool = True,
) -> list[tuple[str, Any]]:
    entries = [(name, payload.get(name)) for name in field_names]
    raw_data = payload.get("raw_data")
    if include_raw and isinstance(raw_data, Mapping):
        entries.append((f"raw_data.{raw_field_name}", raw_data.get(raw_field_name)))
    return entries


def _read_entries(
    entries: list[tuple[str, Any]],
    *,
    evidence_name: str,
    required: bool,
    missing_classification: str,
    invalid_classification: str,
    conflict_classification: str,
) -> str | None:
    valid: list[tuple[str, str]] = []
    for name, value in entries:
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if not isinstance(value, str):
            raise OfferTodayIdentityError(
                f"OfferToday identity alias {name} must be a nonblank string; got {value!r}",
                classification=invalid_classification,
            )
        valid.append((name, value.strip()))
    if not valid:
        if not required:
            return None
        rendered = ", ".join(f"{name}={value!r}" for name, value in entries)
        raise OfferTodayIdentityError(
            f"Missing nonblank string {evidence_name}; evidence: {rendered}",
            classification=missing_classification,
        )
    values = {value for _name, value in valid}
    if len(values) != 1:
        rendered = ", ".join(f"{name}={value!r}" for name, value in valid)
        raise OfferTodayIdentityError(
            f"Conflicting {evidence_name} identity evidence: {rendered}",
            classification=conflict_classification,
        )
    return valid[0][1]


def _require_nonblank_string(value: Any, *, evidence_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        classification = (
            "invalid_source_job_id"
            if evidence_name == "source_job_id"
            else "missing_job_id"
        )
        raise OfferTodayIdentityError(
            f"Missing nonblank string {evidence_name}; got {value!r}",
            classification=classification,
        )
    return value.strip()


def _read_resolution_source(
    payload: Mapping[str, Any],
) -> OfferTodayEncryptedJobIdSource | None:
    if "encrypted_job_id_source" not in payload:
        return None
    value = payload.get("encrypted_job_id_source")
    if value not in ("encryptJobId", "jobId_fallback"):
        raise OfferTodayIdentityError(
            "encrypted_job_id_source must be 'encryptJobId' or 'jobId_fallback'",
            classification="invalid_encrypted_job_id_source",
        )
    return value


def resolve_offertoday_listing_identity(
    payload: Mapping[str, Any],
    *,
    source_job_id: Any | None = None,
) -> OfferTodayDetailIdentity:
    if not isinstance(payload, Mapping):
        raise OfferTodayIdentityError(
            f"Missing OfferToday identity payload; got {type(payload).__name__}",
            classification="missing_listing_payload",
        )
    job_id = read_offertoday_identity_evidence(
        payload,
        field_names=("job_id", "jobId"),
        raw_field_name="jobId",
        evidence_name="jobId",
    )
    route_id = read_offertoday_identity_evidence(
        payload,
        field_names=("encrypted_job_id", "encryptJobId"),
        raw_field_name="encryptJobId",
        evidence_name="encryptJobId",
        required=False,
    )
    explicit_route_id = _read_entries(
        _alias_entries(
            payload,
            field_names=("encryptJobId",),
            raw_field_name="encryptJobId",
        ),
        evidence_name="encryptJobId",
        required=False,
        missing_classification="missing_encrypted_job_id",
        invalid_classification="invalid_encrypted_job_id_evidence",
        conflict_classification="encrypted_job_id_alias_conflict",
    )
    declared_source = _read_resolution_source(payload)
    if explicit_route_id is not None:
        if declared_source == "jobId_fallback":
            raise OfferTodayIdentityError(
                "Explicit encryptJobId conflicts with jobId_fallback provenance",
                classification="encrypted_job_id_source_conflict",
            )
        source: OfferTodayEncryptedJobIdSource = "encryptJobId"
        resolved_route_id = explicit_route_id
    elif route_id is None:
        if declared_source == "encryptJobId":
            raise OfferTodayIdentityError(
                "encryptJobId provenance has no encrypted identity evidence",
                classification="missing_encrypted_job_id",
            )
        source = "jobId_fallback"
        resolved_route_id = job_id
    elif declared_source == "jobId_fallback" or (
        declared_source is None and route_id == job_id
    ):
        if route_id != job_id:
            raise OfferTodayIdentityError(
                "jobId_fallback route must equal canonical jobId",
                classification="encrypted_job_id_source_conflict",
            )
        source = "jobId_fallback"
        resolved_route_id = job_id
    else:
        source = "encryptJobId"
        resolved_route_id = route_id
    if source_job_id is not None:
        canonical_source_job_id = _require_nonblank_string(
            source_job_id,
            evidence_name="source_job_id",
        )
        if canonical_source_job_id != job_id:
            raise OfferTodayIdentityError(
                "OfferToday detail identity mismatch: "
                f"source_job_id={canonical_source_job_id!r}, listing jobId={job_id!r}",
                classification="source_job_id_mismatch",
            )
    return OfferTodayDetailIdentity(
        job_id=job_id,
        encrypted_job_id=resolved_route_id,
        encrypted_job_id_source=source,
    )


def resolve_offertoday_detail_identity(
    *,
    source_job_id: Any,
    listing_payload: Mapping[str, Any],
) -> OfferTodayDetailIdentity:
    canonical_source_job_id = _require_nonblank_string(
        source_job_id,
        evidence_name="source_job_id",
    )
    return resolve_offertoday_listing_identity(
        listing_payload,
        source_job_id=canonical_source_job_id,
    )


def choose_offertoday_authoritative_identity(
    *,
    job_id: str,
    identities: Sequence[OfferTodayDetailIdentity],
) -> OfferTodayDetailIdentity:
    canonical_job_id = _require_nonblank_string(job_id, evidence_name="jobId")
    normalized = tuple(identities)
    if not normalized or any(item.job_id != canonical_job_id for item in normalized):
        raise OfferTodayIdentityError(
            "Identity authority requires one canonical jobId",
            classification="source_job_id_mismatch",
        )
    explicit_ids = {
        item.encrypted_job_id
        for item in normalized
        if item.encrypted_job_id_source == "encryptJobId"
    }
    if len(explicit_ids) > 1:
        raise OfferTodayIdentityError(
            f"Multiple explicit encryptJobId values for jobId={canonical_job_id!r}",
            classification="one_job_id_to_multiple_encrypted_ids",
        )
    if explicit_ids:
        return OfferTodayDetailIdentity(
            job_id=canonical_job_id,
            encrypted_job_id=next(iter(explicit_ids)),
            encrypted_job_id_source="encryptJobId",
        )
    return OfferTodayDetailIdentity(
        job_id=canonical_job_id,
        encrypted_job_id=canonical_job_id,
        encrypted_job_id_source="jobId_fallback",
    )


@dataclass(frozen=True, slots=True)
class OfferTodayIdentityAuthorityIndex:
    authoritative_identity_by_job: Mapping[str, OfferTodayDetailIdentity]
    explicit_ids_by_job: Mapping[str, tuple[str, ...]]
    route_to_job_ids: Mapping[str, tuple[str, ...]]
    fallback_job_ids: tuple[str, ...]
    conflict_reason_by_job: Mapping[str, str]


def build_offertoday_identity_authority_index(
    identities: Sequence[OfferTodayDetailIdentity],
) -> OfferTodayIdentityAuthorityIndex:
    grouped: dict[str, list[OfferTodayDetailIdentity]] = {}
    fallback_job_ids: list[str] = []
    fallback_seen: set[str] = set()
    explicit_ids_by_job: dict[str, tuple[str, ...]] = {}
    for identity in identities:
        grouped.setdefault(identity.job_id, []).append(identity)
        if (
            identity.encrypted_job_id_source == "jobId_fallback"
            and identity.job_id not in fallback_seen
        ):
            fallback_seen.add(identity.job_id)
            fallback_job_ids.append(identity.job_id)

    authoritative: dict[str, OfferTodayDetailIdentity] = {}
    conflict_reason_by_job: dict[str, str] = {}
    for job_id, values in grouped.items():
        explicit_ids_by_job[job_id] = tuple(
            sorted(
                {
                    value.encrypted_job_id
                    for value in values
                    if value.encrypted_job_id_source == "encryptJobId"
                }
            )
        )
        try:
            authoritative[job_id] = choose_offertoday_authoritative_identity(
                job_id=job_id,
                identities=values,
            )
        except OfferTodayIdentityError as exc:
            if exc.classification != "one_job_id_to_multiple_encrypted_ids":
                raise
            conflict_reason_by_job[job_id] = "multiple_explicit_encrypted_ids"

    route_to_jobs: dict[str, set[str]] = {}
    for job_id, identity in authoritative.items():
        route_to_jobs.setdefault(identity.encrypted_job_id, set()).add(job_id)
    for job_ids in route_to_jobs.values():
        if len(job_ids) > 1:
            for job_id in job_ids:
                conflict_reason_by_job[job_id] = "reverse_collision"

    return OfferTodayIdentityAuthorityIndex(
        authoritative_identity_by_job=MappingProxyType(dict(authoritative)),
        explicit_ids_by_job=MappingProxyType(dict(explicit_ids_by_job)),
        route_to_job_ids=MappingProxyType(
            {
                route_id: tuple(sorted(job_ids))
                for route_id, job_ids in route_to_jobs.items()
            }
        ),
        fallback_job_ids=tuple(fallback_job_ids),
        conflict_reason_by_job=MappingProxyType(
            dict(sorted(conflict_reason_by_job.items()))
        ),
    )


def validate_offertoday_detail_identity(
    identity: OfferTodayDetailIdentity,
    detail_payload: Mapping[str, Any],
) -> None:
    response_identity = resolve_offertoday_listing_identity(detail_payload)
    if response_identity.job_id != identity.job_id:
        raise OfferTodayIdentityError(
            "OfferToday detail response identity mismatch: "
            f"requested jobId={identity.job_id!r}, "
            f"response jobId={response_identity.job_id!r}",
            classification="detail_job_id_mismatch",
        )
    if (
        response_identity.encrypted_job_id_source == "encryptJobId"
        and response_identity.encrypted_job_id != identity.encrypted_job_id
    ):
        raise OfferTodayIdentityError(
            "OfferToday detail response identity mismatch: "
            f"requested encryptJobId={identity.encrypted_job_id!r}, "
            f"response encryptJobId={response_identity.encrypted_job_id!r}",
            classification="detail_encrypted_job_id_mismatch",
        )
