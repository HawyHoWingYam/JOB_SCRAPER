from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.jev_evaluation import (
    EvaluationArtifactError,
    EvaluationObservation,
    load_controlled_cases,
    score_evaluation,
)


FIXTURE = Path(__file__).parent / "fixtures" / "jev_skill_controlled_v1.jsonl"


def test_controlled_fixture_is_bilingual_grouped_and_hash_verified() -> None:
    cases = load_controlled_cases(FIXTURE)

    assert len(cases) >= 16
    assert {case.split for case in cases} == {"development", "held_out"}
    assert {case.decision_kind for case in cases} == {
        "evidence_support",
        "candidate_recommendation",
    }
    assert {case.language for case in cases} >= {"en", "zh-Hant", "mixed"}
    assert {case.group_id for case in cases if case.split == "development"}.isdisjoint(
        {case.group_id for case in cases if case.split == "held_out"}
    )
    assert {tag for case in cases for tag in case.scenario_tags} >= {
        "required",
        "preferred",
        "negation",
        "incidental",
        "missing_evidence",
        "option_reordered",
    }


def test_controlled_fixture_rejects_group_leakage_and_hash_drift(
    tmp_path: Path,
) -> None:
    source = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    source[1]["group_id"] = source[0]["group_id"]
    source[1]["split"] = "held_out"
    leaky = tmp_path / "leaky.jsonl"
    leaky.write_text("\n".join(json.dumps(row) for row in source) + "\n")

    with pytest.raises(EvaluationArtifactError, match="group leakage"):
        load_controlled_cases(leaky)

    source[1]["group_id"] = "restored"
    source[0]["state"]["evidence"] += " changed"
    drifted = tmp_path / "drifted.jsonl"
    drifted.write_text("\n".join(json.dumps(row) for row in source) + "\n")
    with pytest.raises(EvaluationArtifactError, match="evidence_sha256"):
        load_controlled_cases(drifted)


def test_metrics_keep_unresolved_and_failures_in_coverage_denominator() -> None:
    observations = [
        EvaluationObservation(
            case_id="a",
            split="held_out",
            decision_kind="evidence_support",
            status="answered",
            expected="required",
            predicted="required",
            latency_ms=10,
            input_tokens=4,
            output_tokens=1,
            actual_microdollars=5,
        ),
        EvaluationObservation(
            case_id="b",
            split="held_out",
            decision_kind="evidence_support",
            status="abstained",
            expected="preferred",
        ),
        EvaluationObservation(
            case_id="c",
            split="held_out",
            decision_kind="evidence_support",
            status="unavailable",
            expected="absent",
            error_code="transport_error",
        ),
    ]

    report = score_evaluation(observations)
    evidence = report["controlled"]["evidence_support"]
    assert evidence["eligible"] == 3
    assert evidence["answered"] == 1
    assert evidence["correct"] == 1
    assert evidence["answered_correctness"] == "1.000"
    assert evidence["actionable_coverage"] == "0.333"
    assert evidence["technical_failure_rate"] == "0.333"
    assert evidence["latency_ms_p50"] == 10
    assert evidence["latency_ms_p95"] == 10
    assert evidence["provider_reported_microdollars"] == 5
    assert report["decision"] == "inconclusive"
    assert report["option_reordering_stability"]["rate"] is None


def test_report_requires_stability_pairs_and_independent_bilingual_references() -> None:
    controlled = []
    for kind, expected in (
        ("evidence_support", "required"),
        ("candidate_recommendation", "backend.python"),
    ):
        for index in range(2):
            controlled.append(
                EvaluationObservation(
                    case_id=f"{kind}-{index}",
                    split="held_out",
                    decision_kind=kind,
                    status="answered",
                    expected=expected,
                    predicted=expected,
                    stability_group="stable-pair"
                    if kind == "candidate_recommendation"
                    else None,
                )
            )
    real = [
        EvaluationObservation(
            case_id=f"real-{language}",
            split="real_corpus",
            decision_kind="evidence_support",
            status="answered",
            expected="required",
            predicted="required",
            reference_provenance="independent_reviewer",
            language=language,
        )
        for language in ("en", "zh-Hant")
    ]

    report = score_evaluation(controlled + real)

    assert report["option_reordering_stability"]["rate"] == "1.000"
    assert report["decision"] == "proceed_limited_review"
    assert report["real_corpus_strata"]["language"] == {"en": 1, "zh-Hant": 1}
    assert report["real_corpus_strata"]["reference_provenance"] == {
        "independent_reviewer": 2
    }
