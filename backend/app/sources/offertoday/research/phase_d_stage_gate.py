"""Strict artifact replay for OfferToday Phase D research."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import UUID

from app.sources.offertoday.research.artifacts import verify_research_artifact
from app.sources.offertoday.research.phase_d import (
    DISCOVERY_POLICY_CANDIDATE_EXPERIMENT,
    PHASE_D_CENSUS_EXPERIMENT,
    PHASE_D_COMPARISON_EXPERIMENT,
    PHASE_D_FIXED_REPEAT_EXPERIMENT,
    PhaseDRunEvidence,
    canonical_phase_c_hash,
    phase_d_comparison_payload,
    validate_discovery_policy_candidate_artifact_payload,
    validate_phase_d_comparison_payload,
    validate_phase_d_run_artifact_payload,
)


_FILE_BY_EXPERIMENT = {
    DISCOVERY_POLICY_CANDIDATE_EXPERIMENT: "discovery-policy.json",
    PHASE_D_CENSUS_EXPERIMENT: "phase-d-run.json",
    PHASE_D_FIXED_REPEAT_EXPERIMENT: "phase-d-run.json",
    PHASE_D_COMPARISON_EXPERIMENT: "phase-d-comparison.json",
}
PHASE_D_EXPERIMENTS = frozenset(_FILE_BY_EXPERIMENT)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_CREDENTIAL_URL_RE = re.compile(r"://[^\s/:]+:[^\s/@]+@")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----",
    re.IGNORECASE,
)
_FORBIDDEN_NORMALIZED_KEYS = {
    "authstatepath",
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
    "storagestatepath",
}


def _sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


def _nonblank(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be a nonblank trimmed string")
    return value


def _canonical_uuid(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a canonical UUID")
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a canonical UUID") from exc
    return value


@dataclass(frozen=True, slots=True)
class PhaseDArtifactReference:
    experiment: str
    run_id: str
    manifest_hash: str
    payload_hash: str
    accepted: bool
    candidate_hash: str
    captured_at: str

    def __post_init__(self) -> None:
        if self.experiment not in {
            PHASE_D_CENSUS_EXPERIMENT,
            PHASE_D_FIXED_REPEAT_EXPERIMENT,
        }:
            raise ValueError("unsupported Phase D parent experiment")
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
    def from_payload(cls, payload: Any) -> "PhaseDArtifactReference":
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
            raise ValueError("Phase D parent reference fields do not match")
        return cls(**{field: payload[field] for field in expected})


def build_phase_d_comparison_artifact_payload(
    parents: Sequence[tuple[PhaseDArtifactReference, Mapping[str, Any]]],
    *,
    active_holdout_ids: Sequence[str] = (),
) -> dict[str, Any]:
    items = tuple(parents)
    if len(items) != 6:
        raise ValueError("Phase D comparison requires exactly six parents")
    references = tuple(item[0] for item in items)
    if len({reference.run_id for reference in references}) != 6:
        raise ValueError("Phase D comparison parent run IDs must be distinct")
    if len({reference.manifest_hash for reference in references}) != 6:
        raise ValueError("Phase D comparison parent manifests must be distinct")

    runs: list[PhaseDRunEvidence] = []
    for reference, raw_payload in items:
        payload = dict(raw_payload)
        run, _, _, _ = validate_phase_d_run_artifact_payload(payload)
        if (
            reference.experiment != run.experiment
            or reference.run_id != run.run_id
            or reference.payload_hash != canonical_phase_c_hash(payload)
            or reference.accepted is not payload["accepted"]
            or reference.candidate_hash != run.candidate_hash
            or reference.captured_at != run.captured_at
        ):
            raise ValueError("Phase D comparison parent projection does not match")
        runs.append(run)

    censuses = tuple(
        run for run in runs if run.experiment == PHASE_D_CENSUS_EXPERIMENT
    )
    fixed = tuple(
        run for run in runs if run.experiment == PHASE_D_FIXED_REPEAT_EXPERIMENT
    )
    comparison = phase_d_comparison_payload(
        censuses,
        fixed,
        active_holdout_ids=active_holdout_ids,
    )
    reference_payloads = [reference.to_payload() for reference in references]
    return {
        "schema_version": 1,
        "experiment": PHASE_D_COMPARISON_EXPERIMENT,
        "parents": reference_payloads,
        "parent_set_hash": canonical_phase_c_hash(reference_payloads),
        "comparison": comparison,
        "comparison_hash": canonical_phase_c_hash(comparison),
        "stable_reference_frozen": comparison["stable_reference_frozen"],
    }


def validate_phase_d_comparison_artifact_payload(
    payload: Any,
) -> tuple[tuple[PhaseDArtifactReference, ...], Any]:
    expected = {
        "schema_version",
        "experiment",
        "parents",
        "parent_set_hash",
        "comparison",
        "comparison_hash",
        "stable_reference_frozen",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("Phase D comparison artifact fields do not match")
    if (
        payload["schema_version"] != 1
        or payload["experiment"] != PHASE_D_COMPARISON_EXPERIMENT
    ):
        raise ValueError("Phase D comparison artifact contract does not match v2")
    raw_parents = payload["parents"]
    if not isinstance(raw_parents, list) or len(raw_parents) != 6:
        raise ValueError("Phase D comparison artifact requires six parents")
    parents = tuple(
        PhaseDArtifactReference.from_payload(item) for item in raw_parents
    )
    if len({parent.run_id for parent in parents}) != 6:
        raise ValueError("Phase D comparison parent run IDs must be distinct")
    if len({parent.manifest_hash for parent in parents}) != 6:
        raise ValueError("Phase D comparison parent manifests must be distinct")
    if payload["parent_set_hash"] != canonical_phase_c_hash(raw_parents):
        raise ValueError("Phase D comparison parent_set_hash does not match")
    comparison = validate_phase_d_comparison_payload(payload["comparison"])
    if payload["comparison_hash"] != canonical_phase_c_hash(
        payload["comparison"]
    ):
        raise ValueError("Phase D comparison hash does not match")
    comparison_runs = (
        *payload["comparison"]["inputs"]["census_runs"],
        *payload["comparison"]["inputs"]["fixed_runs"],
    )
    for parent, run_payload in zip(parents, comparison_runs, strict=True):
        run = PhaseDRunEvidence.from_payload(run_payload)
        if (
            parent.experiment != run.experiment
            or parent.run_id != run.run_id
            or parent.candidate_hash != run.candidate_hash
            or parent.captured_at != run.captured_at
            or parent.accepted is not run.accepted
        ):
            raise ValueError("Phase D comparison parent/run evidence mismatch")
    if payload["stable_reference_frozen"] is not comparison.decision.accepted:
        raise ValueError("Phase D stable-reference decision does not match")
    return parents, comparison


def phase_d_metadata(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    planner_version: str,
) -> dict[str, Any]:
    _canonical_uuid(run_id, "run_id")
    _nonblank(planner_version, "planner_version")
    experiment = payload.get("experiment")
    if experiment == DISCOVERY_POLICY_CANDIDATE_EXPERIMENT:
        candidate = validate_discovery_policy_candidate_artifact_payload(payload)
        return {
            "experiment": experiment,
            "crawl_job_id": run_id,
            "crawl_job_status": "completed",
            "candidate_frozen": True,
            "candidate_hash": candidate.candidate_hash,
            "phase_b_comparison_artifact_hash": (
                candidate.phase_b_comparison_artifact_hash
            ),
            "phase_c_comparison_artifact_hash": (
                candidate.phase_c_comparison_artifact_hash
            ),
            "source_artifact_hash": candidate.source_artifact_hash,
            "planner_version": planner_version,
        }
    if experiment in {PHASE_D_CENSUS_EXPERIMENT, PHASE_D_FIXED_REPEAT_EXPERIMENT}:
        run, candidate, baseline, product = validate_phase_d_run_artifact_payload(
            payload
        )
        planned_condition_count = (
            len(candidate.phase_d_partitions)
            if experiment == PHASE_D_CENSUS_EXPERIMENT
            else len(candidate.fixed_repeat_category_ids)
        )
        logical_budget = (
            planned_condition_count * candidate.max_pages_per_condition
        )
        return {
            "experiment": experiment,
            "crawl_job_id": run_id,
            "crawl_job_status": "completed" if payload["accepted"] else "failed",
            "accepted": payload["accepted"],
            "candidate_hash": candidate.candidate_hash,
            "candidate_artifact_hash": run.candidate_artifact_hash,
            "baseline_artifact_hashes": list(baseline.artifact_hashes),
            "baseline_run_ids": list(baseline.run_ids),
            "baseline_snapshot_hash": baseline.snapshot_hash,
            "baseline_inventory_hash": baseline.inventory_hash,
            "run_index": run.run_index,
            "window_id": run.window_id,
            "request_budget": {
                "listing_logical": logical_budget,
                "listing_attempt_max": (
                    logical_budget * candidate.max_attempts_per_page
                ),
                "detail": 0,
                "product_writes": 0,
            },
            "staging_mode": product.staging.staging_mode,
            "planner_version": planner_version,
        }
    if experiment == PHASE_D_COMPARISON_EXPERIMENT:
        parents, comparison = validate_phase_d_comparison_artifact_payload(payload)
        return {
            "experiment": experiment,
            "crawl_job_id": run_id,
            "crawl_job_status": "completed",
            "accepted": comparison.decision.accepted,
            "stable_reference_frozen": comparison.decision.accepted,
            "candidate_hash": comparison.candidate_hash,
            "parent_run_ids": [parent.run_id for parent in parents],
            "parent_manifest_hashes": [
                parent.manifest_hash for parent in parents
            ],
            "planner_version": planner_version,
        }
    raise ValueError("unsupported Phase D artifact experiment")


def phase_d_artifact_events(
    payload: Mapping[str, Any],
    *,
    created_at: str,
) -> list[dict[str, Any]]:
    _nonblank(created_at, "created_at")
    experiment = payload.get("experiment")
    if experiment == DISCOVERY_POLICY_CANDIDATE_EXPERIMENT:
        validate_discovery_policy_candidate_artifact_payload(payload)
        event_payloads = (("research.candidate_frozen", dict(payload)),)
    elif experiment in {
        PHASE_D_CENSUS_EXPERIMENT,
        PHASE_D_FIXED_REPEAT_EXPERIMENT,
    }:
        run, _, _, product = validate_phase_d_run_artifact_payload(payload)
        event_payloads: list[tuple[str, dict[str, Any]]] = [
            (
                "research.run_started",
                {
                    "experiment": experiment,
                    "run_id": run.run_id,
                    "run_index": run.run_index,
                    "window_id": run.window_id,
                    "candidate_hash": run.candidate_hash,
                },
            )
        ]
        for condition in run.conditions:
            event_payloads.extend(
                ("research.page_attempt", page.to_payload())
                for page in condition.pages
            )
            event_payloads.append(
                ("research.condition_completed", condition.to_payload())
            )
        event_payloads.append(
            (
                "research.run_summary",
                {
                    "run": run.to_payload(),
                    "product": product.to_payload(),
                    "accepted": payload["accepted"],
                },
            )
        )
    elif experiment == PHASE_D_COMPARISON_EXPERIMENT:
        validate_phase_d_comparison_artifact_payload(payload)
        event_payloads = [("research.comparison_completed", dict(payload))]
    else:
        raise ValueError("unsupported Phase D artifact experiment")
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


@dataclass(frozen=True, slots=True)
class PhaseDArtifactVerification:
    valid: bool
    issues: tuple[str, ...]
    experiment: str | None
    run_id: str | None


def _load_phase_d_artifact(
    artifact_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Phase D manifest metadata must be an object")
    experiment = metadata.get("experiment")
    try:
        file_name = _FILE_BY_EXPERIMENT[experiment]
    except (KeyError, TypeError) as exc:
        raise ValueError("unsupported Phase D artifact experiment") from exc
    expected_files = {"observations.jsonl", "working-tree.patch", file_name}
    if set(manifest.get("files", {})) != expected_files:
        raise ValueError("Phase D artifact files do not match experiment")
    payload = json.loads((artifact_dir / file_name).read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (artifact_dir / "observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    return manifest, events, payload


def verify_phase_d_artifact(artifact_dir: Path) -> PhaseDArtifactVerification:
    artifact_dir = Path(artifact_dir)
    generic = verify_research_artifact(artifact_dir)
    if not generic.valid:
        return PhaseDArtifactVerification(
            valid=False,
            issues=("invalid_research_artifact",),
            experiment=None,
            run_id=None,
        )
    try:
        manifest, events, payload = _load_phase_d_artifact(artifact_dir)
        metadata = manifest["metadata"]
        experiment = metadata["experiment"]
        run_id = manifest["run_id"]
        planner_version = metadata.get("planner_version")
        if experiment == DISCOVERY_POLICY_CANDIDATE_EXPERIMENT:
            validate_discovery_policy_candidate_artifact_payload(payload)
        elif experiment in {
            PHASE_D_CENSUS_EXPERIMENT,
            PHASE_D_FIXED_REPEAT_EXPERIMENT,
        }:
            run, _, _, _ = validate_phase_d_run_artifact_payload(payload)
            if run.run_id != run_id:
                raise ValueError("Phase D run payload run_id does not match manifest")
        elif experiment == PHASE_D_COMPARISON_EXPERIMENT:
            validate_phase_d_comparison_artifact_payload(payload)
        else:  # pragma: no cover - file map guards this branch
            raise ValueError("unsupported Phase D artifact experiment")
        expected_metadata = phase_d_metadata(
            payload,
            run_id=run_id,
            planner_version=planner_version,
        )
        if metadata != expected_metadata:
            raise ValueError("Phase D manifest metadata does not replay")
        expected_events = phase_d_artifact_events(
            payload,
            created_at=(events[0].get("created_at") if events else ""),
        )
        if events != expected_events:
            raise ValueError("Phase D artifact events do not replay")
        if _contains_forbidden_evidence(
            {"metadata": metadata, "events": events, "payload": payload}
        ):
            raise ValueError("Phase D artifact contains forbidden secret evidence")
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
        return PhaseDArtifactVerification(
            valid=False,
            issues=(f"invalid_phase_d_artifact:{type(exc).__name__}",),
            experiment=experiment_value,
            run_id=run_id_value,
        )
    return PhaseDArtifactVerification(
        valid=True,
        issues=(),
        experiment=experiment,
        run_id=run_id,
    )


def phase_d_artifact_reference(artifact_dir: Path) -> PhaseDArtifactReference:
    verification = verify_phase_d_artifact(artifact_dir)
    if not verification.valid or verification.experiment not in {
        PHASE_D_CENSUS_EXPERIMENT,
        PHASE_D_FIXED_REPEAT_EXPERIMENT,
    }:
        raise ValueError("Phase D run artifact failed strict verification")
    artifact_dir = Path(artifact_dir)
    manifest, _, payload = _load_phase_d_artifact(artifact_dir)
    run, _, _, _ = validate_phase_d_run_artifact_payload(payload)
    return PhaseDArtifactReference(
        experiment=run.experiment,
        run_id=run.run_id,
        manifest_hash=hashlib.sha256(
            (artifact_dir / "manifest.json").read_bytes()
        ).hexdigest(),
        payload_hash=canonical_phase_c_hash(payload),
        accepted=payload["accepted"],
        candidate_hash=run.candidate_hash,
        captured_at=run.captured_at,
    )
