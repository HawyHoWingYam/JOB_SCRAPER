from __future__ import annotations

import hashlib
import json
import math
import statistics

import pytest

from app.sources.offertoday.research.stability import (
    StabilityRun,
    canonical_id_set_hash,
    coefficient_of_variation,
    compare_stability,
    jaccard,
)


def run(
    run_id: str,
    job_ids: set[str],
    *,
    requests: int = 10,
    seconds: float = 20.0,
    accepted: bool = True,
    gaps: int = 0,
    conflicts: int = 0,
    conservation: int = 0,
    unclassified: int = 0,
) -> StabilityRun:
    return StabilityRun(
        run_id=run_id,
        job_ids=frozenset(job_ids),
        listing_requests=requests,
        duration_seconds=seconds,
        accepted=accepted,
        unresolved_gaps=gaps,
        identity_conflicts=conflicts,
        conservation_difference=conservation,
        unclassified_failures=unclassified,
    )


def test_canonical_id_set_hash_is_sorted_distinct_and_reproducible() -> None:
    expected = hashlib.sha256(
        json.dumps(
            ["a", "b"],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    assert canonical_id_set_hash(["b", "a", "b"]) == expected
    assert canonical_id_set_hash({"a", "b"}) == expected


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    (
        (set(), set(), 1.0),
        ({"a"}, set(), 0.0),
        ({"a", "b"}, {"b", "c"}, 1 / 3),
        ({"a", "b"}, {"a", "b"}, 1.0),
    ),
)
def test_jaccard_uses_exact_set_overlap(left, right, expected) -> None:
    assert jaccard(left, right) == expected


def test_coefficient_of_variation_uses_population_standard_deviation() -> None:
    values = (8, 10, 12)

    assert coefficient_of_variation(values) == pytest.approx(
        statistics.pstdev(values) / statistics.fmean(values)
    )
    assert coefficient_of_variation((0, 0, 0)) == 0.0
    with pytest.raises(ValueError, match="at least one value is required"):
        coefficient_of_variation(())


def test_compare_stability_records_exact_churn_cost_and_failing_gates() -> None:
    censuses = (
        run("c1", {"a", "b", "c"}, requests=6, seconds=12),
        run("c2", {"b", "c", "d"}, requests=8, seconds=16),
        run("c3", {"b", "c", "d", "e"}, requests=10, seconds=20),
    )
    fixed = (
        run("f1", {"x", "y", "z"}),
        run("f2", {"x", "y", "z"}),
        run("f3", {"x", "y"}),
    )

    comparison = compare_stability(censuses, fixed)

    assert tuple(item.jaccard for item in comparison.census_pairwise) == (
        0.5,
        0.4,
        0.75,
    )
    assert comparison.census_pairwise[0].added_ids == ("d",)
    assert comparison.census_pairwise[0].removed_ids == ("a",)
    assert comparison.census_pairwise[1].added_ids == ("d", "e")
    assert comparison.census_pairwise[1].removed_ids == ("a",)
    assert comparison.census_pairwise[2].added_ids == ("e",)
    assert comparison.census_pairwise[2].removed_ids == ()
    assert tuple(item.jaccard for item in comparison.fixed_pairwise) == (
        1.0,
        2 / 3,
        2 / 3,
    )
    assert comparison.fixed_cohort_jaccard == 2 / 3
    assert comparison.fixed_union_ids == ("x", "y", "z")
    assert comparison.fixed_union_hash == canonical_id_set_hash(("x", "y", "z"))
    assert comparison.fixed_unique_counts == (3, 3, 2)
    assert comparison.union_ids == ("a", "b", "c", "d", "e")
    assert comparison.union_hash == canonical_id_set_hash(comparison.union_ids)
    assert comparison.unique_counts == (3, 3, 4)
    assert comparison.unique_count_cv == pytest.approx(
        coefficient_of_variation((3, 3, 4))
    )
    assert comparison.requests_per_new_id == 24 / 5
    assert comparison.seconds_per_new_id == 48 / 5
    assert comparison.decision.accepted is False
    assert comparison.decision.failing_gates == (
        "fixed_cohort_jaccard",
        "unique_count_cv",
    )


def test_compare_stability_accepts_only_when_every_plan3_gate_passes() -> None:
    stable_ids = {"a", "b", "c"}
    accepted = compare_stability(
        tuple(run(f"c{index}", stable_ids) for index in range(1, 4)),
        tuple(run(f"f{index}", stable_ids) for index in range(1, 4)),
    )

    assert accepted.fixed_cohort_jaccard == 1.0
    assert accepted.unique_count_cv == 0.0
    assert accepted.decision.accepted is True
    assert accepted.decision.failing_gates == ()

    rejected = compare_stability(
        (
            run("c1", stable_ids, accepted=False),
            run("c2", stable_ids, gaps=1),
            run("c3", stable_ids, conflicts=1, conservation=1, unclassified=1),
        ),
        tuple(run(f"f{index}", stable_ids) for index in range(1, 4)),
    )

    assert rejected.decision.accepted is False
    assert rejected.decision.failing_gates == (
        "all_three_censuses_accepted",
        "unresolved_gaps",
        "identity_conflicts",
        "conservation_difference",
        "unclassified_failures",
    )


def test_zero_union_cost_is_explicit() -> None:
    empty_censuses = tuple(
        run(f"c{index}", set(), requests=0, seconds=0.0) for index in range(1, 4)
    )
    empty_fixed = tuple(run(f"f{index}", set()) for index in range(1, 4))

    comparison = compare_stability(empty_censuses, empty_fixed)

    assert comparison.requests_per_new_id == 0.0
    assert comparison.seconds_per_new_id == 0.0

    nonzero_cost = compare_stability(
        tuple(
            run(f"c{index}", set(), requests=1, seconds=1.0) for index in range(1, 4)
        ),
        empty_fixed,
    )
    assert math.isinf(nonzero_cost.requests_per_new_id)
    assert math.isinf(nonzero_cost.seconds_per_new_id)
