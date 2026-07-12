from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.sources.offertoday.detail_identity import (
    OfferTodayDetailIdentity,
    OfferTodayEncryptedJobIdSource,
    OfferTodayIdentityError,
    build_offertoday_identity_authority_index,
    resolve_offertoday_listing_identity,
)
from app.sources.offertoday.research.artifacts import verify_research_artifact
from app.sources.offertoday.research.calibration import build_calibration_conditions
from app.sources.offertoday.research.smoke import (
    SMOKE_LISTING_REQUEST_LIMIT,
    runtime_smoke_request_budget,
)

_COUNT_KEYS = (
    "staged_rows",
    "distinct_staged_ids",
    "published_jobs",
    "distinct_staged_unpublished_ids",
    "pending_rows",
    "duplicate_staging_rows",
    "missing_encrypted_job_id_rows",
    "observed_encrypted_job_id_rows",
    "job_id_fallback_rows",
    "unusable_identity_rows",
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_UNEXPECTED_ERROR_RE = re.compile(r"unexpected_live_smoke_error:[A-Za-z_][A-Za-z0-9_]*")
_UNEXPECTED_CALIBRATION_ERROR_RE = re.compile(
    r"unexpected_listing_calibration_error:[A-Za-z_][A-Za-z0-9_]*"
)
_CALIBRATION_REQUEST_BUDGET = {
    "listing_logical": 24,
    "listing_attempt_max": 72,
    "detail": 0,
}


@dataclass(frozen=True, slots=True)
class BaselineArtifactEvidence:
    artifact_dir: Path
    run_id: str
    manifest_hash: str
    snapshot_hash: str
    inventory_hash: str
    counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class MatchingBaselineGate:
    first: BaselineArtifactEvidence
    second: BaselineArtifactEvidence

    @property
    def parent_artifact_hash(self) -> str:
        return self.second.manifest_hash


@dataclass(frozen=True, slots=True)
class LiveRunVerification:
    valid: bool
    issues: tuple[str, ...]
    experiment: str | None
    run_id: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": list(self.issues),
            "experiment": self.experiment,
            "run_id": self.run_id,
        }


def _require_mapping(value: Any, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(message)
    return value


def _require_sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"baseline {field_name} must be lowercase SHA-256")
    return value


