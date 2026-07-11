#!/usr/bin/env python3
"""Stage-gated live OfferToday Plan 2 research commands."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from dataclasses import asdict
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
from app.services.offertoday_research_live_service import (  # noqa: E402
    OfferTodayResearchLiveService,
)
from app.services.offertoday_research_observation_service import (  # noqa: E402
    OfferTodayResearchObservationService,
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
from app.sources.offertoday.research.contracts import (  # noqa: E402
    ResearchMetadata,
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
    verify = commands.add_parser("verify-run")
    verify.add_argument("--artifact", type=Path, required=True)
    return parser


def _print_json(value: dict[str, Any], *, stream=None) -> None:
    print(json.dumps(value, ensure_ascii=True, sort_keys=True), file=stream)


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
) -> dict[str, Any]:
    listing_attempts, detail_attempts, event_frozen_count = _event_counts(
        events_before_summary
    )
    missing_encrypted_job_id_count, job_id_fallback_count = (
        _listing_identity_counts(
            execution=execution,
            events_before_summary=events_before_summary,
        )
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
            event.get("payload", {}).get("classification")
            == "terminal_unavailable"
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


def _unexpected_error_message(error: BaseException) -> str:
    return f"unexpected_live_smoke_error:{type(error).__name__}"


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
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    error_message = _unexpected_error_message(error)
    product_data_evidence_complete = end_snapshot is not None and end_inventory is not None
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
        event.get("event_type") == "research.run_summary"
        for event in current_events
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

    summary = _build_summary(
        status="failed",
        start_snapshot=start_snapshot,
        start_inventory=start_inventory,
        end_snapshot=end_snapshot,
        end_inventory=end_inventory,
        execution=None,
        events_before_summary=current_events,
        failure_reason=error_message,
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
    provenance_provider=capture_research_provenance,
    artifact_exporter=export_research_artifact,
    artifact_verifier=verify_research_artifact,
) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "verify-run":
        result = verify_live_research_run(args.artifact)
        _print_json(result.to_payload())
        return EXIT_OK if result.valid else EXIT_EVIDENCE_FAILURE

    if len(args.baseline_artifact) != 2:
        _print_json(
            {"error": "smoke requires exactly two baseline artifacts"},
            stream=sys.stderr,
        )
        return EXIT_USAGE

    try:
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

    try:
        db = session_factory()
        start_snapshot, start_inventory = _capture_snapshot(research_repository, db)
        _require_current_baseline(baseline_gate, start_snapshot, start_inventory)
        observation_service = observation_service_factory(db)
        observation_service.create_run(
            ResearchMetadata(
                run_id=run_id,
                experiment="runtime-smoke",
                variant="search-rcdtype-7-fresh-headless",
                planner_version=planner_version,
                plan=2,
                parent_artifact_hash=baseline_gate.parent_artifact_hash,
                request_budget={"listing": 1, "detail": 20},
            ),
            run_start_inventory=start_inventory,
        )
        observation_service.record_event(
            "research.run_started",
            {
                "experiment": "runtime-smoke",
                "parent_artifact_hash": baseline_gate.parent_artifact_hash,
                "request_budget": {"listing": 1, "detail": 20},
                "session_mode": "fresh-headless",
            },
        )

        try:
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
            failure_reason = _unexpected_error_message(original_error)
            observation_service.record_event(
                "research.run_stopped",
                {"reason": failure_reason},
            )
        elif not product_data_unchanged:
            failure_reason = "product_data_changed"
            observation_service.record_event(
                "research.run_stopped",
                {"reason": failure_reason},
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
        summary = _build_summary(
            status=terminal_status,
            start_snapshot=start_snapshot,
            start_inventory=start_inventory,
            end_snapshot=end_snapshot,
            end_inventory=end_inventory,
            execution=execution,
            events_before_summary=events_before_summary,
            failure_reason=failure_reason,
        )
        if not product_data_unchanged:
            exit_code = EXIT_EVIDENCE_FAILURE
        observation_service.finish_run(
            status=terminal_status,
            summary=summary,
            error_message=(
                _unexpected_error_message(original_error)
                if original_error is not None
                else None
            ),
        )
        events = [*events_before_summary, _summary_event(events_before_summary, summary)]
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
                        "command": "smoke",
                        "session_mode": "fresh-headless",
                        "crawl_job_status": terminal_status,
                    },
                    captured_at=utc_now().isoformat(),
                )
                artifact_dir = artifact_exporter(
                    root=args.artifact_root,
                    run_id=run_id,
                    metadata={
                        "experiment": "runtime-smoke",
                        "crawl_job_id": run_id,
                        "crawl_job_status": terminal_status,
                        "parent_artifact_hash": baseline_gate.parent_artifact_hash,
                        "request_budget": {"listing": 1, "detail": 20},
                        "smoke_passed": bool(summary.get("smoke_passed")),
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
            {"error": f"artifact finalization failed:{type(finalization_error).__name__}"},
            stream=sys.stderr,
        )
        return EXIT_EVIDENCE_FAILURE

    _print_json(
        {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "exit_code": exit_code,
            "smoke_passed": bool(summary.get("smoke_passed")),
            "missing_encrypted_job_id_count": int(
                summary.get("missing_encrypted_job_id_count", 0)
            ),
            "job_id_fallback_count": int(
                summary.get("job_id_fallback_count", 0)
            ),
        }
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
