from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from app.sources.offertoday.constants import (
    OFFERTODAY_LISTING_SEARCH_URL,
    build_offertoday_listing_payload,
)
from app.sources.offertoday.listing_contract import (
    OfferTodayListingPageEvidenceV2,
)
from app.sources.offertoday.listing_runner import (
    OfferTodayListingCondition,
    offertoday_listing_request_fingerprint,
)
from app.sources.offertoday.research.artifacts import verify_research_artifact
from app.sources.offertoday.research.live_contracts import DiscoveryCandidateV2
from app.sources.offertoday.research.pagination_bakeoff import (
    BAKEOFF_CATEGORY_IDS,
    BAKEOFF_ENDPOINT,
    BAKEOFF_MAX_ATTEMPTS_PER_PAGE,
    BAKEOFF_MAX_LOGICAL_PAGES_PER_CONDITION,
    BAKEOFF_PAGE_DELAY_RANGE_SECONDS,
    BAKEOFF_RCD_TYPE,
    BAKEOFF_REQUIRE_EMPTY_CONFIRMATION,
    BAKEOFF_RETRY_DELAYS_SECONDS,
    BAKEOFF_SESSION_MODE,
    BAKEOFF_TERMINAL_POLICY,
    BAKEOFF_VARIANTS,
    bakeoff_variant,
    canonical_bakeoff_payload_hash,
    compare_bakeoff_payloads,
    pagination_bakeoff_controls_payload,
    pagination_bakeoff_thresholds_payload,
    validate_bakeoff_payload,
)


PAGINATION_BAKEOFF_REQUEST_BUDGET = {
    "listing_logical": 150,
    "listing_attempt_max": 300,
    "detail": 0,
    "product_writes": 0,
}

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_FORBIDDEN_CURSOR_KEY_RE = re.compile(
    r'"sessionId"\s*:|"session_id"\s*:\s*"'
)


@dataclass(frozen=True, slots=True)
class PaginationArtifactVerification:
    valid: bool
    issues: tuple[str, ...]
    experiment: str | None
    run_id: str | None


def _load_artifact(artifact_dir: Path):
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
    return manifest, events


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _ordered_distinct(values):
    return list(dict.fromkeys(str(value) for value in values if str(value)))


_OBSERVATION_KEYS = {
    "condition_id",
    "search_family",
    "category_id",
    "keyword",
    "endpoint",
    "rcd_type",
    "page",
    "attempt",
    "request_fingerprint",
    "classification",
    "api_code",
    "reported_total",
    "has_more",
    "row_count",
    "missing_job_id_count",
    "missing_encrypted_job_id_count",
    "job_id_fallback_count",
    "id_pairs",
    "rows",
    "identity_issues",
    "identity_conflicts",
    "latency_ms",
    "session_mode",
    "retry_reason",
    "stop_reason",
    "cursor_evidence",
}
_IDENTITY_PAIR_KEYS = {
    "job_id",
    "encrypted_job_id",
    "encrypted_job_id_source",
}
_ROW_EVIDENCE_KEYS = {
    "job_id",
    "encrypted_job_id",
    "encrypted_job_id_source",
    "observed_encrypted_job_id",
    "title",
    "job_function_codes",
    "title_language",
    "api_language",
}
_IDENTITY_ISSUE_KEYS = {"job_id", "encrypted_job_id", "reason"}
_IDENTITY_CONFLICT_KEYS = {"job_ids", "encrypted_job_ids", "reason"}
_IDENTITY_SOURCES = {"encryptJobId", "jobId_fallback"}


def _is_nonblank_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _is_optional_nonblank_string(value: Any) -> bool:
    return value is None or _is_nonblank_string(value)


def _valid_identity_pair(item: Any) -> bool:
    return (
        isinstance(item, Mapping)
        and set(item) == _IDENTITY_PAIR_KEYS
        and _is_nonblank_string(item["job_id"])
        and _is_nonblank_string(item["encrypted_job_id"])
        and item["encrypted_job_id_source"] in _IDENTITY_SOURCES
    )


def _valid_row_evidence(item: Any) -> bool:
    return (
        isinstance(item, Mapping)
        and set(item) == _ROW_EVIDENCE_KEYS
        and _is_optional_nonblank_string(item["job_id"])
        and _is_optional_nonblank_string(item["encrypted_job_id"])
        and (
            item["encrypted_job_id_source"] is None
            or item["encrypted_job_id_source"] in _IDENTITY_SOURCES
        )
        and _is_optional_nonblank_string(item["observed_encrypted_job_id"])
        and isinstance(item["title"], str)
        and isinstance(item["job_function_codes"], list)
        and all(isinstance(value, str) for value in item["job_function_codes"])
        and item["title_language"] in {"zh", "en", "mixed", "other"}
        and isinstance(item["api_language"], str)
    )


def _valid_identity_issue(item: Any) -> bool:
    return (
        isinstance(item, Mapping)
        and set(item) == _IDENTITY_ISSUE_KEYS
        and _is_optional_nonblank_string(item["job_id"])
        and _is_optional_nonblank_string(item["encrypted_job_id"])
        and _is_nonblank_string(item["reason"])
    )


def _valid_identity_conflict(item: Any) -> bool:
    return (
        isinstance(item, Mapping)
        and set(item) == _IDENTITY_CONFLICT_KEYS
        and isinstance(item["job_ids"], list)
        and all(_is_nonblank_string(value) for value in item["job_ids"])
        and isinstance(item["encrypted_job_ids"], list)
        and all(
            _is_nonblank_string(value) for value in item["encrypted_job_ids"]
        )
        and _is_nonblank_string(item["reason"])
    )