def load_baseline_artifact(artifact_dir: Path) -> BaselineArtifactEvidence:
    artifact_dir = Path(artifact_dir).resolve(strict=True)
    verification = verify_research_artifact(artifact_dir)
    if not verification.valid:
        raise ValueError(f"invalid baseline artifact: {artifact_dir}")

    manifest_path = artifact_dir / "manifest.json"
    observations_path = artifact_dir / "observations.jsonl"
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes)
        observations = [
            json.loads(line)
            for line in observations_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("baseline artifact contains invalid JSON evidence") from exc

    baseline_events = [
        event
        for event in observations
        if isinstance(event, dict) and event.get("event_type") == "research.baseline"
    ]
    if len(baseline_events) != 1:
        raise ValueError(
            "baseline artifact must contain exactly one research.baseline event"
        )

    payload = _require_mapping(
        baseline_events[0].get("payload"),
        "baseline artifact is missing baseline payload evidence",
    )
    snapshot = _require_mapping(
        payload.get("snapshot"),
        "baseline artifact is missing snapshot or inventory evidence",
    )
    inventory = _require_mapping(
        payload.get("run_start_inventory"),
        "baseline artifact is missing snapshot or inventory evidence",
    )
    snapshot_hash = _require_sha256(snapshot.get("data_hash"), "snapshot hash")
    metadata = manifest.get("metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("experiment") != "foundation-baseline"
        or metadata.get("data_hash") != snapshot_hash
    ):
        raise ValueError("baseline artifact has invalid foundation-baseline metadata")

    counts: list[tuple[str, int]] = []
    for key in _COUNT_KEYS:
        value = snapshot.get(key)
        if type(value) is not int or value < 0:
            raise ValueError(
                f"baseline snapshot {key} must be a non-negative exact integer"
            )
        counts.append((key, value))

    run_id = manifest.get("run_id")
    if not isinstance(run_id, str):
        raise ValueError("baseline manifest is missing run_id")

    return BaselineArtifactEvidence(
        artifact_dir=artifact_dir,
        run_id=run_id,
        manifest_hash=hashlib.sha256(manifest_bytes).hexdigest(),
        snapshot_hash=snapshot_hash,
        inventory_hash=_require_sha256(
            inventory.get("data_hash"),
            "inventory hash",
        ),
        counts=tuple(counts),
    )


def require_matching_baselines(
    first_dir: Path,
    second_dir: Path,
) -> MatchingBaselineGate:
    first = load_baseline_artifact(first_dir)
    second = load_baseline_artifact(second_dir)
    if first.run_id == second.run_id:
        raise ValueError("matching baseline gate requires two distinct run IDs")
    if first.snapshot_hash != second.snapshot_hash:
        raise ValueError("baseline snapshot hashes do not match")
    if first.inventory_hash != second.inventory_hash:
        raise ValueError("baseline inventory hashes do not match")
    if first.counts != second.counts:
        raise ValueError("baseline count evidence does not match")
    return MatchingBaselineGate(first=first, second=second)


_LEGACY_RUNTIME_SMOKE_REQUEST_BUDGET = {"listing": 1, "detail": 20}
_RUNTIME_SMOKE_PAGE_CONTROL = {
    "search_family": "runtime_smoke",
    "category_id": 118000,
    "keyword": "",
    "endpoint": "search",
    "rcd_type": 7,
    "session_mode": "fresh-headless",
}
_DETAIL_FAILURE_KINDS = {
    "auth_expired",
    "waf_challenge",
    "ip_blocked",
    "transient_transport",
    "invalid_payload",
    "id_mismatch",
    "persist_failure",
}
_DETAIL_HARD_STOP_KINDS = {
    "auth_expired",
    "waf_challenge",
    "ip_blocked",
    "id_mismatch",
}
_NATURAL_EXHAUSTION_STOP_REASON = "natural_exhaustion"


def _runtime_smoke_common_page_control_is_valid(payload: Any) -> bool:
    return isinstance(payload, dict) and all(
        type(payload.get(key)) is type(expected_value)
        and payload.get(key) == expected_value
        for key, expected_value in _RUNTIME_SMOKE_PAGE_CONTROL.items()
    )


def _runtime_smoke_page_scalar_types_are_valid(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    api_code = payload.get("api_code")
    has_more = payload.get("has_more")
    return (api_code is None or type(api_code) is int) and (
        has_more is None or type(has_more) is bool
    )


def _runtime_smoke_success_control_values_are_valid(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    api_code = payload.get("api_code")
    return api_code is None or (type(api_code) is int and api_code == 0)


def _runtime_smoke_terminal_semantics_are_valid(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    has_more = payload.get("has_more")
    natural_exhaustion = payload.get("stop_reason") == _NATURAL_EXHAUSTION_STOP_REASON
    if natural_exhaustion:
        rows = payload.get("rows")
        return (isinstance(rows, list) and not rows) or has_more is False
    return has_more is not False


def _runtime_smoke_success_page_controls_are_valid(payload: Any) -> bool:
    return (
        _runtime_smoke_common_page_control_is_valid(payload)
        and _runtime_smoke_page_scalar_types_are_valid(payload)
        and _runtime_smoke_success_control_values_are_valid(payload)
        and _runtime_smoke_terminal_semantics_are_valid(payload)
    )


def _runtime_smoke_success_row_count_is_valid(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    rows = payload.get("rows")
    row_count = payload.get("row_count")
    return (
        isinstance(rows, list)
        and type(row_count) is int
        and row_count == len(rows)
        and (
            row_count > 0
            or payload.get("stop_reason") == _NATURAL_EXHAUSTION_STOP_REASON
        )
    )


def _canonical_smoke_target(
    payload: Any,
    *,
    expected_position: int,
    issues: list[str],
    allow_missing_resolution_hash: bool = False,
) -> tuple[int, str, str, OfferTodayEncryptedJobIdSource] | None:
    if not isinstance(payload, dict):
        issues.append("invalid_detail_target_payload")
        return None
    position = payload.get("position")
    job_id = payload.get("job_id")
    encrypted_job_id = payload.get("encrypted_job_id")
    encrypted_job_id_source = payload.get("encrypted_job_id_source")
    if type(position) is not int or position != expected_position:
        issues.append("invalid_detail_target_position")
        return None
    if not isinstance(job_id, str) or not job_id.strip():
        issues.append("invalid_detail_target_job_id")
        return None
    if not isinstance(encrypted_job_id, str) or not encrypted_job_id.strip():
        issues.append("invalid_detail_target_encrypted_job_id")
        return None
    if encrypted_job_id_source not in ("encryptJobId", "jobId_fallback"):
        issues.append("detail_cohort_identity_mismatch")
        return None
    try:
        identity = resolve_offertoday_listing_identity(payload)
    except OfferTodayIdentityError:
        issues.append("detail_cohort_identity_mismatch")
        return None
    if identity.encrypted_job_id_source != encrypted_job_id_source:
        issues.append("detail_cohort_identity_mismatch")
        return None

    expected_job_hash = hashlib.sha256(identity.job_id.encode()).hexdigest()
    expected_encrypted_hash = hashlib.sha256(
        identity.encrypted_job_id.encode()
    ).hexdigest()
    if payload.get("job_id_hash") != expected_job_hash:
        issues.append("detail_target_job_id_hash_mismatch")
    if payload.get("encrypted_job_id_hash") != expected_encrypted_hash:
        issues.append("detail_target_encrypted_job_id_hash_mismatch")
    identity_canonical = json.dumps(
        {
            "job_id": identity.job_id,
            "encrypted_job_id": identity.encrypted_job_id,
            "encrypted_job_id_source": identity.encrypted_job_id_source,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    expected_resolution_hash = hashlib.sha256(identity_canonical.encode()).hexdigest()
    if (
        not (
            allow_missing_resolution_hash and "identity_resolution_hash" not in payload
        )
        and payload.get("identity_resolution_hash") != expected_resolution_hash
    ):
        issues.append("invalid_detail_identity_resolution_hash")
    return (
        position,
        identity.job_id,
        identity.encrypted_job_id,
        identity.encrypted_job_id_source,
    )


def _canonical_page_identity_pair(payload: Any) -> OfferTodayDetailIdentity | None:
    if not isinstance(payload, dict):
        return None
    job_id = payload.get("job_id")
    encrypted_job_id = payload.get("encrypted_job_id")
    encrypted_job_id_source = payload.get("encrypted_job_id_source")
    if (
        not isinstance(job_id, str)
        or not job_id.strip()
        or not isinstance(encrypted_job_id, str)
        or not encrypted_job_id.strip()
        or encrypted_job_id_source not in ("encryptJobId", "jobId_fallback")
    ):
        return None
    try:
        identity = resolve_offertoday_listing_identity(payload)
    except OfferTodayIdentityError:
        return None
    if identity.encrypted_job_id_source != encrypted_job_id_source:
        return None
    return identity


def _canonical_page_row(payload: Any) -> OfferTodayDetailIdentity | None:
    if not isinstance(payload, dict) or "observed_encrypted_job_id" not in payload:
        return None
    identity = _canonical_page_identity_pair(payload)
    if identity is None:
        return None
    observed_encrypted_job_id = payload.get("observed_encrypted_job_id")
    if identity.encrypted_job_id_source == "jobId_fallback":
        if observed_encrypted_job_id is not None:
            return None
    elif (
        not isinstance(observed_encrypted_job_id, str)
        or not observed_encrypted_job_id.strip()
        or observed_encrypted_job_id != payload.get("encrypted_job_id")
    ):
        return None
    return identity


def _canonical_page_authority(
    payload: dict[str, Any],
    prior_committed_rows: list[OfferTodayDetailIdentity],
    issues: list[str],
) -> tuple[
    list[OfferTodayDetailIdentity],
    list[OfferTodayDetailIdentity],
    int,
    int,
]:
    serialized_pairs = payload.get("id_pairs")
    rows = payload.get("rows")
    identity_evidence_valid = True
    if not isinstance(serialized_pairs, list):
        identity_evidence_valid = False
        serialized_pairs = []
    if not isinstance(rows, list):
        identity_evidence_valid = False
        rows = []

    canonical_pairs: list[OfferTodayDetailIdentity] = []
    for pair in serialized_pairs:
        canonical = _canonical_page_identity_pair(pair)
        if canonical is None:
            identity_evidence_valid = False
        else:
            canonical_pairs.append(canonical)

    canonical_rows: list[OfferTodayDetailIdentity] = []
    for row in rows:
        canonical = _canonical_page_row(row)
        if canonical is None:
            identity_evidence_valid = False
        else:
            canonical_rows.append(canonical)

    raw_missing_count = sum(
        isinstance(row, dict) and row.get("observed_encrypted_job_id") is None
        for row in rows
    )
    fallback_count = sum(
        isinstance(row, dict) and row.get("encrypted_job_id_source") == "jobId_fallback"
        for row in rows
    )
    if payload.get("classification") == "success":
        declared_missing_job_id_count = payload.get("missing_job_id_count")
        if not _runtime_smoke_success_row_count_is_valid(payload):
            identity_evidence_valid = False
        if (
            type(declared_missing_job_id_count) is not int
            or declared_missing_job_id_count != 0
        ):
            identity_evidence_valid = False
        declared_missing_count = payload.get("missing_encrypted_job_id_count")
        if (
            type(declared_missing_count) is not int
            or declared_missing_count < 0
            or declared_missing_count != raw_missing_count
        ):
            issues.append("missing_encrypted_job_id_count_mismatch")
            identity_evidence_valid = False
        declared_fallback_count = payload.get("job_id_fallback_count")
        if (
            type(declared_fallback_count) is not int
            or declared_fallback_count < 0
            or declared_fallback_count != fallback_count
        ):
            issues.append("job_id_fallback_count_mismatch")
            identity_evidence_valid = False

        identity_issues = payload.get("identity_issues")
        identity_conflicts = payload.get("identity_conflicts")
        if identity_issues != [] or identity_conflicts != []:
            identity_evidence_valid = False

    authority_index = build_offertoday_identity_authority_index(
        [*prior_committed_rows, *canonical_rows]
    )
    first_seen_job_ids: list[str] = []
    seen_job_ids: set[str] = set()
    for identity in canonical_rows:
        if identity.job_id not in seen_job_ids:
            seen_job_ids.add(identity.job_id)
            first_seen_job_ids.append(identity.job_id)
    authoritative_rows = [
        authority_index.authoritative_identity_by_job[job_id]
        for job_id in first_seen_job_ids
        if job_id in authority_index.authoritative_identity_by_job
        and job_id not in authority_index.conflict_reason_by_job
    ]
    canonical_pair_triples = [
        (
            identity.job_id,
            identity.encrypted_job_id,
            identity.encrypted_job_id_source,
        )
        for identity in canonical_pairs
    ]
    authoritative_row_triples = [
        (
            identity.job_id,
            identity.encrypted_job_id,
            identity.encrypted_job_id_source,
        )
        for identity in authoritative_rows
    ]
    if payload.get("classification") == "success" and (
        not identity_evidence_valid
        or canonical_pair_triples != authoritative_row_triples
        or bool(authority_index.conflict_reason_by_job)
    ):
        issues.append("page_identity_authority_mismatch")
    return (
        authoritative_rows,
        canonical_rows,
        raw_missing_count,
        fallback_count,
    )


def _is_legacy_failed_identity_page(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    identity_issues = payload.get("identity_issues")
    return (
        payload.get("classification") == "identity_issue"
        and payload.get("id_pairs") == []
        and isinstance(identity_issues, list)
        and bool(identity_issues)
        and all(
            isinstance(issue, dict)
            and issue.get("reason") == "missing_encrypted_job_id"
            for issue in identity_issues
        )
    )


def _analyze_runtime_smoke_events(
    events: list[dict[str, Any]],
    issues: list[str],
    *,
    allow_legacy_failed_identity_evidence: bool,
    detail_budget: int,
) -> dict[str, Any]:
    run_started_indexes = [
        index
        for index, event in enumerate(events)
        if event.get("event_type") == "research.run_started"
    ]
    if len(run_started_indexes) != 1:
        issues.append(f"run_started_count:{len(run_started_indexes)}")
    elif run_started_indexes[0] != 0:
        issues.append("run_started_must_be_first")

    page_indexes = [
        index
        for index, event in enumerate(events)
        if event.get("event_type") == "research.page_attempt"
    ]
    page_events = [events[index] for index in page_indexes]
    legacy_failed_identity_evidence = (
        allow_legacy_failed_identity_evidence
        and len(page_events) == 1
        and _is_legacy_failed_identity_page(page_events[0].get("payload"))
    )
    page_payloads = [event.get("payload") for event in page_events]
    observed_pages = [
        (
            payload.get("page")
            if isinstance(payload, dict) and type(payload.get("page")) is int
            else None
        )
        for payload in page_payloads
    ]
    if observed_pages != list(range(1, len(page_events) + 1)):
        issues.append("invalid_runtime_smoke_page_sequence")
    if any(
        not isinstance(payload, dict)
        or type(payload.get("attempt")) is not int
        or payload.get("attempt") != 1
        for payload in page_payloads
    ):
        issues.append("invalid_runtime_smoke_listing_attempt")

    committed_rows: list[OfferTodayDetailIdentity] = []
    first_seen_job_ids: list[str] = []
    seen_job_ids: set[str] = set()
    clean_page_flags: list[bool] = []
    accumulated_authority_counts: list[int] = []
    page_missing_encrypted_job_id_count = 0
    page_job_id_fallback_count = 0
    first_listing_failure: str | None = None
    for page_index, page_payload in enumerate(page_payloads):
        common_control_valid = _runtime_smoke_common_page_control_is_valid(page_payload)
        successful_page = (
            isinstance(page_payload, dict)
            and page_payload.get("classification") == "success"
        )
        scalar_types_valid = _runtime_smoke_page_scalar_types_are_valid(page_payload)
        success_control_values_valid = (
            not successful_page
            or _runtime_smoke_success_control_values_are_valid(page_payload)
        )
        if (
            not common_control_valid
            or not scalar_types_valid
            or not success_control_values_valid
        ):
            issues.append("invalid_runtime_smoke_page_control")
        page_issues: list[str] = []
        current_canonical_rows: list[OfferTodayDetailIdentity] = []
        if isinstance(page_payload, dict) and not legacy_failed_identity_evidence:
            (
                _page_authority,
                current_canonical_rows,
                raw_missing_count,
                fallback_count,
            ) = _canonical_page_authority(
                page_payload,
                committed_rows,
                page_issues,
            )
            page_missing_encrypted_job_id_count += raw_missing_count
            page_job_id_fallback_count += fallback_count
        terminal_semantics_valid = (
            not successful_page
            or _runtime_smoke_terminal_semantics_are_valid(page_payload)
        )
        if not terminal_semantics_valid:
            page_issues.append("invalid_runtime_smoke_page_terminal_signal")
        issues.extend(page_issues)

        expected_page = page_index + 1
        page_sequence_valid = (
            isinstance(page_payload, dict)
            and type(page_payload.get("page")) is int
            and page_payload.get("page") == expected_page
        )
        page_attempt_valid = (
            isinstance(page_payload, dict)
            and type(page_payload.get("attempt")) is int
            and page_payload.get("attempt") == 1
        )
        page_entry_valid = True
        if page_index == 1:
            first_page = page_payloads[0]
            page_entry_valid = (
                isinstance(first_page, dict)
                and clean_page_flags[0]
                and first_page.get("stop_reason") is None
                and _runtime_smoke_success_page_controls_are_valid(first_page)
                and type(first_page.get("row_count")) is int
                and first_page.get("row_count") > 0
                and first_page.get("identity_issues") == []
                and first_page.get("identity_conflicts") == []
                and accumulated_authority_counts[0] < detail_budget
            )
            if not page_entry_valid:
                issues.append("invalid_runtime_smoke_page_two_entry")
        elif page_index >= SMOKE_LISTING_REQUEST_LIMIT:
            page_entry_valid = False
        clean_page = (
            isinstance(page_payload, dict)
            and page_payload.get("classification") == "success"
            and common_control_valid
            and page_sequence_valid
            and page_attempt_valid
            and page_entry_valid
            and not page_issues
            and _runtime_smoke_success_page_controls_are_valid(page_payload)
            and _runtime_smoke_success_row_count_is_valid(page_payload)
            and page_payload.get("stop_reason")
            in (None, "page_cap", "target_cap", _NATURAL_EXHAUSTION_STOP_REASON)
            and page_payload.get("identity_issues") == []
            and page_payload.get("identity_conflicts") == []
            and (
                bool(current_canonical_rows)
                or page_payload.get("stop_reason") == _NATURAL_EXHAUSTION_STOP_REASON
            )
        )
        clean_page_flags.append(clean_page)
        if clean_page:
            committed_rows.extend(current_canonical_rows)
            for identity in current_canonical_rows:
                if identity.job_id not in seen_job_ids:
                    seen_job_ids.add(identity.job_id)
                    first_seen_job_ids.append(identity.job_id)

        accumulated_index = build_offertoday_identity_authority_index(committed_rows)
        accumulated_authority_counts.append(
            sum(
                job_id in accumulated_index.authoritative_identity_by_job
                and job_id not in accumulated_index.conflict_reason_by_job
                for job_id in first_seen_job_ids
            )
        )
        if isinstance(page_payload, dict) and first_listing_failure is None:
            page_stop_reason = page_payload.get("stop_reason")
            classification = page_payload.get("classification")
            if isinstance(page_stop_reason, str) and page_stop_reason not in {
                "",
                "page_cap",
                "target_cap",
            }:
                first_listing_failure = f"listing_{page_stop_reason}"
            elif classification != "success":
                first_listing_failure = f"listing_{classification}"

    final_authority_index = build_offertoday_identity_authority_index(committed_rows)
    authoritative_page_triples: list[
        tuple[str, str, OfferTodayEncryptedJobIdSource]
    ] = []
    for job_id in first_seen_job_ids:
        if (
            job_id not in final_authority_index.authoritative_identity_by_job
            or job_id in final_authority_index.conflict_reason_by_job
        ):
            continue
        identity = final_authority_index.authoritative_identity_by_job[job_id]
        authoritative_page_triples.append(
            (
                identity.job_id,
                identity.encrypted_job_id,
                identity.encrypted_job_id_source,
            )
        )
    detail_events = [
        event
        for event in events
        if event.get("event_type") == "research.detail_attempt"
    ]
    run_stopped_indexes = [
        index
        for index, event in enumerate(events)
        if event.get("event_type") == "research.run_stopped"
    ]
    run_stopped_events = [events[index] for index in run_stopped_indexes]
    cohort_indexes = [
        index
        for index, event in enumerate(events)
        if event.get("event_type") == "research.detail_cohort_frozen"
    ]
    if len(cohort_indexes) > 1:
        issues.append(f"detail_cohort_event_count:{len(cohort_indexes)}")

    frozen_targets: list[tuple[int, str, str, OfferTodayEncryptedJobIdSource]] = []
    frozen_count = 0
    if cohort_indexes:
        cohort_event = events[cohort_indexes[0]]
        cohort_payload = cohort_event.get("payload")
        if not isinstance(cohort_payload, dict):
            issues.append("invalid_detail_cohort_payload")
        else:
            declared_count = cohort_payload.get("count")
            targets = cohort_payload.get("targets")
            if type(declared_count) is not int or declared_count < 0:
                issues.append("invalid_detail_cohort_count")
            else:
                frozen_count = declared_count
            if not isinstance(targets, list):
                issues.append("invalid_detail_cohort_targets")
                targets = []
            if frozen_count != len(targets):
                issues.append("detail_cohort_count_mismatch")
            if frozen_count > detail_budget:
                issues.append("detail_cohort_budget_exceeded")
            for position, target in enumerate(targets, start=1):
                canonical = _canonical_smoke_target(
                    target,
                    expected_position=position,
                    issues=issues,
                    allow_missing_resolution_hash=(legacy_failed_identity_evidence),
                )
                if canonical is not None:
                    frozen_targets.append(canonical)
            if len({target[1] for target in frozen_targets}) != len(frozen_targets):
                issues.append("duplicate_frozen_job_id")
            if len({target[2] for target in frozen_targets}) != len(frozen_targets):
                issues.append("duplicate_frozen_encrypted_job_id")
    elif detail_events:
        issues.append("detail_attempt_without_frozen_cohort")

    expected_frozen_targets = [
        (position, job_id, encrypted_job_id, encrypted_job_id_source)
        for position, (job_id, encrypted_job_id, encrypted_job_id_source) in enumerate(
            authoritative_page_triples[:detail_budget],
            start=1,
        )
    ]
    if frozen_targets != expected_frozen_targets:
        issues.append("detail_cohort_identity_mismatch")

    if cohort_indexes:
        cohort_index = cohort_indexes[0]
        if any(page_index >= cohort_index for page_index in page_indexes):
            issues.append("page_attempt_after_cohort_freeze")
        if any(
            index <= cohort_index
            for index, event in enumerate(events)
            if event.get("event_type") == "research.detail_attempt"
        ):
            issues.append("detail_attempt_before_cohort_freeze")

    request_evidence_indexes = [
        index
        for index, event in enumerate(events)
        if event.get("event_type")
        in {
            "research.page_attempt",
            "research.detail_cohort_frozen",
            "research.detail_attempt",
        }
    ]
    if run_stopped_indexes and any(
        index > run_stopped_indexes[0] for index in request_evidence_indexes
    ):
        issues.append("request_evidence_after_run_stopped")

    success_count = 0
    terminal_count = 0
    failure_count = 0
    first_failure: str | None = None
    first_hard_stop: str | None = None
    batch_stopped = False
    for attempt_index, event in enumerate(detail_events):
        payload = event.get("payload")
        if not isinstance(payload, dict):
            issues.append("invalid_detail_attempt_payload")
            continue
        if batch_stopped:
            issues.append("detail_attempt_after_batch_stop")
        canonical = _canonical_smoke_target(
            payload.get("target"),
            expected_position=attempt_index + 1,
            issues=issues,
            allow_missing_resolution_hash=legacy_failed_identity_evidence,
        )
        if (
            canonical is None
            or attempt_index >= len(frozen_targets)
            or canonical != frozen_targets[attempt_index]
        ):
            issues.append("detail_attempt_target_order_mismatch")

        classification = payload.get("classification")
        stop_batch = payload.get("stop_batch")
        if type(stop_batch) is not bool:
            issues.append("invalid_detail_stop_batch_flag")
            stop_batch = False
        if classification == "success":
            success_count += 1
            if stop_batch:
                issues.append("successful_detail_stopped_batch")
            if not all(
                payload.get(key) is True
                for key in (
                    "identity_valid",
                    "parsed",
                    "has_title",
                    "has_company",
                    "has_description",
                )
            ):
                failure_count += 1
                if first_failure is None:
                    first_failure = "incomplete_success_detail"
        elif classification == "terminal_unavailable":
            terminal_count += 1
            if payload.get("api_code") != 2520:
                issues.append("terminal_unavailable_code_mismatch")
                failure_count += 1
                if first_failure is None:
                    first_failure = "invalid_terminal_unavailable"
            if stop_batch:
                issues.append("terminal_unavailable_stopped_batch")
        elif classification in _DETAIL_FAILURE_KINDS:
            failure_count += 1
            if first_failure is None:
                first_failure = classification
            if classification in _DETAIL_HARD_STOP_KINDS:
                if stop_batch is not True:
                    issues.append("hard_stop_missing_stop_batch")
                if first_hard_stop is None:
                    first_hard_stop = classification
        else:
            failure_count += 1
            issues.append(f"invalid_detail_classification:{classification}")
        if stop_batch:
            batch_stopped = True

    detail_ready_for_attempts = (
        bool(page_payloads)
        and clean_page_flags == [True] * len(page_payloads)
        and isinstance(page_payloads[-1], dict)
        and page_payloads[-1].get("stop_reason") == "target_cap"
        and frozen_count == detail_budget
    )
    if (
        first_failure is None
        and detail_ready_for_attempts
        and len(detail_events) < frozen_count
        and not batch_stopped
    ):
        first_failure = "unattempted_without_batch_stop"

    return {
        "listing_attempt_count": len(page_events),
        "detail_attempt_count": len(detail_events),
        "frozen_count": frozen_count,
        "success_count": success_count,
        "terminal_count": terminal_count,
        "failure_count": failure_count,
        "unattempted_count": max(0, frozen_count - len(detail_events)),
        "first_hard_stop": first_hard_stop,
        "first_failure": first_failure,
        "first_listing_failure": first_listing_failure,
        "page_events": page_events,
        "clean_page_flags": clean_page_flags,
        "page_missing_encrypted_job_id_count": (page_missing_encrypted_job_id_count),
        "page_job_id_fallback_count": page_job_id_fallback_count,
        "legacy_failed_identity_evidence": legacy_failed_identity_evidence,
        "run_stopped_events": run_stopped_events,
    }


def _completed_no_write_evidence_is_valid(summary: dict[str, Any]) -> bool:
    snapshot_start = summary.get("run_start_snapshot_hash")
    snapshot_end = summary.get("run_end_snapshot_hash")
    product_start = summary.get("run_start_product_data_hash")
    product_end = summary.get("run_end_product_data_hash")
    inventory_start = summary.get("run_start_inventory_hash")
    inventory_end = summary.get("run_end_inventory_hash")
    return (
        summary.get("product_data_unchanged") is True
        and isinstance(snapshot_start, str)
        and _SHA256_RE.fullmatch(snapshot_start) is not None
        and snapshot_start == snapshot_end
        and isinstance(product_start, str)
        and _SHA256_RE.fullmatch(product_start) is not None
        and product_start == product_end
        and isinstance(inventory_start, str)
        and _SHA256_RE.fullmatch(inventory_start) is not None
        and inventory_start == inventory_end
    )


def _request_budget_matches(value: Any, expected: dict[str, int]) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == set(expected)
        and all(
            type(value.get(key)) is int and value.get(key) == expected_value
            for key, expected_value in expected.items()
        )
    )


def _request_budget_limit(
    request_budget: dict[str, int],
    key: str,
    *,
    fallback: int,
) -> int:
    value = request_budget.get(key)
    return value if type(value) is int and value >= 0 else fallback


def _calibration_condition_payload(condition: Any) -> dict[str, Any]:
    return {
        "search_family": condition.search_family,
        "category_id": condition.category_id,
        "keyword": condition.keyword,
        "endpoint": condition.endpoint,
        "rcd_type": condition.rcd_type,
    }


def _verify_calibration_research_run(
    artifact_dir: Path,
) -> LiveRunVerification:
    verification = verify_research_artifact(artifact_dir)
    if not verification.valid:
        artifact_issues = [
            *(f"missing_artifact_file:{name}" for name in verification.missing_files),
            *(
                f"mismatched_artifact_file:{name}"
                for name in verification.mismatched_files
            ),
        ]
        return LiveRunVerification(
            valid=False,
            issues=tuple(artifact_issues or ["invalid_research_artifact"]),
            experiment=None,
            run_id=None,
        )

    try:
        manifest = json.loads(
            (artifact_dir / "manifest.json").read_text(encoding="utf-8")
        )
        events = [
            json.loads(line)
            for line in (artifact_dir / "observations.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return LiveRunVerification(
            valid=False,
            issues=(f"invalid_live_run_json:{type(exc).__name__}",),
            experiment="listing-calibration",
            run_id=None,
        )

    metadata = manifest.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    run_id_value = manifest.get("run_id")
    run_id = run_id_value if isinstance(run_id_value, str) else None
    issues: list[str] = []
    if metadata.get("experiment") != "listing-calibration":
        issues.append("unsupported_live_experiment")
    if metadata.get("crawl_job_id") != run_id:
        issues.append("crawl_job_id_run_id_mismatch")
    for field_name in ("parent_artifact_hash", "baseline_artifact_hash"):
        if _SHA256_RE.fullmatch(str(metadata.get(field_name) or "")) is None:
            issues.append(f"invalid_{field_name}")
    if not _request_budget_matches(
        metadata.get("request_budget"),
        _CALIBRATION_REQUEST_BUDGET,
    ):
        issues.append("invalid_calibration_request_budget")

    normalized_events = [event for event in events if isinstance(event, dict)]
    if len(normalized_events) != len(events):
        issues.append("non_object_research_event")
    if [event.get("sequence_no") for event in normalized_events] != list(
        range(1, len(normalized_events) + 1)
    ):
        issues.append("non_contiguous_event_sequence")

    run_started = [
        event
        for event in normalized_events
        if event.get("event_type") == "research.run_started"
    ]
    if len(run_started) != 1:
        issues.append(f"run_started_count:{len(run_started)}")
    elif normalized_events.index(run_started[0]) != 0:
        issues.append("run_started_must_be_first")
    else:
        payload = run_started[0].get("payload")
        if not isinstance(payload, dict):
            issues.append("invalid_run_started_payload")
        else:
            if payload.get("experiment") != "listing-calibration":
                issues.append("invalid_calibration_run_started_experiment")
            if payload.get("session_mode") != "fresh-headless":
                issues.append("invalid_calibration_session_mode")
            if payload.get("condition_count") != 8:
                issues.append("invalid_calibration_condition_budget")
            if payload.get("parent_artifact_hash") != metadata.get(
                "parent_artifact_hash"
            ):
                issues.append("calibration_parent_hash_mismatch")
            if payload.get("baseline_artifact_hash") != metadata.get(
                "baseline_artifact_hash"
            ):
                issues.append("calibration_baseline_hash_mismatch")
            if not _request_budget_matches(
                payload.get("request_budget"),
                _CALIBRATION_REQUEST_BUDGET,
            ):
                issues.append("invalid_calibration_request_budget")

    summary_events = [
        event
        for event in normalized_events
        if event.get("event_type") == "research.run_summary"
    ]
    if len(summary_events) != 1:
        issues.append(f"terminal_summary_count:{len(summary_events)}")
        summary = None
    else:
        if normalized_events.index(summary_events[0]) != len(normalized_events) - 1:
            issues.append("event_after_terminal_summary")
        summary_value = summary_events[0].get("payload")
        summary = summary_value if isinstance(summary_value, dict) else None
        if summary is None:
            issues.append("invalid_terminal_summary_payload")

    locked_conditions = build_calibration_conditions()
    locked_by_id = {
        condition.condition_id: condition for condition in locked_conditions
    }
    page_events = [
        event
        for event in normalized_events
        if event.get("event_type") == "research.page_attempt"
    ]
    if len(page_events) > _CALIBRATION_REQUEST_BUDGET["listing_attempt_max"]:
        issues.append("calibration_attempt_budget_exceeded")
    logical_keys: set[tuple[str, int]] = set()
    attempts_by_page: dict[tuple[str, int], list[int]] = {}
    for event in page_events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            issues.append("invalid_calibration_page_payload")
            continue
        condition_id = payload.get("condition_id")
        page = payload.get("page")
        attempt = payload.get("attempt")
        condition = locked_by_id.get(condition_id)
        if condition is None or any(
            type(payload.get(key)) is not type(expected) or payload.get(key) != expected
            for key, expected in _calibration_condition_payload(condition).items()
        ):
            issues.append("invalid_calibration_page_condition")
            continue
        if type(page) is not int or not 1 <= page <= 3:
            issues.append("invalid_calibration_page_number")
            continue
        if type(attempt) is not int or not 1 <= attempt <= 3:
            issues.append("invalid_calibration_attempt_number")
            continue
        key = (condition_id, page)
        logical_keys.add(key)
        attempts_by_page.setdefault(key, []).append(attempt)
        if payload.get("session_mode") != "fresh-headless":
            issues.append("invalid_calibration_session_mode")
    for attempts in attempts_by_page.values():
        if attempts != list(range(1, len(attempts) + 1)):
            issues.append("invalid_calibration_attempt_sequence")
    if len(logical_keys) > _CALIBRATION_REQUEST_BUDGET["listing_logical"]:
        issues.append("calibration_logical_budget_exceeded")

    condition_events = [
        event
        for event in normalized_events
        if event.get("event_type")
        in {"research.condition_completed", "research.condition_incomplete"}
    ]
    observed_conditions: list[dict[str, Any] | None] = []
    completed_condition_semantics_valid = True
    condition_logical_total = 0
    for event in condition_events:
        payload = event.get("payload")
        condition_payload = (
            payload.get("condition") if isinstance(payload, dict) else None
        )
        observed_conditions.append(
            condition_payload if isinstance(condition_payload, dict) else None
        )
        pages_observed = (
            payload.get("pages_observed") if isinstance(payload, dict) else None
        )
        if type(pages_observed) is int:
            condition_logical_total += pages_observed
        natural_exhaustion = (
            isinstance(payload, dict)
            and payload.get("stop_reason") == "natural_exhaustion"
            and payload.get("is_complete") is True
            and event.get("event_type") == "research.condition_completed"
            and type(pages_observed) is int
            and 1 <= pages_observed <= 3
        )
        page_cap = (
            isinstance(payload, dict)
            and payload.get("stop_reason") == "page_cap"
            and payload.get("is_complete") is False
            and event.get("event_type") == "research.condition_incomplete"
            and pages_observed == 3
            and type(pages_observed) is int
        )
        if not natural_exhaustion and not page_cap:
            completed_condition_semantics_valid = False
    expected_prefix = [
        _calibration_condition_payload(condition)
        for condition in locked_conditions[: len(observed_conditions)]
    ]
    if observed_conditions != expected_prefix:
        issues.append("invalid_calibration_condition_sequence")
    if len(condition_events) > len(locked_conditions):
        issues.append("calibration_condition_budget_exceeded")

    detail_attempt_count = sum(
        event.get("event_type") == "research.detail_attempt"
        for event in normalized_events
    )
    if detail_attempt_count:
        issues.append("calibration_detail_request_observed")
    selection_events = [
        event
        for event in normalized_events
        if event.get("event_type") == "research.calibration_selection"
    ]
    stopped_events = [
        event
        for event in normalized_events
        if event.get("event_type") == "research.run_stopped"
    ]

    manifest_status = metadata.get("crawl_job_status")
    manifest_passed = metadata.get("calibration_passed")
    if type(manifest_passed) is not bool:
        issues.append("invalid_manifest_calibration_passed")
    if summary is not None:
        if summary.get("status") != manifest_status:
            issues.append("crawl_job_status_summary_mismatch")
        if summary.get("calibration_passed") is not manifest_passed:
            issues.append("calibration_passed_summary_mismatch")
        if not _request_budget_matches(
            summary.get("request_budget"),
            _CALIBRATION_REQUEST_BUDGET,
        ):
            issues.append("invalid_calibration_request_budget")
        expected_counts = {
            "condition_count": len(condition_events),
            "listing_logical_count": len(logical_keys),
            "listing_attempt_count": len(page_events),
            "detail_attempt_count": detail_attempt_count,
        }
        for field_name, expected_value in expected_counts.items():
            if summary.get(field_name) != expected_value:
                issues.append(f"{field_name}_mismatch")
        if len(selection_events) == 1:
            selection_payload = selection_events[0].get("payload")
            if not isinstance(selection_payload, dict):
                issues.append("invalid_calibration_selection_payload")
            elif summary.get("variant_summaries") != selection_payload.get(
                "variant_summaries"
            ) or summary.get("selection") != selection_payload.get("selection"):
                issues.append("calibration_selection_summary_mismatch")

        if manifest_status == "completed" or manifest_passed is True:
            selection = summary.get("selection")
            selected = (
                selection.get("selected_variants")
                if isinstance(selection, dict)
                else None
            )
            if not (
                manifest_status == "completed"
                and manifest_passed is True
                and summary.get("calibration_passed") is True
                and summary.get("stop_reason") is None
                and len(page_events) <= 72
                and 8 <= len(logical_keys) <= 24
                and len(logical_keys) == condition_logical_total
                and len(condition_events) == 8
                and completed_condition_semantics_valid
                and summary.get("accepted_condition_count") == 8
                and len(selection_events) == 1
                and isinstance(summary.get("variant_summaries"), list)
                and len(summary["variant_summaries"]) == 4
                and isinstance(selected, list)
                and 1 <= len(selected) <= 2
                and all(
                    isinstance(item, dict) and item.get("accepted") is True
                    for item in selected
                )
                and not stopped_events
                and _completed_no_write_evidence_is_valid(summary)
            ):
                issues.append("completed_calibration_status_mismatch")
        elif manifest_status != "failed" or manifest_passed is not False:
            issues.append("invalid_failed_calibration_status")
        else:
            if len(stopped_events) != 1:
                issues.append(f"run_stopped_count:{len(stopped_events)}")
            else:
                stopped_payload = stopped_events[0].get("payload")
                stopped_reason = (
                    stopped_payload.get("reason")
                    if isinstance(stopped_payload, dict)
                    else None
                )
                if (
                    not isinstance(stopped_reason, str)
                    or not stopped_reason.strip()
                    or summary.get("stop_reason") != stopped_reason
                ):
                    issues.append("run_stopped_summary_reason_mismatch")
                if (
                    str(stopped_reason or "").startswith(
                        "unexpected_listing_calibration_error:"
                    )
                    and _UNEXPECTED_CALIBRATION_ERROR_RE.fullmatch(stopped_reason)
                    is None
                ):
                    issues.append("invalid_unexpected_failure_reason")

    return LiveRunVerification(
        valid=not issues,
        issues=tuple(issues),
        experiment="listing-calibration",
        run_id=run_id,
    )


def verify_live_research_run(artifact_dir: Path) -> LiveRunVerification:
    artifact_dir = Path(artifact_dir)
    verification = verify_research_artifact(artifact_dir)
    if not verification.valid:
        artifact_issues = [
            *(f"missing_artifact_file:{name}" for name in verification.missing_files),
            *(
                f"mismatched_artifact_file:{name}"
                for name in verification.mismatched_files
            ),
        ]
        if not artifact_issues:
            artifact_issues.append("invalid_research_artifact")
        return LiveRunVerification(
            valid=False,
            issues=tuple(artifact_issues),
            experiment=None,
            run_id=None,
        )

    try:
        manifest = json.loads(
            (artifact_dir / "manifest.json").read_text(encoding="utf-8")
        )
        events = [
            json.loads(line)
            for line in (artifact_dir / "observations.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return LiveRunVerification(
            valid=False,
            issues=(f"invalid_live_run_json:{type(exc).__name__}",),
            experiment=None,
            run_id=None,
        )

    metadata = manifest.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    experiment_value = metadata.get("experiment")
    experiment = experiment_value if isinstance(experiment_value, str) else None
    run_id_value = manifest.get("run_id")
    run_id = run_id_value if isinstance(run_id_value, str) else None
    if experiment == "listing-calibration":
        return _verify_calibration_research_run(artifact_dir)
    issues: list[str] = []

    if experiment != "runtime-smoke":
        issues.append("unsupported_live_experiment")
    if metadata.get("crawl_job_id") != run_id:
        issues.append("crawl_job_id_run_id_mismatch")
    if _SHA256_RE.fullmatch(str(metadata.get("parent_artifact_hash") or "")) is None:
        issues.append("invalid_parent_artifact_hash")

    manifest_status = metadata.get("crawl_job_status")
    manifest_smoke_passed = metadata.get("smoke_passed")
    request_budget = metadata.get("request_budget")
    current_request_budget = runtime_smoke_request_budget()
    current_budget_matches = _request_budget_matches(
        request_budget,
        current_request_budget,
    )
    legacy_budget_allowed = (
        _request_budget_matches(
            request_budget,
            _LEGACY_RUNTIME_SMOKE_REQUEST_BUDGET,
        )
        and manifest_status == "failed"
        and manifest_smoke_passed is False
    )
    if not current_budget_matches and not legacy_budget_allowed:
        issues.append("invalid_runtime_smoke_request_budget")
    effective_request_budget = (
        dict(_LEGACY_RUNTIME_SMOKE_REQUEST_BUDGET)
        if legacy_budget_allowed
        else dict(current_request_budget)
    )
    listing_budget = _request_budget_limit(
        effective_request_budget,
        "listing",
        fallback=SMOKE_LISTING_REQUEST_LIMIT,
    )
    detail_budget = _request_budget_limit(
        effective_request_budget,
        "detail",
        fallback=_LEGACY_RUNTIME_SMOKE_REQUEST_BUDGET["detail"],
    )

    normalized_events = [event for event in events if isinstance(event, dict)]
    if len(normalized_events) != len(events):
        issues.append("non_object_research_event")
    sequence_numbers = [event.get("sequence_no") for event in normalized_events]
    if sequence_numbers != list(range(1, len(normalized_events) + 1)):
        issues.append("non_contiguous_event_sequence")

    summary_indexes = [
        index
        for index, event in enumerate(normalized_events)
        if event.get("event_type") == "research.run_summary"
    ]
    if len(summary_indexes) != 1:
        issues.append(f"terminal_summary_count:{len(summary_indexes)}")
    if summary_indexes and summary_indexes[-1] != len(normalized_events) - 1:
        issues.append("event_after_terminal_summary")

    run_started_events = [
        event
        for event in normalized_events
        if event.get("event_type") == "research.run_started"
    ]
    if len(run_started_events) == 1:
        run_started_payload = run_started_events[0].get("payload")
        run_started_budget = (
            run_started_payload.get("request_budget")
            if isinstance(run_started_payload, dict)
            else None
        )
        if not _request_budget_matches(
            run_started_budget,
            effective_request_budget,
        ):
            issues.append("invalid_runtime_smoke_request_budget")
    smoke_evidence = _analyze_runtime_smoke_events(
        normalized_events,
        issues,
        allow_legacy_failed_identity_evidence=legacy_budget_allowed,
        detail_budget=detail_budget,
    )
    listing_attempt_count = smoke_evidence["listing_attempt_count"]
    detail_attempt_count = smoke_evidence["detail_attempt_count"]
    if listing_attempt_count > listing_budget:
        issues.append(
            f"listing_request_budget_exceeded:{listing_attempt_count}>{listing_budget}"
        )
    if detail_attempt_count > detail_budget:
        issues.append(
            f"detail_request_budget_exceeded:{detail_attempt_count}>{detail_budget}"
        )

    summary: dict[str, Any] | None = None
    if len(summary_indexes) == 1:
        payload = normalized_events[summary_indexes[0]].get("payload")
        if isinstance(payload, dict) and payload:
            summary = payload
        else:
            issues.append("invalid_terminal_summary_payload")

    if summary is not None:
        summary_budget_is_legacy_omission = (
            legacy_budget_allowed and "request_budget" not in summary
        )
        if not summary_budget_is_legacy_omission and not _request_budget_matches(
            summary.get("request_budget"),
            effective_request_budget,
        ):
            issues.append("invalid_runtime_smoke_request_budget")
        if summary.get("listing_attempt_count") != listing_attempt_count:
            issues.append("listing_attempt_count_mismatch")
        if summary.get("attempted_count") != detail_attempt_count:
            issues.append("detail_attempt_count_mismatch")
        for field_name in (
            "frozen_count",
            "success_count",
            "terminal_count",
            "unattempted_count",
        ):
            if summary.get(field_name) != smoke_evidence[field_name]:
                issues.append(f"{field_name}_mismatch")
        if not smoke_evidence["legacy_failed_identity_evidence"]:
            summary_missing_count = summary.get("missing_encrypted_job_id_count")
            if (
                type(summary_missing_count) is not int
                or summary_missing_count < 0
                or summary_missing_count
                != smoke_evidence["page_missing_encrypted_job_id_count"]
            ):
                issues.append("missing_encrypted_job_id_count_mismatch")
            summary_fallback_count = summary.get("job_id_fallback_count")
            if (
                type(summary_fallback_count) is not int
                or summary_fallback_count < 0
                or summary_fallback_count
                != smoke_evidence["page_job_id_fallback_count"]
            ):
                issues.append("job_id_fallback_count_mismatch")
        if summary.get("status") != manifest_status:
            issues.append("crawl_job_status_summary_mismatch")
        summary_smoke_passed = summary.get("smoke_passed")
        if type(manifest_smoke_passed) is not bool:
            issues.append("invalid_manifest_smoke_passed")
        if summary_smoke_passed is not manifest_smoke_passed:
            issues.append("smoke_passed_summary_mismatch")

        completed_smoke = (
            manifest_status == "completed" or manifest_smoke_passed is True
        )
        run_stopped_events = smoke_evidence["run_stopped_events"]
        if completed_smoke:
            if run_stopped_events:
                issues.append("completed_smoke_has_run_stopped")
            page_events = smoke_evidence["page_events"]
            page_payloads = [event.get("payload") for event in page_events]
            completed_pages_valid = (
                1 <= len(page_payloads) <= SMOKE_LISTING_REQUEST_LIMIT
                and all(isinstance(payload, dict) for payload in page_payloads)
                and all(
                    _runtime_smoke_success_page_controls_are_valid(payload)
                    for payload in page_payloads
                    if isinstance(payload, dict)
                )
                and all(
                    payload.get("page") == position
                    and type(payload.get("page")) is int
                    and payload.get("attempt") == 1
                    and type(payload.get("attempt")) is int
                    and payload.get("classification") == "success"
                    and _runtime_smoke_success_row_count_is_valid(payload)
                    and payload.get("row_count") > 0
                    and payload.get("identity_issues") == []
                    and payload.get("identity_conflicts") == []
                    for position, payload in enumerate(page_payloads, start=1)
                    if isinstance(payload, dict)
                )
                and all(
                    payload.get("stop_reason") is None
                    for payload in page_payloads[:-1]
                    if isinstance(payload, dict)
                )
                and isinstance(page_payloads[-1], dict)
                and page_payloads[-1].get("stop_reason") == "target_cap"
                and smoke_evidence["clean_page_flags"] == [True] * len(page_payloads)
            )
            if not (
                manifest_status == "completed"
                and manifest_smoke_passed is True
                and summary_smoke_passed is True
                and current_budget_matches
                and summary.get("listing_complete") is False
                and summary.get("expected_truncation") is True
                and listing_attempt_count in (1, 2)
                and detail_attempt_count == detail_budget
                and smoke_evidence["frozen_count"] == detail_budget
                and smoke_evidence["failure_count"] == 0
                and completed_pages_valid
                and summary.get("listing_stop_reason") == "target_cap"
                and summary.get("stop_reason") is None
                and _completed_no_write_evidence_is_valid(summary)
            ):
                issues.append("completed_smoke_status_mismatch")
        elif manifest_status != "failed":
            issues.append("invalid_failed_smoke_status")
        else:
            terminal_unexpected = False
            if len(run_stopped_events) != 1:
                issues.append(f"run_stopped_count:{len(run_stopped_events)}")
            else:
                stopped_payload = run_stopped_events[0].get("payload")
                stopped_reason = (
                    stopped_payload.get("reason")
                    if isinstance(stopped_payload, dict)
                    else None
                )
                if (
                    not isinstance(stopped_reason, str)
                    or not stopped_reason.strip()
                    or summary.get("stop_reason") != stopped_reason
                ):
                    issues.append("run_stopped_summary_reason_mismatch")
                if (
                    str(stopped_reason or "").startswith("unexpected_live_smoke_error:")
                    and _UNEXPECTED_ERROR_RE.fullmatch(stopped_reason) is None
                ):
                    issues.append("invalid_unexpected_failure_reason")
                terminal_unexpected = (
                    isinstance(stopped_reason, str)
                    and _UNEXPECTED_ERROR_RE.fullmatch(stopped_reason) is not None
                )
            failed_page_payloads = [
                event.get("payload") for event in smoke_evidence["page_events"]
            ]
            clean_natural_exhaustion_observed = (
                bool(failed_page_payloads)
                and smoke_evidence["clean_page_flags"]
                == [True] * len(failed_page_payloads)
                and isinstance(failed_page_payloads[-1], dict)
                and failed_page_payloads[-1].get("stop_reason")
                == _NATURAL_EXHAUSTION_STOP_REASON
            )
            if (
                not terminal_unexpected
                and clean_natural_exhaustion_observed
                and not (
                    smoke_evidence["frozen_count"] < detail_budget
                    and detail_attempt_count == 0
                    and summary.get("stop_reason") == "listing_natural_exhaustion"
                    and summary.get("listing_stop_reason")
                    == _NATURAL_EXHAUSTION_STOP_REASON
                    and summary.get("listing_complete") is True
                    and summary.get("expected_truncation") is False
                )
            ):
                issues.append("failed_smoke_status_mismatch")
            clean_page_cap_observed = (
                bool(failed_page_payloads)
                and smoke_evidence["clean_page_flags"]
                == [True] * len(failed_page_payloads)
                and isinstance(failed_page_payloads[-1], dict)
                and failed_page_payloads[-1].get("stop_reason") == "page_cap"
            )
            if (
                not terminal_unexpected
                and clean_page_cap_observed
                and not (
                    listing_attempt_count == listing_budget
                    and smoke_evidence["frozen_count"] < detail_budget
                    and detail_attempt_count == 0
                    and summary.get("stop_reason")
                    == "insufficient_valid_detail_targets"
                    and summary.get("listing_stop_reason") == "page_cap"
                    and summary.get("listing_complete") is False
                    and summary.get("expected_truncation") is True
                )
            ):
                issues.append("failed_smoke_status_mismatch")
            clean_target_cap_observed = (
                bool(failed_page_payloads)
                and smoke_evidence["clean_page_flags"]
                == [True] * len(failed_page_payloads)
                and isinstance(failed_page_payloads[-1], dict)
                and failed_page_payloads[-1].get("stop_reason") == "target_cap"
            )
            if (
                not terminal_unexpected
                and clean_target_cap_observed
                and not (
                    smoke_evidence["frozen_count"] == detail_budget
                    and summary.get("listing_stop_reason") == "target_cap"
                    and summary.get("listing_complete") is False
                    and summary.get("expected_truncation") is True
                )
            ):
                issues.append("failed_smoke_status_mismatch")
            first_failure = smoke_evidence["first_failure"]
            if (
                not terminal_unexpected
                and first_failure is not None
                and summary.get("stop_reason") != first_failure
            ):
                issues.append("detail_failure_reason_mismatch")
            first_listing_failure = smoke_evidence["first_listing_failure"]
            if (
                not terminal_unexpected
                and first_listing_failure is not None
                and summary.get("stop_reason") != first_listing_failure
            ):
                issues.append("listing_failure_reason_mismatch")
        hard_stop = smoke_evidence["first_hard_stop"]
        if (
            hard_stop is not None
            and not (
                isinstance(summary.get("stop_reason"), str)
                and _UNEXPECTED_ERROR_RE.fullmatch(summary["stop_reason"]) is not None
            )
            and summary.get("stop_reason") != hard_stop
        ):
            issues.append("hard_stop_reason_mismatch")

    return LiveRunVerification(
        valid=not issues,
        issues=tuple(issues),
        experiment=experiment,
        run_id=run_id,
    )
