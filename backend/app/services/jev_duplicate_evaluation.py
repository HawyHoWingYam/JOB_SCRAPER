from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import hashlib
import math
from pathlib import Path
import re
from difflib import SequenceMatcher
from typing import Literal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.job_intelligence.foundation import normalized_content_hash


class DuplicateArtifactError(ValueError):
    pass


class DuplicateJobSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_site: Literal["jobsdb", "ctgoodjobs", "offertoday", "controlled"]
    source_job_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    company_name: str | None = None
    location: str | None = None
    posted_date: str | None = None
    description_text: str | None = None


class ControlledDuplicateCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    group_id: str = Field(min_length=1)
    split: Literal["development", "held_out"]
    language: Literal["en", "zh-Hant", "mixed"]
    scenario_tags: tuple[str, ...] = Field(min_length=1)
    left: DuplicateJobSnapshot
    right: DuplicateJobSnapshot
    expected: Literal["same_vacancy", "different_vacancy", "insufficient"]
    label_provenance: Literal["explicit_construction_v1"]
    stability_group: str | None = None
    pair_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class DuplicateCandidateJob:
    snapshot: DuplicateJobSnapshot
    embedding: tuple[float, ...] | None = None

    @property
    def identity(self) -> str:
        return f"{self.snapshot.source_site}:{self.snapshot.source_job_id}"


@dataclass(frozen=True)
class DuplicateCandidatePolicy:
    lexical_top_k: int = 10
    embedding_top_k: int = 10
    max_pairs: int = 1_000

    def __post_init__(self) -> None:
        if self.lexical_top_k < 0 or self.embedding_top_k < 0:
            raise ValueError("candidate top-K values cannot be negative")
        if self.max_pairs < 1:
            raise ValueError("candidate max_pairs must be positive")


@dataclass(frozen=True)
class DuplicateCandidate:
    pair_id: str
    left_identity: str
    right_identity: str
    lexical_score: float | None
    embedding_score: float | None
    methods: tuple[Literal["lexical", "embedding"], ...]
    rank: int


@dataclass(frozen=True)
class CandidateRecallMetric:
    eligible_positive_pairs: int
    recalled_positive_pairs: int
    recall: float


@dataclass(frozen=True)
class DuplicateEvaluationGates:
    candidate_recall_at_10: float = 0.95
    answered_precision: float = 0.95
    positive_recall: float = 0.80
    false_association_rate: float = 0.02
    actionable_coverage: float = 0.60
    technical_failure_rate: float = 0.05
    option_reordering_stability: float = 0.95


def duplicate_pair_hash(left: DuplicateJobSnapshot, right: DuplicateJobSnapshot) -> str:
    return normalized_content_hash(
        {"left": left.model_dump(), "right": right.model_dump()}
    )


def load_duplicate_cases(path: Path) -> tuple[ControlledDuplicateCase, ...]:
    cases: list[ControlledDuplicateCase] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DuplicateArtifactError(f"cannot read duplicate artifact: {exc}") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            case = ControlledDuplicateCase.model_validate_json(line)
        except (ValidationError, ValueError) as exc:
            raise DuplicateArtifactError(
                f"invalid duplicate case on line {line_number}: {exc}"
            ) from exc
        if case.pair_sha256 != duplicate_pair_hash(case.left, case.right):
            raise DuplicateArtifactError(
                f"case {case.case_id} pair_sha256 does not match pair evidence"
            )
        cases.append(case)
    if not cases:
        raise DuplicateArtifactError("duplicate artifact is empty")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise DuplicateArtifactError("duplicate case_id values must be unique")
    splits_by_group: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        splits_by_group[case.group_id].add(case.split)
    leaking = sorted(
        group for group, splits in splits_by_group.items() if len(splits) > 1
    )
    if leaking:
        raise DuplicateArtifactError(f"group leakage across splits: {leaking}")
    return tuple(cases)


