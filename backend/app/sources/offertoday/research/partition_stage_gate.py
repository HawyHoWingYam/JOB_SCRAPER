"""Strict artifact contracts for deterministic OfferToday Phase C research."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import UUID

from app.sources.offertoday.listing_contract import offertoday_endpoint_contract
from app.sources.offertoday.research.artifacts import verify_research_artifact
from app.sources.offertoday.research.partition_research import (
    ENDPOINT_PROBE_EXPERIMENT,
    OFFERTODAY_PARTITION_CATALOG,
    PARTITION_COMPARISON_EXPERIMENT,
    PARTITION_PROBE_EXPERIMENT,
    EndpointProbePlan,
    PartitionProbePlan,
    PhaseCProbeExecution,
    canonical_phase_c_hash,
    comparison_payload,
    offertoday_partition_catalog_hash,
    partition_probe_policy_hash,
    phase_c_request_policy_hash,
    phase_c_probe_execution_from_payload,
    validate_comparison_payload,
)


_PROBE_FILE_BY_EXPERIMENT = {
    ENDPOINT_PROBE_EXPERIMENT: "endpoint-probe.json",
    PARTITION_PROBE_EXPERIMENT: "partition-probe.json",
}
_PHASE_C_EXPERIMENTS = {
    ENDPOINT_PROBE_EXPERIMENT,
    PARTITION_PROBE_EXPERIMENT,
    PARTITION_COMPARISON_EXPERIMENT,
}
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_CREDENTIAL_URL_RE = re.compile(r"://[^\s/:]+:[^\s/@]+@")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----",
    re.IGNORECASE,
)
_FORBIDDEN_NORMALIZED_KEYS = {
    "authorization",
    "cdpendpoint",
    "cookie",
    "cookies",
    "csrftoken",
    "cursor",
    "cursorvalue",
    "lastitem",
    "profilepath",
    "rawsessionid",
    "sessionid",
    "suppleamount",
    "supplepage",
    "suppletype",
}
_PARTITION_ORDER = {
    partition.partition_id: index
    for index, partition in enumerate(OFFERTODAY_PARTITION_CATALOG)
}


def _exact_int(value: Any, field_name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(
            f"{field_name} must be an exact integer greater than or equal to {minimum}"
        )
    return value


def _nonblank(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be a nonblank trimmed string")
    return value


def _sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256")
    return value


def _canonical_uuid(value: Any, field_name: str) -> str:
    try:
        canonical = str(UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a canonical UUID") from exc
    if value != canonical:
        raise ValueError(f"{field_name} must be a canonical UUID")
    return canonical


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item or item != item.strip()
        for item in value
    ):
        raise ValueError(f"{field_name} must be a list of nonblank strings")
    return tuple(value)


def _probe_policy_hash(plan: EndpointProbePlan | PartitionProbePlan) -> str:
    if isinstance(plan, PartitionProbePlan):
        return partition_probe_policy_hash(plan)
    return canonical_phase_c_hash(
        {
            "schema_version": 1,
            "contract_ids": list(plan.contract_ids),
            "request_policy_hashes": [
                phase_c_request_policy_hash(contract_id)
                for contract_id in plan.contract_ids
            ],
            "max_pages_per_contract": plan.max_pages_per_contract,
            "max_attempts_per_page": plan.max_attempts_per_page,
            "requested_page_size": plan.requested_page_size,
            "require_empty_confirmation": True,
            "retry_delays_seconds": plan.to_payload()["retry_delays_seconds"],
            "page_delay_range_seconds": plan.to_payload()[
                "page_delay_range_seconds"
            ],
            "session_mode": plan.to_payload()["session_mode"],
        }
    )


@dataclass(frozen=True, slots=True)
class PhaseCArtifactReference:
    experiment: str
    run_id: str
    manifest_hash: str
    payload_hash: str
    accepted: bool

    def __post_init__(self) -> None:
        _nonblank(self.experiment, "parent experiment")
        _canonical_uuid(self.run_id, "parent run_id")
        _sha256(self.manifest_hash, "parent manifest_hash")
        _sha256(self.payload_hash, "parent payload_hash")
        if type(self.accepted) is not bool:
            raise ValueError("parent accepted must be an exact boolean")

    def to_payload(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "run_id": self.run_id,
            "manifest_hash": self.manifest_hash,
            "payload_hash": self.payload_hash,
            "accepted": self.accepted,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> PhaseCArtifactReference:
        expected = {
            "experiment",
            "run_id",
            "manifest_hash",
            "payload_hash",
            "accepted",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("Phase C parent reference fields do not match")
        return cls(**{field: payload[field] for field in expected})


@dataclass(frozen=True, slots=True)
class PhaseCBaselineReference:
    artifact_hashes: tuple[str, str]
    run_ids: tuple[str, str]
    snapshot_hash: str
    inventory_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_hashes, tuple) or len(self.artifact_hashes) != 2:
            raise ValueError("Phase C baseline requires exactly two artifact hashes")
        if not isinstance(self.run_ids, tuple) or len(self.run_ids) != 2:
            raise ValueError("Phase C baseline requires exactly two run IDs")
        for index, value in enumerate(self.artifact_hashes):
            _sha256(value, f"baseline artifact_hashes[{index}]")
        for index, value in enumerate(self.run_ids):
            _canonical_uuid(value, f"baseline run_ids[{index}]")
        if len(set(self.artifact_hashes)) != 2 or len(set(self.run_ids)) != 2:
            raise ValueError("Phase C baseline parents must be distinct")
        _sha256(self.snapshot_hash, "baseline snapshot_hash")
        _sha256(self.inventory_hash, "baseline inventory_hash")

    @property
    def state_hash(self) -> str:
        return canonical_phase_c_hash(
            {
                "snapshot_hash": self.snapshot_hash,
                "inventory_hash": self.inventory_hash,
            }
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "artifact_hashes": list(self.artifact_hashes),
            "run_ids": list(self.run_ids),
            "snapshot_hash": self.snapshot_hash,
            "inventory_hash": self.inventory_hash,
            "state_hash": self.state_hash,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> PhaseCBaselineReference:
        expected = {
            "artifact_hashes",
            "run_ids",
            "snapshot_hash",
            "inventory_hash",
            "state_hash",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("Phase C baseline reference fields do not match")
        artifact_hashes = _string_tuple(
            payload["artifact_hashes"], "baseline artifact_hashes"
        )
        run_ids = _string_tuple(payload["run_ids"], "baseline run_ids")
        if len(artifact_hashes) != 2 or len(run_ids) != 2:
            raise ValueError("Phase C baseline reference requires two parents")
        value = cls(
            artifact_hashes=(artifact_hashes[0], artifact_hashes[1]),
            run_ids=(run_ids[0], run_ids[1]),
            snapshot_hash=payload["snapshot_hash"],
            inventory_hash=payload["inventory_hash"],
        )
        if payload["state_hash"] != value.state_hash:
            raise ValueError("Phase C baseline state_hash does not match")
        return value


@dataclass(frozen=True, slots=True)
class PhaseCNoWriteEvidence:
    start_snapshot_hash: str
    end_snapshot_hash: str
    start_product_data_hash: str
    end_product_data_hash: str
    start_inventory_hash: str
    end_inventory_hash: str
    stage_calls: int
    would_stage_rows: int
    detail_attempts: int = 0
    product_writes: int = 0
    staging_mode: str = "noop"
    product_data_unchanged: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "start_snapshot_hash",
            "end_snapshot_hash",
            "start_product_data_hash",
            "end_product_data_hash",
            "start_inventory_hash",
            "end_inventory_hash",
        ):
            _sha256(getattr(self, field_name), field_name)
        _exact_int(self.stage_calls, "stage_calls")
        _exact_int(self.would_stage_rows, "would_stage_rows")
        if self.detail_attempts != 0 or self.product_writes != 0:
            raise ValueError("Phase C no-write evidence requires zero detail and writes")
        if self.staging_mode != "noop":
            raise ValueError("Phase C staging_mode must equal noop")
        if self.product_data_unchanged is not True:
            raise ValueError("Phase C product_data_unchanged must be true")
        if not (
            self.start_snapshot_hash == self.end_snapshot_hash
            and self.start_product_data_hash == self.end_product_data_hash
            and self.start_inventory_hash == self.end_inventory_hash
        ):
            raise ValueError("Phase C no-write snapshots must remain unchanged")

    def to_payload(self) -> dict[str, Any]:
        return {
            "start_snapshot_hash": self.start_snapshot_hash,
            "end_snapshot_hash": self.end_snapshot_hash,
            "start_product_data_hash": self.start_product_data_hash,
            "end_product_data_hash": self.end_product_data_hash,
            "start_inventory_hash": self.start_inventory_hash,
            "end_inventory_hash": self.end_inventory_hash,
            "stage_calls": self.stage_calls,
            "would_stage_rows": self.would_stage_rows,
            "detail_attempts": self.detail_attempts,
            "product_writes": self.product_writes,
            "staging_mode": self.staging_mode,
            "product_data_unchanged": self.product_data_unchanged,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> PhaseCNoWriteEvidence:
        expected = set(cls.__dataclass_fields__)
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("Phase C no-write evidence fields do not match")
        return cls(**{field: payload[field] for field in expected})


def _plan_contract_ids(
    plan: EndpointProbePlan | PartitionProbePlan,
) -> tuple[str, ...]:
    if isinstance(plan, EndpointProbePlan):
        return plan.contract_ids
    return (plan.endpoint_contract_id,)


def build_phase_c_probe_artifact_payload(
    *,
    execution: PhaseCProbeExecution,
    parent: PhaseCArtifactReference,
    baseline: PhaseCBaselineReference,
    no_write: PhaseCNoWriteEvidence,
) -> dict[str, Any]:
    if execution.experiment == ENDPOINT_PROBE_EXPERIMENT:
        if parent.experiment != "cursor-pagination-comparison-v2":
            raise ValueError("endpoint probe requires a Phase B comparison parent")
    elif execution.experiment == PARTITION_PROBE_EXPERIMENT:
        if parent.experiment != ENDPOINT_PROBE_EXPERIMENT:
            raise ValueError("partition probe requires an endpoint probe parent")
    else:  # pragma: no cover - guarded by PhaseCProbeExecution
        raise ValueError("unsupported Phase C probe experiment")
    if (
        no_write.start_snapshot_hash != baseline.snapshot_hash
        or no_write.start_inventory_hash != baseline.inventory_hash
    ):
        raise ValueError("Phase C start state must match the baseline state")
    contract_ids = _plan_contract_ids(execution.plan)
    execution_payload = execution.to_payload()
    return {
        "schema_version": 1,
        "experiment": execution.experiment,
        "partition_catalog_hash": offertoday_partition_catalog_hash(),
        "endpoint_contract_ids": list(contract_ids),
        "endpoint_contract_hashes": [
            offertoday_endpoint_contract(contract_id).contract_hash
            for contract_id in contract_ids
        ],
        "request_policy_hashes": [
            phase_c_request_policy_hash(contract_id) for contract_id in contract_ids
        ],
        "policy_hash": _probe_policy_hash(execution.plan),
        "parent": parent.to_payload(),
        "baseline": baseline.to_payload(),
        "execution": execution_payload,
        "execution_hash": canonical_phase_c_hash(execution_payload),
        "no_write": no_write.to_payload(),
        "candidate_frozen": False,
    }


def validate_phase_c_probe_artifact_payload(
    payload: Any,
) -> tuple[
    PhaseCProbeExecution,
    PhaseCArtifactReference,
    PhaseCBaselineReference,
    PhaseCNoWriteEvidence,
]:
    expected = {
        "schema_version",
        "experiment",
        "partition_catalog_hash",
        "endpoint_contract_ids",
        "endpoint_contract_hashes",
        "request_policy_hashes",
        "policy_hash",
        "parent",
        "baseline",
        "execution",
        "execution_hash",
        "no_write",
        "candidate_frozen",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("Phase C probe artifact fields do not match")
    if payload["schema_version"] != 1:
        raise ValueError("Phase C probe artifact schema version does not match")
    execution = phase_c_probe_execution_from_payload(payload["execution"])
    if payload["experiment"] != execution.experiment:
        raise ValueError("Phase C probe experiment does not match execution")
    parent = PhaseCArtifactReference.from_payload(payload["parent"])
    baseline = PhaseCBaselineReference.from_payload(payload["baseline"])
    no_write = PhaseCNoWriteEvidence.from_payload(payload["no_write"])
    expected_payload = build_phase_c_probe_artifact_payload(
        execution=execution,
        parent=parent,
        baseline=baseline,
        no_write=no_write,
    )
    if dict(payload) != expected_payload:
        raise ValueError("Phase C probe artifact does not replay")
    return execution, parent, baseline, no_write


@dataclass(frozen=True, slots=True)
class PartitionProbeParentProjection:
    reference: PhaseCArtifactReference
    partition_catalog_hash: str
    endpoint_contract_id: str
    endpoint_contract_hash: str
    policy_hash: str
    baseline_state_hash: str
    plan_hash: str
    execution_hash: str
    condition_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.reference.experiment != PARTITION_PROBE_EXPERIMENT:
            raise ValueError("comparison parent must be a partition probe")
        if self.partition_catalog_hash != offertoday_partition_catalog_hash():
            raise ValueError("comparison parent partition catalog hash does not match")
        contract = offertoday_endpoint_contract(self.endpoint_contract_id)
        if self.endpoint_contract_hash != contract.contract_hash:
            raise ValueError("comparison parent endpoint contract hash does not match")
        for field_name in (
            "policy_hash",
            "baseline_state_hash",
            "plan_hash",
            "execution_hash",
        ):
            _sha256(getattr(self, field_name), field_name)
        if not isinstance(self.condition_hashes, tuple) or not self.condition_hashes:
            raise ValueError("comparison parent requires condition hashes")
        for index, value in enumerate(self.condition_hashes):
            _sha256(value, f"condition_hashes[{index}]")
        if len(set(self.condition_hashes)) != len(self.condition_hashes):
            raise ValueError("comparison parent condition hashes must be distinct")

    def to_payload(self) -> dict[str, Any]:
        return {
            "reference": self.reference.to_payload(),
            "partition_catalog_hash": self.partition_catalog_hash,
            "endpoint_contract_id": self.endpoint_contract_id,
            "endpoint_contract_hash": self.endpoint_contract_hash,
            "policy_hash": self.policy_hash,
            "baseline_state_hash": self.baseline_state_hash,
            "plan_hash": self.plan_hash,
            "execution_hash": self.execution_hash,
            "condition_hashes": list(self.condition_hashes),
        }

    @classmethod
    def from_payload(cls, payload: Any) -> PartitionProbeParentProjection:
        expected = {
            "reference",
            "partition_catalog_hash",
            "endpoint_contract_id",
            "endpoint_contract_hash",
            "policy_hash",
            "baseline_state_hash",
            "plan_hash",
            "execution_hash",
            "condition_hashes",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("partition probe parent projection fields do not match")
        return cls(
            reference=PhaseCArtifactReference.from_payload(payload["reference"]),
            partition_catalog_hash=payload["partition_catalog_hash"],
            endpoint_contract_id=payload["endpoint_contract_id"],
            endpoint_contract_hash=payload["endpoint_contract_hash"],
            policy_hash=payload["policy_hash"],
            baseline_state_hash=payload["baseline_state_hash"],
            plan_hash=payload["plan_hash"],
            execution_hash=payload["execution_hash"],
            condition_hashes=_string_tuple(
                payload["condition_hashes"], "condition_hashes"
            ),
        )


def build_partition_probe_parent_projection(
    *,
    reference: PhaseCArtifactReference,
    probe_payload: Mapping[str, Any],
) -> tuple[PartitionProbeParentProjection, PhaseCProbeExecution]:
    execution, _, baseline, _ = validate_phase_c_probe_artifact_payload(
        probe_payload
    )
    if execution.experiment != PARTITION_PROBE_EXPERIMENT or not isinstance(
        execution.plan, PartitionProbePlan
    ):
        raise ValueError("comparison parent must contain a partition probe")
    if reference.experiment != PARTITION_PROBE_EXPERIMENT:
        raise ValueError("comparison parent reference experiment does not match")
    if reference.payload_hash != canonical_phase_c_hash(probe_payload):
        raise ValueError("comparison parent payload hash does not match")
    if reference.accepted is not execution.accepted:
        raise ValueError("comparison parent acceptance does not match")
    projection = PartitionProbeParentProjection(
        reference=reference,
        partition_catalog_hash=probe_payload["partition_catalog_hash"],
        endpoint_contract_id=execution.plan.endpoint_contract_id,
        endpoint_contract_hash=execution.plan.endpoint_contract.contract_hash,
        policy_hash=partition_probe_policy_hash(execution.plan),
        baseline_state_hash=baseline.state_hash,
        plan_hash=execution.plan.plan_hash,
        execution_hash=canonical_phase_c_hash(execution.to_payload()),
        condition_hashes=tuple(
            canonical_phase_c_hash(condition.to_payload())
            for condition in execution.conditions
        ),
    )
    return projection, execution


def build_partition_comparison_artifact_payload(
    parents: Sequence[tuple[PartitionProbeParentProjection, PhaseCProbeExecution]],
) -> dict[str, Any]:
    if not parents:
        raise ValueError("partition comparison requires parent probes")
    projections = tuple(parent[0] for parent in parents)
    executions = tuple(parent[1] for parent in parents)
    if len({item.reference.run_id for item in projections}) != len(projections):
        raise ValueError("partition comparison parent run IDs must be distinct")
    if len({item.reference.manifest_hash for item in projections}) != len(projections):
        raise ValueError("partition comparison parent manifests must be distinct")
    matching_fields = (
        "partition_catalog_hash",
        "endpoint_contract_id",
        "endpoint_contract_hash",
        "policy_hash",
        "baseline_state_hash",
    )
    for field_name in matching_fields:
        if len({getattr(item, field_name) for item in projections}) != 1:
            raise ValueError(f"partition comparison parent {field_name} mismatch")
    conditions = tuple(
        condition for execution in executions for condition in execution.conditions
    )
    if not conditions:
        raise ValueError("partition comparison requires condition evidence")
    if len({condition.partition_id for condition in conditions}) != len(conditions):
        raise ValueError("partition comparison partition IDs must be distinct")
    ordered_conditions = tuple(
        sorted(conditions, key=lambda item: _PARTITION_ORDER[item.partition_id])
    )
    for projection, execution in parents:
        expected_hashes = tuple(
            canonical_phase_c_hash(condition.to_payload())
            for condition in execution.conditions
        )
        if projection.condition_hashes != expected_hashes:
            raise ValueError("partition comparison parent condition hashes mismatch")
        if projection.execution_hash != canonical_phase_c_hash(execution.to_payload()):
            raise ValueError("partition comparison parent execution hash mismatch")
    projection_payloads = [item.to_payload() for item in projections]
    decision_payload = comparison_payload(ordered_conditions)
    return {
        "schema_version": 1,
        "experiment": PARTITION_COMPARISON_EXPERIMENT,
        "partition_catalog_hash": projections[0].partition_catalog_hash,
        "endpoint_contract_id": projections[0].endpoint_contract_id,
        "endpoint_contract_hash": projections[0].endpoint_contract_hash,
        "policy_hash": projections[0].policy_hash,
        "baseline_state_hash": projections[0].baseline_state_hash,
        "parents": projection_payloads,
        "parent_set_hash": canonical_phase_c_hash(projection_payloads),
        "comparison": decision_payload,
        "comparison_hash": canonical_phase_c_hash(decision_payload),
        "candidate_frozen": False,
    }


def validate_partition_comparison_artifact_payload(payload: Any):
    expected = {
        "schema_version",
        "experiment",
        "partition_catalog_hash",
        "endpoint_contract_id",
        "endpoint_contract_hash",
        "policy_hash",
        "baseline_state_hash",
        "parents",
        "parent_set_hash",
        "comparison",
        "comparison_hash",
        "candidate_frozen",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("partition comparison artifact fields do not match")
    if (
        payload["schema_version"] != 1
        or payload["experiment"] != PARTITION_COMPARISON_EXPERIMENT
        or payload["candidate_frozen"] is not False
    ):
        raise ValueError("partition comparison artifact contract does not match v1")
    raw_parents = payload["parents"]
    if not isinstance(raw_parents, list) or not raw_parents:
        raise ValueError("partition comparison parents must be a nonempty list")
    parents = tuple(
        PartitionProbeParentProjection.from_payload(item) for item in raw_parents
    )
    if len({item.reference.run_id for item in parents}) != len(parents):
        raise ValueError("partition comparison parent run IDs must be distinct")
    if len({item.reference.manifest_hash for item in parents}) != len(parents):
        raise ValueError("partition comparison parent manifests must be distinct")
    for field_name in (
        "partition_catalog_hash",
        "endpoint_contract_id",
        "endpoint_contract_hash",
        "policy_hash",
        "baseline_state_hash",
    ):
        values = {getattr(parent, field_name) for parent in parents}
        if len(values) != 1 or payload[field_name] != next(iter(values)):
            raise ValueError(f"partition comparison parent {field_name} mismatch")
    if payload["parent_set_hash"] != canonical_phase_c_hash(raw_parents):
        raise ValueError("partition comparison parent_set_hash does not match")
    decision = validate_comparison_payload(payload["comparison"])
    if payload["comparison_hash"] != canonical_phase_c_hash(payload["comparison"]):
        raise ValueError("partition comparison hash does not match")
    condition_hashes = tuple(
        canonical_phase_c_hash(item) for item in payload["comparison"]["inputs"]
    )
    parent_condition_hashes = tuple(
        condition_hash
        for parent in parents
        for condition_hash in parent.condition_hashes
    )
    if (
        len(condition_hashes) != len(parent_condition_hashes)
        or set(condition_hashes) != set(parent_condition_hashes)
    ):
        raise ValueError("partition comparison parent condition evidence mismatch")
    return decision, parents


def phase_c_probe_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    execution, _, _, no_write = validate_phase_c_probe_artifact_payload(payload)
    return {
        "experiment": execution.experiment,
        "status": "failed" if execution.failure_reason is not None else "completed",
        "accepted": execution.accepted,
        "failure_reason": execution.failure_reason,
        "plan_hash": execution.plan.plan_hash,
        "policy_hash": payload["policy_hash"],
        "request_budget": execution.plan.budget.to_payload(),
        "logical_listing_requests": execution.logical_requests,
        "physical_listing_attempts": execution.physical_attempts,
        **no_write.to_payload(),
        "candidate_frozen": False,
    }


def phase_c_comparison_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    decision, parents = validate_partition_comparison_artifact_payload(payload)
    return {
        "experiment": PARTITION_COMPARISON_EXPERIMENT,
        "status": "completed",
        "accepted": decision.accepted,
        "parent_count": len(parents),
        "parent_set_hash": payload["parent_set_hash"],
        "comparison_hash": payload["comparison_hash"],
        "reference_union_count": len(decision.reference_union_ids),
        "reference_union_hash": decision.reference_union_hash,
        "retained_partition_ids": [
            item.partition_id for item in decision.contributions if item.retained
        ],
        "rejected_partition_ids": [
            item.partition_id for item in decision.contributions if not item.retained
        ],
        "candidate_frozen": False,
    }


def phase_c_probe_metadata(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    planner_version: str,
) -> dict[str, Any]:
    execution, parent, baseline, no_write = validate_phase_c_probe_artifact_payload(
        payload
    )
    _canonical_uuid(run_id, "run_id")
    _nonblank(planner_version, "planner_version")
    return {
        "experiment": execution.experiment,
        "crawl_job_id": run_id,
        "crawl_job_status": (
            "failed" if execution.failure_reason is not None else "completed"
        ),
        "parent_experiment": parent.experiment,
        "parent_run_id": parent.run_id,
        "parent_artifact_hash": parent.manifest_hash,
        "parent_payload_hash": parent.payload_hash,
        "baseline_artifact_hashes": list(baseline.artifact_hashes),
        "baseline_run_ids": list(baseline.run_ids),
        "baseline_snapshot_hash": baseline.snapshot_hash,
        "baseline_inventory_hash": baseline.inventory_hash,
        "baseline_state_hash": baseline.state_hash,
        "partition_catalog_hash": payload["partition_catalog_hash"],
        "endpoint_contract_ids": payload["endpoint_contract_ids"],
        "endpoint_contract_hashes": payload["endpoint_contract_hashes"],
        "request_policy_hashes": payload["request_policy_hashes"],
        "plan_hash": execution.plan.plan_hash,
        "policy_hash": payload["policy_hash"],
        "request_budget": execution.plan.budget.to_payload(),
        "payload_hash": canonical_phase_c_hash(payload),
        "product_data_unchanged": no_write.product_data_unchanged,
        "staging_mode": no_write.staging_mode,
        "candidate_frozen": False,
        "planner_version": planner_version,
    }


def phase_c_comparison_metadata(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    planner_version: str,
) -> dict[str, Any]:
    decision, parents = validate_partition_comparison_artifact_payload(payload)
    _canonical_uuid(run_id, "run_id")
    _nonblank(planner_version, "planner_version")
    return {
        "experiment": PARTITION_COMPARISON_EXPERIMENT,
        "crawl_job_id": run_id,
        "crawl_job_status": "completed",
        "parent_artifact_hash": parents[-1].reference.manifest_hash,
        "parent_artifact_hashes": [
            item.reference.manifest_hash for item in parents
        ],
        "parent_run_ids": [item.reference.run_id for item in parents],
        "parent_set_hash": payload["parent_set_hash"],
        "partition_catalog_hash": payload["partition_catalog_hash"],
        "endpoint_contract_id": payload["endpoint_contract_id"],
        "endpoint_contract_hash": payload["endpoint_contract_hash"],
        "policy_hash": payload["policy_hash"],
        "baseline_state_hash": payload["baseline_state_hash"],
        "payload_hash": canonical_phase_c_hash(payload),
        "accepted": decision.accepted,
        "candidate_frozen": False,
        "planner_version": planner_version,
    }


def phase_c_artifact_events(
    payload: Mapping[str, Any],
    *,
    created_at: str,
) -> list[dict[str, Any]]:
    _nonblank(created_at, "created_at")
    experiment = payload.get("experiment")
    payload_hash = canonical_phase_c_hash(payload)
    if experiment in _PROBE_FILE_BY_EXPERIMENT:
        execution, parent, baseline, _ = validate_phase_c_probe_artifact_payload(
            payload
        )
        started_payload = {
            "experiment": experiment,
            "plan_hash": execution.plan.plan_hash,
            "policy_hash": payload["policy_hash"],
            "request_budget": execution.plan.budget.to_payload(),
            "parent_artifact_hash": parent.manifest_hash,
            "baseline_state_hash": baseline.state_hash,
        }
        summary = phase_c_probe_summary(payload)
        failure_reason = execution.failure_reason
    elif experiment == PARTITION_COMPARISON_EXPERIMENT:
        _, parents = validate_partition_comparison_artifact_payload(payload)
        started_payload = {
            "experiment": experiment,
            "parent_count": len(parents),
            "parent_set_hash": payload["parent_set_hash"],
            "policy_hash": payload["policy_hash"],
            "baseline_state_hash": payload["baseline_state_hash"],
        }
        summary = phase_c_comparison_summary(payload)
        failure_reason = None
    else:
        raise ValueError("unsupported Phase C artifact experiment")

    event_payloads: list[tuple[str, dict[str, Any]]] = [
        ("research.run_started", started_payload)
    ]
    if failure_reason is not None:
        event_payloads.append(
            ("research.run_stopped", {"reason": failure_reason})
        )
    event_payloads.extend(
        (
            (
                "research.phase_c_evidence_frozen",
                {"experiment": experiment, "payload_hash": payload_hash},
            ),
            ("research.run_summary", summary),
        )
    )
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
class PhaseCArtifactVerification:
    valid: bool
    issues: tuple[str, ...]
    experiment: str | None
    run_id: str | None


def _contains_forbidden_evidence(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in _FORBIDDEN_NORMALIZED_KEYS:
                return True
            if _contains_forbidden_evidence(item):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_forbidden_evidence(item) for item in value)
    if isinstance(value, str):
        return bool(
            _BEARER_RE.search(value)
            or _CREDENTIAL_URL_RE.search(value)
            or _PRIVATE_KEY_RE.search(value)
        )
    return False


def _load_phase_c_artifact(
    artifact_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], str, dict[str, Any]]:
    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Phase C manifest metadata must be an object")
    experiment = metadata.get("experiment")
    if experiment in _PROBE_FILE_BY_EXPERIMENT:
        file_name = _PROBE_FILE_BY_EXPERIMENT[experiment]
    elif experiment == PARTITION_COMPARISON_EXPERIMENT:
        file_name = "partition-comparison.json"
    else:
        raise ValueError("unsupported Phase C artifact experiment")
    expected_files = {"observations.jsonl", "working-tree.patch", file_name}
    if set(manifest.get("files", {})) != expected_files:
        raise ValueError("Phase C artifact files do not match experiment")
    payload = json.loads((artifact_dir / file_name).read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (artifact_dir / "observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    return manifest, events, file_name, payload


def verify_phase_c_artifact(artifact_dir: Path) -> PhaseCArtifactVerification:
    artifact_dir = Path(artifact_dir)
    generic = verify_research_artifact(artifact_dir)
    if not generic.valid:
        return PhaseCArtifactVerification(
            valid=False,
            issues=("invalid_research_artifact",),
            experiment=None,
            run_id=None,
        )
    try:
        manifest, events, _, payload = _load_phase_c_artifact(artifact_dir)
        metadata = manifest["metadata"]
        experiment = metadata["experiment"]
        run_id = manifest["run_id"]
        planner_version = metadata.get("planner_version")
        if experiment in _PROBE_FILE_BY_EXPERIMENT:
            validate_phase_c_probe_artifact_payload(payload)
            expected_metadata = phase_c_probe_metadata(
                payload,
                run_id=run_id,
                planner_version=planner_version,
            )
        else:
            validate_partition_comparison_artifact_payload(payload)
            expected_metadata = phase_c_comparison_metadata(
                payload,
                run_id=run_id,
                planner_version=planner_version,
            )
        if metadata != expected_metadata:
            raise ValueError("Phase C manifest metadata does not replay")
        expected_events = phase_c_artifact_events(
            payload,
            created_at=(events[0].get("created_at") if events else ""),
        )
        if events != expected_events:
            raise ValueError("Phase C artifact events do not replay")
        if _contains_forbidden_evidence(
            {"metadata": metadata, "events": events, "payload": payload}
        ):
            raise ValueError("Phase C artifact contains forbidden secret evidence")
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        experiment_value = None
        run_id_value = None
        try:
            manifest_data = json.loads(
                (artifact_dir / "manifest.json").read_text(encoding="utf-8")
            )
            metadata_value = manifest_data.get("metadata")
            if isinstance(metadata_value, dict) and isinstance(
                metadata_value.get("experiment"), str
            ):
                experiment_value = metadata_value["experiment"]
            if isinstance(manifest_data.get("run_id"), str):
                run_id_value = manifest_data["run_id"]
        except (json.JSONDecodeError, OSError, TypeError):
            pass
        return PhaseCArtifactVerification(
            valid=False,
            issues=(f"invalid_phase_c_artifact:{type(exc).__name__}",),
            experiment=experiment_value,
            run_id=run_id_value,
        )
    return PhaseCArtifactVerification(
        valid=True,
        issues=(),
        experiment=experiment,
        run_id=run_id,
    )


def phase_c_artifact_reference(
    artifact_dir: Path,
) -> PhaseCArtifactReference:
    verification = verify_phase_c_artifact(artifact_dir)
    if not verification.valid or verification.experiment not in _PHASE_C_EXPERIMENTS:
        raise ValueError("Phase C artifact failed strict verification")
    artifact_dir = Path(artifact_dir)
    manifest, _, _, payload = _load_phase_c_artifact(artifact_dir)
    if verification.experiment in _PROBE_FILE_BY_EXPERIMENT:
        execution, _, _, _ = validate_phase_c_probe_artifact_payload(payload)
        accepted = execution.accepted
    else:
        decision, _ = validate_partition_comparison_artifact_payload(payload)
        accepted = decision.accepted
    return PhaseCArtifactReference(
        experiment=verification.experiment,
        run_id=manifest["run_id"],
        manifest_hash=hashlib.sha256(
            (artifact_dir / "manifest.json").read_bytes()
        ).hexdigest(),
        payload_hash=canonical_phase_c_hash(payload),
        accepted=accepted,
    )
