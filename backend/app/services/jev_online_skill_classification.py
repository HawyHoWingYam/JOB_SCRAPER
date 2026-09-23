from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.system_one import (
    ChoiceAnswer,
    ChoiceQuestion,
    SystemOneRequest,
    SystemOneResult,
)
from app.job_intelligence.foundation import normalized_content_hash


EVIDENCE_CHOICES = {
    "required": "The Job directly requires this Skill.",
    "preferred": "The Skill is explicitly preferred or advantageous.",
    "negated": "The Job explicitly says the Skill is not required or should not apply.",
    "incidental": "The term appears only in company, product, or unrelated context.",
    "insufficient": "The evidence is missing, ambiguous, or too weak to classify.",
}
RESERVED_MAPPING_CHOICES = {
    "keep_candidate": "Keep the term unresolved for later taxonomy maintenance.",
    "generic": "The term is a generic capability rather than a governed Skill.",
    "reject": "The term should not be retained as Skill evidence.",
    "insufficient": "There is not enough evidence to choose a taxonomy outcome.",
}


class OnlineSkillOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    label: str = Field(min_length=1)


class OnlineSkillCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_name: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    options: tuple[OnlineSkillOption, ...] = ()


class OnlineSkillCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str = Field(min_length=1)
    source_site: str = Field(min_length=1)
    title: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)
    candidates: tuple[OnlineSkillCandidate, ...] = Field(min_length=1)
    taxonomy_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rubric_version: str = Field(min_length=1)


class OnlineSkillThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_millis: int = Field(ge=0, le=1000)
    recommendation_millis: int = Field(ge=0, le=1000)
    recommendation_margin_millis: int = Field(default=100, ge=0, le=1000)


class RoutedSkillDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_name: str
    route: Literal[
        "match_existing",
        "candidate",
        "generic",
        "rejected",
        "unresolved",
    ]
    evidence_disposition: str | None = None
    skill_code: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    reason: str
    probabilities: dict[str, float] = Field(default_factory=dict)


@dataclass(frozen=True)
class OnlineSkillDispatch:
    input_fingerprint: str
    request: SystemOneRequest


@dataclass(frozen=True)
class OnlineSkillRoutingResult:
    input_fingerprint: str
    status: Literal["answered", "unavailable", "invalid"]
    apply_projection: bool
    decisions: tuple[RoutedSkillDecision, ...]
    error_code: str | None = None


def build_online_skill_dispatch(
    case: OnlineSkillCase,
    *,
    model: str,
    runtime_identity: dict[str, object] | None = None,
) -> OnlineSkillDispatch:
    state = {
        "job": {
            "id": case.job_id,
            "source_site": case.source_site,
            "title": case.title,
            "evidence_text": case.evidence_text,
        },
        "candidates": [
            {
                "index": index,
                "raw_name": candidate.raw_name,
                "evidence": candidate.evidence,
                "options": [
                    {"code": option.code, "label": option.label}
                    for option in candidate.options
                ],
            }
            for index, candidate in enumerate(case.candidates)
        ],
        "taxonomy_snapshot_sha256": case.taxonomy_snapshot_sha256,
        "rubric_version": case.rubric_version,
    }
    questions: dict[str, ChoiceQuestion] = {}
    for index, candidate in enumerate(case.candidates):
        questions[_question_name(index, "evidence")] = ChoiceQuestion(
            instructions=(
                "Classify how the candidate Skill is supported by the supplied "
                "Job evidence. Do not infer requirements from company context."
            ),
            criteria=EVIDENCE_CHOICES,
        )
        mapping_criteria = {
            option.code: f"Map to the existing governed Skill: {option.label}."
            for option in candidate.options
        }
        mapping_criteria.update(RESERVED_MAPPING_CHOICES)
        questions[_question_name(index, "mapping")] = ChoiceQuestion(
            instructions=(
                "Choose an existing governed Skill only when it represents the "
                "candidate in this Job; otherwise retain an explicit fallback."
            ),
            criteria=mapping_criteria,
        )
    fingerprint = normalized_content_hash(
        {
            "requested_model": model,
            "runtime_identity": runtime_identity or {},
            "state": state,
            "questions": {
                name: question.model_dump(exclude_none=True)
                for name, question in questions.items()
            },
        }
    )
    return OnlineSkillDispatch(
        input_fingerprint=fingerprint,
        request=SystemOneRequest(state=state, model=model, questions=questions),
    )


def route_online_skill_result(
    case: OnlineSkillCase,
    result: SystemOneResult,
    *,
    input_fingerprint: str,
    thresholds: OnlineSkillThresholds,
) -> OnlineSkillRoutingResult:
    if result.status != "answered":
        status = "invalid" if result.status == "invalid" else "unavailable"
        return OnlineSkillRoutingResult(
            input_fingerprint=input_fingerprint,
            status=status,
            apply_projection=False,
            decisions=tuple(
                RoutedSkillDecision(
                    raw_name=candidate.raw_name,
                    route="unresolved",
                    reason=result.error_code or status,
                )
                for candidate in case.candidates
            ),
            error_code=result.error_code,
        )

    decisions = tuple(
        _route_candidate(
            candidate,
            evidence=result.answers.get(_question_name(index, "evidence")),
            mapping=result.answers.get(_question_name(index, "mapping")),
            thresholds=thresholds,
        )
        for index, candidate in enumerate(case.candidates)
    )
    invalid = any(decision.route == "unresolved" for decision in decisions)
    return OnlineSkillRoutingResult(
        input_fingerprint=input_fingerprint,
        status="invalid" if invalid else "answered",
        apply_projection=not invalid,
        decisions=decisions,
        error_code="invalid_skill_decision" if invalid else None,
    )