def build_duplicate_candidates(
    jobs: tuple[DuplicateCandidateJob, ...],
    *,
    policy: DuplicateCandidatePolicy,
) -> tuple[DuplicateCandidate, ...]:
    """Build a deterministic symmetric union of bounded directed neighbors."""
    ordered = tuple(sorted(jobs, key=lambda item: item.identity))
    identities = [item.identity for item in ordered]
    if len(identities) != len(set(identities)):
        raise ValueError("candidate Job identities must be unique")
    eligible = tuple(item for item in ordered if _has_pair_evidence(item.snapshot))
    selected: dict[tuple[str, str], dict[str, object]] = {}

    _select_directed_neighbors(
        eligible,
        method="lexical",
        top_k=policy.lexical_top_k,
        scorer=_lexical_similarity,
        selected=selected,
    )
    _select_directed_neighbors(
        eligible,
        method="embedding",
        top_k=policy.embedding_top_k,
        scorer=_embedding_similarity,
        selected=selected,
    )

    candidates = [
        DuplicateCandidate(
            pair_id=hashlib.sha256("\0".join(pair).encode("utf-8")).hexdigest(),
            left_identity=pair[0],
            right_identity=pair[1],
            lexical_score=_optional_float(values.get("lexical_score")),
            embedding_score=_optional_float(values.get("embedding_score")),
            methods=tuple(
                method
                for method in ("lexical", "embedding")
                if method in values["methods"]
            ),
            rank=int(values["rank"]),
        )
        for pair, values in selected.items()
    ]
    candidates.sort(
        key=lambda item: (
            -max(
                item.lexical_score if item.lexical_score is not None else -1.0,
                item.embedding_score if item.embedding_score is not None else -1.0,
            ),
            item.left_identity,
            item.right_identity,
        )
    )
    return tuple(candidates[: policy.max_pairs])


def candidate_recall_at_k(
    cases: tuple[ControlledDuplicateCase, ...],
    candidates: tuple[DuplicateCandidate, ...],
    *,
    k: int,
) -> CandidateRecallMetric:
    if k < 1:
        raise ValueError("candidate recall K must be positive")
    expected_pairs = {
        _canonical_pair(_snapshot_identity(case.left), _snapshot_identity(case.right))
        for case in cases
        if case.expected == "same_vacancy"
        and _has_pair_evidence(case.left)
        and _has_pair_evidence(case.right)
    }
    observed_pairs = {
        (candidate.left_identity, candidate.right_identity)
        for candidate in candidates
        if candidate.rank <= k
    }
    recalled = len(expected_pairs & observed_pairs)
    eligible = len(expected_pairs)
    return CandidateRecallMetric(
        eligible_positive_pairs=eligible,
        recalled_positive_pairs=recalled,
        recall=recalled / eligible if eligible else 0.0,
    )