def _is_exact_nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _decode_executions(
    bakeoff_payload: Mapping[str, Any],
    issues: list[str],
):
    decoded = []
    for execution in bakeoff_payload["executions"]:
        variant = bakeoff_variant(execution["variant_id"])
        if (
            type(execution["repeat_index"]) is not int
            or type(execution["category_id"]) is not int
            or type(execution["category_order"]) is not int
            or type(execution["is_complete"]) is not bool
            or not isinstance(execution["stop_reason"], str)
            or not execution["stop_reason"]
            or execution["stop_reason"] != execution["stop_reason"].strip()
        ):
            issues.append("invalid_execution_scalars")
        for field_name in (
            "gap_count",
            "identity_issue_count",
            "identity_conflict_count",
        ):
            if not _is_exact_nonnegative_int(execution[field_name]):
                issues.append(f"invalid_{field_name}")
        decoded_observations = []
        for observation in execution["observations"]:
            if not isinstance(observation, dict) or set(observation) != _OBSERVATION_KEYS:
                issues.append("invalid_page_observation_fields")
                continue
            try:
                evidence = OfferTodayListingPageEvidenceV2.from_payload(
                    observation["cursor_evidence"]
                )
            except (TypeError, ValueError):
                issues.append("invalid_v2_page_evidence")
                continue
            try:
                condition = OfferTodayListingCondition(
                    search_family=observation["search_family"],
                    category_id=observation["category_id"],
                    keyword=observation["keyword"],
                    endpoint=observation["endpoint"],
                    rcd_type=observation["rcd_type"],
                )
            except (TypeError, ValueError):
                issues.append("invalid_bakeoff_condition")
                continue
            if (
                condition.search_family != "cursor_pagination_bakeoff_v2"
                or condition.category_id != execution["category_id"]
                or condition.category_id not in BAKEOFF_CATEGORY_IDS
                or condition.keyword != ""
                or condition.endpoint != "search"
                or condition.rcd_type is not None
                or observation["condition_id"] != condition.condition_id
            ):
                issues.append("page_condition_mismatch")
            if (
                evidence.protocol_version != 2
                or evidence.variant_id != execution["variant_id"]
                or evidence.repeat_index != bakeoff_payload["repeat_index"]
                or evidence.pagination_mode != variant.pagination_mode
                or evidence.browser_lifecycle != variant.browser_lifecycle
                or evidence.requested_page_size != variant.requested_page_size
            ):
                issues.append("cursor_evidence_control_mismatch")
            policy = replace(
                variant.request_policy(repeat_index=bakeoff_payload["repeat_index"]),
                condition_restart_index=evidence.condition_restart_index,
            )
            page = observation["page"]
            attempt = observation["attempt"]
            if type(page) is not int or not 1 <= page <= 10:
                issues.append("invalid_page_number")
            if type(attempt) is not int or not 1 <= attempt <= 2:
                issues.append("invalid_attempt_number")
            if type(page) is int and page >= 1 and type(attempt) is int and attempt >= 1:
                if (
                    evidence.condition_execution_id
                    != policy.condition_execution_id(condition.condition_id)
                    or evidence.logical_request_id
                    != policy.logical_request_id(condition.condition_id, page)
                    or evidence.physical_attempt_id
                    != policy.physical_attempt_id(condition.condition_id, page, attempt)
                ):
                    issues.append("request_identity_mismatch")
                base_payload = build_offertoday_listing_payload(
                    category_id=condition.category_id,
                    keyword=condition.keyword,
                    page=page,
                    rcd_type=condition.rcd_type,
                    page_size=variant.requested_page_size,
                )
                expected_fingerprint = offertoday_listing_request_fingerprint(
                    OFFERTODAY_LISTING_SEARCH_URL,
                    base_payload,
                    cursor_hash=(
                        evidence.cursor_input.cursor_hash
                        if evidence.cursor_input is not None
                        else None
                    ),
                )
                if observation["request_fingerprint"] != expected_fingerprint:
                    issues.append("request_fingerprint_mismatch")
            if not _is_sha256(observation["request_fingerprint"]):
                issues.append("invalid_request_fingerprint")
            if not _is_sha256(evidence.browser_context_hash):
                issues.append("invalid_browser_context_hash")
            for field_name in (
                "row_count",
                "missing_job_id_count",
                "missing_encrypted_job_id_count",
                "job_id_fallback_count",
                "latency_ms",
            ):
                if not _is_exact_nonnegative_int(observation[field_name]):
                    issues.append(f"invalid_{field_name}")
            if observation["row_count"] != evidence.result_row_count:
                issues.append("result_row_count_mismatch")
            for field_name in (
                "id_pairs",
                "rows",
                "identity_issues",
                "identity_conflicts",
            ):
                if not isinstance(observation[field_name], list):
                    issues.append(f"invalid_{field_name}")
            for field_name, validator in (
                ("id_pairs", _valid_identity_pair),
                ("rows", _valid_row_evidence),
                ("identity_issues", _valid_identity_issue),
                ("identity_conflicts", _valid_identity_conflict),
            ):
                values = observation[field_name]
                if isinstance(values, list) and any(
                    not validator(item) for item in values
                ):
                    issues.append(f"invalid_{field_name}_items")
            if isinstance(observation["rows"], list) and (
                len(observation["rows"]) != observation["row_count"]
            ):
                issues.append("result_row_evidence_count_mismatch")
            if isinstance(observation["rows"], list) and all(
                _valid_row_evidence(item) for item in observation["rows"]
            ):
                observed_row_job_ids = tuple(
                    item["job_id"]
                    for item in observation["rows"]
                    if item["job_id"] is not None
                )
                if observed_row_job_ids != evidence.result_job_ids:
                    issues.append("result_job_id_evidence_mismatch")
            if observation["has_more"] is not None and type(observation["has_more"]) is not bool:
                issues.append("invalid_has_more")
            if observation["reported_total"] is not None and not _is_exact_nonnegative_int(
                observation["reported_total"]
            ):
                issues.append("invalid_reported_total")
            if observation["api_code"] is not None and type(observation["api_code"]) is not int:
                issues.append("invalid_api_code")
            if observation["session_mode"] != "fresh-headless":
                issues.append("invalid_session_mode")
            if (
                not isinstance(observation["classification"], str)
                or not observation["classification"]
                or observation["classification"]
                != observation["classification"].strip()
            ):
                issues.append("invalid_classification")
            for field_name in ("retry_reason", "stop_reason"):
                value = observation[field_name]
                if value is not None and (
                    not isinstance(value, str)
                    or not value
                    or value != value.strip()
                ):
                    issues.append(f"invalid_{field_name}")
            if evidence.cursor_output is not None and not all(
                (
                    evidence.response_cursor_fields.session_id,
                    evidence.response_cursor_fields.supple_page,
                    evidence.response_cursor_fields.supple_amount,
                    evidence.response_cursor_fields.supple_type,
                    evidence.response_cursor_fields.page_size,
                )
            ):
                issues.append("cursor_output_without_complete_fields")
            expected_effective_page_size = (
                evidence.cursor_output.effective_page_size
                if evidence.cursor_output is not None
                else evidence.response_page_size
            )
            if evidence.effective_page_size != expected_effective_page_size:
                issues.append("effective_page_size_mismatch")
            if (
                evidence.cursor_output is not None
                and evidence.cursor_output.effective_page_size
                != evidence.response_page_size
            ):
                issues.append("cursor_response_page_size_mismatch")
            if variant.pagination_mode == "stateless-control":
                expected_session_continuity = "not_applicable"
            elif evidence.contract_error is not None:
                expected_session_continuity = (
                    "violation"
                    if evidence.contract_error
                    in {"session_rollover", "page_size_drift"}
                    else "unavailable"
                )
            elif evidence.cursor_output is None:
                expected_session_continuity = "unavailable"
            elif evidence.cursor_input is None:
                expected_session_continuity = "initial"
            elif (
                evidence.cursor_input.session_id_hash
                == evidence.cursor_output.session_id_hash
            ):
                expected_session_continuity = "continued"
            else:
                expected_session_continuity = "violation"
            if evidence.session_continuity != expected_session_continuity:
                issues.append("session_continuity_mismatch")
            decoded_observations.append((observation, evidence, condition))
        decoded.append((execution, variant, decoded_observations))
    return decoded


