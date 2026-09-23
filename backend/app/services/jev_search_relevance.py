from __future__ import annotations

from collections import defaultdict
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.job_intelligence.foundation import normalized_content_hash


class SearchRelevanceArtifactError(ValueError):
    pass


class SearchCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_identity: str = Field(min_length=1)
    title: str = Field(min_length=1)
    evidence: str | None = None
    baseline_score: float
    relevance_grade: int = Field(ge=0, le=3)


class SearchRelevanceCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: str
    group_id: str
    split: Literal["development", "held_out"]
    language: Literal["en", "zh-Hant", "mixed"]
    query: str = Field(min_length=1)
    candidates: tuple[SearchCandidate, ...] = Field(min_length=3, max_length=20)
    label_provenance: Literal["explicit_construction_v1"]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def search_case_hash(case: SearchRelevanceCase) -> str:
    return normalized_content_hash(
        {
            "query": case.query,
            "candidates": [item.model_dump() for item in case.candidates],
        }
    )


def load_search_relevance_cases(path: Path) -> tuple[SearchRelevanceCase, ...]:
    values = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = SearchRelevanceCase.model_validate_json(line)
        except (ValidationError, ValueError) as exc:
            raise SearchRelevanceArtifactError(
                f"invalid search case line {number}: {exc}"
            ) from exc
        if case.content_sha256 != search_case_hash(case):
            raise SearchRelevanceArtifactError(
                f"case {case.case_id} content hash mismatch"
            )
        identities = [item.source_identity for item in case.candidates]
        if len(identities) != len(set(identities)):
            raise SearchRelevanceArtifactError(
                f"case {case.case_id} has duplicate candidates"
            )
        values.append(case)
    if not values:
        raise SearchRelevanceArtifactError("search artifact is empty")
    if len({item.case_id for item in values}) != len(values):
        raise SearchRelevanceArtifactError("search case IDs must be unique")
    groups: dict[str, set[str]] = defaultdict(set)
    for item in values:
        groups[item.group_id].add(item.split)
    if any(len(splits) > 1 for splits in groups.values()):
        raise SearchRelevanceArtifactError("search group leakage across splits")
    return tuple(values)


def stable_baseline_order(case: SearchRelevanceCase) -> tuple[SearchCandidate, ...]:
    return tuple(
        sorted(
            case.candidates,
            key=lambda item: (-item.baseline_score, item.source_identity),
        )
    )


def page_ranked_candidates(
    case: SearchRelevanceCase, *, page: int, page_size: int
) -> tuple[str, ...]:
    if page < 1 or page_size < 1:
        raise ValueError("page and page_size must be positive")
    ordered = stable_baseline_order(case)
    start = (page - 1) * page_size
    return tuple(item.source_identity for item in ordered[start : start + page_size])


def score_search_relevance(cases: tuple[SearchRelevanceCase, ...]) -> dict[str, float]:
    recalls = []
    reciprocal_ranks = []
    ndcgs = []
    stable = []
    for case in cases:
        ordered = stable_baseline_order(case)
        relevant = [item for item in case.candidates if item.relevance_grade > 0]
        recalls.append(1.0 if all(item in ordered[:20] for item in relevant) else 0.0)
        first = next(
            (
                index
                for index, item in enumerate(ordered, 1)
                if item.relevance_grade > 0
            ),
            None,
        )
        reciprocal_ranks.append(1 / first if first else 0.0)
        dcg = sum(
            (2**item.relevance_grade - 1) / math.log2(index + 2)
            for index, item in enumerate(ordered[:10])
        )
        ideal = sorted(
            case.candidates,
            key=lambda item: (-item.relevance_grade, item.source_identity),
        )
        idcg = sum(
            (2**item.relevance_grade - 1) / math.log2(index + 2)
            for index, item in enumerate(ideal[:10])
        )
        ndcgs.append(dcg / idcg if idcg else 0.0)
        stable.append(ordered == stable_baseline_order(case))
    return {
        "candidate_recall_at_20": sum(recalls) / len(recalls),
        "mrr": sum(reciprocal_ranks) / len(reciprocal_ranks),
        "ndcg_at_10": sum(ndcgs) / len(ndcgs),
        "tie_stability": sum(stable) / len(stable),
    }


__all__ = [
    "SearchRelevanceArtifactError",
    "SearchRelevanceCase",
    "load_search_relevance_cases",
    "page_ranked_candidates",
    "score_search_relevance",
    "search_case_hash",
    "stable_baseline_order",
]
