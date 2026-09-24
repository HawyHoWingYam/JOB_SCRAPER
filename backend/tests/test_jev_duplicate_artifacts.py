from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.jev_duplicate_evaluation import (
    DuplicateArtifactError,
    load_duplicate_cases,
)


FIXTURE = Path(__file__).parent / "fixtures" / "jev_duplicate_controlled_v1.jsonl"


def test_controlled_duplicate_fixture_is_bilingual_grouped_and_hash_verified() -> None:
    cases = load_duplicate_cases(FIXTURE)

    assert len(cases) >= 16
    assert {case.split for case in cases} == {"development", "held_out"}
    assert {case.language for case in cases} >= {"en", "zh-Hant", "mixed"}
    assert {case.expected for case in cases} == {
        "same_vacancy",
        "different_vacancy",
        "insufficient",
    }
    assert {tag for case in cases for tag in case.scenario_tags} >= {
        "exact_repost",
        "paraphrase",
        "translated_repost",
        "same_title_different_company",
        "same_company_different_role",
        "materially_changed_vacancy",
        "missing_evidence",
        "option_reordered",
        "transitive_chain_trap",
    }
    development_groups = {
        case.group_id for case in cases if case.split == "development"
    }
    held_out_groups = {case.group_id for case in cases if case.split == "held_out"}
    assert development_groups.isdisjoint(held_out_groups)


def test_controlled_duplicate_fixture_rejects_hash_drift_group_leakage_and_extra_fields(
    tmp_path: Path,
) -> None:
    rows = [json.loads(line) for line in FIXTURE.read_text().splitlines()]

    rows[0]["left"]["title"] += " changed"
    drifted = tmp_path / "drifted.jsonl"
    drifted.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    with pytest.raises(DuplicateArtifactError, match="pair_sha256"):
        load_duplicate_cases(drifted)

    rows = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    rows[1]["group_id"] = rows[0]["group_id"]
    rows[1]["split"] = "held_out"
    leaking = tmp_path / "leaking.jsonl"
    leaking.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    with pytest.raises(DuplicateArtifactError, match="group leakage"):
        load_duplicate_cases(leaking)

    rows = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    rows[0]["unexpected"] = True
    extra = tmp_path / "extra.jsonl"
    extra.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    with pytest.raises(DuplicateArtifactError, match="invalid duplicate case"):
        load_duplicate_cases(extra)
