from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.repositories import offertoday_research_repository as research_repository
from app.models.crawl_job import CrawlJob, CrawlJobEvent
from app.models.crawl_job_listing import CrawlJobListing
from app.models.company import Company
from app.models.job import Job
from app.repositories.offertoday_research_repository import (
    OfferTodayResearchRepository,
    classify_persisted_detail_error,
    extract_snapshot_identity_error,
)
from app.sources.offertoday.research.baseline import (
    build_baseline_snapshot as _build_baseline_snapshot,
    build_run_start_inventory,
)
from app.sources.offertoday.research.contracts import (
    ProductDataSnapshot,
    PublishedJobSnapshot,
    StagedListingSnapshot,
)


_UNSET = object()


def _listing(
    row_id: str,
    source_job_id: str,
    detail_status: str,
    published_job_id: str | None,
    crawl_job_id: str,
    **changes,
) -> SimpleNamespace:
    identity_error_classification = changes.get(
        "identity_error_classification"
    )
    encrypted_job_id = changes.pop("encrypted_job_id", _UNSET)
    encrypted_job_id_source = changes.pop(
        "encrypted_job_id_source",
        _UNSET,
    )
    observed_encrypted_job_id = changes.pop(
        "observed_encrypted_job_id",
        _UNSET,
    )
    if encrypted_job_id is _UNSET:
        encrypted_job_id = (
            None if identity_error_classification else source_job_id.strip()
        )
    if encrypted_job_id_source is _UNSET:
        canonical_source_job_id = source_job_id.strip()
        canonical_route_id = (
            encrypted_job_id.strip()
            if isinstance(encrypted_job_id, str)
            else None
        )
        if identity_error_classification or not canonical_route_id:
            encrypted_job_id_source = None
        elif canonical_route_id == canonical_source_job_id:
            encrypted_job_id_source = "jobId_fallback"
        else:
            encrypted_job_id_source = "encryptJobId"
    if observed_encrypted_job_id is _UNSET:
        observed_encrypted_job_id = (
            encrypted_job_id
            if encrypted_job_id_source == "encryptJobId"
            else None
        )
    values = {
        "detail_attempts": 0,
        "detail_started_at": None,
        "updated_at": None,
        "identity_error": None,
        "identity_error_classification": None,
        "detail_error_classification": None,
        "last_detail_crawl_job_id": None,
        "has_detail_payload": False,
        **changes,
    }
    return SimpleNamespace(
        row_id=row_id,
        source_job_id=source_job_id,
        detail_status=detail_status,
        published_job_id=published_job_id,
        crawl_job_id=crawl_job_id,
        encrypted_job_id=encrypted_job_id,
        encrypted_job_id_source=encrypted_job_id_source,
        observed_encrypted_job_id=observed_encrypted_job_id,
        **values,
    )


def _product_data_snapshot(
    *,
    staged_rows_hash: str = "a" * 64,
    published_jobs_hash: str = "b" * 64,
    companies_hash: str = "c" * 64,
) -> ProductDataSnapshot:
    return ProductDataSnapshot.from_table_hashes(
        staged_rows_hash=staged_rows_hash,
        published_jobs_hash=published_jobs_hash,
        companies_hash=companies_hash,
    )