def score_duplicate_evaluation(
    observations,
    *,
    eligible_positive_pairs: int,
    candidate_eligible_positive_pairs: int | None = None,
    candidate_recalled_positive_pairs: int,
    real_reference_languages: set[str],
    gates: DuplicateEvaluationGates = DuplicateEvaluationGates(),
) -> dict[str, object]:
    observations = tuple(observations)
    total = len(observations)
    positives = [item for item in observations if item.expected == "same_vacancy"]
    negatives = [item for item in observations if item.expected == "different_vacancy"]
    predicted_positive = [
        item for item in observations if item.predicted == "same_vacancy"
    ]
    true_positive = sum(
        item.expected == "same_vacancy" and item.predicted == "same_vacancy"
        for item in observations
    )
    false_positive = sum(
        item.expected == "different_vacancy" and item.predicted == "same_vacancy"
        for item in observations
    )
    actionable = sum(
        item.status == "answered"
        and item.predicted in {"same_vacancy", "different_vacancy"}
        for item in observations
    )
    technical_failures = sum(
        item.status in {"unavailable", "invalid"} for item in observations
    )
    precision = _ratio(true_positive, len(predicted_positive))
    recall = _ratio(true_positive, eligible_positive_pairs)
    false_association = _ratio(false_positive, len(negatives))
    coverage = _ratio(actionable, total)
    technical_failure = _ratio(technical_failures, total)
    if candidate_eligible_positive_pairs is None:
        candidate_eligible_positive_pairs = eligible_positive_pairs
    candidate_recall = _ratio(
        candidate_recalled_positive_pairs, candidate_eligible_positive_pairs
    )

    stability_groups: dict[str, list[str | None]] = defaultdict(list)
    for item in observations:
        if item.stability_group:
            stability_groups[item.stability_group].append(item.predicted)
    eligible_stability = [
        values for values in stability_groups.values() if len(values) >= 2
    ]
    stable_count = sum(
        values[0] is not None and len(set(values)) == 1 for values in eligible_stability
    )
    stability_rate = _ratio(stable_count, len(eligible_stability))
    latencies = sorted(
        item.latency_ms for item in observations if item.latency_ms is not None
    )
    controlled_metrics = {
        "eligible_pairs": total,
        "eligible_positive_pairs": eligible_positive_pairs,
        "observed_positive_cases": len(positives),
        "eligible_negative_pairs": len(negatives),
        "answered": sum(item.status == "answered" for item in observations),
        "precision": precision,
        "recall": recall,
        "false_association_rate": false_association,
        "actionable_coverage": coverage,
        "technical_failure_rate": technical_failure,
    }
    candidate_metrics = {
        "k": 10,
        "eligible_positive_pairs": candidate_eligible_positive_pairs,
        "recalled_positive_pairs": candidate_recalled_positive_pairs,
        "recall_at_10": candidate_recall,
    }
    stability_metrics = {
        "eligible_groups": len(eligible_stability),
        "stable_groups": stable_count,
        "rate": stability_rate,
    }
    gate_results = {
        "candidate_recall_at_10": _meets_minimum(
            candidate_recall, gates.candidate_recall_at_10
        ),
        "answered_precision": _meets_minimum(precision, gates.answered_precision),
        "positive_recall": _meets_minimum(recall, gates.positive_recall),
        "false_association_rate": _meets_maximum(
            false_association, gates.false_association_rate
        ),
        "actionable_coverage": _meets_minimum(coverage, gates.actionable_coverage),
        "technical_failure_rate": _meets_maximum(
            technical_failure, gates.technical_failure_rate
        ),
        "option_reordering_stability": _meets_minimum(
            stability_rate, gates.option_reordering_stability
        ),
    }
    limitations: list[str] = []
    unevaluable = any(value == "not_evaluable" for value in gate_results.values())
    controlled_failed = any(value is False for value in gate_results.values())
    bilingual_review = {"en", "zh-Hant"}.issubset(real_reference_languages)
    if not bilingual_review:
        limitations.append(
            "Real-corpus release evidence lacks independently reviewed English "
            "and Traditional-Chinese reference slices."
        )
    if unevaluable:
        limitations.append("One or more frozen gate denominators are not evaluable.")
    if controlled_failed:
        decision = "defer"
    elif unevaluable or not bilingual_review:
        decision = "inconclusive"
    else:
        decision = "proceed_limited_review"
    return {
        "schema_version": "jev-duplicate-report.v1",
        "decision": decision,
        "gates": {
            "thresholds": {
                "candidate_recall_at_10": gates.candidate_recall_at_10,
                "answered_precision": gates.answered_precision,
                "positive_recall": gates.positive_recall,
                "false_association_rate": gates.false_association_rate,
                "actionable_coverage": gates.actionable_coverage,
                "technical_failure_rate": gates.technical_failure_rate,
                "option_reordering_stability": gates.option_reordering_stability,
            },
            "results": gate_results,
        },
        "candidate": candidate_metrics,
        "controlled": controlled_metrics,
        "option_reordering_stability": stability_metrics,
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
        "limitations": limitations,
    }


def _ratio(numerator: int, denominator: int) -> float | str:
    return numerator / denominator if denominator else "not_evaluable"


def _meets_minimum(value: float | str, threshold: float) -> bool | str:
    return value >= threshold if isinstance(value, float) else "not_evaluable"


def _meets_maximum(value: float | str, threshold: float) -> bool | str:
    return value <= threshold if isinstance(value, float) else "not_evaluable"


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    index = math.ceil(percentile * len(values)) - 1
    return values[max(0, index)]


