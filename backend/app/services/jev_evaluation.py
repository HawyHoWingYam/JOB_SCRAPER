from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from difflib import SequenceMatcher
import json
from math import ceil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.job_intelligence.foundation import normalized_content_hash
from app.ai.system_one import SystemOneRequest
from app.job_intelligence.current_taxonomies.normalization import (
    normalize_exact_skill_key,
)
from app.job_intelligence.current_taxonomies.skill_curation import (
    load_skill_curation_rules,
    resolve_skill_curation,
)


class EvaluationArtifactError(ValueError):
    pass


class ControlledEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    group_id: str = Field(min_length=1)
    split: Literal["development", "held_out"]
    decision_kind: Literal["evidence_support", "candidate_recommendation"]
    language: Literal["en", "zh-Hant", "mixed"]
    source: Literal["controlled_fixture_v1"]
    scenario_tags: list[str] = Field(min_length=1)
    stability_group: str | None = None
    state: dict[str, object]
    questions: dict[str, dict[str, object]] = Field(min_length=1)
    expected: str = Field(min_length=1)
    label_provenance: Literal["explicit_construction_v1"]
    evidence_refs: list[str] = Field(min_length=1)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    taxonomy_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvaluationObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    run_id: str | None = None
    manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    rubric_version: str | None = None
    model: str | None = None
    split: Literal["development", "held_out", "real_corpus"]
    decision_kind: Literal["evidence_support", "candidate_recommendation"]
    status: Literal["answered", "abstained", "unavailable", "invalid"]
    expected: str | None = None
    predicted: str | None = None
    reference_provenance: str | None = None
    language: str | None = None
    source: str | None = None
    stability_group: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    actual_microdollars: int | None = Field(default=None, ge=0)
    error_code: str | None = None


class SkillOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    labels: dict[str, str]
    aliases: tuple[str, ...] = ()


def _display_name(option: SkillOption) -> str:
    return next(
        (
            option.labels[key]
            for key in ("en", "en_HK", "zh_HK", "zh")
            if option.labels.get(key)
        ),
        option.code,
    )


def _skill_similarity_keys(left_key: str, right_key: str) -> float:
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0
    left_tokens = set(left_key.split())
    right_tokens = set(right_key.split())
    shared = left_tokens & right_tokens
    if shared:
        smaller_coverage = len(shared) / min(len(left_tokens), len(right_tokens))
        if smaller_coverage >= 0.75:
            jaccard = len(shared) / len(left_tokens | right_tokens)
            return 0.75 + (0.25 * jaccard)
    if min(len(left_key), len(right_key)) >= 3 and (
        left_key in right_key or right_key in left_key
    ):
        return 0.8 + (
            0.2
            * min(len(left_key), len(right_key))
            / max(len(left_key), len(right_key))
        )
    # SequenceMatcher cannot exceed twice the shorter length divided by the
    # combined length. Skip pairs that cannot possibly reach our acceptance
    # threshold; this preserves results while avoiding most taxonomy-wide
    # fuzzy comparisons during Jev batch previews.
    maximum_ratio = (2 * min(len(left_key), len(right_key))) / (
        len(left_key) + len(right_key)
    )
    if maximum_ratio < 0.82:
        return 0.0
    ratio = SequenceMatcher(None, left_key, right_key).ratio()
    return ratio if ratio >= 0.82 else 0.0


def _skill_similarity(left: str, right: str) -> float:
    return _skill_similarity_keys(
        normalize_exact_skill_key(left),
        normalize_exact_skill_key(right),
    )


def deterministic_skill_baseline(
    candidate: str,
    options: tuple[SkillOption, ...],
) -> dict[str, str | None]:
    candidate_key = normalize_exact_skill_key(candidate)
    for option in sorted(options, key=lambda item: item.code):
        if any(
            normalize_exact_skill_key(label) == candidate_key
            for label in option.labels.values()
        ):
            return {
                "outcome": "match_existing",
                "skill_code": option.code,
                "reason": "label_exact",
            }
    for option in sorted(options, key=lambda item: item.code):
        if any(
            normalize_exact_skill_key(alias) == candidate_key
            for alias in option.aliases
        ):
            return {
                "outcome": "match_existing",
                "skill_code": option.code,
                "reason": "alias_exact",
            }
    disposition = resolve_skill_curation(candidate)
    if disposition is not None:
        return {
            "outcome": disposition.kind,
            "skill_code": None,
            "reason": disposition.generic_tag or disposition.rejection_reason,
        }
    return {"outcome": "unresolved", "skill_code": None, "reason": None}


PreparedSkillOptions = tuple[
    tuple[SkillOption, tuple[tuple[str, str], ...]], ...
]