def build_baseline_snapshot(
    *,
    listings: list[StagedListingSnapshot],
    jobs: list[PublishedJobSnapshot],
    product_data: ProductDataSnapshot | None = None,
):
    return _build_baseline_snapshot(
        listings=listings,
        jobs=jobs,
        product_data=product_data or _product_data_snapshot(),
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


def test_baseline_data_hash_binds_full_product_content_hashes() -> None:
    listings = [_listing("row-1", "j-1", "completed", "job-1", "run-1")]
    jobs = [PublishedJobSnapshot("job-1", "j-1", True, True, True)]

    first = build_baseline_snapshot(
        listings=listings,
        jobs=jobs,
        product_data=_product_data_snapshot(),
    )
    changed = build_baseline_snapshot(
        listings=listings,
        jobs=jobs,
        product_data=_product_data_snapshot(published_jobs_hash="d" * 64),
    )

    assert first.staged_rows == changed.staged_rows
    assert first.published_jobs == changed.published_jobs
    assert first.data_hash != changed.data_hash


def test_baseline_canonicalizes_nonblank_source_ids_and_accounts_invalid_rows():
    listings = [
        _listing("row-1", "j-1", "pending", None, "run-1"),
        _listing("row-2", " j-1 ", "failed", None, "run-2"),
        _listing(
            "row-3",
            "   ",
            "pending",
            None,
            "run-3",
            encrypted_job_id="enc-1",
        ),
    ]

    snapshot = build_baseline_snapshot(listings=listings, jobs=[])
    reordered = build_baseline_snapshot(
        listings=list(reversed(listings)),
        jobs=[],
    )
    inventory = build_run_start_inventory(listings=listings, jobs=[])

    assert snapshot.staged_rows == 3
    assert snapshot.distinct_staged_ids == 1
    assert snapshot.invalid_source_job_id_rows == 1
    assert snapshot.duplicate_staging_rows == 1
    assert snapshot.distinct_pending_ids == 1
    assert snapshot.identity_mapping_conflict_ids == ()
    assert snapshot.data_hash == reordered.data_hash
    assert inventory.staged_unpublished_job_ids == ("j-1",)


def test_baseline_counts_whitespace_encrypted_id_as_missing_in_canonical_hash():
    listings = [
        _listing(
            "row-1",
            "j-1",
            "pending",
            None,
            "run-1",
            encrypted_job_id="   ",
        ),
        _listing(
            "row-2",
            "j-2",
            "pending",
            None,
            "run-1",
            encrypted_job_id="enc-2",
        ),
    ]

    snapshot = build_baseline_snapshot(listings=listings, jobs=[])
    reordered = build_baseline_snapshot(
        listings=list(reversed(listings)),
        jobs=[],
    )
    changed = build_baseline_snapshot(
        listings=[
            _listing(
                "row-1",
                "j-1",
                "pending",
                None,
                "run-1",
                encrypted_job_id="enc-1",
            ),
            listings[1],
        ],
        jobs=[],
    )

    assert snapshot.missing_encrypted_job_id_rows == 1
    assert snapshot.data_hash == reordered.data_hash
    assert changed.missing_encrypted_job_id_rows == 0
    assert snapshot.data_hash != changed.data_hash


def test_baseline_separates_job_id_fallback_from_observed_encrypted_identity():
    snapshot = build_baseline_snapshot(
        listings=[_listing("row-1", "j-1", "pending", None, "run-1")],
        jobs=[],
    )

    assert snapshot.missing_encrypted_job_id_rows == 1
    assert snapshot.observed_encrypted_job_id_rows == 0
    assert snapshot.job_id_fallback_rows == 1
    assert snapshot.unusable_identity_rows == 0
    assert snapshot.identity_mapping_conflict_ids == ()
    assert snapshot.identity_evidence_conflict_ids == ()
    assert snapshot.identity_error_classifications == {}


def test_baseline_promotes_explicit_identity_over_job_id_fallback_without_conflict():
    snapshot = build_baseline_snapshot(
        listings=[
            _listing("fallback", "j-1", "pending", None, "run-1"),
            _listing(
                "explicit",
                "j-1",
                "pending",
                None,
                "run-2",
                encrypted_job_id="enc-1",
            ),
        ],
        jobs=[],
    )

    assert snapshot.missing_encrypted_job_id_rows == 1
    assert snapshot.observed_encrypted_job_id_rows == 1
    assert snapshot.job_id_fallback_rows == 1
    assert snapshot.unusable_identity_rows == 0
    assert snapshot.identity_mapping_conflict_ids == ()


def test_baseline_rejects_two_explicit_routes_for_one_job_id():
    snapshot = build_baseline_snapshot(
        listings=[
            _listing(
                "first",
                "j-1",
                "pending",
                None,
                "run-1",
                encrypted_job_id="enc-a",
            ),
            _listing(
                "second",
                "j-1",
                "pending",
                None,
                "run-2",
                encrypted_job_id="enc-b",
            ),
        ],
        jobs=[],
    )

    assert snapshot.identity_mapping_conflict_ids == ("j-1",)


def test_baseline_rejects_authoritative_route_shared_by_two_job_ids():
    snapshot = build_baseline_snapshot(
        listings=[
            _listing(
                "first",
                "j-1",
                "pending",
                None,
                "run-1",
                encrypted_job_id="enc-shared",
            ),
            _listing(
                "second",
                "j-2",
                "pending",
                None,
                "run-1",
                encrypted_job_id="enc-shared",
            ),
        ],
        jobs=[],
    )

    assert snapshot.identity_mapping_conflict_ids == ("j-1", "j-2")


def test_baseline_treats_declared_source_conflict_as_evidence_conflict():
    snapshot = build_baseline_snapshot(
        listings=[
            _listing(
                "row-1",
                "j-1",
                "pending",
                None,
                "run-1",
                identity_error_classification=(
                    "encrypted_job_id_source_conflict"
                ),
            )
        ],
        jobs=[],
    )

    assert snapshot.identity_evidence_conflict_ids == ("j-1",)
    assert snapshot.identity_mapping_conflict_ids == ("j-1",)
    assert snapshot.unusable_identity_rows == 1


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
        ({"job_id": "j-4", "encrypted_job_id": "enc-normalized"}, None),
        ({"job_id": "j-4", "raw_data": {"jobId": "j-4"}}, None),
    ],
)
def test_extract_snapshot_observed_encrypted_id_uses_only_upstream_evidence(
    payload,
    expected,
):
    assert (
        research_repository.extract_snapshot_observed_encrypted_job_id(payload)
        == expected
    )


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
    assert extract_snapshot_identity_error(
        source_job_id="j-1", listing_payload=missing_encrypted
    ) is None
    assert "Conflicting encryptJobId" in extract_snapshot_identity_error(
        source_job_id="j-1", listing_payload=mismatched
    )
    assert (
        research_repository.extract_snapshot_observed_encrypted_job_id(
            mismatched
        )
        == "enc-b"
    )

    persist_failure = SimpleNamespace(
        detail_status="failed",
        detail_error_message="persist_failure:RuntimeError",
    )
    assert classify_persisted_detail_error(persist_failure) == "persist_failure"
    assert extract_snapshot_identity_error(
        source_job_id="j-1", listing_payload=missing_encrypted
    ) is None