def _recompute_variant_summaries(decoded_executions):
    summaries = []
    id_sets = {}
    base = []
    available_variant_ids = {
        item[0]["variant_id"] for item in decoded_executions
    }
    for variant in BAKEOFF_VARIANTS:
        if variant.variant_id not in available_variant_ids:
            continue
        selected = [
            item for item in decoded_executions if item[0]["variant_id"] == variant.variant_id
        ]
        observations = [
            item
            for _execution, _variant, decoded in selected
            for item in decoded
        ]
        evidence = [item[1] for item in observations]
        result_ids = _ordered_distinct(
            job_id for item in evidence for job_id in item.result_job_ids
        )
        supplemental_ids = _ordered_distinct(
            job_id for item in evidence for job_id in item.supplemental_job_ids
        )
        all_ids = _ordered_distinct((*result_ids, *supplemental_ids))
        result_rows = sum(item.result_row_count for item in evidence)
        supplemental_rows = sum(item.supplemental_row_count for item in evidence)
        raw_rows = result_rows + supplemental_rows
        duplicate_rows = sum(item.duplicate_job_id_count for item in evidence)
        identity_rows = sum(
            len(item.result_job_ids) + len(item.supplemental_job_ids)
            for item in evidence
        )
        latency_ms = sum(item[0]["latency_ms"] for item in observations)
        summary = {
            "variant_id": variant.variant_id,
            "logical_pages": len({item.logical_request_id for item in evidence}),
            "physical_attempts": len(evidence),
            "result_rows": result_rows,
            "supplemental_rows": supplemental_rows,
            "distinct_result_ids": result_ids,
            "distinct_supplemental_ids": supplemental_ids,
            "distinct_all_ids": all_ids,
            "duplicate_rows": duplicate_rows,
            "duplicate_rate": duplicate_rows / raw_rows if raw_rows else 0.0,
            "zero_new_full_pages": sum(
                item.zero_new_full_page and item.condition_restart_index == 0
                for item in evidence
            ),
            "cursor_violations": sum(
                item[0]["classification"]
                in {"cursor_contract_violation", "contract_anomaly"}
                for item in observations
            ),
            "unresolved_gaps": sum(
                item[0]["gap_count"] + int(not item[0]["is_complete"])
                for item in selected
            ),
            "identity_issues": sum(item[0]["identity_issue_count"] for item in selected),
            "identity_conflicts": sum(
                item[0]["identity_conflict_count"] for item in selected
            ),
            "conservation_difference": raw_rows - identity_rows,
            "unclassified_failures": sum(
                item[0]["classification"] not in {"success", "transient_transport"}
                for item in observations
            ),
            "latency_ms": latency_ms,
            "response_page_sizes": [
                item.response_page_size
                for item in evidence
                if item.response_page_size is not None
            ],
            "reported_totals": [
                item[0]["reported_total"]
                for item in observations
                if item[0]["reported_total"] is not None
            ],
            "response_page_size_drift_conditions": sum(
                len(
                    {
                        evidence.response_page_size
                        for _observation, evidence, _condition in decoded
                        if evidence.response_page_size is not None
                    }
                )
                > 1
                for _execution, _variant, decoded in selected
            ),
            "reported_total_drift_conditions": sum(
                len(
                    {
                        observation["reported_total"]
                        for observation, _evidence, _condition in decoded
                        if observation["reported_total"] is not None
                    }
                )
                > 1
                for _execution, _variant, decoded in selected
            ),
            "requests_per_distinct_id": (
                len(evidence) / len(all_ids) if all_ids else None
            ),
            "seconds_per_distinct_id": (
                latency_ms / 1000 / len(all_ids) if all_ids else None
            ),
        }
        base.append(summary)
        id_sets[variant.variant_id] = set(all_ids)
    for summary in base:
        summary["unique_contribution_ids"] = sorted(
            id_sets[summary["variant_id"]]
            - set().union(
                *(
                    values
                    for key, values in id_sets.items()
                    if key != summary["variant_id"]
                )
            )
        )
        summaries.append(summary)
    return summaries


def _validate_event_sequence(events: list[dict[str, Any]], issues: list[str]) -> None:
    expected_keys = {
        "sequence_no",
        "event_type",
        "payload",
        "emitted_by",
        "created_at",
    }
    if any(not isinstance(event, dict) or set(event) != expected_keys for event in events):
        issues.append("invalid_event_fields")
    sequence = [event.get("sequence_no") for event in events]
    if sequence != list(range(1, len(events) + 1)):
        issues.append("invalid_event_sequence")
    if any(event.get("emitted_by") != "offertoday-research" for event in events):
        issues.append("invalid_event_emitter")
    if any(not isinstance(event.get("payload"), dict) for event in events):
        issues.append("invalid_event_payload")
    for event in events:
        try:
            created_at = datetime.fromisoformat(event.get("created_at"))
        except (TypeError, ValueError):
            issues.append("invalid_event_timestamp")
            break
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            issues.append("invalid_event_timestamp")
            break


