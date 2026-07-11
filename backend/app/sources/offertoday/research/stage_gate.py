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