def test_structured_identity_errors_distinguish_alias_conflict_from_missing():
    alias_conflict = {
        "job_id": "j-1",
        "encrypted_job_id": "enc-a",
        "raw_data": {"jobId": "j-1", "encryptJobId": "enc-b"},
    }
    missing_encrypted = {
        "job_id": "j-2",
        "raw_data": {"jobId": "j-2"},
    }

    conflict_classification = research_repository.classify_snapshot_identity_error(
        source_job_id="j-1",
        listing_payload=alias_conflict,
    )
    missing_classification = research_repository.classify_snapshot_identity_error(
        source_job_id="j-2",
        listing_payload=missing_encrypted,
    )

    assert conflict_classification == "encrypted_job_id_alias_conflict"
    assert missing_classification is None

    snapshot = build_baseline_snapshot(
        listings=[
            _listing(
                "row-1",
                "j-1",
                "pending",
                None,
                "run-1",
                identity_error_classification=conflict_classification,
            ),
            _listing(
                "row-2",
                "j-2",
                "pending",
                None,
                "run-1",
                identity_error_classification=missing_classification,
            ),
        ],
        jobs=[],
    )

    assert snapshot.identity_evidence_conflict_ids == ("j-1",)
    assert snapshot.identity_mapping_conflict_ids == ("j-1",)
    assert snapshot.identity_error_classifications == {
        "encrypted_job_id_alias_conflict": 1,
    }


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
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    def query(self, *entities):
        if not self.responses:
            raise AssertionError("unexpected extra repository query")
        query = _ReadOnlyQuery(self.responses.pop(0))
        selected = entities[0] if len(entities) == 1 else entities
        self.queries.append((selected, query))
        return query

    def get_bind(self):
        return self.bind

    @property
    def no_autoflush(self):
        return nullcontext()

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
        has_detail_payload=True,
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
    assert snapshot.encrypted_job_id_source == "encryptJobId"
    assert snapshot.observed_encrypted_job_id == "enc-1"
    assert snapshot.identity_error is None
    assert snapshot.detail_error_classification == "persist_failure"
    assert snapshot.last_detail_crawl_job_id == str(row.last_detail_crawl_job_id)
    assert snapshot.has_detail_payload is True
    model, query = db.queries[0]
    assert tuple(str(entity) for entity in model[:-1]) == (
        "CrawlJobListing.id",
        "CrawlJobListing.source_job_id",
        "CrawlJobListing.detail_status",
        "CrawlJobListing.published_job_id",
        "CrawlJobListing.crawl_job_id",
        "CrawlJobListing.detail_attempts",
        "CrawlJobListing.detail_started_at",
        "CrawlJobListing.updated_at",
        "CrawlJobListing.listing_payload",
        "CrawlJobListing.detail_error_message",
        "CrawlJobListing.last_detail_crawl_job_id",
    )
    assert model[-1].name == "has_detail_payload"
    assert "crawl_job_listings.source_site" in _criteria_text(query)
    assert [str(value) for value in query.ordering] == [
        "crawl_job_listings.created_at ASC",
        "crawl_job_listings.id ASC",
    ]
    assert db.write_calls == []


