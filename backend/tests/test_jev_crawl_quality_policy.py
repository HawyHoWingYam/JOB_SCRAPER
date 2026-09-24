from pathlib import Path

from app.services.jev_crawl_quality import (
    classify_crawl_quality_candidate,
    crawl_quality_candidate_recall,
    load_crawl_quality_cases,
)


FIXTURE = Path(__file__).parent / "fixtures" / "jev_crawl_quality_controlled_v1.jsonl"


def test_deterministic_policy_keeps_known_failures_out_of_paid_work() -> None:
    cases = load_crawl_quality_cases(FIXTURE)
    dispositions = {
        case.case_id: classify_crawl_quality_candidate(case) for case in cases
    }

    assert dispositions["dev-jobsdb-waf"] == "deterministic_problem"
    assert dispositions["dev-ct-terminal"] == "deterministic_problem"
    assert dispositions["held-jobsdb-missing"] == "insufficient"
    assert dispositions["dev-jobsdb-valid-en"] == "jev_candidate"
    assert dispositions["dev-offertoday-listing-as-detail"] == "jev_candidate"


def test_candidate_policy_meets_frozen_problem_recall() -> None:
    cases = load_crawl_quality_cases(FIXTURE)
    metric = crawl_quality_candidate_recall(cases)

    assert metric["eligible_problem_cases"] >= 1
    assert metric["recalled_problem_cases"] == metric["eligible_problem_cases"]
    assert metric["recall"] >= 0.95