def _select_directed_neighbors(
    jobs: tuple[DuplicateCandidateJob, ...],
    *,
    method: Literal["lexical", "embedding"],
    top_k: int,
    scorer,
    selected: dict[tuple[str, str], dict[str, object]],
) -> None:
    if top_k == 0:
        return
    for subject in jobs:
        neighbors: list[tuple[float, str]] = []
        for candidate in jobs:
            if candidate.identity == subject.identity:
                continue
            score = scorer(subject, candidate)
            if score is not None:
                neighbors.append((score, candidate.identity))
        neighbors.sort(key=lambda value: (-value[0], value[1]))
        for rank, (score, candidate_identity) in enumerate(neighbors[:top_k], 1):
            pair = _canonical_pair(subject.identity, candidate_identity)
            values = selected.setdefault(
                pair,
                {"methods": set(), "rank": rank},
            )
            methods = values["methods"]
            assert isinstance(methods, set)
            methods.add(method)
            values["rank"] = min(int(values["rank"]), rank)
            score_key = f"{method}_score"
            values[score_key] = max(float(values.get(score_key, -1.0)), score)


def _lexical_similarity(
    left: DuplicateCandidateJob, right: DuplicateCandidateJob
) -> float:
    left_snapshot = left.snapshot
    right_snapshot = right.snapshot
    return round(
        0.4
        * _string_similarity(left_snapshot.company_name, right_snapshot.company_name)
        + 0.35 * _string_similarity(left_snapshot.title, right_snapshot.title)
        + 0.15
        * _string_similarity(
            left_snapshot.description_text, right_snapshot.description_text
        )
        + 0.05 * _string_similarity(left_snapshot.location, right_snapshot.location)
        + 0.05
        * _date_similarity(left_snapshot.posted_date, right_snapshot.posted_date),
        12,
    )


def _embedding_similarity(
    left: DuplicateCandidateJob, right: DuplicateCandidateJob
) -> float | None:
    if left.embedding is None or right.embedding is None:
        return None
    if not left.embedding or len(left.embedding) != len(right.embedding):
        return None
    left_norm = math.sqrt(sum(value * value for value in left.embedding))
    right_norm = math.sqrt(sum(value * value for value in right.embedding))
    if left_norm == 0 or right_norm == 0:
        return None
    return round(
        sum(a * b for a, b in zip(left.embedding, right.embedding, strict=True))
        / (left_norm * right_norm),
        12,
    )


def _has_pair_evidence(snapshot: DuplicateJobSnapshot) -> bool:
    return bool(
        _normalize(snapshot.title)
        and (_normalize(snapshot.company_name) or _normalize(snapshot.description_text))
    )


def _string_similarity(left: str | None, right: str | None) -> float:
    normalized_left = _normalize(left)
    normalized_right = _normalize(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    left_tokens = set(normalized_left.split())
    right_tokens = set(normalized_right.split())
    token_union = left_tokens | right_tokens
    token_score = len(left_tokens & right_tokens) / len(token_union)
    sequence_score = SequenceMatcher(None, normalized_left, normalized_right).ratio()
    return max(token_score, sequence_score)


def _date_similarity(left: str | None, right: str | None) -> float:
    try:
        left_date = date.fromisoformat(left or "")
        right_date = date.fromisoformat(right or "")
    except ValueError:
        return 0.0
    distance = abs((left_date - right_date).days)
    return max(0.0, 1.0 - distance / 30)


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"[\w]+", normalized, flags=re.UNICODE))


def _snapshot_identity(snapshot: DuplicateJobSnapshot) -> str:
    return f"{snapshot.source_site}:{snapshot.source_job_id}"


def _canonical_pair(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left < right else (right, left)


def _optional_float(value: object) -> float | None:
    return float(value) if value is not None else None


__all__ = [
    "CandidateRecallMetric",
    "ControlledDuplicateCase",
    "DuplicateCandidate",
    "DuplicateCandidateJob",
    "DuplicateCandidatePolicy",
    "DuplicateEvaluationGates",
    "DuplicateArtifactError",
    "DuplicateJobSnapshot",
    "build_duplicate_candidates",
    "candidate_recall_at_k",
    "score_duplicate_evaluation",
    "duplicate_pair_hash",
    "load_duplicate_cases",
]
