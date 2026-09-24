from __future__ import annotations

from app.ai.system_one import ChoiceAnswer, SystemOneResult
from app.services.jev_online_skill_classification import (
    OnlineSkillCandidate,
    OnlineSkillCase,
    OnlineSkillOption,
    OnlineSkillThresholds,
    build_online_skill_dispatch,
    build_projection_skills,
    route_online_skill_result,
)


def _case() -> OnlineSkillCase:
    return OnlineSkillCase(
        job_id="job-1",
        source_site="jobsdb",
        title="Backend Engineer",
        evidence_text="Python is required. Java is useful but optional.",
        candidates=(
            OnlineSkillCandidate(
                raw_name="Python",
                evidence="Python is required.",
                options=(
                    OnlineSkillOption(code="backend.python", label="Python"),
                    OnlineSkillOption(code="backend.java", label="Java"),
                ),
            ),
        ),
        taxonomy_snapshot_sha256="a" * 64,
        rubric_version="jev-online-skill-v1",
    )


def _answer(choice: str, confidence: float, probabilities: dict[str, float]):
    return ChoiceAnswer(
        type="choice",
        choice=choice,
        confidence=confidence,
        probabilities=probabilities,
    )


def test_online_skill_dispatch_is_deterministic_and_binds_taxonomy_and_rubric() -> None:
    first = build_online_skill_dispatch(_case(), model="typesafe/jev-1.13")
    second = build_online_skill_dispatch(_case(), model="typesafe/jev-1.13")

    assert first.input_fingerprint == second.input_fingerprint
    assert first.request.state["taxonomy_snapshot_sha256"] == "a" * 64
    assert first.request.state["rubric_version"] == "jev-online-skill-v1"
    assert tuple(first.request.questions) == (
        "skill_000_evidence",
        "skill_000_mapping",
    )
    assert set(first.request.questions["skill_000_mapping"].criteria) == {
        "backend.python",
        "backend.java",
        "keep_candidate",
        "generic",
        "reject",
        "insufficient",
    }


def test_online_skill_dispatch_fingerprint_changes_with_evidence_or_taxonomy() -> None:
    original = _case()
    changed_evidence = original.model_copy(
        update={"evidence_text": "Python is explicitly not required."}
    )
    changed_taxonomy = original.model_copy(
        update={"taxonomy_snapshot_sha256": "b" * 64}
    )

    original_hash = build_online_skill_dispatch(original, model="jev").input_fingerprint
    assert (
        build_online_skill_dispatch(changed_evidence, model="jev").input_fingerprint
        != original_hash
    )
    assert (
        build_online_skill_dispatch(changed_taxonomy, model="jev").input_fingerprint
        != original_hash
    )
    assert (
        build_online_skill_dispatch(original, model="jev-next").input_fingerprint
        != original_hash
    )


def test_high_confidence_existing_skill_routes_to_automatic_projection() -> None:
    dispatch = build_online_skill_dispatch(_case(), model="typesafe/jev-1.13")
    routed = route_online_skill_result(
        _case(),
        SystemOneResult(
            status="answered",
            model="typesafe/jev-1.13",
            answers={
                "skill_000_evidence": _answer(
                    "required", 0.96, {"required": 0.96, "preferred": 0.04}
                ),
                "skill_000_mapping": _answer(
                    "backend.python",
                    0.94,
                    {"backend.python": 0.94, "backend.java": 0.06},
                ),
            },
        ),
        input_fingerprint=dispatch.input_fingerprint,
        thresholds=OnlineSkillThresholds(
            evidence_millis=900,
            recommendation_millis=900,
            recommendation_margin_millis=200,
        ),
    )

    assert routed.status == "answered"
    assert routed.apply_projection is True
    assert routed.decisions[0].route == "match_existing"
    assert routed.decisions[0].skill_code == "backend.python"


def test_low_confidence_or_close_mapping_stays_candidate() -> None:
    dispatch = build_online_skill_dispatch(_case(), model="typesafe/jev-1.13")
    routed = route_online_skill_result(
        _case(),
        SystemOneResult(
            status="answered",
            model="typesafe/jev-1.13",
            answers={
                "skill_000_evidence": _answer(
                    "required", 0.97, {"required": 0.97, "preferred": 0.03}
                ),
                "skill_000_mapping": _answer(
                    "backend.python",
                    0.91,
                    {"backend.python": 0.51, "backend.java": 0.49},
                ),
            },
        ),
        input_fingerprint=dispatch.input_fingerprint,
        thresholds=OnlineSkillThresholds(
            evidence_millis=900,
            recommendation_millis=900,
            recommendation_margin_millis=200,
        ),
    )

    assert routed.apply_projection is True
    assert routed.decisions[0].route == "candidate"
    assert routed.decisions[0].skill_code is None