def test_repository_snapshot_resolves_job_only_payload_as_usable_fallback():
    row = SimpleNamespace(
        id=uuid4(),
        source_job_id="j-1",
        detail_status="pending",
        published_job_id=None,
        crawl_job_id=uuid4(),
        detail_attempts=0,
        detail_started_at=None,
        updated_at=None,
        listing_payload={
            "job_id": "j-1",
            "raw_data": {"jobId": "j-1"},
        },
        detail_error_message=None,
        last_detail_crawl_job_id=None,
        has_detail_payload=False,
    )
    db = _ReadOnlySession([row])

    snapshot = OfferTodayResearchRepository().list_staged_snapshots(db)[0]
    baseline = build_baseline_snapshot(listings=[snapshot], jobs=[])

    assert snapshot.encrypted_job_id == "j-1"
    assert snapshot.encrypted_job_id_source == "jobId_fallback"
    assert snapshot.observed_encrypted_job_id is None
    assert snapshot.identity_error is None
    assert snapshot.identity_error_classification is None
    assert baseline.missing_encrypted_job_id_rows == 1
    assert baseline.observed_encrypted_job_id_rows == 0
    assert baseline.job_id_fallback_rows == 1
    assert baseline.unusable_identity_rows == 0
    assert baseline.identity_mapping_conflict_ids == ()
    assert db.write_calls == []


def test_snapshot_projection_retains_observation_when_normalized_alias_conflicts():
    projection = research_repository._project_snapshot_identity(
        source_job_id="j-1",
        listing_payload={
            "job_id": "j-1",
            "encrypted_job_id": "enc-normalized",
            "raw_data": {"jobId": "j-1", "encryptJobId": "enc-raw"},
        },
    )

    assert projection.encrypted_job_id is None
    assert projection.encrypted_job_id_source is None
    assert projection.observed_encrypted_job_id == "enc-raw"
    assert projection.identity_error is not None
    assert (
        projection.identity_error_classification
        == "encrypted_job_id_alias_conflict"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"job_id": "j-1", "raw_data": {"jobId": "j-1"}},
        {
            "job_id": "j-1",
            "encrypted_job_id": "enc-normalized",
            "raw_data": {"jobId": "j-1", "encryptJobId": "enc-raw"},
        },
    ],
    ids=["success", "identity-error"],
)
def test_snapshot_projection_calls_shared_resolver_exactly_once(
    monkeypatch,
    payload,
):
    calls = 0
    original = research_repository.resolve_offertoday_detail_identity

    def counted_resolver(**kwargs):
        nonlocal calls
        calls += 1
        return original(**kwargs)

    monkeypatch.setattr(
        research_repository,
        "resolve_offertoday_detail_identity",
        counted_resolver,
    )

    research_repository._project_snapshot_identity(
        source_job_id="j-1",
        listing_payload=payload,
    )

    assert calls == 1


