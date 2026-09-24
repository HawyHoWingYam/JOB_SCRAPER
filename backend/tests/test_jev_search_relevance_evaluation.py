from pathlib import Path

from app.services.jev_search_relevance import (
    load_search_relevance_cases,
    page_ranked_candidates,
    score_search_relevance,
)


FIXTURE = Path(__file__).parent / "fixtures" / "jev_search_relevance_v1.jsonl"


def test_search_fixture_is_bilingual_strict_and_group_safe() -> None:
    cases = load_search_relevance_cases(FIXTURE)
    assert len(cases) >= 6
    assert {case.split for case in cases} == {"development", "held_out"}
    assert {case.language for case in cases} >= {"en", "zh-Hant", "mixed"}
    assert all(len(case.candidates) >= 3 for case in cases)
    assert all(len(case.candidates) <= 20 for case in cases)
    assert all(
        len({item.source_identity for item in case.candidates}) == len(case.candidates)
        for case in cases
    )


def test_baseline_metrics_and_page_export_membership_are_deterministic() -> None:
    cases = load_search_relevance_cases(FIXTURE)
    report = score_search_relevance(cases)
    assert report["candidate_recall_at_20"] == 1.0
    assert 0 <= report["mrr"] <= 1
    assert 0 <= report["ndcg_at_10"] <= 1
    assert report["tie_stability"] == 1.0

    case = cases[0]
    first = page_ranked_candidates(case, page=1, page_size=2)
    second = page_ranked_candidates(case, page=2, page_size=2)
    exported = page_ranked_candidates(case, page=1, page_size=len(case.candidates))
    assert tuple(first + second) == exported[:4]
    assert set(exported) == {candidate.source_identity for candidate in case.candidates}
