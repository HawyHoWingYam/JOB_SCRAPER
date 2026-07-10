from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.sources.offertoday.research.contracts import (
    PublishedJobSnapshot,
    StagedListingSnapshot,
)


DETAIL_OUTCOME_BY_STATUS = {
    "terminal_unavailable": "terminal_unavailable",
    "identity_conflict": "manual_action_required",
    "manual_action_required": "manual_action_required",
    "failed": "retryable_failed",
    "pending": "pending",
    "running": "running",
}

_DETAIL_OUTCOMES = (
    "completed",
    "terminal_unavailable",
    "retryable_failed",
    "manual_action_required",
    "pending",
    "running",
)

_REPLAYABLE_PAGE_CLASSIFICATIONS = {
    "success",
    "contract_anomaly",
    "identity_issue",
    "identity_conflict",
}

_PAGE_EVENT_TYPES = {
    "research.page_attempt",
    "crawl.listing_page_attempt",
}

_INCOMPLETE_CONDITION_EVENT_TYPES = {
    "research.condition_incomplete",
    "crawl.listing_condition_incomplete",
}

_COMPLETED_CONDITION_EVENT_TYPES = {
    "research.condition_completed",
    "crawl.listing_condition_completed",
}

_TERMINAL_CRAWL_STATUSES = {
    "completed",
    "failed",
    "manual_action_required",
}


@dataclass(frozen=True, slots=True)
class ConservationEquation:
    left_name: str
    left_value: int
    right_parts: dict[str, int]

    @property
    def difference(self) -> int:
        return self.left_value - sum(self.right_parts.values())


@dataclass(frozen=True, slots=True)
class ListingConservationReport:
    raw_rows: ConservationEquation
    distinct_ids: ConservationEquation
    partition_overlap_ids: tuple[str, ...]
    unexplained_ids: tuple[str, ...]
    unresolved_gaps: int
    newly_created_staging_rows: int
    newly_staged_distinct_ids: int
    staging_amplification: float | None
    staging_amplification_violation: bool
    identity_pair_mismatch_page_keys: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return (
            self.raw_rows.difference == 0
            and self.distinct_ids.difference == 0
            and not self.partition_overlap_ids
            and not self.unexplained_ids
            and self.unresolved_gaps == 0
            and not self.staging_amplification_violation
            and not self.identity_pair_mismatch_page_keys
        )


@dataclass(frozen=True, slots=True)
class DetailConservationReport:
    distinct_eligible: int
    outcomes: dict[str, int]
    difference: int
    status_job_mismatches: tuple[str, ...]
    missing_eligible_ids: tuple[str, ...]
    unclassified_statuses: tuple[str, ...]
    run_is_terminal: bool
    persisted_evidence_mismatch_ids: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return (
            self.difference == 0
            and not self.status_job_mismatches
            and not self.missing_eligible_ids
            and not self.unclassified_statuses
            and not self.persisted_evidence_mismatch_ids
            and (
                not self.run_is_terminal
                or self.outcomes.get("running", 0) == 0
            )
        )


@dataclass(frozen=True, slots=True)
class ResearchConservationReport:
    listing: ListingConservationReport | None
    detail: DetailConservationReport | None
    reconciled_source_job_ids: tuple[str, ...] = ()
    reconciled_fetch_overlap_ids: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        reports = [report for report in (self.listing, self.detail) if report]
        return (
            bool(reports)
            and all(report.is_valid for report in reports)
            and not self.reconciled_fetch_overlap_ids
        )


