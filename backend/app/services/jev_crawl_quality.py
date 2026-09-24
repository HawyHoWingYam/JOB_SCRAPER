from __future__ import annotations

from collections import defaultdict
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.job_intelligence.foundation import normalized_content_hash


class CrawlQualityArtifactError(ValueError):
    pass


class ControlledCrawlQualityCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    group_id: str = Field(min_length=1)
    split: Literal["development", "held_out"]
    source_site: Literal["jobsdb", "ctgoodjobs", "offertoday"]
    language: Literal["en", "zh-Hant", "mixed"]
    stage: Literal["listing_page", "detail_page"]
    transport_state: Literal[
        "success",
        "transport_failure",
        "manual_action_required",
        "terminal_unavailable",
    ]
    deterministic_classification: Literal[
        "auth_expired",
        "ip_blocked",
        "waf_challenge",
        "terminal_unavailable",
    ] | None = None
    title: str | None = None
    evidence_excerpt: str | None = None
    scenario_tags: tuple[str, ...] = Field(min_length=1)
    expected: Literal["usable_job_detail", "quality_problem", "insufficient"]
    problem_kind: Literal[
        "none",
        "empty_or_short",
        "access_wall",
        "terminal_page",
        "listing_or_template",
        "truncated",
        "irrelevant",
        "other",
        "insufficient",
    ]
    label_provenance: Literal["explicit_construction_v1"]
    stability_group: str | None = None
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def crawl_quality_evidence_hash(case: ControlledCrawlQualityCase) -> str:
    return normalized_content_hash(
        {
            "source_site": case.source_site,
            "stage": case.stage,
            "transport_state": case.transport_state,
            "deterministic_classification": case.deterministic_classification,
            "title": case.title,
            "evidence_excerpt": case.evidence_excerpt,
        }
    )


def load_crawl_quality_cases(
    path: Path,
) -> tuple[ControlledCrawlQualityCase, ...]:
    cases: list[ControlledCrawlQualityCase] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CrawlQualityArtifactError(
            f"cannot read crawl quality artifact: {exc}"
        ) from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            case = ControlledCrawlQualityCase.model_validate_json(line)
        except (ValidationError, ValueError) as exc:
            raise CrawlQualityArtifactError(
                f"invalid crawl quality case on line {line_number}: {exc}"
            ) from exc
        if case.evidence_sha256 != crawl_quality_evidence_hash(case):
            raise CrawlQualityArtifactError(
                f"case {case.case_id} evidence_sha256 does not match evidence"
            )
        cases.append(case)
    if not cases:
        raise CrawlQualityArtifactError("crawl quality artifact is empty")
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise CrawlQualityArtifactError("crawl quality case_id values must be unique")
    splits_by_group: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        splits_by_group[case.group_id].add(case.split)
    leaking = sorted(
        group for group, splits in splits_by_group.items() if len(splits) > 1
    )
    if leaking:
        raise CrawlQualityArtifactError(f"group leakage across splits: {leaking}")
    return tuple(cases)


def classify_crawl_quality_candidate(
    case: ControlledCrawlQualityCase,
) -> Literal["deterministic_problem", "insufficient", "jev_candidate"]:
    if case.deterministic_classification in {
        "auth_expired",
        "ip_blocked",
        "waf_challenge",
        "terminal_unavailable",
    }:
        return "deterministic_problem"
    if case.transport_state != "success" or not (
        (case.title or "").strip() or (case.evidence_excerpt or "").strip()
    ):
        return "insufficient"
    return "jev_candidate"


def crawl_quality_candidate_recall(
    cases: tuple[ControlledCrawlQualityCase, ...],
) -> dict[str, float | int]:
    eligible = [
        case
        for case in cases
        if case.expected == "quality_problem"
        and classify_crawl_quality_candidate(case) != "deterministic_problem"
    ]
    recalled = sum(
        classify_crawl_quality_candidate(case) == "jev_candidate" for case in eligible
    )
    return {
        "eligible_problem_cases": len(eligible),
        "recalled_problem_cases": recalled,
        "recall": recalled / len(eligible) if eligible else 0.0,
    }