def test_staged_snapshot_query_projects_json_object_flag_without_detail_body():
    engine = create_engine("sqlite://")
    CrawlJobListing.__table__.create(engine)
    created_at = datetime(2026, 7, 10, 1, tzinfo=UTC)
    payloads = [
        {"jobId": "j-object", "encryptJobId": "enc-object"},
        {"jobId": "j-null", "encryptJobId": "enc-null"},
        {"jobId": "j-array", "encryptJobId": "enc-array"},
        {"jobId": "j-scalar", "encryptJobId": "enc-scalar"},
    ]
    rows = [
        CrawlJobListing(
            id=uuid4(),
            crawl_job_id=uuid4(),
            source_site="offertoday",
            source_job_id=source_job_id,
            source_url=f"https://example.test/{source_job_id}",
            listing_payload=listing_payload,
            detail_payload=detail_payload,
            detail_status=("failed" if index == 0 else "pending"),
            detail_attempts=index,
            detail_error_message=(
                "persist_failure:RuntimeError" if index == 0 else None
            ),
            created_at=created_at.replace(minute=index),
            updated_at=created_at.replace(minute=index + 10),
        )
        for index, (source_job_id, listing_payload, detail_payload) in enumerate(
            zip(
                ("j-object", "j-null", "j-array", "j-scalar"),
                payloads,
                ({"description": "body"}, None, ["array"], "scalar"),
                strict=True,
            )
        )
    ]
    statements: list[str] = []

    with Session(engine) as db:
        db.add_all(rows)
        db.commit()
        db.add(
            CrawlJobListing(
                id=uuid4(),
                crawl_job_id=uuid4(),
                source_site="offertoday",
                source_job_id="pending-write",
                source_url="https://example.test/pending-write",
                listing_payload={
                    "jobId": "pending-write",
                    "encryptJobId": "enc-pending",
                },
                detail_payload={"pending": True},
                detail_status="pending",
            )
        )
        event.listen(
            engine,
            "before_cursor_execute",
            lambda _conn, _cursor, statement, _parameters, _context, _many: (
                statements.append(statement)
            ),
        )

        snapshots = OfferTodayResearchRepository().list_staged_snapshots(db)

        assert len(db.new) == 1

    assert [snapshot.source_job_id for snapshot in snapshots] == [
        "j-object",
        "j-null",
        "j-array",
        "j-scalar",
    ]
    assert [snapshot.has_detail_payload for snapshot in snapshots] == [
        True,
        False,
        False,
        False,
    ]
    assert snapshots[0].encrypted_job_id == "enc-object"
    assert snapshots[0].identity_error is None
    assert snapshots[0].detail_attempts == 0
    assert snapshots[0].updated_at == created_at.replace(
        minute=10,
        tzinfo=None,
    ).isoformat()
    assert snapshots[0].detail_error_classification == "persist_failure"
    assert len(statements) == 1
    assert statements[0].lstrip().upper().startswith("SELECT")
    select_clause = statements[0].lower().split(" from ", maxsplit=1)[0]
    assert "crawl_job_listings.detail_payload as" not in select_clause
    assert "json_type(crawl_job_listings.detail_payload)" in select_clause
    engine.dispose()


