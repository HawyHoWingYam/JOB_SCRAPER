from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.sources.offertoday.research.baseline import build_baseline_snapshot
from app.sources.offertoday.research.conservation import (
    ResearchConservationReport,
    build_detail_conservation_report,
    build_listing_conservation_report,
    replay_research_conservation,
)
from app.sources.offertoday.research.contracts import (
    PublishedJobSnapshot,
    StagedListingSnapshot,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "offertoday_research"


def _staged(
    row_id: str,
    source_job_id: str,
    detail_status: str,
    published_job_id: str | None,
    crawl_job_id: str,
    detail_attempts: int = 0,
    **changes,
) -> StagedListingSnapshot:
    return StagedListingSnapshot(
        row_id=row_id,
        source_job_id=source_job_id,
        detail_status=detail_status,
        published_job_id=published_job_id,
        crawl_job_id=crawl_job_id,
        detail_attempts=detail_attempts,
        **changes,
    )


def _valid_listing_conservation(**changes):
    arguments = {
        "raw_listing_rows": 1,
        "rows_missing_job_id": 0,
        "rows_containing_job_id": 1,
        "valid_distinct_job_ids": {"j-1"},
        "already_published_ids": {"j-1"},
        "preexisting_staged_unpublished_ids": set(),
        "newly_staged_ids": set(),
        "deferred_identity_conflict_ids": set(),
        "newly_created_staging_rows": 0,
        "unresolved_gaps": 0,
    }
    arguments.update(changes)
    return build_listing_conservation_report(**arguments)


def test_listing_conservation_requires_both_equations_and_no_gap():
    report = build_listing_conservation_report(
        raw_listing_rows=6,
        rows_missing_job_id=1,
        rows_containing_job_id=5,
        valid_distinct_job_ids={"j-1", "j-2", "j-3", "j-4"},
        already_published_ids={"j-1"},
        preexisting_staged_unpublished_ids={"j-2"},
        newly_staged_ids={"j-3"},
        deferred_identity_conflict_ids={"j-4"},
        newly_created_staging_rows=1,
        unresolved_gaps=0,
    )

    assert report.raw_rows.left_name == "raw_listing_rows"
    assert report.raw_rows.left_value == 6
    assert report.raw_rows.right_parts == {
        "rows_missing_job_id": 1,
        "rows_containing_job_id": 5,
    }
    assert report.raw_rows.difference == 0
    assert report.distinct_ids.difference == 0
    assert report.is_valid is True


def test_listing_gap_invalidates_zero_difference_report():
    report = _valid_listing_conservation(unresolved_gaps=1)

    assert report.raw_rows.difference == 0
    assert report.distinct_ids.difference == 0
    assert report.is_valid is False


def test_listing_overlap_and_symmetric_unexplained_ids_are_sorted_and_invalid():
    report = build_listing_conservation_report(
        raw_listing_rows=2,
        rows_missing_job_id=0,
        rows_containing_job_id=2,
        valid_distinct_job_ids={"j-1", "j-2"},
        already_published_ids={"j-1", "j-extra"},
        preexisting_staged_unpublished_ids={"j-1"},
        newly_staged_ids=set(),
        deferred_identity_conflict_ids=set(),
        newly_created_staging_rows=0,
        unresolved_gaps=0,
    )

    assert report.partition_overlap_ids == ("j-1",)
    assert report.unexplained_ids == ("j-2", "j-extra")
    assert report.is_valid is False


@pytest.mark.parametrize(
    ("new_ids", "created_rows", "amplification", "violation"),
    [
        (set(), 1, None, True),
        ({f"j-{index}" for index in range(100)}, 101, 1.01, False),
        ({f"j-{index}" for index in range(100)}, 102, 1.02, True),
    ],
)
def test_listing_staging_amplification_guard(
    new_ids,
    created_rows,
    amplification,
    violation,
):
    report = build_listing_conservation_report(
        raw_listing_rows=len(new_ids),
        rows_missing_job_id=0,
        rows_containing_job_id=len(new_ids),
        valid_distinct_job_ids=set(new_ids),
        already_published_ids=set(),
        preexisting_staged_unpublished_ids=set(),
        newly_staged_ids=set(new_ids),
        deferred_identity_conflict_ids=set(),
        newly_created_staging_rows=created_rows,
        unresolved_gaps=0,
    )

    if amplification is None:
        assert report.staging_amplification is None
    else:
        assert report.staging_amplification == pytest.approx(amplification)
    assert report.staging_amplification_violation is violation


def test_detail_conservation_counts_duplicate_rows_once_by_canonical_id():
    rows = [
        _staged(
            "row-1",
            "j-1",
            "failed",
            None,
            "run-1",
            1,
            last_detail_crawl_job_id="detail-run-1",
        ),
        _staged("row-2", "j-1", "pending", None, "run-2"),
        _staged(
            "row-3",
            "j-2",
            "terminal_unavailable",
            None,
            "run-1",
            1,
            last_detail_crawl_job_id="detail-run-1",
        ),
        _staged(
            "row-4",
            "j-3",
            "completed",
            "job-3",
            "run-1",
            1,
            last_detail_crawl_job_id="detail-run-1",
            has_detail_payload=True,
        ),
    ]
    jobs = [PublishedJobSnapshot("job-3", "j-3", True, True, True)]

    report = build_detail_conservation_report(
        detail_crawl_job_id="detail-run-1",
        fetch_cohort_source_job_ids={"j-1", "j-2", "j-3"},
        persisted_source_job_ids={"j-3"},
        listings=rows,
        jobs=jobs,
    )

    assert report.distinct_eligible == 3
    assert report.outcomes == {
        "completed": 1,
        "terminal_unavailable": 1,
        "retryable_failed": 1,
        "manual_action_required": 0,
        "pending": 0,
        "running": 0,
    }
    assert report.difference == 0
    assert report.is_valid is True


def test_stale_complete_job_does_not_count_as_current_run_fetch_success():
    rows = [
        _staged("row-1", "j-1", "pending", None, "run-1"),
        _staged("row-2", "j-1", "failed", None, "run-2", 1),
    ]
    jobs = [PublishedJobSnapshot("job-1", "j-1", True, True, True)]

    report = build_detail_conservation_report(
        detail_crawl_job_id="detail-run-1",
        fetch_cohort_source_job_ids={"j-1"},
        persisted_source_job_ids=set(),
        listings=rows,
        jobs=jobs,
    )

    assert report.outcomes["completed"] == 0
    assert report.outcomes["pending"] == 1
    assert report.status_job_mismatches == ("j-1",)
    assert report.is_valid is False


def test_terminal_detail_report_rejects_running_id():
    report = build_detail_conservation_report(
        detail_crawl_job_id="detail-run-1",
        fetch_cohort_source_job_ids={"j-1"},
        persisted_source_job_ids=set(),
        listings=[
            _staged(
                "row-1",
                "j-1",
                "running",
                None,
                "listing-run",
                1,
                last_detail_crawl_job_id="detail-run-1",
            )
        ],
        jobs=[],
        run_is_terminal=True,
    )

    assert report.difference == 0
    assert report.outcomes["running"] == 1
    assert report.is_valid is False


def test_partial_job_does_not_validate_completed_staging_row():
    report = build_detail_conservation_report(
        detail_crawl_job_id="detail-run-1",
        fetch_cohort_source_job_ids={"j-1"},
        persisted_source_job_ids={"j-1"},
        listings=[
            _staged(
                "row-1",
                "j-1",
                "completed",
                "job-1",
                "listing-run",
                1,
                last_detail_crawl_job_id="detail-run-1",
                has_detail_payload=True,
            )
        ],
        jobs=[PublishedJobSnapshot("job-1", "j-1", True, True, False)],
    )

    assert report.outcomes["completed"] == 0
    assert report.outcomes["retryable_failed"] == 1
    assert report.status_job_mismatches == ("j-1",)
    assert report.is_valid is False


def test_recovered_old_job_without_persisted_event_is_not_fetch_success():
    report = build_detail_conservation_report(
        detail_crawl_job_id="detail-run-1",
        fetch_cohort_source_job_ids={"j-1"},
        persisted_source_job_ids=set(),
        listings=[
            _staged(
                "row-1",
                "j-1",
                "completed",
                "job-1",
                "listing-run",
                1,
                last_detail_crawl_job_id="detail-run-1",
                has_detail_payload=True,
            )
        ],
        jobs=[PublishedJobSnapshot("job-1", "j-1", True, True, True)],
    )

    assert report.outcomes["completed"] == 0
    assert report.outcomes["retryable_failed"] == 1
    assert report.status_job_mismatches == ("j-1",)
    assert report.is_valid is False


def test_attempted_failed_row_beats_unattempted_pending_duplicate():
    report = build_detail_conservation_report(
        detail_crawl_job_id="detail-run-1",
        fetch_cohort_source_job_ids={"j-1"},
        persisted_source_job_ids=set(),
        listings=[
            _staged("pending", "j-1", "pending", None, "listing-a"),
            _staged(
                "failed",
                "j-1",
                "failed",
                None,
                "listing-b",
                2,
                last_detail_crawl_job_id="detail-run-1",
            ),
        ],
        jobs=[],
    )

    assert report.outcomes["retryable_failed"] == 1
    assert report.outcomes["pending"] == 0


def test_missing_eligible_and_unknown_status_are_reported_and_invalid():
    report = build_detail_conservation_report(
        detail_crawl_job_id="detail-run-1",
        fetch_cohort_source_job_ids={"j-missing", "j-unknown"},
        persisted_source_job_ids=set(),
        listings=[
            _staged(
                "row-unknown",
                "j-unknown",
                "mystery_status",
                None,
                "listing-run",
                1,
                last_detail_crawl_job_id="detail-run-1",
            )
        ],
        jobs=[],
    )

    assert report.missing_eligible_ids == ("j-missing",)
    assert report.unclassified_statuses == ("mystery_status",)
    assert report.difference == 2
    assert report.is_valid is False


@pytest.mark.parametrize(
    ("rows", "expected_outcome"),
    [
        (
            [
                ("high-attempt", "manual_action_required", 2, "2026-01-01", "2026-01-01"),
                ("low-attempt", "failed", 1, "2026-12-01", "2026-12-01"),
            ],
            "manual_action_required",
        ),
        (
            [
                ("late-start", "terminal_unavailable", 2, "2026-02-01", "2026-01-01"),
                ("early-start", "failed", 2, "2026-01-01", "2026-12-01"),
            ],
            "terminal_unavailable",
        ),
        (
            [
                ("late-update", "running", 2, "2026-02-01", "2026-03-01"),
                ("early-update", "failed", 2, "2026-02-01", "2026-01-01"),
            ],
            "running",
        ),
        (
            [
                ("row-z", "pending", 2, "2026-02-01", "2026-03-01"),
                ("row-a", "failed", 2, "2026-02-01", "2026-03-01"),
            ],
            "pending",
        ),
    ],
)
def test_authoritative_row_uses_attempt_started_updated_and_row_id_order(
    rows,
    expected_outcome,
):
    listings = [
        _staged(
            row_id,
            "j-1",
            status,
            None,
            "listing-run",
            attempts,
            detail_started_at=started_at,
            updated_at=updated_at,
            last_detail_crawl_job_id="detail-run-1",
        )
        for row_id, status, attempts, started_at, updated_at in rows
    ]

    report = build_detail_conservation_report(
        detail_crawl_job_id="detail-run-1",
        fetch_cohort_source_job_ids={"j-1"},
        persisted_source_job_ids=set(),
        listings=listings,
        jobs=[],
        run_is_terminal=False,
    )

    assert report.outcomes[expected_outcome] == 1
    assert sum(report.outcomes.values()) == 1


def test_completed_row_must_link_to_same_canonical_published_job():
    report = build_detail_conservation_report(
        detail_crawl_job_id="detail-run-1",
        fetch_cohort_source_job_ids={"j-1"},
        persisted_source_job_ids={"j-1"},
        listings=[
            _staged(
                "row-1",
                "j-1",
                "completed",
                "job-other",
                "listing-run",
                1,
                last_detail_crawl_job_id="detail-run-1",
                has_detail_payload=True,
            )
        ],
        jobs=[
            PublishedJobSnapshot("job-other", "j-other", True, True, True)
        ],
    )

    assert report.outcomes["retryable_failed"] == 1
    assert report.status_job_mismatches == ("j-1",)
    assert report.is_valid is False


def test_research_report_requires_at_least_one_valid_subreport():
    assert ResearchConservationReport(listing=None, detail=None).is_valid is False
    assert ResearchConservationReport(
        listing=_valid_listing_conservation(),
        detail=None,
    ).is_valid is True


def _crawl_job(*, crawl_job_id="crawl-run", status="completed", published=(), staged=()):
    return SimpleNamespace(
        id=crawl_job_id,
        status=status,
        request_payload={
            "research": {
                "run_start_inventory": {
                    "published_job_ids": list(published),
                    "staged_unpublished_job_ids": list(staged),
                    "data_hash": "synthetic-hash",
                }
            }
        },
    )


def test_replay_partitions_listing_ids_by_frozen_run_start_priority():
    rows = [
        {"job_id": "j-1", "encrypted_job_id": "enc-1"},
        {"job_id": "j-2", "encrypted_job_id": "enc-2"},
        {"job_id": "j-3", "encrypted_job_id": "enc-3"},
        {"job_id": "j-4", "encrypted_job_id": None},
    ]
    events = [
        {
            "sequence_no": 1,
            "event_type": "crawl.listing_page_attempt",
            "payload": {
                "condition_id": "condition-1",
                "page": 1,
                "classification": "identity_issue",
                "row_count": 4,
                "missing_job_id_count": 0,
                "rows": rows,
                "identity_issues": [
                    {"job_id": "j-4", "reason": "missing_encrypted_job_id"}
                ],
            },
        },
        {
            "sequence_no": 2,
            "event_type": "crawl.listing_observed",
            "payload": {
                "records": [
                    {"source_job_id": job_id, "classification": "newly_staged"}
                    for job_id in ("j-1", "j-2", "j-3", "j-4")
                ],
                "rows_created": 1,
            },
        },
    ]

    report = replay_research_conservation(
        crawl_job=_crawl_job(published=("j-1",), staged=("j-2",)),
        events=events,
        listings=[],
        jobs=[],
    )

    assert report.listing is not None
    assert report.listing.distinct_ids.right_parts == {
        "already_published": 1,
        "preexisting_staged_unpublished": 1,
        "newly_staged": 1,
        "deferred_identity_conflict": 1,
    }
    assert report.listing.partition_overlap_ids == ()
    assert report.listing.unexplained_ids == ()
    assert report.is_valid is True


def test_replay_keeps_reconciled_ids_outside_frozen_fetch_conservation():
    listings = [
        _staged(
            "row-fetch",
            "j-fetch",
            "completed",
            "job-fetch",
            "listing-run",
            1,
            last_detail_crawl_job_id="detail-run",
            has_detail_payload=True,
        )
    ]
    jobs = [
        PublishedJobSnapshot("job-fetch", "j-fetch", True, True, True),
        PublishedJobSnapshot(
            "job-reconciled", "j-reconciled", True, True, True
        ),
    ]
    events = [
        {
            "sequence_no": 1,
            "event_type": "crawl.detail_cohort_frozen",
            "payload": {
                "fetch_cohort_source_job_ids": ["j-fetch"],
                "reconciled_source_job_ids": ["j-reconciled"],
            },
        },
        SimpleNamespace(
            sequence_no=2,
            event_type="crawl.detail_persisted",
            payload={"source_job_id": "j-fetch"},
        ),
    ]

    report = replay_research_conservation(
        crawl_job=_crawl_job(crawl_job_id="detail-run"),
        events=events,
        listings=listings,
        jobs=jobs,
    )

    assert report.detail is not None
    assert report.detail.distinct_eligible == 1
    assert report.detail.outcomes["completed"] == 1
    assert report.reconciled_source_job_ids == ("j-reconciled",)
    assert "j-reconciled" not in {
        row.source_job_id
        for row in listings
        if row.last_detail_crawl_job_id == "detail-run"
    }
    assert report.is_valid is True


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.mark.parametrize(
    ("fixture_name", "expected_valid", "expected_gaps"),
    [
        ("complete", True, 0),
        ("gap", False, 1),
        ("identity_conflict", False, 1),
    ],
)
def test_fixed_listing_observation_fixtures_replay_deterministically(
    fixture_name,
    expected_valid,
    expected_gaps,
):
    events = _load_jsonl(FIXTURE_ROOT / fixture_name / "observations.jsonl")

    report = replay_research_conservation(
        crawl_job=_crawl_job(published=("j-1",)),
        events=events,
        listings=[],
        jobs=[],
    )

    assert report.listing is not None
    assert report.listing.unresolved_gaps == expected_gaps
    assert report.is_valid is expected_valid


def test_duplicate_cross_run_fixture_counts_one_canonical_detail_outcome():
    payload = json.loads(
        (FIXTURE_ROOT / "duplicate_cross_run" / "snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    listings = [StagedListingSnapshot(**row) for row in payload["listings"]]
    jobs = [PublishedJobSnapshot(**row) for row in payload["jobs"]]

    baseline = build_baseline_snapshot(listings=listings, jobs=jobs)
    detail = build_detail_conservation_report(
        detail_crawl_job_id="detail-run-1",
        fetch_cohort_source_job_ids={"j-1"},
        persisted_source_job_ids={"j-1"},
        listings=listings,
        jobs=jobs,
    )

    assert baseline.staged_rows == 2
    assert baseline.distinct_staged_ids == 1
    assert baseline.duplicate_staging_rows == 1
    assert detail.distinct_eligible == 1
    assert detail.outcomes["completed"] == 1
    assert sum(detail.outcomes.values()) == 1
    assert detail.is_valid is True
