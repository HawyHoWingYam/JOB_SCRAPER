#!/usr/bin/env python3
"""Stage-gated live OfferToday Plan 2 research commands."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

BACKEND = str(Path(__file__).resolve().parents[1])
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from app.database import SessionLocal  # noqa: E402
from app.repositories.offertoday_research_repository import (  # noqa: E402
    OfferTodayResearchRepository,
)
from app.scraper.offertoday_browser_runtime import (  # noqa: E402
    OfferTodayBrowserRuntime,
)
from app.services.crawl_job_runtime import CrawlJobRuntime  # noqa: E402
from app.services.offertoday_research_live_service import (  # noqa: E402
    OfferTodayResearchLiveService,
)
from app.services.offertoday_research_observation_service import (  # noqa: E402
    OfferTodayResearchObservationService,
)
from app.services.offertoday_research_staging_service import (  # noqa: E402
    OfferTodayReconciledListingStagingSink,
)
from app.sources.offertoday.listing_runner import (  # noqa: E402
    listing_observation_to_payload,
)
from app.sources.offertoday.research.artifacts import (  # noqa: E402
    capture_research_provenance,
    export_research_artifact,
    verify_research_artifact,
)
from app.sources.offertoday.research.baseline import (  # noqa: E402
    build_baseline_snapshot,
    build_run_start_inventory,
)
from app.sources.offertoday.research.calibration import (  # noqa: E402
    build_calibration_conditions,
    build_pilot_conditions,
    select_calibration_variants,
    summarize_calibration_variants,
)
from app.sources.offertoday.research.contracts import ResearchMetadata  # noqa: E402
from app.sources.offertoday.research.smoke import (  # noqa: E402
    runtime_smoke_request_budget,
)
from app.sources.offertoday.research.stage_gate import (  # noqa: E402
    MatchingBaselineGate,
    require_matching_baselines,
    verify_live_research_run,
)
from app.utils.time import utc_now  # noqa: E402

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INCOMPLETE = 3
EXIT_HARD_STOP = 4
EXIT_EVIDENCE_FAILURE = 5

_HARD_STOP_REASONS = {
    "auth_expired",
    "waf_challenge",
    "ip_blocked",
    "id_mismatch",
    "listing_auth_expired",
    "listing_waf_challenge",
    "listing_ip_blocked",
    "listing_id_mismatch",
}
_CALIBRATION_REQUEST_BUDGET = {
    "listing_logical": 24,
    "listing_attempt_max": 72,
    "detail": 0,
}
_PILOT_REQUEST_BUDGET = {
    "listing_logical": 93,
    "listing_attempt_max": 279,
    "detail": 0,
}


@dataclass(frozen=True, slots=True)
class PilotVariantEvidence:
    endpoint: str
    rcd_type: int | None
    variant_rank: int
    parent_artifact_hash: str
    calibration_run_id: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live OfferToday Plan 2 research")
    commands = parser.add_subparsers(dest="command", required=True)
    smoke = commands.add_parser("smoke")
    smoke.add_argument(
        "--baseline-artifact",
        action="append",
        type=Path,
        required=True,
    )
    smoke.add_argument("--run-id", default=None)
    smoke.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    smoke.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    calibrate = commands.add_parser("calibrate")
    calibrate.add_argument("--smoke-artifact", type=Path, required=True)
    calibrate.add_argument(
        "--baseline-artifact",
        action="append",
        type=Path,
        required=True,
    )
    calibrate.add_argument("--run-id", default=None)
    calibrate.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    calibrate.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    pilot = commands.add_parser("pilot")
    pilot.add_argument("--calibration-artifact", type=Path, required=True)
    pilot.add_argument(
        "--baseline-artifact",
        action="append",
        type=Path,
        required=True,
    )
    pilot.add_argument("--variant-rank", type=int, default=1)
    pilot.add_argument("--run-id", default=None)
    pilot.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    pilot.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    verify = commands.add_parser("verify-run")
    verify.add_argument("--artifact", type=Path, required=True)
    return parser


def _print_json(value: dict[str, Any], *, stream=None) -> None:
    print(json.dumps(value, ensure_ascii=True, sort_keys=True), file=stream)


def _require_accepted_smoke_artifact(artifact_dir: Path) -> dict[str, Any]:
    verification = verify_live_research_run(artifact_dir)
    if not verification.valid:
        raise ValueError("smoke artifact failed strict verification")
    manifest_path = Path(artifact_dir) / "manifest.json"
    observations_path = Path(artifact_dir) / "observations.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summaries = [
        event.get("payload")
        for line in observations_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        and (event := json.loads(line)).get("event_type") == "research.run_summary"
    ]
    expected_budget = runtime_smoke_request_budget()
    metadata = manifest.get("metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("crawl_job_status") != "completed"
        or metadata.get("smoke_passed") is not True
        or metadata.get("request_budget") != expected_budget
        or len(summaries) != 1
        or not isinstance(summaries[0], dict)
        or summaries[0].get("smoke_passed") is not True
        or summaries[0].get("request_budget") != expected_budget
    ):
        raise ValueError("smoke artifact is not an accepted 2/20 predecessor")
    return manifest


def _require_accepted_calibration_variant(
    artifact_dir: Path,
    *,
    variant_rank: int,
) -> PilotVariantEvidence:
    if type(variant_rank) is not int or variant_rank < 1:
        raise ValueError("selected variant rank must be a positive exact integer")
    artifact_dir = Path(artifact_dir)
    verification = verify_live_research_run(artifact_dir)
    if not verification.valid:
        raise ValueError("calibration artifact failed strict verification")
    manifest_bytes = (artifact_dir / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    observations = [
        json.loads(line)
        for line in (artifact_dir / "observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    metadata = manifest.get("metadata")
    summaries = [
        event.get("payload")
        for event in observations
        if isinstance(event, dict) and event.get("event_type") == "research.run_summary"
    ]
    if (
        not isinstance(metadata, dict)
        or metadata.get("experiment") != "listing-calibration"
        or metadata.get("crawl_job_status") != "completed"
        or metadata.get("calibration_passed") is not True
        or len(summaries) != 1
        or not isinstance(summaries[0], dict)
        or summaries[0].get("calibration_passed") is not True
    ):
        raise ValueError("calibration artifact is not an accepted predecessor")
    selection = summaries[0].get("selection")
    selected_variants = (
        selection.get("selected_variants") if isinstance(selection, dict) else None
    )
    if not isinstance(selected_variants, list) or variant_rank > len(selected_variants):
        raise ValueError("selected variant rank is not present in calibration artifact")
    selected = selected_variants[variant_rank - 1]
    if not isinstance(selected, dict) or selected.get("accepted") is not True:
        raise ValueError("selected variant rank is not accepted")
    endpoint = selected.get("endpoint")
    rcd_type = selected.get("rcd_type")
    if not isinstance(endpoint, str) or (
        rcd_type is not None and type(rcd_type) is not int
    ):
        raise ValueError("selected calibration variant controls are invalid")
    build_pilot_conditions(endpoint, rcd_type)
    calibration_run_id = manifest.get("run_id")
    if not isinstance(calibration_run_id, str):
        raise ValueError("calibration artifact is missing run_id")
    return PilotVariantEvidence(
        endpoint=endpoint,
        rcd_type=rcd_type,
        variant_rank=variant_rank,
        parent_artifact_hash=hashlib.sha256(manifest_bytes).hexdigest(),
        calibration_run_id=calibration_run_id,
    )


def _event_dict(event: Any) -> dict[str, Any]:
    created_at = event.created_at
    return {
        "sequence_no": int(event.sequence_no),
        "event_type": str(event.event_type),
        "payload": listing_observation_to_payload(event.payload or {}),
        "emitted_by": event.emitted_by,
        "created_at": (
            created_at.isoformat()
            if hasattr(created_at, "isoformat")
            else str(created_at)
        ),
    }


def _ordered_events(events: list[Any]) -> list[dict[str, Any]]:
    return [
        _event_dict(event)
        for event in sorted(events, key=lambda item: int(item.sequence_no))
    ]


def _capture_snapshot(repository, db):
    listings = repository.list_staged_snapshots(db)
    jobs = repository.list_published_snapshots(db)
    product_data = repository.capture_product_data_snapshot(db)
    return (
        build_baseline_snapshot(
            listings=listings,
            jobs=jobs,
            product_data=product_data,
        ),
        build_run_start_inventory(listings=listings, jobs=jobs),
    )


def _snapshot_counts(snapshot) -> tuple[tuple[str, int], ...]:
    payload = asdict(snapshot)
    return tuple(
        (key, payload[key])
        for key in (
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
    )


def _require_current_baseline(
    baseline_gate: MatchingBaselineGate,
    snapshot,
    inventory,
) -> None:
    if snapshot.data_hash != baseline_gate.second.snapshot_hash:
        raise ValueError("run-start snapshot differs from the verified baselines")
    if inventory.data_hash != baseline_gate.second.inventory_hash:
        raise ValueError("run-start inventory differs from the verified baselines")
    if _snapshot_counts(snapshot) != baseline_gate.second.counts:
        raise ValueError("run-start counts differ from the verified baselines")


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


async def _execute_smoke_with_runtime(
    *,
    runtime_factory,
    service,
    observation_service,
):
    runtime = runtime_factory(headed=False)
    async with runtime as active_runtime:
        return await service.run_smoke(
            runtime=active_runtime,
            observation_service=observation_service,
        )


async def _execute_calibration_with_runtime(
    *,
    runtime_factory,
    service,
    observation_service,
):
    runtime = runtime_factory(headed=False)
    async with runtime as active_runtime:
        return await service.run_bounded_conditions(
            runtime=active_runtime,
            observation_service=observation_service,
            conditions=build_calibration_conditions(),
        )


async def _execute_pilot_with_runtime(
    *,
    runtime_factory,
    service,
    observation_service,
    conditions,
    staging_sink,
):
    runtime = runtime_factory(headed=False)
    async with runtime as active_runtime:
        return await service.run_bounded_conditions(
            runtime=active_runtime,
            observation_service=observation_service,
            conditions=conditions,
            staging_sink=staging_sink,
        )


def _event_counts(events: list[dict[str, Any]]) -> tuple[int, int, int]:
    listing_attempts = sum(
        event.get("event_type") == "research.page_attempt" for event in events
    )
    detail_attempts = sum(
        event.get("event_type") == "research.detail_attempt" for event in events
    )
    frozen_counts = [
        event.get("payload", {}).get("count")
        for event in events
        if event.get("event_type") == "research.detail_cohort_frozen"
        and isinstance(event.get("payload"), dict)
    ]
    frozen_count = frozen_counts[-1] if frozen_counts else 0
    if type(frozen_count) is not int or frozen_count < 0:
        frozen_count = 0
    return listing_attempts, detail_attempts, frozen_count


def _listing_identity_counts(
    *,
    execution,
    events_before_summary: list[dict[str, Any]],
) -> tuple[int, int]:
    if execution is not None:
        page_payloads = [
            listing_observation_to_payload(observation)
            for observation in execution.listing_result.observations
        ]
    else:
        page_payloads = [
            event["payload"]
            for event in events_before_summary
            if event.get("event_type") == "research.page_attempt"
            and isinstance(event.get("payload"), dict)
        ]

    def total(field_name: str) -> int:
        values = [payload.get(field_name, 0) for payload in page_payloads]
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError(
                f"research page {field_name} must be a non-negative exact integer"
            )
        return sum(values)

    return (
        total("missing_encrypted_job_id_count"),
        total("job_id_fallback_count"),
    )


def _build_summary(
    *,
    status: str,
    start_snapshot,
    start_inventory,
    end_snapshot,
    end_inventory,
    execution,
    events_before_summary: list[dict[str, Any]],
    failure_reason: str | None,
    request_budget: dict[str, int],
) -> dict[str, Any]:
    listing_attempts, detail_attempts, event_frozen_count = _event_counts(
        events_before_summary
    )
    missing_encrypted_job_id_count, job_id_fallback_count = _listing_identity_counts(
        execution=execution,
        events_before_summary=events_before_summary,
    )
    product_data_unchanged = (
        start_snapshot.data_hash == end_snapshot.data_hash
        and start_inventory.data_hash == end_inventory.data_hash
    )
    if execution is None:
        smoke_passed = False
        listing_complete = False
        expected_truncation = False
        frozen_count = event_frozen_count
        success_count = sum(
            event.get("payload", {}).get("classification") == "success"
            for event in events_before_summary
            if event.get("event_type") == "research.detail_attempt"
            and isinstance(event.get("payload"), dict)
        )
        terminal_count = sum(
            event.get("payload", {}).get("classification") == "terminal_unavailable"
            for event in events_before_summary
            if event.get("event_type") == "research.detail_attempt"
            and isinstance(event.get("payload"), dict)
        )
        unattempted_count = max(0, frozen_count - detail_attempts)
        listing_stop_reason = failure_reason
        would_stage_rows = 0
        stage_calls = 0
    else:
        decision = execution.decision
        smoke_passed = decision.smoke_passed and product_data_unchanged
        listing_complete = execution.listing_result.is_complete
        expected_truncation = decision.expected_truncation
        frozen_count = decision.frozen_count
        success_count = decision.success_count
        terminal_count = decision.terminal_count
        unattempted_count = decision.unattempted_count
        listing_stop_reason = execution.listing_result.stop_reason
        failure_reason = failure_reason or decision.stop_reason
        would_stage_rows = execution.would_stage_rows
        stage_calls = execution.stage_calls
    return {
        "status": status,
        "smoke_passed": smoke_passed,
        "listing_complete": listing_complete,
        "expected_truncation": expected_truncation,
        "frozen_count": frozen_count,
        "attempted_count": detail_attempts,
        "success_count": success_count,
        "terminal_count": terminal_count,
        "unattempted_count": unattempted_count,
        "missing_encrypted_job_id_count": missing_encrypted_job_id_count,
        "job_id_fallback_count": job_id_fallback_count,
        "listing_attempt_count": listing_attempts,
        "listing_stop_reason": listing_stop_reason,
        "stop_reason": failure_reason,
        "request_budget": dict(request_budget),
        "would_stage_rows": would_stage_rows,
        "stage_calls": stage_calls,
        "product_data_unchanged": product_data_unchanged,
        "run_start_snapshot_hash": start_snapshot.data_hash,
        "run_end_snapshot_hash": end_snapshot.data_hash,
        "run_start_product_data_hash": start_snapshot.product_data_hash,
        "run_end_product_data_hash": end_snapshot.product_data_hash,
        "run_start_inventory_hash": start_inventory.data_hash,
        "run_end_inventory_hash": end_inventory.data_hash,
    }


def _calibration_page_counts(
    *,
    results,
    events_before_summary: list[dict[str, Any]],
) -> tuple[int, int]:
    if results is not None:
        page_payloads = [
            listing_observation_to_payload(observation)
            for result in results
            for observation in result.listing_result.observations
        ]
    else:
        page_payloads = [
            event["payload"]
            for event in events_before_summary
            if event.get("event_type") == "research.page_attempt"
            and isinstance(event.get("payload"), dict)
        ]
    logical_pages = {
        (payload.get("condition_id"), payload.get("page"))
        for payload in page_payloads
        if isinstance(payload.get("condition_id"), str)
        and type(payload.get("page")) is int
        and payload.get("page") > 0
    }
    return len(logical_pages), len(page_payloads)


def _calibration_analysis(results) -> tuple[bool, str | None, list[dict], dict | None]:
    locked_conditions = build_calibration_conditions()
    variant_summaries = summarize_calibration_variants(results or ())
    variant_payloads = [asdict(item) for item in variant_summaries]
    selection_payload = None
    try:
        selection_payload = asdict(
            select_calibration_variants(variant_summaries, limit=2)
        )
    except ValueError:
        pass

    exact_matrix = (
        results is not None
        and tuple(item.condition for item in results) == locked_conditions
    )
    all_accepted = bool(results) and all(item.accepted for item in results)
    calibration_passed = exact_matrix and all_accepted and selection_payload is not None
    if calibration_passed:
        failure_reason = None
    else:
        rejected = next(
            (
                item.rejection_reason
                for item in (results or ())
                if not item.accepted and item.rejection_reason
            ),
            None,
        )
        failure_reason = rejected or "calibration_incomplete"
        if failure_reason.startswith("batch_stop:"):
            failure_reason = failure_reason.split(":", 1)[1]
    return (
        calibration_passed,
        failure_reason,
        variant_payloads,
        selection_payload,
    )


def _build_calibration_summary(
    *,
    status: str,
    start_snapshot,
    start_inventory,
    end_snapshot,
    end_inventory,
    results,
    events_before_summary: list[dict[str, Any]],
    failure_reason: str | None,
    request_budget: dict[str, int],
) -> dict[str, Any]:
    logical_count, attempt_count = _calibration_page_counts(
        results=results,
        events_before_summary=events_before_summary,
    )
    detail_attempt_count = sum(
        event.get("event_type") == "research.detail_attempt"
        for event in events_before_summary
    )
    (
        calibration_passed,
        analysis_failure_reason,
        variant_summaries,
        selection,
    ) = _calibration_analysis(results)
    product_data_unchanged = (
        start_snapshot.data_hash == end_snapshot.data_hash
        and start_inventory.data_hash == end_inventory.data_hash
    )
    calibration_passed = (
        calibration_passed
        and status == "completed"
        and failure_reason is None
        and product_data_unchanged
        and detail_attempt_count == 0
    )
    condition_count = (
        len(results)
        if results is not None
        else sum(
            event.get("event_type")
            in {"research.condition_completed", "research.condition_incomplete"}
            for event in events_before_summary
        )
    )
    accepted_condition_count = sum(item.accepted for item in (results or ()))
    return {
        "status": status,
        "calibration_passed": calibration_passed,
        "condition_count": condition_count,
        "accepted_condition_count": accepted_condition_count,
        "listing_logical_count": logical_count,
        "listing_attempt_count": attempt_count,
        "detail_attempt_count": detail_attempt_count,
        "stop_reason": failure_reason or analysis_failure_reason,
        "request_budget": dict(request_budget),
        "variant_summaries": variant_summaries,
        "selection": selection,
        "product_data_unchanged": product_data_unchanged,
        "run_start_snapshot_hash": start_snapshot.data_hash,
        "run_end_snapshot_hash": end_snapshot.data_hash,
        "run_start_product_data_hash": start_snapshot.product_data_hash,
        "run_end_product_data_hash": end_snapshot.product_data_hash,
        "run_start_inventory_hash": start_inventory.data_hash,
        "run_end_inventory_hash": end_inventory.data_hash,
    }


def _pilot_analysis(
    *,
    results,
    conditions,
    reconciliation,
) -> tuple[bool, str | None]:
    if results is None:
        return False, "pilot_condition_matrix_mismatch"
    result_conditions = tuple(item.condition for item in results)
    if result_conditions != tuple(conditions[: len(result_conditions)]):
        return False, "pilot_condition_matrix_mismatch"
    rejected = next((item for item in results if not item.accepted), None)
    if rejected is not None:
        reason = rejected.rejection_reason or "pilot_condition_rejected"
        if reason.startswith("batch_stop:"):
            reason = reason.split(":", 1)[1]
        return False, reason
    if len(results) != len(conditions):
        return False, "pilot_condition_matrix_mismatch"
    if reconciliation.deferred_identity_conflict_ids:
        return False, "deferred_identity_conflict"
    if not reconciliation.staging_amplification_within_limit:
        return False, "staging_amplification"
    return True, None


def _build_pilot_summary(
    *,
    status: str,
    start_snapshot,
    start_inventory,
    end_snapshot,
    end_inventory,
    results,
    conditions,
    events_before_summary: list[dict[str, Any]],
    failure_reason: str | None,
    request_budget: dict[str, int],
    variant: PilotVariantEvidence,
    reconciliation,
) -> dict[str, Any]:
    logical_count, attempt_count = _calibration_page_counts(
        results=results,
        events_before_summary=events_before_summary,
    )
    detail_attempt_count = sum(
        event.get("event_type") == "research.detail_attempt"
        for event in events_before_summary
    )
    condition_count = (
        len(results)
        if results is not None
        else sum(
            event.get("event_type")
            in {"research.condition_completed", "research.condition_incomplete"}
            for event in events_before_summary
        )
    )
    accepted_condition_count = sum(item.accepted for item in (results or ()))
    pilot_accepted, analysis_failure_reason = _pilot_analysis(
        results=results,
        conditions=conditions,
        reconciliation=reconciliation,
    )
    staged_rows_delta = end_snapshot.staged_rows - start_snapshot.staged_rows
    conservation_difference = staged_rows_delta - reconciliation.rows_created
    published_jobs_unchanged = (
        start_snapshot.published_jobs == end_snapshot.published_jobs
        and start_snapshot.published_jobs_hash == end_snapshot.published_jobs_hash
    )
    companies_unchanged = start_snapshot.companies_hash == end_snapshot.companies_hash
    pilot_passed = (
        pilot_accepted
        and status == "completed"
        and failure_reason is None
        and detail_attempt_count == 0
        and conservation_difference == 0
        and published_jobs_unchanged
        and companies_unchanged
    )
    return {
        "status": status,
        "pilot_passed": pilot_passed,
        "planned_condition_count": len(conditions),
        "condition_count": condition_count,
        "accepted_condition_count": accepted_condition_count,
        "planned_listing_logical_count": request_budget["listing_logical"],
        "listing_logical_count": logical_count,
        "listing_attempt_count": attempt_count,
        "detail_attempt_count": detail_attempt_count,
        "variant_rank": variant.variant_rank,
        "endpoint": variant.endpoint,
        "rcd_type": variant.rcd_type,
        "calibration_run_id": variant.calibration_run_id,
        "stop_reason": failure_reason or analysis_failure_reason,
        "request_budget": dict(request_budget),
        "reconciliation": reconciliation.to_payload(),
        "staged_rows_delta": staged_rows_delta,
        "conservation_difference": conservation_difference,
        "published_jobs_unchanged": published_jobs_unchanged,
        "companies_unchanged": companies_unchanged,
        "run_start_snapshot_hash": start_snapshot.data_hash,
        "run_end_snapshot_hash": end_snapshot.data_hash,
        "run_start_product_data_hash": start_snapshot.product_data_hash,
        "run_end_product_data_hash": end_snapshot.product_data_hash,
        "run_start_inventory_hash": start_inventory.data_hash,
        "run_end_inventory_hash": end_inventory.data_hash,
    }


def _unexpected_error_message(
    error: BaseException,
    *,
    experiment: str = "runtime-smoke",
) -> str:
    prefix = (
        "unexpected_listing_calibration_error"
        if experiment == "listing-calibration"
        else (
            "unexpected_category_pilot_error"
            if experiment == "category-pilot"
            else "unexpected_live_smoke_error"
        )
    )
    return f"{prefix}:{type(error).__name__}"


def _summary_event(
    events_before_summary: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "sequence_no": len(events_before_summary) + 1,
        "event_type": "research.run_summary",
        "payload": listing_observation_to_payload(summary),
        "emitted_by": "offertoday-research",
        "created_at": utc_now().isoformat(),
    }


def _best_effort_finalize_unexpected_failure(
    *,
    db,
    repository,
    observation_service,
    run_id: str,
    error: BaseException,
    start_snapshot,
    start_inventory,
    end_snapshot,
    end_inventory,
    fallback_events: list[dict[str, Any]],
    request_budget: dict[str, int],
    experiment: str = "runtime-smoke",
    pilot_variant: PilotVariantEvidence | None = None,
    pilot_conditions=(),
    pilot_reconciliation=None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    error_message = _unexpected_error_message(error, experiment=experiment)
    product_data_evidence_complete = (
        end_snapshot is not None and end_inventory is not None
    )
    if not product_data_evidence_complete:
        try:
            end_snapshot, end_inventory = _capture_snapshot(repository, db)
            product_data_evidence_complete = True
        except BaseException as snapshot_error:
            error.add_note(
                "run-end evidence capture also failed: "
                f"{type(snapshot_error).__name__}"
            )
            end_snapshot = start_snapshot
            end_inventory = start_inventory

    try:
        current_events = _ordered_events(
            repository.list_research_events(db, UUID(run_id))
        )
    except BaseException as event_error:
        error.add_note(
            "partial event loading also failed: " f"{type(event_error).__name__}"
        )
        current_events = list(fallback_events)

    has_terminal_summary = any(
        event.get("event_type") == "research.run_summary" for event in current_events
    )
    if not has_terminal_summary:
        try:
            observation_service.record_event(
                "research.run_stopped",
                {"reason": error_message},
            )
            current_events = _ordered_events(
                repository.list_research_events(db, UUID(run_id))
            )
        except BaseException as stop_error:
            error.add_note(
                "failure stop event persistence also failed: "
                f"{type(stop_error).__name__}"
            )

    if (
        experiment == "category-pilot"
        and pilot_variant is not None
        and pilot_reconciliation is not None
    ):
        summary = _build_pilot_summary(
            status="failed",
            start_snapshot=start_snapshot,
            start_inventory=start_inventory,
            end_snapshot=end_snapshot,
            end_inventory=end_inventory,
            results=None,
            conditions=pilot_conditions,
            events_before_summary=current_events,
            failure_reason=error_message,
            request_budget=request_budget,
            variant=pilot_variant,
            reconciliation=pilot_reconciliation,
        )
    elif experiment == "listing-calibration":
        summary = _build_calibration_summary(
            status="failed",
            start_snapshot=start_snapshot,
            start_inventory=start_inventory,
            end_snapshot=end_snapshot,
            end_inventory=end_inventory,
            results=None,
            events_before_summary=current_events,
            failure_reason=error_message,
            request_budget=request_budget,
        )
    else:
        summary = _build_summary(
            status="failed",
            start_snapshot=start_snapshot,
            start_inventory=start_inventory,
            end_snapshot=end_snapshot,
            end_inventory=end_inventory,
            execution=None,
            events_before_summary=current_events,
            failure_reason=error_message,
            request_budget=request_budget,
        )
    if not product_data_evidence_complete:
        summary["product_data_unchanged"] = False

    if not has_terminal_summary:
        try:
            observation_service.finish_run(
                status="failed",
                summary=summary,
                error_message=error_message,
            )
            current_events = [*current_events, _summary_event(current_events, summary)]
        except BaseException as finish_error:
            error.add_note(
                "type-only failure finalization also failed: "
                f"{type(finish_error).__name__}"
            )
            try:
                current_events = _ordered_events(
                    repository.list_research_events(db, UUID(run_id))
                )
            except BaseException as reload_error:
                error.add_note(
                    "failure event reload also failed: "
                    f"{type(reload_error).__name__}"
                )
    return summary, current_events


def main(
    argv: list[str] | None = None,
    *,
    session_factory=SessionLocal,
    repository: OfferTodayResearchRepository | None = None,
    runtime_factory=OfferTodayBrowserRuntime,
    service_factory=OfferTodayResearchLiveService,
    observation_service_factory=OfferTodayResearchObservationService,
    crawl_runtime_factory=CrawlJobRuntime,
    staging_sink_factory=OfferTodayReconciledListingStagingSink,
    provenance_provider=capture_research_provenance,
    artifact_exporter=export_research_artifact,
    artifact_verifier=verify_research_artifact,
) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "verify-run":
        result = verify_live_research_run(args.artifact)
        _print_json(result.to_payload())
        return EXIT_OK if result.valid else EXIT_EVIDENCE_FAILURE

    request_budget = (
        dict(_CALIBRATION_REQUEST_BUDGET)
        if args.command == "calibrate"
        else (
            dict(_PILOT_REQUEST_BUDGET)
            if args.command == "pilot"
            else runtime_smoke_request_budget()
        )
    )
    if len(args.baseline_artifact) != 2:
        _print_json(
            {"error": (f"{args.command} requires exactly two baseline artifacts")},
            stream=sys.stderr,
        )
        return EXIT_USAGE

    try:
        smoke_artifact_hash = None
        pilot_variant = None
        if args.command == "calibrate":
            _require_accepted_smoke_artifact(args.smoke_artifact)
            smoke_artifact_hash = hashlib.sha256(
                (Path(args.smoke_artifact) / "manifest.json").read_bytes()
            ).hexdigest()
        elif args.command == "pilot":
            pilot_variant = _require_accepted_calibration_variant(
                args.calibration_artifact,
                variant_rank=args.variant_rank,
            )
        baseline_gate = require_matching_baselines(
            args.baseline_artifact[0],
            args.baseline_artifact[1],
        )
        run_id = str(UUID(args.run_id)) if args.run_id else str(uuid4())
        repo_root = args.repo_root.resolve(strict=True)
        planner_version = _git_head(repo_root)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE

    research_repository = repository or OfferTodayResearchRepository()
    db = None
    observation_service = None
    start_snapshot = None
    start_inventory = None
    end_snapshot = None
    end_inventory = None
    execution = None
    events: list[dict[str, Any]] = []
    events_before_summary: list[dict[str, Any]] = []
    terminal_status = "failed"
    summary: dict[str, Any] = {}
    exit_code = EXIT_EVIDENCE_FAILURE
    original_error: BaseException | None = None
    pre_run_error: BaseException | None = None
    finalization_error: BaseException | None = None
    artifact_dir: Path | None = None
    is_calibration = args.command == "calibrate"
    is_pilot = args.command == "pilot"
    experiment = (
        "listing-calibration"
        if is_calibration
        else "category-pilot" if is_pilot else "runtime-smoke"
    )
    variant = (
        "locked-2x2x2-fresh-headless"
        if is_calibration
        else (
            (
                f"{pilot_variant.endpoint}-rcdtype-"
                f"{pilot_variant.rcd_type if pilot_variant.rcd_type is not None else 'omitted'}"
                "-31-category-pilot"
            )
            if is_pilot and pilot_variant is not None
            else "search-rcdtype-7-fresh-headless"
        )
    )
    parent_artifact_hash = (
        smoke_artifact_hash
        if is_calibration and smoke_artifact_hash is not None
        else (
            pilot_variant.parent_artifact_hash
            if is_pilot and pilot_variant is not None
            else baseline_gate.parent_artifact_hash
        )
    )
    calibration_results = None
    pilot_results = None
    pilot_conditions = (
        build_pilot_conditions(pilot_variant.endpoint, pilot_variant.rcd_type)
        if is_pilot and pilot_variant is not None
        else ()
    )
    pilot_staging_sink = None

    try:
        db = session_factory()
        start_snapshot, start_inventory = _capture_snapshot(research_repository, db)
        _require_current_baseline(baseline_gate, start_snapshot, start_inventory)
        observation_service = observation_service_factory(db)
        observation_service.create_run(
            ResearchMetadata(
                run_id=run_id,
                experiment=experiment,
                variant=variant,
                planner_version=planner_version,
                plan=2,
                parent_artifact_hash=parent_artifact_hash,
                request_budget=dict(request_budget),
            ),
            run_start_inventory=start_inventory,
        )
        observation_service.record_event(
            "research.run_started",
            {
                "experiment": experiment,
                "parent_artifact_hash": parent_artifact_hash,
                "baseline_artifact_hash": baseline_gate.parent_artifact_hash,
                "request_budget": dict(request_budget),
                "session_mode": "fresh-headless",
                **(
                    {"condition_count": len(build_calibration_conditions())}
                    if is_calibration
                    else (
                        {
                            "condition_count": len(pilot_conditions),
                            "variant_rank": pilot_variant.variant_rank,
                            "endpoint": pilot_variant.endpoint,
                            "rcd_type": pilot_variant.rcd_type,
                            "calibration_run_id": pilot_variant.calibration_run_id,
                        }
                        if is_pilot and pilot_variant is not None
                        else {}
                    )
                ),
            },
        )

        try:
            if is_calibration:
                calibration_results = asyncio.run(
                    _execute_calibration_with_runtime(
                        runtime_factory=runtime_factory,
                        service=service_factory(),
                        observation_service=observation_service,
                    )
                )
            elif is_pilot:
                pilot_staging_sink = staging_sink_factory(
                    crawl_runtime=crawl_runtime_factory(),
                    crawl_job_id=run_id,
                    skip_existing=True,
                )
                pilot_results = asyncio.run(
                    _execute_pilot_with_runtime(
                        runtime_factory=runtime_factory,
                        service=service_factory(),
                        observation_service=observation_service,
                        conditions=pilot_conditions,
                        staging_sink=pilot_staging_sink,
                    )
                )
            else:
                execution = asyncio.run(
                    _execute_smoke_with_runtime(
                        runtime_factory=runtime_factory,
                        service=service_factory(),
                        observation_service=observation_service,
                    )
                )
        except BaseException as exc:
            original_error = exc

        end_snapshot, end_inventory = _capture_snapshot(research_repository, db)
        product_data_unchanged = (
            start_snapshot.data_hash == end_snapshot.data_hash
            and start_inventory.data_hash == end_inventory.data_hash
        )
        if original_error is not None:
            failure_reason = _unexpected_error_message(
                original_error,
                experiment=experiment,
            )
            observation_service.record_event(
                "research.run_stopped",
                {"reason": failure_reason},
            )
        elif is_pilot and pilot_staging_sink is not None:
            pilot_accepted, failure_reason = _pilot_analysis(
                results=pilot_results,
                conditions=pilot_conditions,
                reconciliation=pilot_staging_sink.reconciliation,
            )
            conservation_difference = (
                end_snapshot.staged_rows
                - start_snapshot.staged_rows
                - pilot_staging_sink.reconciliation.rows_created
            )
            published_jobs_unchanged = (
                start_snapshot.published_jobs == end_snapshot.published_jobs
                and start_snapshot.published_jobs_hash
                == end_snapshot.published_jobs_hash
            )
            companies_unchanged = (
                start_snapshot.companies_hash == end_snapshot.companies_hash
            )
            if (
                pilot_accepted
                and conservation_difference == 0
                and published_jobs_unchanged
                and companies_unchanged
            ):
                failure_reason = None
                terminal_status = "completed"
                exit_code = EXIT_OK
            else:
                if failure_reason is None:
                    if conservation_difference != 0:
                        failure_reason = "conservation_difference"
                    elif not published_jobs_unchanged:
                        failure_reason = "published_jobs_changed"
                    else:
                        failure_reason = "companies_changed"
                observation_service.record_event(
                    "research.run_stopped",
                    {"reason": failure_reason},
                )
                exit_code = (
                    EXIT_EVIDENCE_FAILURE
                    if failure_reason
                    in {
                        "staging_amplification",
                        "conservation_difference",
                        "published_jobs_changed",
                        "companies_changed",
                    }
                    else (
                        EXIT_HARD_STOP
                        if failure_reason in _HARD_STOP_REASONS
                        else EXIT_INCOMPLETE
                    )
                )
        elif not product_data_unchanged:
            failure_reason = "product_data_changed"
            observation_service.record_event(
                "research.run_stopped",
                {"reason": failure_reason},
            )
        elif is_calibration:
            (
                calibration_passed,
                failure_reason,
                variant_summaries,
                selection,
            ) = _calibration_analysis(calibration_results)
            observation_service.record_event(
                "research.calibration_selection",
                {
                    "variant_summaries": variant_summaries,
                    "selection": selection,
                },
            )
            if calibration_passed:
                terminal_status = "completed"
                exit_code = EXIT_OK
            else:
                observation_service.record_event(
                    "research.run_stopped",
                    {"reason": failure_reason},
                )
                exit_code = (
                    EXIT_HARD_STOP
                    if failure_reason in _HARD_STOP_REASONS
                    else EXIT_INCOMPLETE
                )
        elif execution is not None and execution.decision.smoke_passed:
            failure_reason = None
            terminal_status = "completed"
            exit_code = EXIT_OK
        else:
            failure_reason = (
                execution.decision.stop_reason
                if execution is not None
                else "smoke_execution_missing"
            )
            observation_service.record_event(
                "research.run_stopped",
                {"reason": failure_reason},
            )
            exit_code = (
                EXIT_HARD_STOP
                if failure_reason in _HARD_STOP_REASONS
                else EXIT_INCOMPLETE
            )

        events_before_summary = _ordered_events(
            research_repository.list_research_events(db, UUID(run_id))
        )
        if is_pilot and pilot_variant is not None and pilot_staging_sink is not None:
            summary = _build_pilot_summary(
                status=terminal_status,
                start_snapshot=start_snapshot,
                start_inventory=start_inventory,
                end_snapshot=end_snapshot,
                end_inventory=end_inventory,
                results=pilot_results,
                conditions=pilot_conditions,
                events_before_summary=events_before_summary,
                failure_reason=failure_reason,
                request_budget=request_budget,
                variant=pilot_variant,
                reconciliation=pilot_staging_sink.reconciliation,
            )
        elif is_calibration:
            summary = _build_calibration_summary(
                status=terminal_status,
                start_snapshot=start_snapshot,
                start_inventory=start_inventory,
                end_snapshot=end_snapshot,
                end_inventory=end_inventory,
                results=calibration_results,
                events_before_summary=events_before_summary,
                failure_reason=failure_reason,
                request_budget=request_budget,
            )
        else:
            summary = _build_summary(
                status=terminal_status,
                start_snapshot=start_snapshot,
                start_inventory=start_inventory,
                end_snapshot=end_snapshot,
                end_inventory=end_inventory,
                execution=execution,
                events_before_summary=events_before_summary,
                failure_reason=failure_reason,
                request_budget=request_budget,
            )
        if not is_pilot and not product_data_unchanged:
            exit_code = EXIT_EVIDENCE_FAILURE
        observation_service.finish_run(
            status=terminal_status,
            summary=summary,
            error_message=(
                _unexpected_error_message(original_error, experiment=experiment)
                if original_error is not None
                else None
            ),
        )
        events = [
            *events_before_summary,
            _summary_event(events_before_summary, summary),
        ]
    except BaseException as exc:
        if observation_service is None and isinstance(
            exc,
            (OSError, SQLAlchemyError, ValueError),
        ):
            pre_run_error = exc
        else:
            if original_error is None:
                original_error = exc
            if (
                observation_service is not None
                and start_snapshot is not None
                and start_inventory is not None
                and db is not None
            ):
                try:
                    summary, events = _best_effort_finalize_unexpected_failure(
                        db=db,
                        repository=research_repository,
                        observation_service=observation_service,
                        run_id=run_id,
                        error=original_error,
                        start_snapshot=start_snapshot,
                        start_inventory=start_inventory,
                        end_snapshot=end_snapshot,
                        end_inventory=end_inventory,
                        fallback_events=events_before_summary,
                        request_budget=request_budget,
                        experiment=experiment,
                        pilot_variant=pilot_variant,
                        pilot_conditions=pilot_conditions,
                        pilot_reconciliation=(
                            pilot_staging_sink.reconciliation
                            if pilot_staging_sink is not None
                            else None
                        ),
                    )
                    terminal_status = "failed"
                    exit_code = EXIT_EVIDENCE_FAILURE
                except BaseException as finalization_exc:
                    original_error.add_note(
                        "best-effort failure finalization also failed: "
                        f"{type(finalization_exc).__name__}"
                    )
    finally:
        if db is not None:
            try:
                db.close()
            except BaseException as exc:
                if original_error is None:
                    original_error = exc
                else:
                    original_error.add_note(
                        f"database cleanup also failed: {type(exc).__name__}"
                    )

        if observation_service is not None:
            try:
                provenance = provenance_provider(
                    repo_root=repo_root,
                    runtime_context={
                        "command": args.command,
                        "session_mode": "fresh-headless",
                        "crawl_job_status": terminal_status,
                    },
                    captured_at=utc_now().isoformat(),
                )
                artifact_dir = artifact_exporter(
                    root=args.artifact_root,
                    run_id=run_id,
                    metadata={
                        "experiment": experiment,
                        "crawl_job_id": run_id,
                        "crawl_job_status": terminal_status,
                        "parent_artifact_hash": parent_artifact_hash,
                        "baseline_artifact_hash": baseline_gate.parent_artifact_hash,
                        "request_budget": dict(request_budget),
                        **(
                            {
                                "pilot_passed": bool(summary.get("pilot_passed")),
                                "variant_rank": pilot_variant.variant_rank,
                                "endpoint": pilot_variant.endpoint,
                                "rcd_type": pilot_variant.rcd_type,
                                "calibration_run_id": (
                                    pilot_variant.calibration_run_id
                                ),
                            }
                            if is_pilot and pilot_variant is not None
                            else (
                                {
                                    "calibration_passed": bool(
                                        summary.get("calibration_passed")
                                    )
                                }
                                if is_calibration
                                else {"smoke_passed": bool(summary.get("smoke_passed"))}
                            )
                        ),
                    },
                    events=events,
                    provenance=provenance,
                )
                artifact_check = artifact_verifier(artifact_dir)
                live_check = verify_live_research_run(artifact_dir)
                if not artifact_check.valid or not live_check.valid:
                    exit_code = EXIT_EVIDENCE_FAILURE
            except BaseException as exc:
                finalization_error = exc
                exit_code = EXIT_EVIDENCE_FAILURE

    if pre_run_error is not None and original_error is None:
        _print_json({"error": str(pre_run_error)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE
    if original_error is not None:
        if finalization_error is not None:
            original_error.add_note(
                "artifact finalization also failed: "
                f"{type(finalization_error).__name__}"
            )
        raise original_error
    if finalization_error is not None:
        _print_json(
            {
                "error": f"artifact finalization failed:{type(finalization_error).__name__}"
            },
            stream=sys.stderr,
        )
        return EXIT_EVIDENCE_FAILURE

    if is_pilot:
        reconciliation = summary.get("reconciliation")
        reconciliation = reconciliation if isinstance(reconciliation, dict) else {}
        output = {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "exit_code": exit_code,
            "pilot_passed": bool(summary.get("pilot_passed")),
            "request_budget": dict(request_budget),
            "condition_count": int(summary.get("condition_count", 0)),
            "listing_logical_count": int(summary.get("listing_logical_count", 0)),
            "listing_attempt_count": int(summary.get("listing_attempt_count", 0)),
            "detail_attempt_count": int(summary.get("detail_attempt_count", 0)),
            "rows_created": int(reconciliation.get("rows_created", 0)),
            "conservation_difference": int(summary.get("conservation_difference", 0)),
        }
    elif is_calibration:
        output = {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "exit_code": exit_code,
            "calibration_passed": bool(summary.get("calibration_passed")),
            "request_budget": dict(request_budget),
            "condition_count": int(summary.get("condition_count", 0)),
            "listing_logical_count": int(summary.get("listing_logical_count", 0)),
            "listing_attempt_count": int(summary.get("listing_attempt_count", 0)),
            "detail_attempt_count": int(summary.get("detail_attempt_count", 0)),
        }
    else:
        output = {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "exit_code": exit_code,
            "smoke_passed": bool(summary.get("smoke_passed")),
            "request_budget": dict(request_budget),
            "missing_encrypted_job_id_count": int(
                summary.get("missing_encrypted_job_id_count", 0)
            ),
            "job_id_fallback_count": int(summary.get("job_id_fallback_count", 0)),
        }
    _print_json(output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