def _validate_cursor_chains(decoded_executions, issues: list[str]) -> None:
    physical_attempt_ids: set[str] = set()
    execution_id_owners: dict[str, tuple[str, int, int]] = {}
    shared_current_context: dict[str, str] = {}
    condition_contexts_seen: set[str] = set()

    for execution, variant, observations in decoded_executions:
        if not observations:
            issues.append("empty_condition_observations")
            continue
        seen_job_ids: set[str] = set()
        current_restart_index = 0
        last_successful_output = None
        awaiting_empty_confirmation = False
        previous = None
        logical_contexts: dict[str, set[str]] = {}
        contexts_by_restart: dict[int, set[str]] = {}

        for observation, evidence, _condition in observations:
            physical_id = evidence.physical_attempt_id
            if physical_id in physical_attempt_ids:
                issues.append("duplicate_physical_attempt_id")
            physical_attempt_ids.add(physical_id)
            owner = (
                execution["variant_id"],
                execution["category_id"],
                evidence.condition_restart_index,
            )
            prior_owner = execution_id_owners.setdefault(
                evidence.condition_execution_id,
                owner,
            )
            if prior_owner != owner:
                issues.append("condition_execution_id_reused")

            if previous is None:
                if (
                    evidence.condition_restart_index != 0
                    or observation["page"] != 1
                    or observation["attempt"] != 1
                ):
                    issues.append("condition_did_not_start_at_page_one")
            elif evidence.condition_restart_index != current_restart_index:
                previous_observation, previous_evidence, _ = previous
                if (
                    evidence.condition_restart_index != current_restart_index + 1
                    or previous_observation.get("retry_reason")
                    != "browser_context_lost_restart"
                    or observation["page"] != 1
                    or observation["attempt"] != 1
                    or evidence.cursor_input is not None
                ):
                    issues.append("invalid_browser_restart_transition")
                current_restart_index = evidence.condition_restart_index
                last_successful_output = None
                awaiting_empty_confirmation = False
            elif previous is not None:
                previous_observation, previous_evidence, _ = previous
                if previous_observation.get("retry_reason") is not None:
                    expected_page = previous_observation["page"]
                    expected_attempt = previous_observation["attempt"] + 1
                else:
                    expected_page = previous_observation["page"] + 1
                    expected_attempt = 1
                if (
                    observation["page"] != expected_page
                    or observation["attempt"] != expected_attempt
                ):
                    issues.append("invalid_page_attempt_sequence")
                if observation["page"] == previous_observation["page"]:
                    if (
                        evidence.logical_request_id
                        != previous_evidence.logical_request_id
                        or evidence.cursor_input != previous_evidence.cursor_input
                        or observation["request_fingerprint"]
                        != previous_observation["request_fingerprint"]
                        or evidence.browser_context_hash
                        != previous_evidence.browser_context_hash
                    ):
                        issues.append("retry_request_changed")

            current_restart_index = evidence.condition_restart_index
            if evidence.condition_restart_index > 1:
                issues.append("browser_restart_budget_exceeded")
            if variant.pagination_mode == "stateless-control":
                if evidence.cursor_input is not None:
                    issues.append("stateless_cursor_input_present")
            elif observation["page"] == 1:
                if evidence.cursor_input is not None:
                    issues.append("page_one_cursor_input_present")
            elif evidence.cursor_input != last_successful_output:
                issues.append("cursor_transition_mismatch")

            logical_contexts.setdefault(evidence.logical_request_id, set()).add(
                evidence.browser_context_hash
            )
            contexts_by_restart.setdefault(
                evidence.condition_restart_index,
                set(),
            ).add(evidence.browser_context_hash)

            all_job_ids = (
                *evidence.result_job_ids,
                *evidence.supplemental_job_ids,
            )
            new_job_ids = set(all_job_ids) - seen_job_ids
            if evidence.new_job_id_count != len(new_job_ids):
                issues.append("new_job_id_count_mismatch")
            if evidence.duplicate_job_id_count != len(all_job_ids) - len(new_job_ids):
                issues.append("duplicate_job_id_count_mismatch")
            expected_zero_new_full_page = (
                evidence.effective_page_size is not None
                and evidence.result_row_count + evidence.supplemental_row_count
                >= evidence.effective_page_size
                and not new_job_ids
            )
            if evidence.zero_new_full_page is not expected_zero_new_full_page:
                issues.append("zero_new_full_page_mismatch")
            response_classified = observation["classification"] in {
                "success",
                "identity_conflict",
                "identity_issue",
                "contract_anomaly",
            }
            expected_terminal = response_classified and (
                evidence.result_row_count + evidence.supplemental_row_count == 0
                or observation["has_more"] is False
            )
            if evidence.terminal_signal is not expected_terminal:
                issues.append("terminal_signal_mismatch")

            committed_success = (
                observation["classification"] == "success"
                and evidence.contract_error is None
                and not observation["identity_issues"]
                and not observation["identity_conflicts"]
            )
            if committed_success:
                seen_job_ids.update(all_job_ids)
                if variant.pagination_mode == "response-cursor":
                    if evidence.cursor_output is None:
                        issues.append("missing_cursor_output")
                    else:
                        if (
                            evidence.cursor_input is not None
                            and evidence.cursor_input.session_id_hash
                            != evidence.cursor_output.session_id_hash
                        ):
                            issues.append("session_rollover")
                        last_successful_output = evidence.cursor_output
                if awaiting_empty_confirmation:
                    if evidence.result_row_count + evidence.supplemental_row_count:
                        issues.append("nonempty_confirmation")
                elif evidence.terminal_signal:
                    awaiting_empty_confirmation = True
            elif (
                evidence.cursor_output is not None
                and observation["classification"]
                not in {"success", "contract_anomaly"}
            ):
                issues.append("failed_attempt_advanced_cursor")
            if (
                evidence.awaiting_empty_confirmation
                is not awaiting_empty_confirmation
            ):
                issues.append("empty_confirmation_state_mismatch")

            previous = (observation, evidence, _condition)

        logical_page_count = len(logical_contexts)
        if logical_page_count > BAKEOFF_MAX_LOGICAL_PAGES_PER_CONDITION:
            issues.append("condition_logical_page_budget_exceeded")
        if any(len(values) != 1 for values in logical_contexts.values()):
            issues.append("retry_browser_context_changed")
        if variant.browser_lifecycle == "restart-each-page":
            logical_page_contexts = [next(iter(values)) for values in logical_contexts.values()]
            if len(logical_page_contexts) != len(set(logical_page_contexts)):
                issues.append("restart_each_page_context_reused")
        else:
            if any(len(values) != 1 for values in contexts_by_restart.values()):
                issues.append("runtime_context_changed_within_chain")
            chain_contexts = [
                next(iter(contexts_by_restart[index]))
                for index in sorted(contexts_by_restart)
                if contexts_by_restart[index]
            ]
            if len(chain_contexts) != len(set(chain_contexts)):
                issues.append("browser_restart_context_reused")
            if variant.browser_lifecycle == "condition-local-runtime":
                for context_hash in chain_contexts:
                    if context_hash in condition_contexts_seen:
                        issues.append("condition_runtime_context_reused")
                    condition_contexts_seen.add(context_hash)
            else:
                first_context = chain_contexts[0] if chain_contexts else None
                current_context = shared_current_context.get(variant.variant_id)
                if current_context is not None and first_context != current_context:
                    issues.append("shared_runtime_context_mismatch")
                if chain_contexts:
                    shared_current_context[variant.variant_id] = chain_contexts[-1]

        final_observation, final_evidence, _ = observations[-1]
        if execution["is_complete"]:
            if (
                execution["stop_reason"] != "natural_exhaustion"
                or final_observation["stop_reason"] != "natural_exhaustion"
                or not final_evidence.awaiting_empty_confirmation
                or final_evidence.result_row_count
                + final_evidence.supplemental_row_count
                != 0
                or not final_evidence.terminal_signal
            ):
                issues.append("invalid_natural_exhaustion")
        else:
            if execution["stop_reason"] == "natural_exhaustion":
                issues.append("invalid_incomplete_stop_reason")
            if (
                final_observation["stop_reason"] is not None
                and final_observation["stop_reason"] != execution["stop_reason"]
            ):
                issues.append("condition_stop_reason_mismatch")
            if (
                final_observation["stop_reason"] is None
                and execution["stop_reason"] != "page_cap"
            ):
                issues.append("missing_condition_stop_reason")
        expected_gap_count = int(execution["stop_reason"] == "unresolved_gap")
        if execution["gap_count"] != expected_gap_count:
            issues.append("gap_count_mismatch")
        if execution["identity_issue_count"] != sum(
            len(item[0]["identity_issues"]) for item in observations
        ):
            issues.append("identity_issue_count_mismatch")
        if execution["identity_conflict_count"] != sum(
            len(item[0]["identity_conflicts"]) for item in observations
        ):
            issues.append("identity_conflict_count_mismatch")