def score_crawl_quality_evaluation(
    observations,
    *,
    eligible_problem_cases: int,
    candidate_recalled_problem_cases: int,
    real_reference_languages: set[str],
) -> dict[str, object]:
    observations = tuple(observations)
    predicted_problems = [
        item for item in observations if item.predicted == "quality_problem"
    ]
    true_problems = sum(
        item.expected == "quality_problem" and item.predicted == "quality_problem"
        for item in observations
    )
    false_flags = sum(
        item.expected == "usable_job_detail" and item.predicted == "quality_problem"
        for item in observations
    )
    valid_cases = sum(item.expected == "usable_job_detail" for item in observations)
    actionable = sum(
        item.status == "answered"
        and item.predicted in {"usable_job_detail", "quality_problem"}
        for item in observations
    )
    failures = sum(item.status in {"unavailable", "invalid"} for item in observations)
    answered_problems = [
        item
        for item in observations
        if item.status == "answered" and item.expected == "quality_problem"
    ]
    kind_correct = sum(
        item.predicted_problem_kind == item.expected_problem_kind
        for item in answered_problems
    )
    groups: dict[str, list[str | None]] = defaultdict(list)
    for item in observations:
        if item.stability_group:
            groups[item.stability_group].append(item.predicted)
    eligible_groups = [values for values in groups.values() if len(values) >= 2]
    stable = sum(
        values[0] is not None and len(set(values)) == 1 for values in eligible_groups
    )
    candidate_recall = _ratio(candidate_recalled_problem_cases, eligible_problem_cases)
    precision = _ratio(true_problems, len(predicted_problems))
    problem_recall = _ratio(true_problems, eligible_problem_cases)
    false_flag_rate = _ratio(false_flags, valid_cases)
    coverage = _ratio(actionable, len(observations))
    failure_rate = _ratio(failures, len(observations))
    kind_accuracy = _ratio(kind_correct, len(answered_problems))
    stability = _ratio(stable, len(eligible_groups))
    gates = {
        "candidate_recall": _minimum(candidate_recall, 0.95),
        "problem_precision": _minimum(precision, 0.95),
        "problem_recall": _minimum(problem_recall, 0.90),
        "false_flag_rate": _maximum(false_flag_rate, 0.02),
        "actionable_coverage": _minimum(coverage, 0.70),
        "problem_kind_accuracy": _minimum(kind_accuracy, 0.90),
        "technical_failure_rate": _maximum(failure_rate, 0.05),
        "option_order_stability": _minimum(stability, 0.95),
    }
    bilingual = {"en", "zh-Hant"}.issubset(real_reference_languages)
    unevaluable = any(value == "not_evaluable" for value in gates.values())
    failed = any(value is False for value in gates.values())
    decision = (
        "defer"
        if failed
        else "inconclusive"
        if unevaluable or not bilingual
        else "proceed_limited_review"
    )
    latencies = sorted(
        item.latency_ms for item in observations if item.latency_ms is not None
    )
    return {
        "schema_version": "jev-crawl-quality-report.v1",
        "decision": decision,
        "candidate": {
            "eligible_problem_cases": eligible_problem_cases,
            "recalled_problem_cases": candidate_recalled_problem_cases,
            "recall": candidate_recall,
        },
        "quality": {
            "eligible_cases": len(observations),
            "problem_precision": precision,
            "problem_recall": problem_recall,
            "false_flag_rate": false_flag_rate,
            "actionable_coverage": coverage,
            "problem_kind_accuracy": kind_accuracy,
            "technical_failure_rate": failure_rate,
        },
        "stability": {
            "eligible_groups": len(eligible_groups),
            "stable_groups": stable,
            "rate": stability,
        },
        "gates": gates,
        "execution": {
            "input_tokens": sum(item.input_tokens for item in observations),
            "output_tokens": sum(item.output_tokens for item in observations),
            "provider_reported_microdollars": sum(
                item.actual_microdollars or 0 for item in observations
            ),
            "latency_ms_p50": _percentile(latencies, 0.50),
            "latency_ms_p95": _percentile(latencies, 0.95),
        },
        "real_reference_languages": sorted(real_reference_languages),
        "limitations": []
        if bilingual
        else [
            "Real-corpus evidence lacks independently reviewed English and Traditional-Chinese slices."
        ],
    }


def _ratio(numerator: int, denominator: int) -> float | str:
    return numerator / denominator if denominator else "not_evaluable"


def _minimum(value: float | str, threshold: float) -> bool | str:
    return value >= threshold if isinstance(value, float) else "not_evaluable"


def _maximum(value: float | str, threshold: float) -> bool | str:
    return value <= threshold if isinstance(value, float) else "not_evaluable"


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    return values[max(0, math.ceil(percentile * len(values)) - 1)]


__all__ = [
    "ControlledCrawlQualityCase",
    "CrawlQualityArtifactError",
    "crawl_quality_evidence_hash",
    "classify_crawl_quality_candidate",
    "crawl_quality_candidate_recall",
    "load_crawl_quality_cases",
    "score_crawl_quality_evaluation",
]
