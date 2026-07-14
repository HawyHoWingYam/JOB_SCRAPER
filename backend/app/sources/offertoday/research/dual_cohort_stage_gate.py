"""Strict artifact replay for additive OfferToday dual-cohort research."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import UUID

from app.sources.offertoday.research.artifacts import verify_research_artifact
from app.sources.offertoday.research.dual_cohort import (
    DUAL_COHORT_CENSUS_EXPERIMENT,
    DUAL_COHORT_COMPARISON_EXPERIMENT,
    DUAL_COHORT_DISCOVERY_CANDIDATE_EXPERIMENT,
    DUAL_COHORT_FIXED_REPEAT_EXPERIMENT,
    DualCohortPhaseDRunV3,
    RESULT_PARTITION_POLICY_EXPERIMENT,
    RESULT_PARTITION_PROBE_EXPERIMENT,
    RESULT_PARTIAL_CENSUS_EXPERIMENT,
    RESULT_PARTIAL_FIXED_REPEAT_EXPERIMENT,
    SUPPLEMENTAL_COHORT_COMPARISON_EXPERIMENT,
    SUPPLEMENTAL_COHORT_PROBE_EXPERIMENT,
    ResultPartitionProbeExecutionV2,
    SupplementalCohortProbeExecutionV1,
    canonical_dual_cohort_hash,
    dual_cohort_phase_d_comparison_payload_v3,
    validate_dual_cohort_candidate_artifact_payload_v3,
    validate_dual_cohort_phase_d_comparison_payload_v3,
    validate_dual_cohort_phase_d_run_artifact_payload_v3,
    validate_result_partial_phase_d_artifact_payload_v3,
    validate_result_partition_policy_artifact_payload_v1,
    validate_supplemental_cohort_comparison_payload_v1,
)
from app.sources.offertoday.research.phase_d_stage_gate import (
    _contains_forbidden_evidence,
)
from app.sources.offertoday.research.partition_research import (
    ENDPOINT_PROBE_EXPERIMENT,
)
from app.sources.offertoday.research.partition_stage_gate import (
    PhaseCArtifactReference,
    PhaseCBaselineReference,
    PhaseCNoWriteEvidence,
)


_FILE_BY_EXPERIMENT = {
    DUAL_COHORT_DISCOVERY_CANDIDATE_EXPERIMENT: (
        "dual-cohort-discovery-policy.json"
    ),
    RESULT_PARTIAL_CENSUS_EXPERIMENT: "dual-cohort-phase-d-run.json",
    RESULT_PARTIAL_FIXED_REPEAT_EXPERIMENT: "dual-cohort-phase-d-run.json",
    DUAL_COHORT_CENSUS_EXPERIMENT: "dual-cohort-phase-d-run.json",
    DUAL_COHORT_FIXED_REPEAT_EXPERIMENT: "dual-cohort-phase-d-run.json",
    DUAL_COHORT_COMPARISON_EXPERIMENT: "dual-cohort-phase-d-comparison.json",
    RESULT_PARTITION_PROBE_EXPERIMENT: "result-partition-probe.json",
    RESULT_PARTITION_POLICY_EXPERIMENT: "result-partition-policy.json",
    SUPPLEMENTAL_COHORT_PROBE_EXPERIMENT: "supplemental-cohort-probe.json",
    SUPPLEMENTAL_COHORT_COMPARISON_EXPERIMENT: (
        "supplemental-cohort-comparison.json"
    ),
}
DUAL_COHORT_EXPERIMENTS = frozenset(_FILE_BY_EXPERIMENT)


def _canonical_uuid(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a canonical UUID")
    try:
        canonical = str(UUID(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a canonical UUID") from exc
    if value != canonical:
        raise ValueError(f"{field_name} must be a canonical UUID")
    return canonical


def _nonblank(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be a nonblank trimmed string")
    return value


def _sha256(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


def build_dual_cohort_probe_artifact_payload(
    *,
    execution: ResultPartitionProbeExecutionV2
    | SupplementalCohortProbeExecutionV1,
    parent: PhaseCArtifactReference,
    baseline: PhaseCBaselineReference,
    no_write: PhaseCNoWriteEvidence,
) -> dict[str, Any]:
    if isinstance(execution, ResultPartitionProbeExecutionV2):
        experiment = RESULT_PARTITION_PROBE_EXPERIMENT
        if parent.experiment != ENDPOINT_PROBE_EXPERIMENT:
            raise ValueError("result probe requires an endpoint parent")
    elif isinstance(execution, SupplementalCohortProbeExecutionV1):
        experiment = SUPPLEMENTAL_COHORT_PROBE_EXPERIMENT
        if (
            parent.experiment != RESULT_PARTITION_POLICY_EXPERIMENT
            or not parent.accepted
        ):
            raise ValueError("supplemental probe requires an accepted result policy")
    else:  # pragma: no cover - typed boundary
        raise TypeError("unsupported dual-cohort probe execution")
    if (
        no_write.start_snapshot_hash != baseline.snapshot_hash
        or no_write.start_inventory_hash != baseline.inventory_hash
    ):
        raise ValueError("dual-cohort probe start state must match the baseline")
    execution_payload = execution.to_payload()
    return {
        "schema_version": 1,
        "experiment": experiment,
        "execution": execution_payload,
        "execution_hash": canonical_dual_cohort_hash(execution_payload),
        "parent": parent.to_payload(),
        "baseline": baseline.to_payload(),
        "no_write": no_write.to_payload(),
        "accepted": execution.accepted,
    }


def validate_dual_cohort_probe_artifact_payload(
    payload: Any,
) -> tuple[
    ResultPartitionProbeExecutionV2 | SupplementalCohortProbeExecutionV1,
    PhaseCArtifactReference,
    PhaseCBaselineReference,
    PhaseCNoWriteEvidence,
]:
    expected = {
        "schema_version",
        "experiment",
        "execution",
        "execution_hash",
        "parent",
        "baseline",
        "no_write",
        "accepted",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("dual-cohort probe artifact fields do not match")
    if payload["schema_version"] != 1:
        raise ValueError("dual-cohort probe artifact schema does not match")
    experiment = payload["experiment"]
    if experiment == RESULT_PARTITION_PROBE_EXPERIMENT:
        execution = ResultPartitionProbeExecutionV2.from_payload(
            payload["execution"]
        )
    elif experiment == SUPPLEMENTAL_COHORT_PROBE_EXPERIMENT:
        execution = SupplementalCohortProbeExecutionV1.from_payload(
            payload["execution"]
        )
    else:
        raise ValueError("unsupported dual-cohort probe artifact experiment")
    parent = PhaseCArtifactReference.from_payload(payload["parent"])
    baseline = PhaseCBaselineReference.from_payload(payload["baseline"])
    no_write = PhaseCNoWriteEvidence.from_payload(payload["no_write"])
    expected_payload = build_dual_cohort_probe_artifact_payload(
        execution=execution,
        parent=parent,
        baseline=baseline,
        no_write=no_write,
    )
    if dict(payload) != expected_payload:
        raise ValueError("dual-cohort probe artifact does not replay")
    return execution, parent, baseline, no_write


@dataclass(frozen=True, slots=True)
class DualCohortPhaseDArtifactReferenceV3:
    experiment: str
    run_id: str
    manifest_hash: str
    payload_hash: str
    accepted: bool
    candidate_hash: str
    captured_at: str

    def __post_init__(self) -> None:
        if self.experiment not in {
            DUAL_COHORT_CENSUS_EXPERIMENT,
            DUAL_COHORT_FIXED_REPEAT_EXPERIMENT,
        }:
            raise ValueError("unsupported complete dual-cohort parent experiment")
        _canonical_uuid(self.run_id, "parent run_id")
        _sha256(self.manifest_hash, "parent manifest_hash")
        _sha256(self.payload_hash, "parent payload_hash")
        if type(self.accepted) is not bool:
            raise ValueError("parent accepted must be an exact boolean")
        _sha256(self.candidate_hash, "parent candidate_hash")
        _nonblank(self.captured_at, "parent captured_at")

    def to_payload(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "run_id": self.run_id,
            "manifest_hash": self.manifest_hash,
            "payload_hash": self.payload_hash,
            "accepted": self.accepted,
            "candidate_hash": self.candidate_hash,
            "captured_at": self.captured_at,
        }

    @classmethod
    def from_payload(
        cls,
        payload: Any,
    ) -> "DualCohortPhaseDArtifactReferenceV3":
        expected = {
            "experiment",
            "run_id",
            "manifest_hash",
            "payload_hash",
            "accepted",
            "candidate_hash",
            "captured_at",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("dual-cohort parent reference fields do not match")
        return cls(**{field: payload[field] for field in expected})


def build_dual_cohort_phase_d_comparison_artifact_payload_v3(
    parents: Sequence[
        tuple[DualCohortPhaseDArtifactReferenceV3, Mapping[str, Any]]
    ],
) -> dict[str, Any]:
    items = tuple(parents)
    if len(items) != 6:
        raise ValueError("dual-cohort comparison requires exactly six parents")
    references = tuple(item[0] for item in items)
    if len({reference.run_id for reference in references}) != 6:
        raise ValueError("dual-cohort parent run IDs must be distinct")
    if len({reference.manifest_hash for reference in references}) != 6:
        raise ValueError("dual-cohort parent manifests must be distinct")

    runs: list[DualCohortPhaseDRunV3] = []
    for reference, raw_payload in items:
        payload = dict(raw_payload)
        run, _, _ = validate_dual_cohort_phase_d_run_artifact_payload_v3(
            payload
        )
        if (
            reference.experiment != run.experiment
            or reference.run_id != run.run_id
            or reference.payload_hash
            != canonical_dual_cohort_hash(run.to_payload())
            or reference.accepted is not run.accepted
            or reference.candidate_hash != run.candidate_hash
            or reference.captured_at != run.captured_at
        ):
            raise ValueError("dual-cohort parent projection does not match")
        runs.append(run)

    censuses = tuple(
        run for run in runs if run.experiment == DUAL_COHORT_CENSUS_EXPERIMENT
    )
    fixed = tuple(
        run
        for run in runs
        if run.experiment == DUAL_COHORT_FIXED_REPEAT_EXPERIMENT
    )
    comparison = dual_cohort_phase_d_comparison_payload_v3(censuses, fixed)
    reference_payloads = [reference.to_payload() for reference in references]
    return {
        "schema_version": 1,
        "experiment": DUAL_COHORT_COMPARISON_EXPERIMENT,
        "parents": reference_payloads,
        "parent_set_hash": canonical_dual_cohort_hash(reference_payloads),
        "comparison": comparison,
        "comparison_hash": canonical_dual_cohort_hash(comparison),
        "stable_reference_frozen": comparison["stable_reference_frozen"],
        "downstream_eligible": comparison["downstream_eligible"],
    }


def validate_dual_cohort_phase_d_comparison_artifact_payload_v3(
    payload: Any,
) -> tuple[
    tuple[DualCohortPhaseDArtifactReferenceV3, ...],
    Any,
]:
    expected = {
        "schema_version",
        "experiment",
        "parents",
        "parent_set_hash",
        "comparison",
        "comparison_hash",
        "stable_reference_frozen",
        "downstream_eligible",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("dual-cohort comparison artifact fields do not match")
    if (
        payload["schema_version"] != 1
        or payload["experiment"] != DUAL_COHORT_COMPARISON_EXPERIMENT
        or not isinstance(payload["parents"], list)
        or len(payload["parents"]) != 6
    ):
        raise ValueError("dual-cohort comparison artifact contract does not match")
    parents = tuple(
        DualCohortPhaseDArtifactReferenceV3.from_payload(item)
        for item in payload["parents"]
    )
    if len({parent.run_id for parent in parents}) != 6:
        raise ValueError("dual-cohort comparison parent run IDs must be distinct")
    if len({parent.manifest_hash for parent in parents}) != 6:
        raise ValueError("dual-cohort comparison parent manifests must be distinct")
    if payload["parent_set_hash"] != canonical_dual_cohort_hash(
        payload["parents"]
    ):
        raise ValueError("dual-cohort comparison parent_set_hash does not match")
    comparison = validate_dual_cohort_phase_d_comparison_payload_v3(
        payload["comparison"]
    )
    if payload["comparison_hash"] != canonical_dual_cohort_hash(
        payload["comparison"]
    ):
        raise ValueError("dual-cohort comparison hash does not match")
    comparison_runs = (
        *payload["comparison"]["inputs"]["census_runs"],
        *payload["comparison"]["inputs"]["fixed_runs"],
    )
    for parent, run_payload in zip(parents, comparison_runs, strict=True):
        run = DualCohortPhaseDRunV3.from_payload(run_payload)
        if (
            parent.experiment != run.experiment
            or parent.run_id != run.run_id
            or parent.payload_hash
            != canonical_dual_cohort_hash(run_payload)
            or parent.accepted is not run.accepted
            or parent.candidate_hash != run.candidate_hash
            or parent.captured_at != run.captured_at
        ):
            raise ValueError("dual-cohort parent/run evidence mismatch")
    if (
        payload["stable_reference_frozen"] is not comparison.decision.accepted
        or payload["downstream_eligible"] is not comparison.decision.accepted
    ):
        raise ValueError("dual-cohort comparison decision does not match")
    return parents, comparison


def _validate_payload(payload: Mapping[str, Any]) -> Any:
    experiment = payload.get("experiment")
    if experiment in {
        RESULT_PARTITION_PROBE_EXPERIMENT,
        SUPPLEMENTAL_COHORT_PROBE_EXPERIMENT,
    }:
        return validate_dual_cohort_probe_artifact_payload(payload)
    if experiment == DUAL_COHORT_DISCOVERY_CANDIDATE_EXPERIMENT:
        return validate_dual_cohort_candidate_artifact_payload_v3(payload)
    if experiment in {
        RESULT_PARTIAL_CENSUS_EXPERIMENT,
        RESULT_PARTIAL_FIXED_REPEAT_EXPERIMENT,
    }:
        return validate_result_partial_phase_d_artifact_payload_v3(payload)
    if experiment in {
        DUAL_COHORT_CENSUS_EXPERIMENT,
        DUAL_COHORT_FIXED_REPEAT_EXPERIMENT,
    }:
        return validate_dual_cohort_phase_d_run_artifact_payload_v3(payload)
    if experiment == DUAL_COHORT_COMPARISON_EXPERIMENT:
        return validate_dual_cohort_phase_d_comparison_artifact_payload_v3(
            payload
        )
    if experiment == RESULT_PARTITION_POLICY_EXPERIMENT:
        return validate_result_partition_policy_artifact_payload_v1(payload)
    if experiment == SUPPLEMENTAL_COHORT_COMPARISON_EXPERIMENT:
        return validate_supplemental_cohort_comparison_payload_v1(payload)
    raise ValueError("unsupported dual-cohort artifact experiment")


def dual_cohort_metadata(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    planner_version: str,
) -> dict[str, Any]:
    _canonical_uuid(run_id, "run_id")
    _nonblank(planner_version, "planner_version")
    value = _validate_payload(payload)
    experiment = payload["experiment"]
    if experiment == RESULT_PARTITION_PROBE_EXPERIMENT:
        execution, parent, baseline, _ = value
        return {
            "experiment": experiment,
            "crawl_job_id": run_id,
            "crawl_job_status": (
                "completed" if execution.failure_reason is None else "failed"
            ),
            "accepted": execution.accepted,
            "plan_hash": execution.plan.plan_hash,
            "parent_manifest_hash": parent.manifest_hash,
            "baseline_artifact_hashes": list(baseline.artifact_hashes),
            "request_budget": {
                "listing_logical": execution.plan.listing_logical_budget,
                "listing_attempt_max": execution.plan.listing_attempt_budget,
                "detail": 0,
                "product_writes": 0,
            },
            "planner_version": planner_version,
        }
    if experiment == DUAL_COHORT_DISCOVERY_CANDIDATE_EXPERIMENT:
        return {
            "experiment": experiment,
            "crawl_job_id": run_id,
            "crawl_job_status": "completed",
            "candidate_frozen": True,
            "downstream_eligible": True,
            "candidate_hash": value.candidate_hash,
            "result_partition_policy_hash": (
                value.result_partition_policy_hash
            ),
            "supplemental_cohort_policy_hash": (
                value.supplemental_cohort_policy_hash
            ),
            "planner_version": planner_version,
        }
    if experiment in {
        RESULT_PARTIAL_CENSUS_EXPERIMENT,
        RESULT_PARTIAL_FIXED_REPEAT_EXPERIMENT,
    }:
        run, scope, baseline = value
        if run.run_id != run_id:
            raise ValueError("partial Phase D payload run_id does not match manifest")
        return {
            "experiment": experiment,
            "crawl_job_id": run_id,
            "crawl_job_status": (
                "completed" if run.failure_reason is None else "failed"
            ),
            "partial_research_complete": run.partial_research_complete,
            "accepted": False,
            "downstream_eligible": False,
            "scope_hash": scope.scope_hash,
            "result_partition_policy_hash": (
                scope.result_policy.policy_hash
            ),
            "supplemental_gate_hash": scope.supplemental_gate.gate_hash,
            "baseline_artifact_hashes": list(baseline.artifact_hashes),
            "run_index": run.run_index,
            "window_id": run.window_id,
            "planner_version": planner_version,
        }
    if experiment in {
        DUAL_COHORT_CENSUS_EXPERIMENT,
        DUAL_COHORT_FIXED_REPEAT_EXPERIMENT,
    }:
        run, candidate, baseline = value
        if run.run_id != run_id:
            raise ValueError("complete Phase D payload run_id does not match manifest")
        return {
            "experiment": experiment,
            "crawl_job_id": run_id,
            "crawl_job_status": (
                "completed" if run.failure_reason is None else "failed"
            ),
            "accepted": run.accepted,
            "downstream_eligible": run.accepted,
            "candidate_hash": candidate.candidate_hash,
            "candidate_artifact_hash": run.candidate_artifact_hash,
            "result_partition_policy_hash": (
                candidate.result_partition_policy_hash
            ),
            "supplemental_cohort_policy_hash": (
                candidate.supplemental_cohort_policy_hash
            ),
            "baseline_artifact_hashes": list(baseline.artifact_hashes),
            "run_index": run.run_index,
            "window_id": run.window_id,
            "planner_version": planner_version,
        }
    if experiment == DUAL_COHORT_COMPARISON_EXPERIMENT:
        parents, comparison = value
        return {
            "experiment": experiment,
            "crawl_job_id": run_id,
            "crawl_job_status": "completed",
            "accepted": comparison.decision.accepted,
            "stable_reference_frozen": comparison.decision.accepted,
            "downstream_eligible": comparison.decision.accepted,
            "candidate_hash": comparison.candidate_hash,
            "stable_reference_hash": comparison.to_payload()[
                "stable_reference_hash"
            ],
            "parent_run_ids": [parent.run_id for parent in parents],
            "parent_manifest_hashes": [
                parent.manifest_hash for parent in parents
            ],
            "planner_version": planner_version,
        }
    if experiment == RESULT_PARTITION_POLICY_EXPERIMENT:
        return {
            "experiment": experiment,
            "crawl_job_id": run_id,
            "crawl_job_status": "completed",
            "policy_frozen": True,
            "policy_hash": value.policy_hash,
            "source_probe_artifact_hash": value.source_probe_artifact_hash,
            "planner_version": planner_version,
        }
    if experiment == SUPPLEMENTAL_COHORT_PROBE_EXPERIMENT:
        execution, parent, baseline, _ = value
        if execution.run_id != run_id:
            raise ValueError("supplemental payload run_id does not match manifest")
        return {
            "experiment": experiment,
            "crawl_job_id": run_id,
            "crawl_job_status": (
                "completed" if execution.failure_reason is None else "failed"
            ),
            "accepted": execution.accepted,
            "run_index": execution.run_index,
            "plan_hash": execution.plan.plan_hash,
            "parent_manifest_hash": parent.manifest_hash,
            "baseline_artifact_hashes": list(baseline.artifact_hashes),
            "request_budget": {
                "listing_logical": execution.plan.listing_logical_budget,
                "listing_attempt_max": execution.plan.listing_attempt_budget,
                "detail": 0,
                "product_writes": 0,
            },
            "planner_version": planner_version,
        }
    return {
        "experiment": experiment,
        "crawl_job_id": run_id,
        "crawl_job_status": "completed",
        "accepted": value.decision.accepted,
        "policy_frozen": value.decision.accepted,
        "policy_hash": value.policy_hash,
        "parent_run_ids": list(value.run_ids),
        "planner_version": planner_version,
    }


def dual_cohort_artifact_events(
    payload: Mapping[str, Any],
    *,
    created_at: str,
) -> list[dict[str, Any]]:
    _nonblank(created_at, "created_at")
    value = _validate_payload(payload)
    experiment = payload["experiment"]
    event_payloads: list[tuple[str, dict[str, Any]]]
    if experiment == RESULT_PARTITION_PROBE_EXPERIMENT:
        execution, _, _, _ = value
        event_payloads = [
            (
                "research.run_started",
                {
                    "experiment": experiment,
                    "plan_hash": execution.plan.plan_hash,
                },
            )
        ]
        for item in execution.conditions:
            event_payloads.extend(
                ("research.page_attempt", page.to_payload())
                for page in item.condition.pages
            )
            event_payloads.append(
                ("research.result_partition_completed", item.to_payload())
            )
        event_payloads.append(("research.run_summary", dict(payload)))
    elif experiment == DUAL_COHORT_DISCOVERY_CANDIDATE_EXPERIMENT:
        event_payloads = [
            ("research.dual_cohort_candidate_frozen", dict(payload))
        ]
    elif experiment in {
        RESULT_PARTIAL_CENSUS_EXPERIMENT,
        RESULT_PARTIAL_FIXED_REPEAT_EXPERIMENT,
    }:
        run, _, _ = value
        event_payloads = [
            (
                "research.run_started",
                {
                    "experiment": experiment,
                    "run_id": run.run_id,
                    "run_index": run.run_index,
                    "scope_hash": run.scope_hash,
                },
            )
        ]
        for item in run.conditions:
            event_payloads.extend(
                ("research.page_attempt", page.to_payload())
                for page in item.condition.pages
            )
            event_payloads.append(
                ("research.result_partition_completed", item.to_payload())
            )
        event_payloads.append(("research.partial_run_summary", dict(payload)))
    elif experiment in {
        DUAL_COHORT_CENSUS_EXPERIMENT,
        DUAL_COHORT_FIXED_REPEAT_EXPERIMENT,
    }:
        run, _, _ = value
        event_payloads = [
            (
                "research.run_started",
                {
                    "experiment": experiment,
                    "run_id": run.run_id,
                    "run_index": run.run_index,
                    "candidate_hash": run.candidate_hash,
                },
            )
        ]
        for item in run.result_conditions:
            event_payloads.extend(
                ("research.page_attempt", page.to_payload())
                for page in item.condition.pages
            )
            event_payloads.append(
                ("research.result_partition_completed", item.to_payload())
            )
        if run.supplemental_condition is not None:
            event_payloads.extend(
                ("research.page_attempt", page.to_payload())
                for page in run.supplemental_condition.condition.pages
            )
            event_payloads.append(
                (
                    "research.supplemental_seed_completed",
                    run.supplemental_condition.to_payload(),
                )
            )
        event_payloads.append(("research.dual_cohort_run_summary", dict(payload)))
    elif experiment == DUAL_COHORT_COMPARISON_EXPERIMENT:
        event_payloads = [
            ("research.dual_cohort_comparison_completed", dict(payload))
        ]
    elif experiment == RESULT_PARTITION_POLICY_EXPERIMENT:
        event_payloads = [("research.result_partition_policy_frozen", dict(payload))]
    elif experiment == SUPPLEMENTAL_COHORT_PROBE_EXPERIMENT:
        execution, _, _, _ = value
        event_payloads = [
            (
                "research.run_started",
                {
                    "experiment": experiment,
                    "run_id": execution.run_id,
                    "run_index": execution.run_index,
                    "plan_hash": execution.plan.plan_hash,
                },
            )
        ]
        for item in execution.conditions:
            event_payloads.extend(
                ("research.page_attempt", page.to_payload())
                for page in item.condition.pages
            )
            event_payloads.append(
                ("research.supplemental_seed_completed", item.to_payload())
            )
        event_payloads.append(("research.run_summary", dict(payload)))
    else:
        event_payloads = [
            ("research.supplemental_comparison_completed", dict(payload))
        ]
    return [
        {
            "sequence_no": sequence_no,
            "event_type": event_type,
            "payload": event_payload,
            "emitted_by": "offertoday-research",
            "created_at": created_at,
        }
        for sequence_no, (event_type, event_payload) in enumerate(
            event_payloads,
            start=1,
        )
    ]


@dataclass(frozen=True, slots=True)
class DualCohortArtifactVerification:
    valid: bool
    issues: tuple[str, ...]
    experiment: str | None
    run_id: str | None


def _load_dual_cohort_artifact(
    artifact_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("dual-cohort manifest metadata must be an object")
    experiment = metadata.get("experiment")
    try:
        file_name = _FILE_BY_EXPERIMENT[experiment]
    except (KeyError, TypeError) as exc:
        raise ValueError("unsupported dual-cohort artifact experiment") from exc
    expected_files = {"observations.jsonl", "working-tree.patch", file_name}
    if set(manifest.get("files", {})) != expected_files:
        raise ValueError("dual-cohort artifact files do not match experiment")
    payload = json.loads((artifact_dir / file_name).read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (artifact_dir / "observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    return manifest, events, payload


def verify_dual_cohort_artifact(
    artifact_dir: Path,
) -> DualCohortArtifactVerification:
    artifact_dir = Path(artifact_dir)
    generic = verify_research_artifact(artifact_dir)
    if not generic.valid:
        return DualCohortArtifactVerification(
            valid=False,
            issues=("invalid_research_artifact",),
            experiment=None,
            run_id=None,
        )
    try:
        manifest, events, payload = _load_dual_cohort_artifact(artifact_dir)
        metadata = manifest["metadata"]
        experiment = metadata["experiment"]
        run_id = manifest["run_id"]
        planner_version = metadata.get("planner_version")
        _validate_payload(payload)
        expected_metadata = dual_cohort_metadata(
            payload,
            run_id=run_id,
            planner_version=planner_version,
        )
        if metadata != expected_metadata:
            raise ValueError("dual-cohort manifest metadata does not replay")
        expected_events = dual_cohort_artifact_events(
            payload,
            created_at=(events[0].get("created_at") if events else ""),
        )
        if events != expected_events:
            raise ValueError("dual-cohort artifact events do not replay")
        if _contains_forbidden_evidence(
            {
                "metadata": metadata,
                "provenance": manifest.get("provenance"),
                "events": events,
                "payload": payload,
            }
        ):
            raise ValueError("dual-cohort artifact contains forbidden evidence")
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        experiment_value = None
        run_id_value = None
        try:
            manifest_data = json.loads(
                (artifact_dir / "manifest.json").read_text(encoding="utf-8")
            )
            metadata_value = manifest_data.get("metadata")
            if isinstance(metadata_value, dict) and isinstance(
                metadata_value.get("experiment"),
                str,
            ):
                experiment_value = metadata_value["experiment"]
            if isinstance(manifest_data.get("run_id"), str):
                run_id_value = manifest_data["run_id"]
        except (json.JSONDecodeError, OSError, TypeError):
            pass
        return DualCohortArtifactVerification(
            valid=False,
            issues=(f"invalid_dual_cohort_artifact:{type(exc).__name__}",),
            experiment=experiment_value,
            run_id=run_id_value,
        )
    return DualCohortArtifactVerification(
        valid=True,
        issues=(),
        experiment=experiment,
        run_id=run_id,
    )


def dual_cohort_phase_d_artifact_reference_v3(
    artifact_dir: Path,
) -> DualCohortPhaseDArtifactReferenceV3:
    verification = verify_dual_cohort_artifact(artifact_dir)
    if not verification.valid or verification.experiment not in {
        DUAL_COHORT_CENSUS_EXPERIMENT,
        DUAL_COHORT_FIXED_REPEAT_EXPERIMENT,
    }:
        raise ValueError("complete dual-cohort run failed strict verification")
    artifact_dir = Path(artifact_dir)
    manifest, _, payload = _load_dual_cohort_artifact(artifact_dir)
    run, _, _ = validate_dual_cohort_phase_d_run_artifact_payload_v3(payload)
    return DualCohortPhaseDArtifactReferenceV3(
        experiment=run.experiment,
        run_id=run.run_id,
        manifest_hash=hashlib.sha256(
            (artifact_dir / "manifest.json").read_bytes()
        ).hexdigest(),
        payload_hash=canonical_dual_cohort_hash(run.to_payload()),
        accepted=run.accepted,
        candidate_hash=run.candidate_hash,
        captured_at=run.captured_at,
    )
