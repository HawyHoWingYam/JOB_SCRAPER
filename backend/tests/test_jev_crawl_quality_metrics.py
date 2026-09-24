from dataclasses import replace

from app.services.jev_crawl_quality import score_crawl_quality_evaluation
from app.services.jev_crawl_quality_runner import CrawlQualityObservation


def _observation(
    case_id: str, expected: str, predicted: str | None, kind: str
) -> CrawlQualityObservation:
    return CrawlQualityObservation(
        case_id=case_id,
        run_id="run",
        manifest_sha256="a" * 64,
        evidence_sha256="b" * 64,
        status="answered" if predicted else "unavailable",
        expected=expected,
        expected_problem_kind=kind,
        predicted=predicted,
        predicted_problem_kind=kind if predicted else None,
        quality_probabilities={predicted: 1.0} if predicted else {},
        problem_kind_probabilities={kind: 1.0} if predicted else {},
        source_site="jobsdb",
        language="en",
        stability_group=None,
        request_id=None,
        model="typesafe/jev-1.13",
        provider="TypeSafe",
        actual_microdollars=5 if predicted else 0,
        input_tokens=100 if predicted else 0,
        output_tokens=10 if predicted else 0,
        latency_ms=20 if predicted else None,
        error_code=None if predicted else "transport_error",
    )


def test_metrics_keep_missed_candidates_and_non_answers_in_denominators() -> None:
    observations = (
        _observation("problem", "quality_problem", "quality_problem", "truncated"),
        _observation("valid", "usable_job_detail", None, "none"),
    )
    report = score_crawl_quality_evaluation(
        observations,
        eligible_problem_cases=2,
        candidate_recalled_problem_cases=1,
        real_reference_languages=set(),
    )
    assert report["candidate"]["recall"] == 0.5
    assert report["quality"]["problem_recall"] == 0.5
    assert report["quality"]["actionable_coverage"] == 0.5
    assert report["quality"]["technical_failure_rate"] == 0.5
    assert report["decision"] == "defer"


def test_metrics_pass_controlled_gates_but_require_bilingual_real_references() -> None:
    observations = tuple(
        [
            _observation(f"bad-{i}", "quality_problem", "quality_problem", "irrelevant")
            for i in range(10)
        ]
        + [
            _observation(f"good-{i}", "usable_job_detail", "usable_job_detail", "none")
            for i in range(4)
        ]
    )
    observations = observations + (
        replace(observations[0], case_id="stable-a", stability_group="stable"),
        replace(observations[0], case_id="stable-b", stability_group="stable"),
    )
    report = score_crawl_quality_evaluation(
        observations,
        eligible_problem_cases=12,
        candidate_recalled_problem_cases=12,
        real_reference_languages=set(),
    )
    assert report["quality"]["problem_precision"] == 1.0
    assert report["quality"]["false_flag_rate"] == 0.0
    assert report["quality"]["problem_kind_accuracy"] == 1.0
    assert report["stability"]["rate"] == 1.0
    assert report["decision"] == "inconclusive"

    passed = score_crawl_quality_evaluation(
        observations,
        eligible_problem_cases=12,
        candidate_recalled_problem_cases=12,
        real_reference_languages={"en", "zh-Hant"},
    )
    assert passed["decision"] == "proceed_limited_review"
