from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.sources.offertoday.research.artifacts import verify_research_artifact


_COUNT_KEYS = (
    "staged_rows",
    "distinct_staged_ids",
    "published_jobs",
    "distinct_staged_unpublished_ids",
    "pending_rows",
    "duplicate_staging_rows",
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


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
        if isinstance(event, dict)
        and event.get("event_type") == "research.baseline"
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
        snapshot_hash=_require_sha256(snapshot.get("data_hash"), "snapshot hash"),
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
    issues: list[str] = []

    if experiment != "runtime-smoke":
        issues.append("unsupported_live_experiment")
    if metadata.get("crawl_job_id") != run_id:
        issues.append("crawl_job_id_run_id_mismatch")
    if _SHA256_RE.fullmatch(str(metadata.get("parent_artifact_hash") or "")) is None:
        issues.append("invalid_parent_artifact_hash")

    request_budget = metadata.get("request_budget")
    if not isinstance(request_budget, dict):
        issues.append("invalid_request_budget")
        request_budget = {}
    listing_budget = request_budget.get("listing")
    detail_budget = request_budget.get("detail")
    if type(listing_budget) is not int or listing_budget < 0:
        issues.append("invalid_listing_request_budget")
        listing_budget = 0
    if type(detail_budget) is not int or detail_budget < 0:
        issues.append("invalid_detail_request_budget")
        detail_budget = 0

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

    listing_attempt_count = sum(
        event.get("event_type") == "research.page_attempt"
        for event in normalized_events
    )
    detail_attempt_count = sum(
        event.get("event_type") == "research.detail_attempt"
        for event in normalized_events
    )
    if listing_attempt_count > listing_budget:
        issues.append(
            f"listing_request_budget_exceeded:{listing_attempt_count}>{listing_budget}"
        )
    if detail_attempt_count > detail_budget:
        issues.append(
            f"detail_request_budget_exceeded:{detail_attempt_count}>{detail_budget}"
        )

    summary: dict[str, Any] = {}
    if len(summary_indexes) == 1:
        payload = normalized_events[summary_indexes[0]].get("payload")
        if isinstance(payload, dict):
            summary = payload
        else:
            issues.append("invalid_terminal_summary_payload")

    if summary:
        if summary.get("listing_attempt_count") != listing_attempt_count:
            issues.append("listing_attempt_count_mismatch")
        if summary.get("attempted_count") != detail_attempt_count:
            issues.append("detail_attempt_count_mismatch")
        manifest_status = metadata.get("crawl_job_status")
        if summary.get("status") != manifest_status:
            issues.append("crawl_job_status_summary_mismatch")
        manifest_smoke_passed = metadata.get("smoke_passed")
        summary_smoke_passed = summary.get("smoke_passed")
        if type(manifest_smoke_passed) is not bool:
            issues.append("invalid_manifest_smoke_passed")
        if summary_smoke_passed is not manifest_smoke_passed:
            issues.append("smoke_passed_summary_mismatch")

        completed_smoke = (
            manifest_status == "completed" or manifest_smoke_passed is True
        )
        if completed_smoke:
            if not (
                manifest_status == "completed"
                and manifest_smoke_passed is True
                and summary_smoke_passed is True
                and summary.get("listing_complete") is False
                and summary.get("expected_truncation") is True
                and listing_attempt_count == 1
                and detail_attempt_count == 20
                and summary.get("frozen_count") == 20
            ):
                issues.append("completed_smoke_status_mismatch")
        elif manifest_status != "failed":
            issues.append("invalid_failed_smoke_status")

    return LiveRunVerification(
        valid=not issues,
        issues=tuple(issues),
        experiment=experiment,
        run_id=run_id,
    )