def test_negated_evidence_is_retained_as_rejected_not_positive_skill() -> None:
    dispatch = build_online_skill_dispatch(_case(), model="typesafe/jev-1.13")
    routed = route_online_skill_result(
        _case(),
        SystemOneResult(
            status="answered",
            model="typesafe/jev-1.13",
            answers={
                "skill_000_evidence": _answer(
                    "negated", 0.98, {"negated": 0.98, "required": 0.02}
                ),
                "skill_000_mapping": _answer(
                    "backend.python", 0.99, {"backend.python": 0.99}
                ),
            },
        ),
        input_fingerprint=dispatch.input_fingerprint,
        thresholds=OnlineSkillThresholds(
            evidence_millis=900,
            recommendation_millis=900,
        ),
    )

    assert routed.apply_projection is True
    assert routed.decisions[0].route == "rejected"
    assert routed.decisions[0].reason == "evidence_negated"


def test_technical_failure_is_unresolved_and_never_replaces_projection() -> None:
    dispatch = build_online_skill_dispatch(_case(), model="typesafe/jev-1.13")
    routed = route_online_skill_result(
        _case(),
        SystemOneResult(
            status="unavailable",
            model="typesafe/jev-1.13",
            error_code="http_520",
        ),
        input_fingerprint=dispatch.input_fingerprint,
        thresholds=OnlineSkillThresholds(
            evidence_millis=900,
            recommendation_millis=900,
        ),
    )

    assert routed.status == "unavailable"
    assert routed.apply_projection is False
    assert routed.decisions[0].route == "unresolved"
    assert routed.decisions[0].reason == "http_520"


def test_unknown_model_choice_fails_closed_without_projection() -> None:
    dispatch = build_online_skill_dispatch(_case(), model="typesafe/jev-1.13")
    routed = route_online_skill_result(
        _case(),
        SystemOneResult(
            status="answered",
            model="typesafe/jev-1.13",
            answers={
                "skill_000_evidence": _answer("required", 0.99, {"required": 0.99}),
                "skill_000_mapping": _answer(
                    "invented.skill", 0.99, {"invented.skill": 0.99}
                ),
            },
        ),
        input_fingerprint=dispatch.input_fingerprint,
        thresholds=OnlineSkillThresholds(
            evidence_millis=900,
            recommendation_millis=900,
        ),
    )

    assert routed.status == "invalid"
    assert routed.apply_projection is False
    assert routed.decisions[0].route == "unresolved"
    assert routed.error_code == "invalid_skill_decision"


def test_answered_routing_translates_to_explicit_projection_routes() -> None:
    dispatch = build_online_skill_dispatch(_case(), model="typesafe/jev-1.13")
    routed = route_online_skill_result(
        _case(),
        SystemOneResult(
            status="answered",
            answers={
                "skill_000_evidence": _answer(
                    "required", 0.99, {"required": 0.99, "preferred": 0.01}
                ),
                "skill_000_mapping": _answer(
                    "backend.python", 0.99, {"backend.python": 0.99}
                ),
            },
        ),
        input_fingerprint=dispatch.input_fingerprint,
        thresholds=OnlineSkillThresholds(
            evidence_millis=900,
            recommendation_millis=900,
        ),
    )

    assert build_projection_skills(routed) == (
        {
            "name": "Python",
            "jev_route": "match_existing",
            "evidence_disposition": "required",
            "decision_reason": "high_confidence_existing_skill",
            "existing_skill": "backend.python",
        },
    )


def test_unavailable_routing_cannot_be_translated_into_empty_projection() -> None:
    dispatch = build_online_skill_dispatch(_case(), model="typesafe/jev-1.13")
    routed = route_online_skill_result(
        _case(),
        SystemOneResult(status="unavailable", error_code="budget_exhausted"),
        input_fingerprint=dispatch.input_fingerprint,
        thresholds=OnlineSkillThresholds(
            evidence_millis=900,
            recommendation_millis=900,
        ),
    )

    try:
        build_projection_skills(routed)
    except ValueError as error:
        assert str(error) == "unresolved Jev routing cannot replace Job Skills"
    else:
        raise AssertionError("unavailable routing must fail closed")
