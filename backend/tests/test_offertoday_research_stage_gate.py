from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.sources.offertoday.research.artifacts import (
    ResearchProvenance,
    export_research_artifact,
)
from app.sources.offertoday.research.stage_gate import (
    load_baseline_artifact,
    require_matching_baselines,
)


SNAPSHOT_HASH = "a" * 64
INVENTORY_HASH = "b" * 64
RUN_ID_1 = "11111111-1111-1111-1111-111111111111"
RUN_ID_2 = "22222222-2222-2222-2222-222222222222"
BASELINE_COUNTS = {
    "staged_rows": 100,
    "distinct_staged_ids": 80,
    "published_jobs": 40,
    "distinct_staged_unpublished_ids": 40,
    "pending_rows": 25,
    "duplicate_staging_rows": 20,
}


def _provenance() -> ResearchProvenance:
    return ResearchProvenance(
        commit_sha="fixture-sha",
        working_tree_patch="",
        source_hashes={},
        compose_file_hashes={},
        captured_at="2026-07-11T00:00:00+00:00",
        runtime_context={"session_mode": "offline-fixture"},
        untracked_file_hashes={},
        excluded_tracked_file_hashes={},
        excluded_untracked_file_hashes={},
    )


def _baseline_event(
    *,
    snapshot_hash: str = SNAPSHOT_HASH,
    inventory_hash: str = INVENTORY_HASH,
    count_changes: dict[str, int] | None = None,
) -> dict:
    snapshot = {**BASELINE_COUNTS, **(count_changes or {})}
    snapshot["data_hash"] = snapshot_hash
    return {
        "sequence_no": 1,
        "event_type": "research.baseline",
        "payload": {
            "snapshot": snapshot,
            "run_start_inventory": {"data_hash": inventory_hash},
        },
    }


def _export(
    root: Path,
    *,
    run_id: str,
    events: list[dict] | None = None,
    snapshot_hash: str = SNAPSHOT_HASH,
    inventory_hash: str = INVENTORY_HASH,
    count_changes: dict[str, int] | None = None,
) -> Path:
    if events is None:
        events = [
            _baseline_event(
                snapshot_hash=snapshot_hash,
                inventory_hash=inventory_hash,
                count_changes=count_changes,
            )
        ]
    return export_research_artifact(
        root=root,
        run_id=run_id,
        metadata={"experiment": "foundation-baseline"},
        events=events,
        provenance=_provenance(),
    )


def test_matching_baselines_require_distinct_runs_with_identical_evidence(
    tmp_path,
) -> None:
    first_dir = _export(tmp_path, run_id=RUN_ID_1)
    second_dir = _export(tmp_path, run_id=RUN_ID_2)

    gate = require_matching_baselines(first_dir, second_dir)

    assert gate.first.run_id == RUN_ID_1
    assert gate.second.run_id == RUN_ID_2
    assert gate.first.snapshot_hash == gate.second.snapshot_hash == SNAPSHOT_HASH
    assert gate.first.inventory_hash == gate.second.inventory_hash == INVENTORY_HASH
    assert gate.first.counts == gate.second.counts == tuple(BASELINE_COUNTS.items())
    assert gate.parent_artifact_hash == hashlib.sha256(
        (second_dir / "manifest.json").read_bytes()
    ).hexdigest()


def test_load_baseline_artifact_rejects_tampered_artifact(tmp_path) -> None:
    artifact_dir = _export(tmp_path, run_id=RUN_ID_1)
    with (artifact_dir / "observations.jsonl").open("ab") as handle:
        handle.write(b"{}\n")

    with pytest.raises(ValueError, match="invalid baseline artifact"):
        load_baseline_artifact(artifact_dir)


def test_matching_baselines_reject_same_run_twice(tmp_path) -> None:
    artifact_dir = _export(tmp_path, run_id=RUN_ID_1)

    with pytest.raises(ValueError, match="two distinct run IDs"):
        require_matching_baselines(artifact_dir, artifact_dir)


@pytest.mark.parametrize(
    ("second_options", "message"),
    [
        ({"count_changes": {"staged_rows": 101}}, "count evidence"),
        ({"snapshot_hash": "c" * 64}, "snapshot hashes"),
        ({"inventory_hash": "d" * 64}, "inventory hashes"),
    ],
)
def test_matching_baselines_reject_drift(
    tmp_path,
    second_options: dict,
    message: str,
) -> None:
    first_dir = _export(tmp_path, run_id=RUN_ID_1)
    second_dir = _export(tmp_path, run_id=RUN_ID_2, **second_options)

    with pytest.raises(ValueError, match=message):
        require_matching_baselines(first_dir, second_dir)


def test_load_baseline_artifact_requires_one_baseline_event(tmp_path) -> None:
    artifact_dir = _export(tmp_path, run_id=RUN_ID_1, events=[])

    with pytest.raises(ValueError, match="exactly one research.baseline"):
        load_baseline_artifact(artifact_dir)


def test_load_baseline_artifact_rejects_multiple_baseline_events(tmp_path) -> None:
    artifact_dir = _export(
        tmp_path,
        run_id=RUN_ID_1,
        events=[_baseline_event(), _baseline_event()],
    )

    with pytest.raises(ValueError, match="exactly one research.baseline"):
        load_baseline_artifact(artifact_dir)
