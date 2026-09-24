from __future__ import annotations

from app.services.jev_evaluation import (
    SkillOption,
    build_system_one_request,
    controlled_baseline_observations,
    deterministic_skill_baseline,
    rank_skill_options,
)


OPTIONS = (
    SkillOption(code="backend.python", labels={"en": "Python"}, aliases=("Py",)),
    SkillOption(code="frontend.react", labels={"en": "React"}, aliases=("ReactJS",)),
    SkillOption(
        code="database.postgresql", labels={"en": "PostgreSQL"}, aliases=("Postgres",)
    ),
)


def test_deterministic_baseline_separates_exact_alias_generic_and_unresolved() -> None:
    assert deterministic_skill_baseline("Python", OPTIONS) == {
        "outcome": "match_existing",
        "skill_code": "backend.python",
        "reason": "label_exact",
    }
    assert deterministic_skill_baseline("ReactJS", OPTIONS) == {
        "outcome": "match_existing",
        "skill_code": "frontend.react",
        "reason": "alias_exact",
    }
    assert deterministic_skill_baseline("項目管理", OPTIONS)["outcome"] == "generic"
    assert deterministic_skill_baseline("Unknown Framework", OPTIONS) == {
        "outcome": "unresolved",
        "skill_code": None,
        "reason": None,
    }


def test_similarity_ranking_has_stable_ties_and_labels_score_as_heuristic() -> None:
    ranked = rank_skill_options("Postgres", tuple(reversed(OPTIONS)), limit=3)
    assert ranked[0] == {
        "code": "database.postgresql",
        "name": "PostgreSQL",
        "score": 1.0,
        "reason": "alias_similarity",
        "score_kind": "heuristic_string_similarity",
    }


def test_controlled_case_builds_native_request_without_mutation() -> None:
    from pathlib import Path

    from app.services.jev_evaluation import load_controlled_cases

    fixture = Path(__file__).parent / "fixtures" / "jev_skill_controlled_v1.jsonl"
    case = load_controlled_cases(fixture)[0]
    request = build_system_one_request(case, model="jev-latest")

    assert request.state == case.state
    assert request.model == "jev-latest"
    assert tuple(request.questions) == ("decision",)
    assert request.questions["decision"].type == "choice"


def test_controlled_baseline_scores_candidate_only_and_abstains_on_evidence() -> None:
    from pathlib import Path

    from app.services.jev_evaluation import load_controlled_cases, score_evaluation

    fixture = Path(__file__).parent / "fixtures" / "jev_skill_controlled_v1.jsonl"
    observations = controlled_baseline_observations(load_controlled_cases(fixture))
    report = score_evaluation(observations)

    assert report["controlled"]["evidence_support"]["actionable_coverage"] == "0.000"
    assert report["controlled"]["candidate_recommendation"]["eligible"] == 5
    assert report["controlled"]["candidate_recommendation"]["answered"] == 5
    assert report["option_reordering_stability"]["rate"] == "1.000"
    assert report["decision"] == "defer"
