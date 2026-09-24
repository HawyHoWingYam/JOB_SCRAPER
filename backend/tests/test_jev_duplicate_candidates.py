from __future__ import annotations

from pathlib import Path

from app.services.jev_duplicate_evaluation import (
    DuplicateCandidateJob,
    DuplicateCandidatePolicy,
    DuplicateJobSnapshot,
    build_duplicate_candidates,
    candidate_recall_at_k,
    load_duplicate_cases,
)


FIXTURE = Path(__file__).parent / "fixtures" / "jev_duplicate_controlled_v1.jsonl"


def _job(
    source_job_id: str,
    *,
    source_site: str = "controlled",
    title: str = "Platform Engineer",
    company: str | None = "Acme",
    location: str | None = "Central",
    posted_date: str | None = "2026-09-01",
    description: str | None = "Operate the cloud platform.",
    embedding: tuple[float, ...] | None = None,
) -> DuplicateCandidateJob:
    return DuplicateCandidateJob(
        snapshot=DuplicateJobSnapshot(
            source_site=source_site,
            source_job_id=source_job_id,
            title=title,
            company_name=company,
            location=location,
            posted_date=posted_date,
            description_text=description,
        ),
        embedding=embedding,
    )


def test_candidates_are_symmetric_deterministic_and_union_directed_top_k() -> None:
    jobs = (
        _job("a", embedding=(1.0, 0.0)),
        _job("b", title="Platform Developer", embedding=(0.99, 0.01)),
        _job("c", title="Platform Specialist", embedding=(0.9, 0.1)),
    )
    policy = DuplicateCandidatePolicy(
        lexical_top_k=1,
        embedding_top_k=1,
        max_pairs=10,
    )

    forward = build_duplicate_candidates(jobs, policy=policy)
    reversed_input = build_duplicate_candidates(tuple(reversed(jobs)), policy=policy)

    assert forward == reversed_input
    assert len({candidate.pair_id for candidate in forward}) == len(forward)
    assert all(
        candidate.left_identity < candidate.right_identity for candidate in forward
    )
    assert {
        (candidate.left_identity, candidate.right_identity) for candidate in forward
    } >= {
        ("controlled:a", "controlled:b"),
        ("controlled:a", "controlled:c"),
    }


def test_candidates_keep_hard_negatives_and_same_source_reposts_but_skip_missing_evidence() -> (
    None
):
    jobs = (
        _job("same-source-a", source_site="jobsdb"),
        _job("same-source-b", source_site="jobsdb"),
        _job("same-title-other-company", company="Contoso"),
        _job("same-company-other-role", title="HR Manager"),
        _job("missing", company=None, description=None),
    )

    candidates = build_duplicate_candidates(
        jobs,
        policy=DuplicateCandidatePolicy(
            lexical_top_k=10,
            embedding_top_k=10,
            max_pairs=20,
        ),
    )
    identities = {
        (candidate.left_identity, candidate.right_identity) for candidate in candidates
    }

    assert ("jobsdb:same-source-a", "jobsdb:same-source-b") in identities
    assert any(
        any("same-title-other-company" in identity for identity in pair)
        for pair in identities
    )
    assert any(
        any("same-company-other-role" in identity for identity in pair)
        for pair in identities
    )
    assert all(
        all("missing" not in identity for identity in pair) for pair in identities
    )


def test_controlled_candidate_recall_at_10_meets_the_frozen_gate() -> None:
    cases = load_duplicate_cases(FIXTURE)
    snapshots = {
        f"{snapshot.source_site}:{snapshot.source_job_id}": snapshot
        for case in cases
        for snapshot in (case.left, case.right)
    }
    jobs = tuple(
        DuplicateCandidateJob(snapshot=snapshot)
        for _, snapshot in sorted(snapshots.items())
    )
    candidates = build_duplicate_candidates(
        jobs,
        policy=DuplicateCandidatePolicy(
            lexical_top_k=10,
            embedding_top_k=10,
            max_pairs=200,
        ),
    )

    metric = candidate_recall_at_k(cases, candidates, k=10)

    assert metric.eligible_positive_pairs >= 1
    assert metric.recalled_positive_pairs <= metric.eligible_positive_pairs
    assert metric.recall >= 0.95
