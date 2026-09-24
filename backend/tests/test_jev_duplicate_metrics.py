from __future__ import annotations

from app.services.jev_duplicate_evaluation import (
    score_duplicate_evaluation,
)
from app.services.jev_duplicate_runner import DuplicateObservation


def _observation(
    case_id: str,
    *,
    expected: str,
    predicted: str | None,
    status: str = "answered",
    language: str = "en",
    stability_group: str | None = None,
) -> DuplicateObservation:
    return DuplicateObservation(
        case_id=case_id,
        run_id="run-1",
        manifest_sha256="a" * 64,
        pair_sha256="b" * 64,
        rubric_version="jev-duplicate-pair-v1",
        status=status,
        expected=expected,
        predicted=predicted,
        probabilities={predicted: 1.0} if predicted else {},
        request_id="request-1" if status == "answered" else None,
        model="typesafe/jev-1.13",
        provider="TypeSafe",
        language=language,
        scenario_tags=(),
        stability_group=stability_group,
        actual_microdollars=5 if status == "answered" else 0,
        input_tokens=100 if status == "answered" else 0,
        output_tokens=10 if status == "answered" else 0,
        latency_ms=20 if status == "answered" else None,
        error_code=None if status == "answered" else "transport_error",
    )


def test_metrics_count_blocker_misses_and_non_answers_in_full_denominators() -> None:
    observations = (
        _observation(
            "positive-answered", expected="same_vacancy", predicted="same_vacancy"
        ),
        _observation(
            "negative-unavailable",
            expected="different_vacancy",
            predicted=None,
            status="unavailable",
        ),
    )

    report = score_duplicate_evaluation(
        observations,
        eligible_positive_pairs=2,
        candidate_recalled_positive_pairs=1,
        real_reference_languages=set(),
    )

    assert report["candidate"]["recall_at_10"] == 0.5
    assert report["controlled"]["recall"] == 0.5
    assert report["controlled"]["actionable_coverage"] == 0.5
    assert report["controlled"]["technical_failure_rate"] == 0.5
    assert report["decision"] == "defer"


def test_metrics_do_not_turn_low_coverage_or_zero_denominators_into_success() -> None:
    low_coverage = (
        _observation("one", expected="same_vacancy", predicted="same_vacancy"),
        *(
            _observation(
                f"missing-{index}",
                expected="different_vacancy",
                predicted=None,
                status="unavailable",
            )
            for index in range(4)
        ),
    )
    report = score_duplicate_evaluation(
        low_coverage,
        eligible_positive_pairs=1,
        candidate_recalled_positive_pairs=1,
        real_reference_languages={"en", "zh-Hant"},
    )
    assert report["controlled"]["precision"] == 1.0
    assert report["controlled"]["actionable_coverage"] == 0.2
    assert report["decision"] == "defer"

    empty = score_duplicate_evaluation(
        (),
        eligible_positive_pairs=0,
        candidate_recalled_positive_pairs=0,
        real_reference_languages=set(),
    )
    assert empty["controlled"]["precision"] == "not_evaluable"
    assert empty["decision"] == "inconclusive"


def test_proceed_requires_all_frozen_gates_stability_and_bilingual_real_review() -> (
    None
):
    observations = (
        *(
            _observation(
                f"positive-{index}",
                expected="same_vacancy",
                predicted="same_vacancy",
            )
            for index in range(4)
        ),
        *(
            _observation(
                f"negative-{index}",
                expected="different_vacancy",
                predicted="different_vacancy",
            )
            for index in range(4)
        ),
        _observation(
            "stable-a",
            expected="same_vacancy",
            predicted="same_vacancy",
            stability_group="stable-pair",
        ),
        _observation(
            "stable-b",
            expected="same_vacancy",
            predicted="same_vacancy",
            stability_group="stable-pair",
        ),
    )
    report = score_duplicate_evaluation(
        observations,
        eligible_positive_pairs=6,
        candidate_recalled_positive_pairs=6,
        real_reference_languages={"en", "zh-Hant"},
    )

    assert report["controlled"]["precision"] == 1.0
    assert report["controlled"]["recall"] == 1.0
    assert report["controlled"]["false_association_rate"] == 0.0
    assert report["option_reordering_stability"]["rate"] == 1.0
    assert report["decision"] == "proceed_limited_review"

    without_real_review = score_duplicate_evaluation(
        observations,
        eligible_positive_pairs=6,
        candidate_recalled_positive_pairs=6,
        real_reference_languages={"en"},
    )
    assert without_real_review["decision"] == "inconclusive"
    assert "independently reviewed" in " ".join(without_real_review["limitations"])


def test_candidate_and_judging_positive_denominators_are_independent() -> None:
    observations = (
        _observation("pair-a", expected="same_vacancy", predicted="same_vacancy"),
        _observation("pair-b-left", expected="same_vacancy", predicted="same_vacancy"),
        _observation("pair-b-right", expected="same_vacancy", predicted="same_vacancy"),
    )

    report = score_duplicate_evaluation(
        observations,
        eligible_positive_pairs=3,
        candidate_eligible_positive_pairs=2,
        candidate_recalled_positive_pairs=2,
        real_reference_languages=set(),
    )

    assert report["candidate"]["recall_at_10"] == 1.0
    assert report["candidate"]["eligible_positive_pairs"] == 2
    assert report["controlled"]["recall"] == 1.0
    assert report["controlled"]["eligible_positive_pairs"] == 3
