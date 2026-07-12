from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import combinations


def _canonical_ids(job_ids: Iterable[str]) -> tuple[str, ...]:
    values = tuple(job_ids)
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("job IDs must be non-empty strings")
    return tuple(sorted(set(values)))


def canonical_id_set_hash(job_ids: Iterable[str]) -> str:
    canonical = json.dumps(
        list(_canonical_ids(job_ids)),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


def coefficient_of_variation(values: Sequence[int]) -> float:
    if not values:
        raise ValueError("at least one value is required")
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError("values must be nonnegative exact integers")
    mean = statistics.fmean(values)
    if mean == 0:
        return 0.0 if all(value == 0 for value in values) else math.inf
    return statistics.pstdev(values) / mean


@dataclass(frozen=True, slots=True)
class StabilityRun:
    run_id: str
    job_ids: frozenset[str]
    listing_requests: int
    duration_seconds: float
    accepted: bool = True
    unresolved_gaps: int = 0
    identity_conflicts: int = 0
    conservation_difference: int = 0
    unclassified_failures: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("run_id is required")
        canonical_ids = frozenset(_canonical_ids(self.job_ids))
        object.__setattr__(self, "job_ids", canonical_ids)
        if type(self.listing_requests) is not int or self.listing_requests < 0:
            raise ValueError("listing_requests must be a nonnegative exact integer")
        if (
            isinstance(self.duration_seconds, bool)
            or not isinstance(self.duration_seconds, (int, float))
            or not math.isfinite(self.duration_seconds)
            or self.duration_seconds < 0
        ):
            raise ValueError("duration_seconds must be a finite nonnegative number")
        object.__setattr__(self, "duration_seconds", float(self.duration_seconds))
        if type(self.accepted) is not bool:
            raise ValueError("accepted must be an exact boolean")
        for field_name in (
            "unresolved_gaps",
            "identity_conflicts",
            "conservation_difference",
            "unclassified_failures",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a nonnegative exact integer")

    @property
    def set_hash(self) -> str:
        return canonical_id_set_hash(self.job_ids)

    def to_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "job_ids": sorted(self.job_ids),
            "listing_requests": self.listing_requests,
            "duration_seconds": self.duration_seconds,
            "accepted": self.accepted,
            "unresolved_gaps": self.unresolved_gaps,
            "identity_conflicts": self.identity_conflicts,
            "conservation_difference": self.conservation_difference,
            "unclassified_failures": self.unclassified_failures,
        }


@dataclass(frozen=True, slots=True)
class PairwiseSetComparison:
    left_run_id: str
    right_run_id: str
    jaccard: float
    added_ids: tuple[str, ...]
    removed_ids: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "left_run_id": self.left_run_id,
            "right_run_id": self.right_run_id,
            "jaccard": self.jaccard,
            "added_ids": list(self.added_ids),
            "removed_ids": list(self.removed_ids),
        }


@dataclass(frozen=True, slots=True)
class Plan3EntryDecision:
    accepted: bool
    failing_gates: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "failing_gates": list(self.failing_gates),
        }


@dataclass(frozen=True, slots=True)
class StabilityComparison:
    census_set_hashes: tuple[tuple[str, str], ...]
    fixed_set_hashes: tuple[tuple[str, str], ...]
    census_pairwise: tuple[PairwiseSetComparison, ...]
    fixed_pairwise: tuple[PairwiseSetComparison, ...]
    fixed_cohort_jaccard: float
    fixed_union_ids: tuple[str, ...]
    fixed_union_hash: str
    fixed_unique_counts: tuple[int, ...]
    union_ids: tuple[str, ...]
    union_hash: str
    unique_counts: tuple[int, ...]
    unique_count_cv: float
    requests_per_new_id: float
    seconds_per_new_id: float
    decision: Plan3EntryDecision

    def to_payload(self) -> dict[str, object]:
        return {
            "census_set_hashes": [
                {"run_id": run_id, "set_hash": set_hash}
                for run_id, set_hash in self.census_set_hashes
            ],
            "fixed_set_hashes": [
                {"run_id": run_id, "set_hash": set_hash}
                for run_id, set_hash in self.fixed_set_hashes
            ],
            "census_pairwise": [item.to_payload() for item in self.census_pairwise],
            "fixed_pairwise": [item.to_payload() for item in self.fixed_pairwise],
            "fixed_cohort_jaccard": self.fixed_cohort_jaccard,
            "fixed_union_ids": list(self.fixed_union_ids),
            "fixed_union_hash": self.fixed_union_hash,
            "fixed_unique_counts": list(self.fixed_unique_counts),
            "union_ids": list(self.union_ids),
            "union_hash": self.union_hash,
            "unique_counts": list(self.unique_counts),
            "unique_count_cv": self.unique_count_cv,
            "requests_per_new_id": self.requests_per_new_id,
            "seconds_per_new_id": self.seconds_per_new_id,
            "decision": self.decision.to_payload(),
        }