def prepare_skill_options(options: tuple[SkillOption, ...]) -> PreparedSkillOptions:
    return tuple(
        (
            option,
            tuple(
                (normalize_exact_skill_key(value), reason)
                for value, reason in (
                    *((label, "label_similarity") for label in option.labels.values()),
                    *((alias, "alias_similarity") for alias in option.aliases),
                )
            ),
        )
        for option in options
    )


def rank_prepared_skill_options(
    candidate: str,
    prepared_options: PreparedSkillOptions,
    *,
    limit: int,
) -> list[dict[str, object]]:
    candidate_key = normalize_exact_skill_key(candidate)
    ranked: list[tuple[float, str, SkillOption]] = []
    for option, values in prepared_options:
        score, reason = max(
            (_skill_similarity_keys(candidate_key, value_key), reason)
            for value_key, reason in values
        )
        if score > 0:
            ranked.append((score, reason, option))
    return [
        {
            "code": option.code,
            "name": _display_name(option),
            "score": round(score, 3),
            "reason": reason,
            "score_kind": "heuristic_string_similarity",
        }
        for score, reason, option in sorted(
            ranked, key=lambda item: (-item[0], item[2].code)
        )[:limit]
    ]


def rank_skill_options(
    candidate: str,
    options: tuple[SkillOption, ...],
    *,
    limit: int,
) -> list[dict[str, object]]:
    return rank_prepared_skill_options(
        candidate,
        prepare_skill_options(options),
        limit=limit,
    )


def build_system_one_request(
    case: ControlledEvaluationCase,
    *,
    model: str,
) -> SystemOneRequest:
    return SystemOneRequest.model_validate(
        {"state": case.state, "model": model, "questions": case.questions}
    )


def controlled_baseline_observations(
    cases: tuple[ControlledEvaluationCase, ...],
) -> list[EvaluationObservation]:
    curation_rules = load_skill_curation_rules()
    canonical_aliases = curation_rules.get("canonical_aliases") or {}
    observations = []
    for case in cases:
        predicted = None
        status = "abstained"
        if case.decision_kind == "candidate_recommendation":
            raw_options = case.state.get("options") or {}
            reserved = {"keep_candidate", "generic", "reject", "insufficient"}
            options = tuple(
                SkillOption(
                    code=code,
                    labels={"en": str(label)},
                    aliases=tuple(
                        alias
                        for alias, canonical in canonical_aliases.items()
                        if normalize_exact_skill_key(canonical)
                        == normalize_exact_skill_key(label)
                    ),
                )
                for code, label in raw_options.items()
                if code not in reserved
            )
            candidate = str(case.state.get("candidate") or "")
            baseline = deterministic_skill_baseline(candidate, options)
            if baseline["outcome"] == "match_existing":
                predicted = baseline["skill_code"]
            elif baseline["outcome"] in {"generic", "reject"}:
                predicted = baseline["outcome"]
            else:
                ranked = rank_skill_options(candidate, options, limit=1)
                predicted = ranked[0]["code"] if ranked else "keep_candidate"
            status = "answered"
        observations.append(
            EvaluationObservation(
                case_id=case.case_id,
                split=case.split,
                decision_kind=case.decision_kind,
                status=status,
                expected=case.expected,
                predicted=predicted,
                reference_provenance=case.label_provenance,
                language=case.language,
                stability_group=case.stability_group,
            )
        )
    return observations


def load_controlled_cases(path: Path) -> tuple[ControlledEvaluationCase, ...]:
    cases: list[ControlledEvaluationCase] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise EvaluationArtifactError(
            f"cannot read controlled artifact: {exc}"
        ) from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            case = ControlledEvaluationCase.model_validate_json(line)
        except (ValidationError, ValueError) as exc:
            raise EvaluationArtifactError(
                f"invalid controlled case on line {line_number}: {exc}"
            ) from exc
        expected_hash = normalized_content_hash(case.state)
        if case.evidence_sha256 != expected_hash:
            raise EvaluationArtifactError(
                f"case {case.case_id} evidence_sha256 does not match state"
            )
        cases.append(case)
    if not cases:
        raise EvaluationArtifactError("controlled artifact is empty")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise EvaluationArtifactError("controlled case_id values must be unique")
    splits_by_group: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        splits_by_group[case.group_id].add(case.split)
    leaking = sorted(
        group_id for group_id, splits in splits_by_group.items() if len(splits) > 1
    )
    if leaking:
        raise EvaluationArtifactError(f"group leakage across splits: {leaking}")
    return tuple(cases)