def build_projection_skills(
    routing: OnlineSkillRoutingResult,
) -> tuple[dict[str, object], ...]:
    """Translate an answered Jev route into the governed projection contract."""
    if routing.status != "answered" or not routing.apply_projection:
        raise ValueError("unresolved Jev routing cannot replace Job Skills")
    projected: list[dict[str, object]] = []
    for decision in routing.decisions:
        if decision.route == "unresolved":
            raise ValueError("unresolved Jev decision cannot be projected")
        payload: dict[str, object] = {
            "name": decision.raw_name,
            "jev_route": decision.route,
            "evidence_disposition": decision.evidence_disposition,
            "decision_reason": decision.reason,
        }
        if decision.route == "match_existing":
            if decision.skill_code is None:
                raise ValueError("matched Jev decision requires an existing Skill code")
            payload["existing_skill"] = decision.skill_code
        projected.append(payload)
    return tuple(projected)


def _route_candidate(
    candidate: OnlineSkillCandidate,
    *,
    evidence: object,
    mapping: object,
    thresholds: OnlineSkillThresholds,
) -> RoutedSkillDecision:
    if not isinstance(evidence, ChoiceAnswer) or not isinstance(mapping, ChoiceAnswer):
        return RoutedSkillDecision(
            raw_name=candidate.raw_name,
            route="unresolved",
            reason="missing_typed_answer",
        )
    if evidence.choice not in EVIDENCE_CHOICES:
        return RoutedSkillDecision(
            raw_name=candidate.raw_name,
            route="unresolved",
            reason="invalid_evidence_choice",
        )
    allowed_mapping = {option.code for option in candidate.options} | set(
        RESERVED_MAPPING_CHOICES
    )
    if mapping.choice not in allowed_mapping:
        return RoutedSkillDecision(
            raw_name=candidate.raw_name,
            route="unresolved",
            evidence_disposition=evidence.choice,
            reason="invalid_mapping_choice",
        )

    evidence_threshold = thresholds.evidence_millis / 1000
    recommendation_threshold = thresholds.recommendation_millis / 1000
    margin_threshold = thresholds.recommendation_margin_millis / 1000
    if (
        evidence.choice in {"negated", "incidental"}
        and evidence.confidence >= evidence_threshold
    ):
        return RoutedSkillDecision(
            raw_name=candidate.raw_name,
            route="rejected",
            evidence_disposition=evidence.choice,
            confidence=evidence.confidence,
            reason=f"evidence_{evidence.choice}",
            probabilities=dict(evidence.probabilities),
        )
    if (
        evidence.choice not in {"required", "preferred"}
        or evidence.confidence < evidence_threshold
    ):
        return RoutedSkillDecision(
            raw_name=candidate.raw_name,
            route="candidate",
            evidence_disposition=evidence.choice,
            confidence=evidence.confidence,
            reason="evidence_below_auto_threshold",
            probabilities=dict(evidence.probabilities),
        )

    if mapping.choice == "generic" and mapping.confidence >= recommendation_threshold:
        route = "generic"
    elif mapping.choice == "reject" and mapping.confidence >= recommendation_threshold:
        route = "rejected"
    elif mapping.choice in RESERVED_MAPPING_CHOICES:
        route = "candidate"
    elif (
        mapping.confidence >= recommendation_threshold
        and _probability_margin(mapping) >= margin_threshold
    ):
        route = "match_existing"
    else:
        route = "candidate"
    return RoutedSkillDecision(
        raw_name=candidate.raw_name,
        route=route,
        evidence_disposition=evidence.choice,
        skill_code=mapping.choice if route == "match_existing" else None,
        confidence=min(evidence.confidence, mapping.confidence),
        reason=(
            "high_confidence_existing_skill"
            if route == "match_existing"
            else f"mapping_{mapping.choice}"
            if route in {"generic", "rejected"}
            else "mapping_below_auto_threshold"
        ),
        probabilities=dict(mapping.probabilities),
    )


def _probability_margin(answer: ChoiceAnswer) -> float:
    probabilities = sorted(answer.probabilities.values(), reverse=True)
    if not probabilities:
        return 0.0
    return probabilities[0] - (probabilities[1] if len(probabilities) > 1 else 0.0)


def _question_name(index: int, kind: str) -> str:
    return f"skill_{index:03d}_{kind}"


__all__ = [
    "OnlineSkillCandidate",
    "OnlineSkillCase",
    "OnlineSkillDispatch",
    "OnlineSkillOption",
    "OnlineSkillRoutingResult",
    "OnlineSkillThresholds",
    "RoutedSkillDecision",
    "build_online_skill_dispatch",
    "build_projection_skills",
    "route_online_skill_result",
]
