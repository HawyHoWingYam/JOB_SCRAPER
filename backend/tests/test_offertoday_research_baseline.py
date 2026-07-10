from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.crawl_job import CrawlJob, CrawlJobEvent
from app.models.crawl_job_listing import CrawlJobListing
from app.models.job import Job
from app.repositories.offertoday_research_repository import (
    OfferTodayResearchRepository,
    classify_persisted_detail_error,
    extract_snapshot_encrypted_job_id,
    extract_snapshot_identity_error,
)
from app.sources.offertoday.research.baseline import (
    build_baseline_snapshot,
    build_run_start_inventory,
)
from app.sources.offertoday.research.contracts import (
    PublishedJobSnapshot,
    StagedListingSnapshot,
)


def _listing(
    row_id: str,
    source_job_id: str,
    detail_status: str,
    published_job_id: str | None,
    crawl_job_id: str,
    **changes,
) -> StagedListingSnapshot:
    return StagedListingSnapshot(
        row_id=row_id,
        source_job_id=source_job_id,
        detail_status=detail_status,
        published_job_id=published_job_id,
        crawl_job_id=crawl_job_id,
        **changes,
    )


def test_build_baseline_snapshot_reports_rows_distinct_ids_and_partial_jobs():
    listings = [
        _listing("row-1", "j-1", "pending", None, "run-1"),
        _listing("row-2", "j-1", "pending", None, "run-2"),
        _listing("row-3", "j-2", "completed", "job-2", "run-1"),
        _listing(
            "row-4",
            "j-3",
            "failed",
            None,
            "run-1",
            detail_error_classification="retryable_failed",
        ),
    ]
    jobs = [
        PublishedJobSnapshot("job-2", "j-2", True, True, True),
        PublishedJobSnapshot("job-3", "j-3", True, True, False),
    ]

    snapshot = build_baseline_snapshot(listings=listings, jobs=jobs)

    assert snapshot.staged_rows == 4
    assert snapshot.distinct_staged_ids == 3
    assert snapshot.published_jobs == 2
    assert snapshot.distinct_staged_unpublished_ids == 1
    assert snapshot.pending_rows == 2
    assert snapshot.distinct_pending_ids == 1
    assert snapshot.pending_rows_with_published_job == 0
    assert snapshot.distinct_published_ids_with_pending_rows == 0
    assert snapshot.published_partial_jobs == 1
    assert snapshot.duplicate_staging_rows == 1
    assert snapshot.detail_status_rows == {
        "completed": 1,
        "failed": 1,
        "pending": 2,
    }
    assert snapshot.detail_error_classifications == {"retryable_failed": 1}

    inventory = build_run_start_inventory(listings=listings, jobs=jobs)
    assert inventory.published_job_ids == ("j-2", "j-3")
    assert inventory.staged_unpublished_job_ids == ("j-1",)


def test_baseline_counts_pending_rows_and_distinct_ids_with_published_jobs():
    listings = [
        _listing(
            "row-1",
            "j-1",
            "pending",
            None,
            "run-1",
            encrypted_job_id="enc-1",
        ),
        _listing(
            "row-2",
            "j-1",
            "pending",
            "job-1",
            "run-2",
            encrypted_job_id="enc-1",
        ),
    ]
    jobs = [PublishedJobSnapshot("job-1", "j-1", True, True, True)]

    snapshot = build_baseline_snapshot(listings=listings, jobs=jobs)

    assert snapshot.pending_rows == 2
    assert snapshot.distinct_pending_ids == 1
    assert snapshot.pending_rows_with_published_job == 2
    assert snapshot.distinct_published_ids_with_pending_rows == 1


def test_baseline_reports_both_directions_of_encrypted_identity_conflicts():
    listings = [
        _listing(
            "row-1",
            "j-1",
            "pending",
            None,
            "run-1",
            encrypted_job_id="enc-shared",
        ),
        _listing(
            "row-2",
            "j-2",
            "pending",
            None,
            "run-1",
            encrypted_job_id="enc-shared",
        ),
        _listing(
            "row-3",
            "j-3",
            "pending",
            None,
            "run-1",
            encrypted_job_id="enc-old",
        ),
        _listing(
            "row-4",
            "j-3",
            "pending",
            None,
            "run-2",
            encrypted_job_id="enc-new",
        ),
    ]

    snapshot = build_baseline_snapshot(listings=listings, jobs=[])

    assert snapshot.identity_mapping_conflict_ids == ("j-1", "j-2", "j-3")