def test_staged_snapshot_postgresql_projection_uses_json_typeof_object_check():
    expression = research_repository._detail_payload_is_object_expression(
        "postgresql"
    )

    compiled = str(
        expression.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()

    assert "json_typeof(crawl_job_listings.detail_payload) = 'object'" in compiled


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
    assert tuple(str(entity) for entity in model) == (
        "Job.id",
        "Job.source_job_id",
        "Job.title",
        "Job.company_id",
        "Job.description",
    )
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


def test_published_snapshot_query_projects_once_without_autoflush_or_deferred_loads():
    engine = create_engine("sqlite://")
    Job.__table__.create(engine)
    company_id = uuid4()
    committed_rows = [
        Job(
            id=uuid4(),
            job_id=f"offertoday:{source_job_id}",
            source_site="offertoday",
            source_job_id=source_job_id,
            company_id=company_id,
            title=title,
            description=description,
            raw_data={"large": "payload"},
            ai_summary="must not be selected",
            is_deleted=False,
        )
        for source_job_id, title, description in (
            ("j-1", "Data Engineer", "Complete description"),
            ("j-2", "Platform Engineer", "Another description"),
        )
    ]
    statements: list[str] = []

    with Session(engine) as db:
        db.add_all(committed_rows)
        db.commit()
        db.add(
            Job(
                id=uuid4(),
                job_id="offertoday:pending",
                source_site="offertoday",
                source_job_id="pending",
                company_id=company_id,
                title="Pending write",
                description="Must remain pending",
                is_deleted=False,
            )
        )

        event.listen(
            engine,
            "before_cursor_execute",
            lambda _conn, _cursor, statement, _parameters, _context, _many: (
                statements.append(statement)
            ),
        )
        snapshots = OfferTodayResearchRepository().list_published_snapshots(db)

        assert [snapshot.source_job_id for snapshot in snapshots] == ["j-1", "j-2"]
        assert len(db.new) == 1

    assert len(statements) == 1
    assert statements[0].lstrip().upper().startswith("SELECT")
    selected_sql = statements[0].lower()
    assert "jobs.raw_data" not in selected_sql
    assert "jobs.ai_summary" not in selected_sql
    assert "jobs.search_vector" not in selected_sql
    assert all(
        column in selected_sql
        for column in (
            "jobs.id",
            "jobs.source_job_id",
            "jobs.title",
            "jobs.company_id",
            "jobs.description",
        )
    )
    engine.dispose()


def test_product_data_snapshot_detects_same_identity_content_mutations() -> None:
    engine = create_engine("sqlite://")
    Company.__table__.create(engine)
    Job.__table__.create(engine)
    CrawlJobListing.__table__.create(engine)
    company_id = uuid4()
    job_id = uuid4()
    listing_id = uuid4()
    crawl_job_id = uuid4()

    with Session(engine) as db:
        db.add_all(
            [
                Company(
                    id=company_id,
                    company_id="offertoday:company-1",
                    source_site="offertoday",
                    source_company_id="company-1",
                    name="Company One",
                    extra_data={"profile": "original"},
                    is_deleted=False,
                ),
                Job(
                    id=job_id,
                    job_id="offertoday:j-1",
                    source_site="offertoday",
                    source_job_id="j-1",
                    company_id=company_id,
                    title="Original title",
                    description="Original description",
                    raw_data={"jobId": "j-1", "detail": "original"},
                    is_deleted=False,
                ),
                CrawlJobListing(
                    id=listing_id,
                    crawl_job_id=crawl_job_id,
                    source_site="offertoday",
                    source_job_id="j-1",
                    source_url="https://www.offertoday.com/hk/job/j-1",
                    listing_payload={"jobId": "j-1", "title": "Original title"},
                    detail_payload={"jobId": "j-1", "description": "Original"},
                    detail_status="completed",
                    published_job_id=job_id,
                ),
            ]
        )
        db.commit()
        repository = OfferTodayResearchRepository()
        first = repository.capture_product_data_snapshot(db)

        db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(title="Changed title")
        )
        db.commit()
        job_changed = repository.capture_product_data_snapshot(db)
        assert job_changed.staged_rows_hash == first.staged_rows_hash
        assert job_changed.published_jobs_hash != first.published_jobs_hash
        assert job_changed.companies_hash == first.companies_hash
        assert job_changed.data_hash != first.data_hash

        db.execute(
            update(Company)
            .where(Company.id == company_id)
            .values(name="Changed company")
        )
        db.commit()
        company_changed = repository.capture_product_data_snapshot(db)
        assert company_changed.staged_rows_hash == job_changed.staged_rows_hash
        assert company_changed.published_jobs_hash == job_changed.published_jobs_hash
        assert company_changed.companies_hash != job_changed.companies_hash
        assert company_changed.data_hash != job_changed.data_hash

        db.execute(
            update(CrawlJobListing)
            .where(CrawlJobListing.id == listing_id)
            .values(listing_payload={"jobId": "j-1", "title": "Changed title"})
        )
        db.commit()
        staging_changed = repository.capture_product_data_snapshot(db)
        assert staging_changed.staged_rows_hash != company_changed.staged_rows_hash
        assert staging_changed.published_jobs_hash == company_changed.published_jobs_hash
        assert staging_changed.companies_hash == company_changed.companies_hash
        assert staging_changed.data_hash != company_changed.data_hash

    engine.dispose()


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
    assert "crawl_jobs.id DESC" in _criteria_text(query)
    assert query.limits == [7]
    assert db.write_calls == []