def _pairwise(runs: Sequence[StabilityRun]) -> tuple[PairwiseSetComparison, ...]:
    return tuple(
        PairwiseSetComparison(
            left_run_id=left.run_id,
            right_run_id=right.run_id,
            jaccard=jaccard(set(left.job_ids), set(right.job_ids)),
            added_ids=tuple(sorted(right.job_ids - left.job_ids)),
            removed_ids=tuple(sorted(left.job_ids - right.job_ids)),
        )
        for left, right in combinations(runs, 2)
    )


def _cost_per_new_id(cost: float, new_id_count: int) -> float:
    if new_id_count:
        return cost / new_id_count
    return 0.0 if cost == 0 else math.inf


def compare_stability(
    census_runs: Sequence[StabilityRun],
    fixed_runs: Sequence[StabilityRun],
) -> StabilityComparison:
    censuses = tuple(census_runs)
    fixed = tuple(fixed_runs)
    if len(censuses) != 3 or len(fixed) != 3:
        raise ValueError("exactly three census and three fixed runs are required")
    run_ids = tuple(item.run_id for item in (*censuses, *fixed))
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("all stability run IDs must be distinct")

    census_pairwise = _pairwise(censuses)
    fixed_pairwise = _pairwise(fixed)
    fixed_cohort_jaccard = min(item.jaccard for item in fixed_pairwise)
    fixed_union_ids = _canonical_ids(
        job_id for item in fixed for job_id in item.job_ids
    )
    union_ids = _canonical_ids(job_id for item in censuses for job_id in item.job_ids)
    unique_counts = tuple(len(item.job_ids) for item in censuses)
    unique_count_cv = coefficient_of_variation(unique_counts)
    total_requests = sum(item.listing_requests for item in censuses)
    total_seconds = sum(item.duration_seconds for item in censuses)

    failing_gates: list[str] = []
    if not all(item.accepted for item in censuses):
        failing_gates.append("all_three_censuses_accepted")
    if fixed_cohort_jaccard < 0.95:
        failing_gates.append("fixed_cohort_jaccard")
    if unique_count_cv > 0.05:
        failing_gates.append("unique_count_cv")
    if sum(item.unresolved_gaps for item in censuses):
        failing_gates.append("unresolved_gaps")
    if sum(item.identity_conflicts for item in censuses):
        failing_gates.append("identity_conflicts")
    if sum(item.conservation_difference for item in censuses):
        failing_gates.append("conservation_difference")
    if sum(item.unclassified_failures for item in censuses):
        failing_gates.append("unclassified_failures")

    return StabilityComparison(
        census_set_hashes=tuple((item.run_id, item.set_hash) for item in censuses),
        fixed_set_hashes=tuple((item.run_id, item.set_hash) for item in fixed),
        census_pairwise=census_pairwise,
        fixed_pairwise=fixed_pairwise,
        fixed_cohort_jaccard=fixed_cohort_jaccard,
        fixed_union_ids=fixed_union_ids,
        fixed_union_hash=canonical_id_set_hash(fixed_union_ids),
        fixed_unique_counts=tuple(len(item.job_ids) for item in fixed),
        union_ids=union_ids,
        union_hash=canonical_id_set_hash(union_ids),
        unique_counts=unique_counts,
        unique_count_cv=unique_count_cv,
        requests_per_new_id=_cost_per_new_id(total_requests, len(union_ids)),
        seconds_per_new_id=_cost_per_new_id(total_seconds, len(union_ids)),
        decision=Plan3EntryDecision(
            accepted=not failing_gates,
            failing_gates=tuple(failing_gates),
        ),
    )