def test_baseline_and_inventory_hashes_are_canonical_and_content_sensitive():
    listings = [
        _listing(
            "row-2",
            "j-2",
            "failed",
            None,
            "run-2",
            encrypted_job_id="enc-2",
        ),
        _listing(
            "row-1",
            "j-1",
            "pending",
            None,
            "run-1",
            encrypted_job_id="enc-1",
        ),
    ]
    jobs = [PublishedJobSnapshot("job-2", "j-2", True, True, False)]

    first = build_baseline_snapshot(listings=listings, jobs=jobs)
    reordered = build_baseline_snapshot(
        listings=list(reversed(listings)),
        jobs=list(reversed(jobs)),
    )
    changed = build_baseline_snapshot(
        listings=[
            listings[0],
            _listing(
                "row-1",
                "j-1",
                "completed",
                None,
                "run-1",
                encrypted_job_id="enc-1",
            ),
        ],
        jobs=jobs,
    )

    assert first.data_hash == reordered.data_hash
    assert first.data_hash != changed.data_hash

    inventory = build_run_start_inventory(listings=listings, jobs=jobs)
    reordered_inventory = build_run_start_inventory(
        listings=list(reversed(listings)),
        jobs=list(reversed(jobs)),
    )
    changed_inventory = build_run_start_inventory(
        listings=[*listings, _listing("row-3", "j-3", "pending", None, "run-3")],
        jobs=jobs,
    )
    assert inventory.data_hash == reordered_inventory.data_hash
    assert inventory.data_hash != changed_inventory.data_hash


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {
                "encrypted_job_id": " enc-normalized ",
                "raw_data": {"jobId": "j-1", "encryptJobId": "enc-normalized"},
            },
            "enc-normalized",
        ),
        ({"raw_data": {"jobId": "j-2", "encryptJobId": "enc-raw"}}, "enc-raw"),
        ({"jobId": "j-3", "encryptJobId": "enc-top"}, "enc-top"),
        ({"job_id": "j-4", "raw_data": {"jobId": "j-4"}}, None),
    ],
)
def test_extract_snapshot_encrypted_id_preserves_evidence_without_job_id_substitution(
    payload,
    expected,
):
    assert extract_snapshot_encrypted_job_id(payload) == expected


def test_snapshot_identity_error_is_separate_from_persisted_error_classification():
    valid = {
        "job_id": "j-1",
        "encrypted_job_id": "enc-1",
        "raw_data": {"jobId": "j-1", "encryptJobId": "enc-1"},
    }
    missing_encrypted = {"job_id": "j-1", "raw_data": {"jobId": "j-1"}}
    mismatched = {
        "job_id": "j-1",
        "encrypted_job_id": "enc-a",
        "raw_data": {"jobId": "j-1", "encryptJobId": "enc-b"},
    }

    assert extract_snapshot_identity_error(
        source_job_id="j-1", listing_payload=valid
    ) is None
    assert "Missing" in extract_snapshot_identity_error(
        source_job_id="j-1", listing_payload=missing_encrypted
    )
    assert "Conflicting encryptJobId" in extract_snapshot_identity_error(
        source_job_id="j-1", listing_payload=mismatched
    )
    assert extract_snapshot_encrypted_job_id(mismatched) is None

    persist_failure = SimpleNamespace(
        detail_status="failed",
        detail_error_message="persist_failure:RuntimeError",
    )
    assert classify_persisted_detail_error(persist_failure) == "persist_failure"
    assert "persist_failure" not in extract_snapshot_identity_error(
        source_job_id="j-1", listing_payload=missing_encrypted
    )


@pytest.mark.parametrize(
    ("status", "error_message", "expected"),
    [
        ("terminal_unavailable", "position unavailable", "terminal_unavailable"),
        ("identity_conflict", "reverse collision", "identity_conflict"),
        ("manual_action_required", "login required", "manual_action_required"),
        ("failed", "persist_failure:IntegrityError", "persist_failure"),
        ("failed", "upstream timeout", "retryable_failed"),
        ("pending", None, None),
    ],
)
def test_persisted_detail_error_classification_preserves_distinct_outcomes(
    status,
    error_message,
    expected,
):
    row = SimpleNamespace(
        detail_status=status,
        detail_error_message=error_message,
    )

    assert classify_persisted_detail_error(row) == expected


class _ReadOnlyQuery:
    def __init__(self, rows):
        self.rows = list(rows)
        self.filters: list[object] = []
        self.ordering: list[object] = []
        self.limits: list[int] = []

    def filter(self, *criteria):
        self.filters.extend(criteria)
        return self

    def order_by(self, *criteria):
        self.ordering.extend(criteria)
        return self

    def limit(self, limit):
        self.limits.append(limit)
        return self

    def all(self):
        return list(self.rows)

    def one_or_none(self):
        if len(self.rows) > 1:
            raise AssertionError("one_or_none received multiple fake rows")
        return self.rows[0] if self.rows else None


class _ReadOnlySession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.queries: list[tuple[object, _ReadOnlyQuery]] = []
        self.write_calls: list[str] = []

    def query(self, model):
        if not self.responses:
            raise AssertionError("unexpected extra repository query")
        query = _ReadOnlyQuery(self.responses.pop(0))
        self.queries.append((model, query))
        return query

    def _forbid_write(self, name):
        self.write_calls.append(name)
        raise AssertionError(f"read-only repository called Session.{name}")

    def add(self, *_args, **_kwargs):
        self._forbid_write("add")

    def flush(self, *_args, **_kwargs):
        self._forbid_write("flush")

    def commit(self, *_args, **_kwargs):
        self._forbid_write("commit")

    def delete(self, *_args, **_kwargs):
        self._forbid_write("delete")

    def execute(self, *_args, **_kwargs):
        self._forbid_write("execute")