def _ratio(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    return f"{Decimal(numerator) / Decimal(denominator):.3f}"


def _score_kind(observations: list[EvaluationObservation]) -> dict[str, object]:
    eligible = len(observations)
    answered = [item for item in observations if item.status == "answered"]
    correct = sum(item.predicted == item.expected for item in answered)
    technical_failures = sum(
        item.status in {"unavailable", "invalid"} for item in observations
    )
    latencies = sorted(
        item.latency_ms for item in observations if item.latency_ms is not None
    )

    def percentile(quantile: Decimal) -> int | None:
        if not latencies:
            return None
        return latencies[max(0, ceil(len(latencies) * quantile) - 1)]

    return {
        "eligible": eligible,
        "answered": len(answered),
        "correct": correct,
        "abstained": sum(item.status == "abstained" for item in observations),
        "unavailable": sum(item.status == "unavailable" for item in observations),
        "invalid": sum(item.status == "invalid" for item in observations),
        "answered_correctness": _ratio(correct, len(answered)),
        "actionable_coverage": _ratio(len(answered), eligible),
        "technical_failure_rate": _ratio(technical_failures, eligible),
        "latency_ms_p50": percentile(Decimal("0.50")),
        "latency_ms_p95": percentile(Decimal("0.95")),
        "input_tokens": sum(item.input_tokens for item in observations),
        "output_tokens": sum(item.output_tokens for item in observations),
        "provider_reported_microdollars": sum(
            item.actual_microdollars or 0 for item in observations
        ),
    }


def score_evaluation(
    observations: list[EvaluationObservation],
) -> dict[str, object]:
    held_out = [item for item in observations if item.split == "held_out"]
    controlled = {
        kind: _score_kind([item for item in held_out if item.decision_kind == kind])
        for kind in ("evidence_support", "candidate_recommendation")
    }
    real_items = [item for item in observations if item.split == "real_corpus"]
    real_corpus = {
        kind: _score_kind([item for item in real_items if item.decision_kind == kind])
        for kind in ("evidence_support", "candidate_recommendation")
    }
    real_corpus_strata = {
        field: dict(sorted(counts.items()))
        for field in ("language", "source", "reference_provenance")
        if (
            counts := {
                value: sum(getattr(item, field) == value for item in real_items)
                for value in sorted(
                    {
                        getattr(item, field)
                        for item in real_items
                        if getattr(item, field) is not None
                    }
                )
            }
        )
    }
    stability_groups: dict[str, list[EvaluationObservation]] = defaultdict(list)
    for item in held_out:
        if item.stability_group:
            stability_groups[item.stability_group].append(item)
    comparable_groups = [
        items for items in stability_groups.values() if len(items) >= 2
    ]
    stable_groups = sum(
        all(item.status == "answered" for item in items)
        and len({item.predicted for item in items}) == 1
        for items in comparable_groups
    )
    stability = {
        "eligible_groups": len(comparable_groups),
        "stable_groups": stable_groups,
        "rate": _ratio(stable_groups, len(comparable_groups)),
    }
    evidence = controlled["evidence_support"]
    recommendation = controlled["candidate_recommendation"]
    evaluable = bool(
        evidence["eligible"]
        and recommendation["eligible"]
        and stability["eligible_groups"]
    )
    controlled_passed = evaluable and all(
        (
            Decimal(str(evidence["answered_correctness"] or 0)) >= Decimal("0.90"),
            Decimal(str(recommendation["answered_correctness"] or 0))
            >= Decimal("0.85"),
            Decimal(str(evidence["technical_failure_rate"] or 1)) <= Decimal("0.05"),
            Decimal(str(recommendation["technical_failure_rate"] or 1))
            <= Decimal("0.05"),
            Decimal(str(evidence["actionable_coverage"] or 0)) >= Decimal("0.60"),
            Decimal(str(recommendation["actionable_coverage"] or 0)) >= Decimal("0.60"),
            Decimal(str(stability["rate"] or 0)) >= Decimal("0.95"),
        )
    )
    independent_languages = {
        item.language
        for item in real_items
        if item.reference_provenance == "independent_reviewer"
        and item.language in {"en", "zh-Hant", "mixed"}
    }
    if not evaluable:
        decision = "inconclusive"
    elif not controlled_passed:
        decision = "defer"
    elif not {"en", "zh-Hant"}.issubset(independent_languages):
        decision = "inconclusive"
    else:
        decision = "proceed_limited_review"
    return {
        "schema_version": "jev-skill-evaluation-report.v1",
        "execution": _score_kind(observations),
        "controlled": controlled,
        "real_corpus": real_corpus,
        "real_corpus_strata": real_corpus_strata,
        "option_reordering_stability": stability,
        "decision": decision,
        "limitations": [
            "Real-corpus agreement is not human-validated accuracy.",
            "Unresolved, abstained, unavailable, and invalid cases remain in denominators.",
            "Operator handling time is not measured in this offline evaluation.",
        ],
    }


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "ControlledEvaluationCase",
    "EvaluationArtifactError",
    "EvaluationObservation",
    "PreparedSkillOptions",
    "SkillOption",
    "build_system_one_request",
    "controlled_baseline_observations",
    "deterministic_skill_baseline",
    "load_controlled_cases",
    "prepare_skill_options",
    "rank_prepared_skill_options",
    "rank_skill_options",
    "score_evaluation",
    "write_json",
]