def _require_nonnegative_int(value: Any, *, evidence_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{evidence_name} must be a nonnegative integer")
    return value


def build_listing_conservation_report(
    *,
    raw_listing_rows: int,
    rows_missing_job_id: int,
    rows_containing_job_id: int,
    valid_distinct_job_ids: set[str],
    already_published_ids: set[str],
    preexisting_staged_unpublished_ids: set[str],
    newly_staged_ids: set[str],
    deferred_identity_conflict_ids: set[str],
    newly_created_staging_rows: int,
    unresolved_gaps: int,
    identity_pair_mismatch_page_keys: Iterable[str] = (),
) -> ListingConservationReport:
    raw_listing_rows = _require_nonnegative_int(
        raw_listing_rows,
        evidence_name="raw_listing_rows",
    )
    rows_missing_job_id = _require_nonnegative_int(
        rows_missing_job_id,
        evidence_name="rows_missing_job_id",
    )
    rows_containing_job_id = _require_nonnegative_int(
        rows_containing_job_id,
        evidence_name="rows_containing_job_id",
    )
    newly_created_staging_rows = _require_nonnegative_int(
        newly_created_staging_rows,
        evidence_name="newly_created_staging_rows",
    )
    unresolved_gaps = _require_nonnegative_int(
        unresolved_gaps,
        evidence_name="unresolved_gaps",
    )
    valid_ids = set(valid_distinct_job_ids)
    partitions = {
        "already_published": set(already_published_ids),
        "preexisting_staged_unpublished": set(
            preexisting_staged_unpublished_ids
        ),
        "newly_staged": set(newly_staged_ids),
        "deferred_identity_conflict": set(
            deferred_identity_conflict_ids
        ),
    }
    memberships = Counter(
        source_job_id
        for partition_ids in partitions.values()
        for source_job_id in partition_ids
    )
    overlap_ids = tuple(
        sorted(
            source_job_id
            for source_job_id, count in memberships.items()
            if count > 1
        )
    )
    partition_union: set[str] = set().union(*partitions.values())
    unexplained_ids = tuple(sorted(valid_ids.symmetric_difference(partition_union)))
    distinct_parts = {
        name: len(partition_ids)
        for name, partition_ids in partitions.items()
    }
    newly_staged_count = len(partitions["newly_staged"])
    staging_amplification = (
        newly_created_staging_rows / newly_staged_count
        if newly_staged_count
        else None
    )
    staging_amplification_violation = (
        newly_created_staging_rows > 0
        if newly_staged_count == 0
        else newly_created_staging_rows * 100 > newly_staged_count * 101
    )
    return ListingConservationReport(
        raw_rows=ConservationEquation(
            left_name="raw_listing_rows",
            left_value=raw_listing_rows,
            right_parts={
                "rows_missing_job_id": rows_missing_job_id,
                "rows_containing_job_id": rows_containing_job_id,
            },
        ),
        distinct_ids=ConservationEquation(
            left_name="valid_distinct_discovered_job_ids",
            left_value=len(valid_ids),
            right_parts=distinct_parts,
        ),
        partition_overlap_ids=overlap_ids,
        unexplained_ids=unexplained_ids,
        unresolved_gaps=unresolved_gaps,
        newly_created_staging_rows=newly_created_staging_rows,
        newly_staged_distinct_ids=newly_staged_count,
        staging_amplification=staging_amplification,
        staging_amplification_violation=staging_amplification_violation,
        identity_pair_mismatch_page_keys=tuple(
            sorted(set(identity_pair_mismatch_page_keys))
        ),
    )


def _canonical_id_set(values: Iterable[Any]) -> set[str]:
    canonical_ids: set[str] = set()
    for value in values:
        if value is None:
            continue
        canonical_id = str(value).strip()
        if canonical_id:
            canonical_ids.add(canonical_id)
    return canonical_ids


def _authoritative_row_key(
    row: StagedListingSnapshot,
) -> tuple[int, str, str, str]:
    return (
        int(row.detail_attempts or 0),
        str(row.detail_started_at or ""),
        str(row.updated_at or ""),
        str(row.row_id),
    )


def build_detail_conservation_report(
    *,
    detail_crawl_job_id: str,
    fetch_cohort_source_job_ids: set[str],
    persisted_source_job_ids: set[str],
    listings: Sequence[StagedListingSnapshot],
    jobs: Sequence[PublishedJobSnapshot],
    run_is_terminal: bool = True,
    persisted_evidence_mismatch_ids: set[str] | None = None,
) -> DetailConservationReport:
    detail_run_id = str(detail_crawl_job_id)
    eligible_ids = _canonical_id_set(fetch_cohort_source_job_ids)
    persisted_ids = _canonical_id_set(persisted_source_job_ids)
    outcomes = {outcome: 0 for outcome in _DETAIL_OUTCOMES}
    rows_by_source_job_id: dict[str, list[StagedListingSnapshot]] = {}
    for row in listings:
        source_job_id = str(row.source_job_id).strip()
        if source_job_id in eligible_ids:
            rows_by_source_job_id.setdefault(source_job_id, []).append(row)

    jobs_by_id = {str(job.job_id): job for job in jobs}
    complete_job_source_ids = {
        str(job.source_job_id)
        for job in jobs
        if job.source_job_id and job.is_complete
    }
    missing_ids: list[str] = []
    mismatch_ids: list[str] = []
    unclassified_statuses: list[str] = []

    for source_job_id in sorted(eligible_ids):
        rows = rows_by_source_job_id.get(source_job_id, [])
        if not rows:
            missing_ids.append(source_job_id)
            continue

        current_rows = [
            row
            for row in rows
            if str(row.last_detail_crawl_job_id or "") == detail_run_id
        ]
        completed_row = next(
            (
                row
                for row in current_rows
                if row.detail_status == "completed"
                and source_job_id in persisted_ids
                and row.has_detail_payload
                and row.published_job_id is not None
                and str(row.published_job_id) in jobs_by_id
                and jobs_by_id[str(row.published_job_id)].is_complete
                and str(
                    jobs_by_id[str(row.published_job_id)].source_job_id
                )
                == source_job_id
            ),
            None,
        )
        if completed_row is not None:
            outcomes["completed"] += 1
            continue

        has_completed_status = any(
            str(row.detail_status).strip().lower() == "completed"
            for row in rows
        )
        if source_job_id in complete_job_source_ids or has_completed_status:
            mismatch_ids.append(source_job_id)

        if not current_rows:
            outcomes["pending"] += 1
            continue

        authoritative = max(current_rows, key=_authoritative_row_key)
        status = str(authoritative.detail_status).strip().lower()
        if status == "completed":
            outcomes["retryable_failed"] += 1
            continue
        outcome = DETAIL_OUTCOME_BY_STATUS.get(status)
        if outcome is None:
            unclassified_statuses.append(status)
            continue
        outcomes[outcome] += 1

    difference = len(eligible_ids) - sum(outcomes.values())
    return DetailConservationReport(
        distinct_eligible=len(eligible_ids),
        outcomes=outcomes,
        difference=difference,
        status_job_mismatches=tuple(sorted(set(mismatch_ids))),
        missing_eligible_ids=tuple(sorted(missing_ids)),
        unclassified_statuses=tuple(sorted(set(unclassified_statuses))),
        run_is_terminal=run_is_terminal,
        persisted_evidence_mismatch_ids=tuple(
            sorted(_canonical_id_set(persisted_evidence_mismatch_ids or set()))
        ),
    )


def _object_value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _payload_nonnegative_int(
    payload: Mapping[str, Any],
    field_name: str,
    *,
    default: int,
) -> int:
    if field_name not in payload:
        return default
    return _require_nonnegative_int(
        payload[field_name],
        evidence_name=field_name,
    )


def _normalize_events(events: Sequence[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for input_order, event in enumerate(events):
        normalized.append(
            {
                "sequence_no": _as_int(
                    _object_value(event, "sequence_no", input_order),
                    input_order,
                ),
                "input_order": input_order,
                "event_type": str(_object_value(event, "event_type", "")),
                "payload": _as_mapping(
                    _object_value(event, "payload", {})
                ),
            }
        )
    return sorted(
        normalized,
        key=lambda event: (event["sequence_no"], event["input_order"]),
    )


def _mapping_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _page_row_evidence(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = _mapping_items(payload.get("rows"))
    if rows:
        return rows
    return _mapping_items(payload.get("id_pairs"))


def _ordered_valid_identity_pairs(
    records: Iterable[Mapping[str, Any]],
) -> tuple[tuple[str, str], ...]:
    ordered_pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        job_ids = _canonical_id_set(
            [
                record.get("job_id"),
                record.get("jobId"),
                record.get("source_job_id"),
            ]
        )
        encrypted_job_ids = _canonical_id_set(
            [record.get("encrypted_job_id"), record.get("encryptJobId")]
        )
        if len(job_ids) != 1 or len(encrypted_job_ids) != 1:
            continue
        pair = (next(iter(job_ids)), next(iter(encrypted_job_ids)))
        if pair in seen:
            continue
        seen.add(pair)
        ordered_pairs.append(pair)
    return tuple(ordered_pairs)


def _find_identity_pair_mismatch_page_keys(
    replayable_pages: Mapping[tuple[str, int], Mapping[str, Any]],
) -> tuple[str, ...]:
    mismatches: list[str] = []
    for (condition_id, page), payload in replayable_pages.items():
        if "rows" not in payload or "id_pairs" not in payload:
            continue
        row_pairs = _ordered_valid_identity_pairs(
            _mapping_items(payload.get("rows"))
        )
        declared_pairs = _ordered_valid_identity_pairs(
            _mapping_items(payload.get("id_pairs"))
        )
        if row_pairs == declared_pairs:
            continue
        mismatches.append(
            json.dumps(
                {"condition_id": condition_id, "page": page},
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    return tuple(sorted(mismatches))


def _identity_evidence(
    page_payloads: Iterable[Mapping[str, Any]],
) -> tuple[set[str], set[str]]:
    deferred_ids: set[str] = set()
    encrypted_ids_by_job_id: dict[str, set[str]] = {}
    job_ids_by_encrypted_id: dict[str, set[str]] = {}

    for payload in page_payloads:
        for issue in _mapping_items(payload.get("identity_issues")):
            deferred_ids.update(
                _canonical_id_set(
                    [issue.get("job_id"), issue.get("source_job_id")]
                )
            )
        for conflict in _mapping_items(payload.get("identity_conflicts")):
            conflict_ids = conflict.get("job_ids")
            if not isinstance(conflict_ids, (list, tuple, set)):
                conflict_ids = conflict.get("source_job_ids")
            if not isinstance(conflict_ids, (list, tuple, set)):
                conflict_ids = [conflict.get("job_id")]
            deferred_ids.update(_canonical_id_set(conflict_ids))

        identity_records = [
            *_mapping_items(payload.get("id_pairs")),
            *_mapping_items(payload.get("rows")),
        ]
        for record in identity_records:
            job_ids = _canonical_id_set(
                [record.get("job_id"), record.get("source_job_id")]
            )
            encrypted_ids = _canonical_id_set(
                [
                    record.get("encrypted_job_id"),
                    record.get("encryptJobId"),
                ]
            )
            for job_id in job_ids:
                encrypted_ids_by_job_id.setdefault(job_id, set()).update(
                    encrypted_ids
                )
            for encrypted_id in encrypted_ids:
                job_ids_by_encrypted_id.setdefault(encrypted_id, set()).update(
                    job_ids
                )

    mapping_conflict_ids = {
        job_id
        for job_id, encrypted_ids in encrypted_ids_by_job_id.items()
        if len(encrypted_ids) > 1
    }
    mapping_conflict_ids.update(
        job_id
        for job_ids in job_ids_by_encrypted_id.values()
        if len(job_ids) > 1
        for job_id in job_ids
    )
    deferred_ids.update(mapping_conflict_ids)
    return deferred_ids, mapping_conflict_ids


def _listing_observation_evidence(
    events: Sequence[Mapping[str, Any]],
) -> tuple[set[str], int]:
    newly_staged_ids: set[str] = set()
    newly_created_rows = 0
    for event in events:
        if event["event_type"] != "crawl.listing_observed":
            continue
        payload = event["payload"]
        records_value = payload.get("records")
        if not isinstance(records_value, (list, tuple)):
            records_value = payload.get("observations")
        records = _mapping_items(records_value)
        newly_staged_records = [
            record
            for record in records
            if str(record.get("classification") or "").strip().lower()
            == "newly_staged"
        ]
        newly_staged_ids.update(
            _canonical_id_set(
                record.get("source_job_id")
                for record in newly_staged_records
            )
        )
        newly_staged_ids.update(
            _canonical_id_set(payload.get("created_source_job_ids") or [])
        )
        if "rows_created" not in payload:
            newly_created_rows += len(newly_staged_records)
        else:
            newly_created_rows += _require_nonnegative_int(
                payload["rows_created"],
                evidence_name="rows_created",
            )
    return newly_staged_ids, newly_created_rows


def _condition_evidence_key(
    payload: Mapping[str, Any],
    *,
    missing_identity_key: str,
) -> str:
    condition_id = payload.get("condition_id")
    if isinstance(condition_id, str) and condition_id.strip():
        return f"condition-id:{condition_id.strip()}"
    condition = payload.get("condition")
    if isinstance(condition, Mapping):
        canonical_json = json.dumps(
            dict(condition),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        return f"condition-json:{digest}"
    return missing_identity_key


def _count_final_unresolved_conditions(
    events: Sequence[Mapping[str, Any]],
) -> int:
    incomplete_by_condition: dict[str, bool] = {}
    condition_event_types = (
        _INCOMPLETE_CONDITION_EVENT_TYPES
        | _COMPLETED_CONDITION_EVENT_TYPES
    )
    for event in events:
        event_type = event["event_type"]
        if event_type not in condition_event_types:
            continue
        condition_key = _condition_evidence_key(
            event["payload"],
            missing_identity_key=(
                f"missing-condition:{event['sequence_no']}:{event['input_order']}"
            ),
        )
        incomplete_by_condition[condition_key] = (
            event_type in _INCOMPLETE_CONDITION_EVENT_TYPES
        )
    return sum(incomplete_by_condition.values())


def _reconciled_source_job_ids(
    events: Sequence[Mapping[str, Any]],
    cohort_event: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    reconciled_ids: set[str] = set()
    if cohort_event is not None:
        reconciled_ids.update(
            _canonical_id_set(
                cohort_event["payload"].get("reconciled_source_job_ids") or []
            )
        )
    for event in events:
        if event["event_type"] != "crawl.detail_reconciled":
            continue
        records = _mapping_items(event["payload"].get("records"))
        reconciled_ids.update(
            _canonical_id_set(
                record.get("source_job_id") for record in records
            )
        )
    return tuple(sorted(reconciled_ids))


def _expected_response_identity_hash(
    *,
    source_job_id: str,
    encrypted_job_id: str,
) -> str:
    canonical_json = json.dumps(
        {
            "encrypted_job_id": encrypted_job_id,
            "job_id": source_job_id,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _expected_persisted_evidence_by_source_id(
    *,
    detail_crawl_job_id: str,
    eligible_ids: set[str],
    listings: Sequence[StagedListingSnapshot],
    jobs: Sequence[PublishedJobSnapshot],
) -> dict[str, dict[str, Any]]:
    jobs_by_id = {str(job.job_id): job for job in jobs}
    rows_by_source_id: dict[str, list[StagedListingSnapshot]] = {}
    for row in listings:
        source_job_ids = _canonical_id_set([row.source_job_id])
        if len(source_job_ids) != 1:
            continue
        source_job_id = next(iter(source_job_ids))
        if (
            source_job_id not in eligible_ids
            or str(row.last_detail_crawl_job_id or "")
            != detail_crawl_job_id
            or str(row.detail_status).strip().lower() != "completed"
        ):
            continue
        rows_by_source_id.setdefault(source_job_id, []).append(row)

    expected: dict[str, dict[str, Any]] = {}
    for source_job_id, rows in rows_by_source_id.items():
        listing_ids = _canonical_id_set(row.row_id for row in rows)
        published_job_ids = _canonical_id_set(
            row.published_job_id for row in rows
        )
        encrypted_job_ids = _canonical_id_set(
            row.encrypted_job_id for row in rows
        )
        if (
            len(listing_ids) != len(rows)
            or len(published_job_ids) != 1
            or len(encrypted_job_ids) != 1
            or not all(row.has_detail_payload for row in rows)
        ):
            continue
        published_job_id = next(iter(published_job_ids))
        encrypted_job_id = next(iter(encrypted_job_ids))
        published_job = jobs_by_id.get(published_job_id)
        if (
            published_job is None
            or not published_job.is_complete
            or _canonical_id_set([published_job.source_job_id])
            != {source_job_id}
        ):
            continue
        expected[source_job_id] = {
            "detail_crawl_job_id": detail_crawl_job_id,
            "listing_ids": listing_ids,
            "published_job_id": published_job_id,
            "response_identity_hash": _expected_response_identity_hash(
                source_job_id=source_job_id,
                encrypted_job_id=encrypted_job_id,
            ),
        }
    return expected


def _validate_persisted_events(
    *,
    events: Sequence[Mapping[str, Any]],
    detail_crawl_job_id: str,
    eligible_ids: set[str],
    listings: Sequence[StagedListingSnapshot],
    jobs: Sequence[PublishedJobSnapshot],
) -> tuple[set[str], set[str]]:
    expected_by_source_id = _expected_persisted_evidence_by_source_id(
        detail_crawl_job_id=detail_crawl_job_id,
        eligible_ids=eligible_ids,
        listings=listings,
        jobs=jobs,
    )
    valid_ids: set[str] = set()
    mismatch_ids: set[str] = set()
    for event in events:
        if event["event_type"] != "crawl.detail_persisted":
            continue
        payload = event["payload"]
        source_ids = _canonical_id_set([payload.get("source_job_id")])
        if len(source_ids) != 1:
            mismatch_ids.add("<missing_source_job_id>")
            continue
        source_job_id = next(iter(source_ids))
        expected = expected_by_source_id.get(source_job_id)
        raw_listing_ids = payload.get("listing_ids")
        listing_ids = (
            _canonical_id_set(raw_listing_ids)
            if isinstance(raw_listing_ids, (list, tuple))
            else set()
        )
        listing_ids_are_exact = (
            isinstance(raw_listing_ids, (list, tuple))
            and len(listing_ids) == len(raw_listing_ids)
        )
        is_valid = (
            source_job_id in eligible_ids
            and expected is not None
            and str(payload.get("detail_crawl_job_id") or "")
            == expected["detail_crawl_job_id"]
            and listing_ids_are_exact
            and listing_ids == expected["listing_ids"]
            and str(payload.get("published_job_id") or "").strip()
            == expected["published_job_id"]
            and str(payload.get("response_identity_hash") or "").strip()
            == expected["response_identity_hash"]
        )
        if is_valid:
            valid_ids.add(source_job_id)
        else:
            mismatch_ids.add(source_job_id)
    return valid_ids, mismatch_ids


def replay_research_conservation(
    *,
    crawl_job: Any,
    events: Sequence[Any],
    listings: Sequence[StagedListingSnapshot],
    jobs: Sequence[PublishedJobSnapshot],
) -> ResearchConservationReport:
    normalized_events = _normalize_events(events)
    request_payload = _as_mapping(
        _object_value(crawl_job, "request_payload", {})
    )
    research_payload = _as_mapping(request_payload.get("research"))
    run_start = _as_mapping(research_payload.get("run_start_inventory"))

    replayable_pages: dict[tuple[str, int], dict[str, Any]] = {}
    for event in normalized_events:
        if event["event_type"] not in _PAGE_EVENT_TYPES:
            continue
        payload = event["payload"]
        classification = str(payload.get("classification") or "").strip().lower()
        if classification not in _REPLAYABLE_PAGE_CLASSIFICATIONS:
            continue
        page_key = (
            str(payload.get("condition_id") or ""),
            _as_int(payload.get("page")),
        )
        replayable_pages[page_key] = payload

    listing_report: ListingConservationReport | None = None
    if replayable_pages:
        page_payloads = list(replayable_pages.values())
        identity_pair_mismatch_page_keys = (
            _find_identity_pair_mismatch_page_keys(replayable_pages)
        )
        row_evidence = [
            row
            for payload in page_payloads
            for row in _page_row_evidence(payload)
        ]
        id_pair_evidence = [
            pair
            for payload in page_payloads
            for pair in _mapping_items(payload.get("id_pairs"))
        ]
        valid_ids = _canonical_id_set(
            [
                *(
                    row.get("job_id") or row.get("source_job_id")
                    for row in row_evidence
                ),
                *(
                    pair.get("job_id") or pair.get("source_job_id")
                    for pair in id_pair_evidence
                ),
            ]
        )
        deferred_ids, mapping_conflict_ids = _identity_evidence(page_payloads)
        newly_staged_ids, newly_created_rows = _listing_observation_evidence(
            normalized_events
        )
        published_at_start = _canonical_id_set(
            run_start.get("published_job_ids") or []
        )
        staged_at_start = _canonical_id_set(
            run_start.get("staged_unpublished_job_ids") or []
        )
        already_published_ids = valid_ids & published_at_start
        preexisting_ids = (
            valid_ids - already_published_ids
        ) & staged_at_start
        deferred_partition_ids = (
            valid_ids
            & deferred_ids
            - already_published_ids
            - preexisting_ids
        )
        newly_staged_partition_ids = (
            valid_ids
            & newly_staged_ids
            - already_published_ids
            - preexisting_ids
            - deferred_partition_ids
        )
        raw_listing_rows = sum(
            _payload_nonnegative_int(
                payload,
                "row_count",
                default=len(_page_row_evidence(payload)),
            )
            for payload in page_payloads
        )
        rows_missing_job_id = sum(
            _payload_nonnegative_int(
                payload,
                "missing_job_id_count",
                default=max(
                    _payload_nonnegative_int(
                        payload,
                        "row_count",
                        default=len(_page_row_evidence(payload)),
                    )
                    - sum(
                        bool(row.get("job_id") or row.get("source_job_id"))
                        for row in _page_row_evidence(payload)
                    ),
                    0,
                ),
            )
            for payload in page_payloads
        )
        rows_containing_job_id = sum(
            bool(row.get("job_id") or row.get("source_job_id"))
            for row in row_evidence
        )
        unresolved_condition_gaps = _count_final_unresolved_conditions(
            normalized_events
        )
        listing_report = build_listing_conservation_report(
            raw_listing_rows=raw_listing_rows,
            rows_missing_job_id=rows_missing_job_id,
            rows_containing_job_id=rows_containing_job_id,
            valid_distinct_job_ids=valid_ids,
            already_published_ids=already_published_ids,
            preexisting_staged_unpublished_ids=preexisting_ids,
            newly_staged_ids=newly_staged_partition_ids,
            deferred_identity_conflict_ids=deferred_partition_ids,
            newly_created_staging_rows=newly_created_rows,
            unresolved_gaps=(
                unresolved_condition_gaps + len(mapping_conflict_ids)
            ),
            identity_pair_mismatch_page_keys=(
                identity_pair_mismatch_page_keys
            ),
        )

    cohort_event = next(
        (
            event
            for event in reversed(normalized_events)
            if event["event_type"] == "crawl.detail_cohort_frozen"
        ),
        None,
    )
    reconciled_ids = _reconciled_source_job_ids(
        normalized_events,
        cohort_event,
    )
    reconciled_fetch_overlap_ids: tuple[str, ...] = ()
    detail_report: DetailConservationReport | None = None
    if cohort_event is not None:
        fetch_ids = _canonical_id_set(
            cohort_event["payload"].get("fetch_cohort_source_job_ids") or []
        )
        reconciled_fetch_overlap_ids = tuple(
            sorted(fetch_ids & set(reconciled_ids))
        )
        fetch_ids.difference_update(reconciled_fetch_overlap_ids)
        detail_crawl_job_id = str(_object_value(crawl_job, "id", ""))
        persisted_ids, persisted_evidence_mismatch_ids = (
            _validate_persisted_events(
                events=normalized_events,
                detail_crawl_job_id=detail_crawl_job_id,
                eligible_ids=fetch_ids,
                listings=listings,
                jobs=jobs,
            )
        )
        detail_report = build_detail_conservation_report(
            detail_crawl_job_id=detail_crawl_job_id,
            fetch_cohort_source_job_ids=fetch_ids,
            persisted_source_job_ids=persisted_ids,
            listings=listings,
            jobs=jobs,
            run_is_terminal=(
                str(_object_value(crawl_job, "status", "")).strip().lower()
                in _TERMINAL_CRAWL_STATUSES
            ),
            persisted_evidence_mismatch_ids=persisted_evidence_mismatch_ids,
        )

    return ResearchConservationReport(
        listing=listing_report,
        detail=detail_report,
        reconciled_source_job_ids=reconciled_ids,
        reconciled_fetch_overlap_ids=reconciled_fetch_overlap_ids,
    )