def _criteria_text(query: _ReadOnlyQuery) -> str:
    return " ".join(str(value) for value in [*query.filters, *query.ordering])


def test_repository_maps_complete_staging_evidence_with_stable_read_only_query():
    created_at = datetime(2026, 7, 10, 1, tzinfo=UTC)
    updated_at = datetime(2026, 7, 10, 2, tzinfo=UTC)
    row = SimpleNamespace(
        id=uuid4(),
        source_job_id="j-1",
        detail_status="failed",
        published_job_id=None,
        crawl_job_id=uuid4(),
        detail_attempts=2,
        detail_started_at=created_at,
        updated_at=updated_at,
        listing_payload={
            "job_id": "j-1",
            "encrypted_job_id": "enc-1",
            "raw_data": {"jobId": "j-1", "encryptJobId": "enc-1"},
        },
        detail_error_message="persist_failure:RuntimeError",
        last_detail_crawl_job_id=uuid4(),
        detail_payload={},
    )
    db = _ReadOnlySession([row])

    snapshots = OfferTodayResearchRepository().list_staged_snapshots(db)

    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.row_id == str(row.id)
    assert snapshot.source_job_id == "j-1"
    assert snapshot.detail_attempts == 2
    assert snapshot.detail_started_at == created_at.isoformat()
    assert snapshot.updated_at == updated_at.isoformat()
    assert snapshot.encrypted_job_id == "enc-1"
    assert snapshot.identity_error is None
    assert snapshot.detail_error_classification == "persist_failure"
    assert snapshot.last_detail_crawl_job_id == str(row.last_detail_crawl_job_id)
    assert snapshot.has_detail_payload is True
    model, query = db.queries[0]
    assert model is CrawlJobListing
    assert "crawl_job_listings.source_site" in _criteria_text(query)
    assert [str(value) for value in query.ordering] == [
        "crawl_job_listings.created_at ASC",
        "crawl_job_listings.id ASC",
    ]
    assert db.write_calls == []


def test_repository_published_events_and_crawl_job_helpers_are_read_only():
    repository = OfferTodayResearchRepository()

    published_row = SimpleNamespace(
        id=uuid4(),
        source_job_id="j-1",
        title="  Data Engineer  ",
        company_id=uuid4(),
        description="   ",
    )
    published_db = _ReadOnlySession([published_row])
    published = repository.list_published_snapshots(published_db)
    assert published == [
        PublishedJobSnapshot(str(published_row.id), "j-1", True, True, False)
    ]
    model, query = published_db.queries[0]
    assert model is Job
    assert "jobs.source_site" in _criteria_text(query)
    assert "jobs.is_deleted" in _criteria_text(query)
    assert published_db.write_calls == []

    events = [SimpleNamespace(sequence_no=1), SimpleNamespace(sequence_no=2)]
    event_db = _ReadOnlySession(events)
    assert repository.list_research_events(event_db, "crawl-1") == events
    model, query = event_db.queries[0]
    assert model is CrawlJobEvent
    assert "crawl_job_events.sequence_no ASC" in _criteria_text(query)
    assert event_db.write_calls == []

    crawl_job = SimpleNamespace(id="crawl-1")
    crawl_db = _ReadOnlySession([crawl_job])
    assert repository.get_crawl_job(crawl_db, "crawl-1") is crawl_job
    assert crawl_db.queries[0][0] is CrawlJob
    assert crawl_db.write_calls == []


def test_recent_crawl_job_snapshots_copy_json_and_timestamps_without_writes():
    started_at = datetime(2026, 7, 10, 3, tzinfo=UTC)
    completed_at = datetime(2026, 7, 10, 4, tzinfo=UTC)
    row = SimpleNamespace(
        id=uuid4(),
        status="completed",
        request_payload={"research": {"run_id": "research-1"}},
        metrics={"nested": {"pages": 3}},
        error_message=None,
        started_at=started_at,
        completed_at=completed_at,
    )
    db = _ReadOnlySession([row])

    snapshots = OfferTodayResearchRepository().list_recent_crawl_jobs(db, limit=7)

    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.crawl_job_id == str(row.id)
    assert snapshot.status == "completed"
    assert snapshot.started_at == started_at.isoformat()
    assert snapshot.completed_at == completed_at.isoformat()
    assert snapshot.request_payload == row.request_payload
    assert snapshot.metrics == row.metrics
    snapshot.request_payload["research"]["run_id"] = "mutated"
    snapshot.metrics["nested"]["pages"] = 99
    assert row.request_payload["research"]["run_id"] == "research-1"
    assert row.metrics["nested"]["pages"] == 3
    model, query = db.queries[0]
    assert model is CrawlJob
    assert "crawl_jobs.source_site" in _criteria_text(query)
    assert "crawl_jobs.created_at DESC" in _criteria_text(query)
    assert query.limits == [7]
    assert db.write_calls == []