def recompute_pagination_bakeoff_summaries(
    bakeoff_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Decode and replay a v2 bake-off payload without trusting its summaries."""

    validate_bakeoff_payload(bakeoff_payload)
    issues: list[str] = []
    decoded_executions = _decode_executions(bakeoff_payload, issues)
    _validate_cursor_chains(decoded_executions, issues)
    if issues:
        raise ValueError(
            "invalid pagination bake-off replay: "
            + ",".join(dict.fromkeys(issues))
        )
    return _recompute_variant_summaries(decoded_executions)


def _verify_bakeoff(artifact_dir, manifest, events):
    issues: list[str] = []
    metadata = manifest.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    run_id = manifest.get("run_id")
    try:
        bakeoff_payload = json.loads(
            (artifact_dir / "bakeoff.json").read_text(encoding="utf-8")
        )
        validate_bakeoff_payload(bakeoff_payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return PaginationArtifactVerification(
            valid=False,
            issues=(f"invalid_bakeoff_payload:{type(exc).__name__}",),
            experiment="cursor-pagination-bakeoff-v2",
            run_id=run_id if isinstance(run_id, str) else None,
        )
    if metadata.get("crawl_job_id") != run_id:
        issues.append("crawl_job_id_run_id_mismatch")
    expected_crawl_job_status = (
        "completed" if bakeoff_payload["status"] == "completed" else "failed"
    )
    if metadata.get("crawl_job_status") != expected_crawl_job_status:
        issues.append("invalid_bakeoff_status")
    if metadata.get("repeat_index") != bakeoff_payload["repeat_index"]:
        issues.append("repeat_index_mismatch")
    if metadata.get("order_seed") != bakeoff_payload["order_seed"]:
        issues.append("order_seed_mismatch")
    if metadata.get("request_budget") != PAGINATION_BAKEOFF_REQUEST_BUDGET:
        issues.append("invalid_bakeoff_request_budget")
    if metadata.get("product_data_unchanged") is not True:
        issues.append("product_data_changed")
    parent_artifact_hash = metadata.get("parent_artifact_hash")
    baseline_artifact_hashes = metadata.get("baseline_artifact_hashes")
    baseline_run_ids = metadata.get("baseline_run_ids")
    if (
        not _is_sha256(parent_artifact_hash)
        or metadata.get("baseline_artifact_hash") != parent_artifact_hash
        or not isinstance(baseline_artifact_hashes, list)
        or len(baseline_artifact_hashes) != 2
        or any(not _is_sha256(value) for value in baseline_artifact_hashes)
        or len(set(baseline_artifact_hashes)) != 2
        or baseline_artifact_hashes[-1] != parent_artifact_hash
        or not isinstance(baseline_run_ids, list)
        or len(baseline_run_ids) != 2
        or any(not isinstance(value, str) or not value for value in baseline_run_ids)
        or len(set(baseline_run_ids)) != 2
        or not _is_sha256(metadata.get("baseline_snapshot_hash"))
        or not _is_sha256(metadata.get("baseline_inventory_hash"))
    ):
        issues.append("invalid_bakeoff_baseline_evidence")
    _validate_event_sequence(events, issues)
    if _FORBIDDEN_CURSOR_KEY_RE.search(
        json.dumps(
            {"manifest": manifest, "events": events, "bakeoff": bakeoff_payload},
            ensure_ascii=True,
        )
    ):
        issues.append("raw_cursor_session_leak")
    decoded_executions = _decode_executions(bakeoff_payload, issues)
    _validate_cursor_chains(decoded_executions, issues)
    event_types = [event.get("event_type") for event in events]
    expected_event_types = ["research.run_started"]
    for execution in bakeoff_payload["executions"]:
        expected_event_types.extend(
            "research.page_attempt" for _ in execution["observations"]
        )
        expected_event_types.append(
            "research.condition_completed"
            if execution["is_complete"]
            else "research.condition_incomplete"
        )
    expected_event_types.append("research.run_summary")
    if event_types != expected_event_types:
        issues.append("invalid_bakeoff_event_order")
    run_started = events[0].get("payload") if events else None
    if run_started != {
        "experiment": "cursor-pagination-bakeoff-v2",
        "repeat_index": bakeoff_payload["repeat_index"],
        "order_seed": bakeoff_payload["order_seed"],
        "condition_count": 15,
        "request_budget": PAGINATION_BAKEOFF_REQUEST_BUDGET,
        "endpoint": BAKEOFF_ENDPOINT,
        "rcd_type": BAKEOFF_RCD_TYPE,
        "category_ids": list(BAKEOFF_CATEGORY_IDS),
        "controls": pagination_bakeoff_controls_payload(),
        "thresholds": pagination_bakeoff_thresholds_payload(),
    }:
        issues.append("invalid_run_started")
    summaries = [
        event.get("payload")
        for event in events
        if event.get("event_type") == "research.run_summary"
    ]
    if len(summaries) != 1 or not isinstance(summaries[0], dict):
        issues.append("invalid_run_summary_count")
        summary = {}
    else:
        summary = summaries[0]
    page_payloads = [
        event.get("payload")
        for event in events
        if event.get("event_type") == "research.page_attempt"
    ]
    expected_page_payloads = [
        observation
        for execution in bakeoff_payload["executions"]
        for observation in execution["observations"]
    ]
    if page_payloads != expected_page_payloads:
        issues.append("bakeoff_event_payload_mismatch")
    expected_stage_calls = sum(
        1
        for execution in bakeoff_payload["executions"]
        if execution["is_complete"]
        for observation in execution["observations"]
        if observation.get("classification") == "success"
        and observation.get("rows")
    )
    expected_would_stage_rows = sum(
        len(observation["rows"])
        for execution in bakeoff_payload["executions"]
        if execution["is_complete"]
        for observation in execution["observations"]
        if observation.get("classification") == "success"
        and isinstance(observation.get("rows"), list)
    )
    condition_events = [
        event
        for event in events
        if event.get("event_type")
        in {"research.condition_completed", "research.condition_incomplete"}
    ]
    if len(condition_events) != len(bakeoff_payload["executions"]):
        issues.append("invalid_condition_event_count")
    else:
        expected_condition_payloads = []
        for execution in bakeoff_payload["executions"]:
            first = execution["observations"][0]
            expected_condition_payloads.append(
                {
                    "condition": {
                        "search_family": first["search_family"],
                        "category_id": first["category_id"],
                        "keyword": first["keyword"],
                        "endpoint": first["endpoint"],
                        "rcd_type": first["rcd_type"],
                    },
                    "pages_observed": sum(
                        item["classification"] == "success"
                        for item in execution["observations"]
                    ),
                    "stop_reason": execution["stop_reason"],
                    "is_complete": execution["is_complete"],
                }
            )
        if [event.get("payload") for event in condition_events] != (
            expected_condition_payloads
        ):
            issues.append("condition_event_payload_mismatch")
    try:
        recomputed_summaries = _recompute_variant_summaries(decoded_executions)
    except (KeyError, TypeError, ValueError) as exc:
        issues.append(f"variant_summary_replay_failed:{type(exc).__name__}")
        recomputed_summaries = []
    if bakeoff_payload["variant_summaries"] != recomputed_summaries:
        issues.append("variant_summary_mismatch")
    logical_count = len(
        {
            evidence.logical_request_id
            for _execution, _variant, decoded in decoded_executions
            for _observation, evidence, _condition in decoded
        }
    )
    if logical_count > PAGINATION_BAKEOFF_REQUEST_BUDGET["listing_logical"]:
        issues.append("logical_request_budget_exceeded")
    if len(page_payloads) > PAGINATION_BAKEOFF_REQUEST_BUDGET["listing_attempt_max"]:
        issues.append("physical_request_budget_exceeded")
    if any(event_type == "research.detail_attempt" for event_type in event_types):
        issues.append("unexpected_detail_attempt")
    expected_payload_hash = canonical_bakeoff_payload_hash(bakeoff_payload)
    expected_summary_keys = {
        "bakeoff_completed",
        "failure_reason",
        "repeat_index",
        "order_seed",
        "request_budget",
        "logical_listing_requests",
        "physical_listing_attempts",
        "detail_attempts",
        "product_writes",
        "product_data_unchanged",
        "run_start_snapshot_hash",
        "run_end_snapshot_hash",
        "run_start_product_data_hash",
        "run_end_product_data_hash",
        "run_start_inventory_hash",
        "run_end_inventory_hash",
        "would_stage_rows",
        "stage_calls",
        "variant_summaries",
        "bakeoff_payload_hash",
    }
    expected_completed = bakeoff_payload["status"] == "completed"
    if (
        set(summary) != expected_summary_keys
        or summary.get("bakeoff_completed") is not expected_completed
        or summary.get("failure_reason") != bakeoff_payload["failure_reason"]
        or summary.get("repeat_index") != bakeoff_payload["repeat_index"]
        or summary.get("order_seed") != bakeoff_payload["order_seed"]
        or summary.get("product_data_unchanged") is not True
        or summary.get("detail_attempts") != 0
        or summary.get("product_writes") != 0
        or any(
            not _is_sha256(summary.get(field_name))
            for field_name in (
                "run_start_snapshot_hash",
                "run_end_snapshot_hash",
                "run_start_product_data_hash",
                "run_end_product_data_hash",
                "run_start_inventory_hash",
                "run_end_inventory_hash",
            )
        )
        or summary.get("run_start_snapshot_hash")
        != summary.get("run_end_snapshot_hash")
        or summary.get("run_start_product_data_hash")
        != summary.get("run_end_product_data_hash")
        or summary.get("run_start_inventory_hash")
        != summary.get("run_end_inventory_hash")
        or summary.get("run_start_snapshot_hash")
        != metadata.get("baseline_snapshot_hash")
        or summary.get("run_start_inventory_hash")
        != metadata.get("baseline_inventory_hash")
        or summary.get("logical_listing_requests") != logical_count
        or summary.get("physical_listing_attempts") != len(page_payloads)
        or summary.get("request_budget") != PAGINATION_BAKEOFF_REQUEST_BUDGET
        or summary.get("bakeoff_payload_hash") != expected_payload_hash
        or summary.get("variant_summaries")
        != bakeoff_payload["variant_summaries"]
        or summary.get("would_stage_rows") != expected_would_stage_rows
        or summary.get("stage_calls") != expected_stage_calls
    ):
        issues.append("invalid_bakeoff_summary")
    return PaginationArtifactVerification(
        valid=not issues,
        issues=tuple(dict.fromkeys(issues)),
        experiment="cursor-pagination-bakeoff-v2",
        run_id=run_id if isinstance(run_id, str) else None,
    )


def _input_artifact_evidence(item: Mapping[str, Any]):
    expected_keys = {
        "artifact",
        "manifest_hash",
        "run_id",
        "repeat_index",
        "parent_artifact_hash",
        "baseline_artifact_hashes",
        "baseline_snapshot_hash",
        "baseline_inventory_hash",
        "bakeoff_payload_hash",
    }
    if not isinstance(item, Mapping) or set(item) != expected_keys:
        raise ValueError("comparison input fields do not match")
    artifact_dir = Path(item["artifact"]).resolve(strict=True)
    verification = verify_pagination_artifact(artifact_dir)
    if not verification.valid or verification.experiment != "cursor-pagination-bakeoff-v2":
        raise ValueError("comparison input failed strict verification")
    manifest_bytes = (artifact_dir / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    metadata = manifest.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    payload = json.loads((artifact_dir / "bakeoff.json").read_text(encoding="utf-8"))
    if (
        item["manifest_hash"] != hashlib.sha256(manifest_bytes).hexdigest()
        or item["run_id"] != verification.run_id
        or item["repeat_index"] != payload["repeat_index"]
        or item["parent_artifact_hash"] != metadata.get("parent_artifact_hash")
        or item["baseline_artifact_hashes"]
        != metadata.get("baseline_artifact_hashes")
        or item["baseline_snapshot_hash"]
        != metadata.get("baseline_snapshot_hash")
        or item["baseline_inventory_hash"]
        != metadata.get("baseline_inventory_hash")
        or item["bakeoff_payload_hash"]
        != canonical_bakeoff_payload_hash(payload)
    ):
        raise ValueError("comparison input evidence mismatch")
    return payload


def validate_pagination_comparison_parents(
    inputs: list[Mapping[str, Any]],
) -> None:
    if len(inputs) != 2:
        raise ValueError("pagination comparison requires exactly two parents")
    first, second = inputs
    if [first.get("repeat_index"), second.get("repeat_index")] != [1, 2]:
        raise ValueError("pagination comparison parents must be ordered by repeat")
    if (
        first.get("baseline_snapshot_hash")
        != second.get("baseline_snapshot_hash")
        or first.get("baseline_inventory_hash")
        != second.get("baseline_inventory_hash")
    ):
        raise ValueError("pagination comparison baseline state does not match")
    first_hashes = first.get("baseline_artifact_hashes")
    second_hashes = second.get("baseline_artifact_hashes")
    if (
        not isinstance(first_hashes, list)
        or not isinstance(second_hashes, list)
        or len(first_hashes) != 2
        or len(second_hashes) != 2
        or not set(first_hashes).isdisjoint(second_hashes)
    ):
        raise ValueError(
            "pagination comparison requires four distinct baseline artifacts"
        )


def _verify_comparison(artifact_dir, manifest, events):
    issues: list[str] = []
    metadata = manifest.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    run_id = manifest.get("run_id")
    try:
        payload = json.loads(
            (artifact_dir / "comparison.json").read_text(encoding="utf-8")
        )
        if set(payload) != {
            "schema_version",
            "input_set_hash",
            "inputs",
            "thresholds",
            "decision",
        } or payload["schema_version"] != 2:
            raise ValueError("comparison payload fields do not match")
        if not isinstance(payload["inputs"], list) or len(payload["inputs"]) != 2:
            raise ValueError("comparison requires two inputs")
        inputs = [_input_artifact_evidence(item) for item in payload["inputs"]]
        validate_pagination_comparison_parents(payload["inputs"])
        decision = compare_bakeoff_payloads(inputs[0], inputs[1])
        if payload["decision"] != decision.to_payload():
            raise ValueError("comparison decision mismatch")
        if payload["input_set_hash"] != _canonical_hash(payload["inputs"]):
            raise ValueError("comparison input_set_hash mismatch")
        if payload["thresholds"] != pagination_bakeoff_thresholds_payload():
            raise ValueError("comparison thresholds mismatch")
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        issues.append(f"invalid_pagination_comparison:{type(exc).__name__}")
        payload = {}
        decision = None
    _validate_event_sequence(events, issues)
    if _FORBIDDEN_CURSOR_KEY_RE.search(
        json.dumps(
            {"manifest": manifest, "events": events, "comparison": payload},
            ensure_ascii=True,
        )
    ):
        issues.append("raw_cursor_session_leak")
    if (
        metadata.get("crawl_job_id") != run_id
        or metadata.get("crawl_job_status") != "completed"
        or metadata.get("pagination_passed")
        is not (decision.accepted if decision is not None else None)
        or metadata.get("parent_artifact_hash") != payload.get("input_set_hash")
        or metadata.get("selected_variant_id")
        != (decision.selected_variant_id if decision is not None else None)
    ):
        issues.append("invalid_pagination_comparison_metadata")
    expected_events = (
        (
            "research.run_started",
            {
                "experiment": "cursor-pagination-comparison-v2",
                "input_set_hash": payload.get("input_set_hash"),
            },
        ),
        (
            "research.pagination_comparison",
            decision.to_payload() if decision is not None else None,
        ),
        (
            "research.run_summary",
            {
                "input_set_hash": payload.get("input_set_hash"),
                "decision": decision.to_payload() if decision is not None else None,
            },
        ),
    )
    if [
        (event.get("event_type"), event.get("payload")) for event in events
    ] != list(expected_events):
        issues.append("invalid_pagination_comparison_events")
    return PaginationArtifactVerification(
        valid=not issues,
        issues=tuple(dict.fromkeys(issues)),
        experiment="cursor-pagination-comparison-v2",
        run_id=run_id if isinstance(run_id, str) else None,
    )


def _verify_candidate(artifact_dir, manifest, events):
    issues: list[str] = []
    metadata = manifest.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    run_id = manifest.get("run_id")
    candidate = None
    decision: dict[str, Any] = {}
    try:
        candidate = DiscoveryCandidateV2.from_payload(
            json.loads((artifact_dir / "candidate.json").read_text(encoding="utf-8"))
        )
        comparison_dir = Path(metadata["comparison_artifact"]).resolve(strict=True)
        comparison_check = verify_pagination_artifact(comparison_dir)
        if (
            not comparison_check.valid
            or comparison_check.experiment != "cursor-pagination-comparison-v2"
        ):
            raise ValueError("candidate comparison failed strict verification")
        comparison_manifest_hash = hashlib.sha256(
            (comparison_dir / "manifest.json").read_bytes()
        ).hexdigest()
        comparison_payload = json.loads(
            (comparison_dir / "comparison.json").read_text(encoding="utf-8")
        )
        decision = comparison_payload["decision"]
        accepted_comparisons = [
            item
            for item in decision.get("comparisons", [])
            if isinstance(item, dict) and item.get("accepted") is True
        ]
        selected_variant = next(
            item
            for item in BAKEOFF_VARIANTS
            if item.variant_id == decision["selected_variant_id"]
        )
        if (
            decision["accepted"] is not True
            or len(accepted_comparisons) != 1
            or accepted_comparisons[0].get("variant_id")
            != decision["selected_variant_id"]
            or candidate.endpoint != BAKEOFF_ENDPOINT
            or candidate.rcd_type != BAKEOFF_RCD_TYPE
            or candidate.category_ids != BAKEOFF_CATEGORY_IDS
            or candidate.pagination_mode != selected_variant.pagination_mode
            or candidate.requested_page_size != selected_variant.requested_page_size
            or candidate.browser_lifecycle != selected_variant.browser_lifecycle
            or candidate.terminal_policy != BAKEOFF_TERMINAL_POLICY
            or candidate.max_pages_per_condition
            != BAKEOFF_MAX_LOGICAL_PAGES_PER_CONDITION
            or candidate.require_empty_confirmation
            is not BAKEOFF_REQUIRE_EMPTY_CONFIRMATION
            or candidate.max_attempts_per_page != BAKEOFF_MAX_ATTEMPTS_PER_PAGE
            or candidate.retry_delays_seconds != BAKEOFF_RETRY_DELAYS_SECONDS
            or candidate.page_delay_range_seconds
            != BAKEOFF_PAGE_DELAY_RANGE_SECONDS
            or candidate.session_mode != BAKEOFF_SESSION_MODE
            or candidate.comparison_artifact_hash != comparison_manifest_hash
            or candidate.source_artifact_hash
            != comparison_payload["input_set_hash"]
        ):
            raise ValueError("candidate does not match accepted comparison")
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        StopIteration,
        TypeError,
        ValueError,
    ) as exc:
        issues.append(f"invalid_discovery_candidate:{type(exc).__name__}")
    _validate_event_sequence(events, issues)
    if _FORBIDDEN_CURSOR_KEY_RE.search(
        json.dumps(
            {"manifest": manifest, "events": events},
            ensure_ascii=True,
        )
    ):
        issues.append("raw_cursor_session_leak")
    if (
        candidate is None
        or metadata.get("crawl_job_id") != run_id
        or metadata.get("crawl_job_status") != "completed"
        or metadata.get("candidate_frozen") is not True
        or metadata.get("candidate_hash") != candidate.candidate_hash
        or metadata.get("parent_artifact_hash")
        != candidate.comparison_artifact_hash
        or metadata.get("selected_variant_id")
        != decision.get("selected_variant_id")
    ):
        issues.append("invalid_discovery_candidate_metadata")
    frozen_events = [
        event.get("payload")
        for event in events
        if event.get("event_type") == "research.candidate_frozen"
    ]
    if (
        candidate is None
        or len(frozen_events) != 1
        or frozen_events[0] != candidate.to_payload()
        or [event.get("event_type") for event in events]
        != ["research.candidate_frozen"]
    ):
        issues.append("invalid_discovery_candidate_event")
    return PaginationArtifactVerification(
        valid=not issues,
        issues=tuple(dict.fromkeys(issues)),
        experiment="discovery-candidate-v2",
        run_id=run_id if isinstance(run_id, str) else None,
    )


def verify_pagination_artifact(
    artifact_dir: Path,
) -> PaginationArtifactVerification:
    artifact_dir = Path(artifact_dir)
    generic = verify_research_artifact(artifact_dir)
    if not generic.valid:
        issues = [
            *(f"missing_artifact_file:{name}" for name in generic.missing_files),
            *(f"mismatched_artifact_file:{name}" for name in generic.mismatched_files),
        ]
        return PaginationArtifactVerification(
            valid=False,
            issues=tuple(issues or ["invalid_research_artifact"]),
            experiment=None,
            run_id=None,
        )
    try:
        manifest, events = _load_artifact(artifact_dir)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return PaginationArtifactVerification(
            valid=False,
            issues=(f"invalid_pagination_artifact_json:{type(exc).__name__}",),
            experiment=None,
            run_id=None,
        )
    if any(not isinstance(event, dict) for event in events):
        return PaginationArtifactVerification(
            valid=False,
            issues=("invalid_event_object",),
            experiment=None,
            run_id=None,
        )
    metadata = manifest.get("metadata")
    experiment = metadata.get("experiment") if isinstance(metadata, dict) else None
    if experiment == "cursor-pagination-bakeoff-v2":
        return _verify_bakeoff(artifact_dir, manifest, events)
    if experiment == "cursor-pagination-comparison-v2":
        return _verify_comparison(artifact_dir, manifest, events)
    if experiment == "discovery-candidate-v2":
        return _verify_candidate(artifact_dir, manifest, events)
    return PaginationArtifactVerification(
        valid=False,
        issues=("unsupported_pagination_experiment",),
        experiment=experiment if isinstance(experiment, str) else None,
        run_id=manifest.get("run_id") if isinstance(manifest.get("run_id"), str) else None,
    )
