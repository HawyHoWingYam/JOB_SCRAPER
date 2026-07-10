from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.crawl_phases import DEFAULT_DETAIL_RETRY_STATUSES, SUPPORTED_DETAIL_STATUSES
from app.repositories.crawl_job_listing_repository import CrawlJobListingRepository
from app.repositories.job_repository import JobRepository
from app.services.crawl_job_runtime import CrawlJobRuntime, ListingBatchPersistResult


class _FakeSession:
    def __init__(self, trace: list[str] | None = None) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.trace = trace

    def commit(self) -> None:
        self.commits += 1
        if self.trace is not None:
            self.trace.append("commit")

    def rollback(self) -> None:
        self.rollbacks += 1
        if self.trace is not None:
            self.trace.append("rollback")

    def close(self) -> None:
        self.closed = True


@dataclass
class _FakeListing:
    id: str
    crawl_job_id: str
    source_site: str
    source_job_id: str
    source_url: str
    source_classification_id: str | None = None
    source_classification_name: str | None = None
    listing_payload: dict | None = field(default_factory=dict)
    detail_payload: dict | None = field(default_factory=dict)
    detail_status: str = "pending"
    last_detail_crawl_job_id: str | None = None
    published_job_id: str | None = None


class _FakeCrawlJobRepository:
    def __init__(self, *, trace: list[str] | None = None, fail_event: bool = False) -> None:
        self.jobs: dict[str, SimpleNamespace] = {}
        self.metric_patches: list[tuple[str, dict]] = []
        self.events: list[dict] = []
        self.trace = trace
        self.fail_event = fail_event

    def get_crawl_job_by_id(self, _db, crawl_job_id):
        return self.jobs.setdefault(crawl_job_id, SimpleNamespace(id=crawl_job_id, metrics={}))

    def merge_metrics(self, _db, *, crawl_job_id, metrics_patch, auto_commit=True):
        job = self.get_crawl_job_by_id(_db, crawl_job_id)
        merged = dict(job.metrics or {})
        merged.update(metrics_patch)
        job.metrics = merged
        self.metric_patches.append((str(crawl_job_id), dict(metrics_patch)))
        if self.trace is not None:
            self.trace.append("merge_metrics")
        return job

    def append_event(self, _db, **kwargs):
        if self.trace is not None:
            self.trace.append("append_event")
        if self.fail_event:
            raise RuntimeError("event write failed")
        self.events.append(dict(kwargs))
        return SimpleNamespace()


class _RecordingRuntimeRepository:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def record_runtime_event(self, _db, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace()


class _FakeCrawlJobListingRepository:
    def __init__(
        self,
        listings: list[_FakeListing] | None = None,
        *,
        trace: list[str] | None = None,
    ) -> None:
        self.listings: list[_FakeListing] = list(listings or [])
        self.trace = trace

    def acquire_offertoday_staging_lock(self, _db) -> None:
        if self.trace is not None:
            self.trace.append("lock")

    def list_existing_source_job_ids(
        self,
        _db,
        *,
        source_site,
        source_job_ids,
        exclude_crawl_job_id=None,
    ):
        if self.trace is not None:
            self.trace.append("staged_lookup")
        requested = set(source_job_ids)
        return {
            listing.source_job_id
            for listing in self.listings
            if listing.source_site == source_site
            and listing.source_job_id in requested
            and (
                exclude_crawl_job_id is None
                or listing.crawl_job_id != str(exclude_crawl_job_id)
            )
        }

    def get_max_listing_rank_for_crawl_job(self, _db, *, crawl_job_id, source_site=None) -> int:
        if self.trace is not None:
            self.trace.append("get_rank")
        relevant = [
            listing
            for listing in self.listings
            if listing.crawl_job_id == crawl_job_id
            and (source_site is None or listing.source_site == source_site)
        ]
        return len(relevant)

    def upsert_listing(
        self,
        _db,
        *,
        crawl_job_id,
        source_site,
        source_job_id,
        source_url,
        source_classification_id,
        source_classification_name,
        listing_page,
        listing_rank,
        listing_payload,
        auto_commit=True,
    ):
        existing = next(
            (
                listing
                for listing in self.listings
                if listing.crawl_job_id == str(crawl_job_id)
                and listing.source_site == source_site
                and listing.source_job_id == source_job_id
            ),
            None,
        )
        if existing is not None:
            existing.source_url = source_url
            existing.source_classification_id = source_classification_id
            existing.source_classification_name = source_classification_name
            existing.listing_payload = dict(listing_payload or {})
            if self.trace is not None:
                self.trace.append(f"upsert:{source_job_id}:updated")
            return existing, "updated"

        listing = _FakeListing(
            id=str(uuid4()),
            crawl_job_id=str(crawl_job_id),
            source_site=source_site,
            source_job_id=source_job_id,
            source_url=source_url,
            source_classification_id=source_classification_id,
            source_classification_name=source_classification_name,
            listing_payload=dict(listing_payload or {}),
        )
        self.listings.append(listing)
        if self.trace is not None:
            self.trace.append(f"upsert:{source_job_id}:created")
        return listing, "created"

    def count_detail_statuses(self, _db, *, source_site=None, source_listing_crawl_job_id=None, category_ids=None):
        counts: dict[str, int] = {}
        for listing in self.listings:
            if source_site is not None and listing.source_site != source_site:
                continue
            if source_listing_crawl_job_id is not None and listing.crawl_job_id != str(source_listing_crawl_job_id):
                continue
            counts[listing.detail_status] = counts.get(listing.detail_status, 0) + 1
        return counts

    def list_detail_candidates(
        self,
        _db,
        *,
        source_site,
        source_listing_crawl_job_id=None,
        category_ids=None,
        statuses=None,
        source_job_ids=None,
        limit=100,
        offset=0,
    ):
        normalized_statuses = set(statuses or ["pending", "failed", "manual_action_required"])
        rows = [
            listing
            for listing in self.listings
            if listing.source_site == source_site
            and (source_listing_crawl_job_id is None or listing.crawl_job_id == str(source_listing_crawl_job_id))
            and (source_job_ids is None or listing.source_job_id in set(source_job_ids))
            and (
                not category_ids
                or str(listing.source_classification_id) in {str(value) for value in category_ids}
            )
            and listing.detail_status in normalized_statuses
        ]
        return rows[offset : offset + limit]

    def mark_detail_completed(
        self,
        _db,
        *,
        listing_id,
        detail_crawl_job_id,
        detail_payload=None,
        published_job_id=None,
        auto_commit=True,
    ):
        listing = next(item for item in self.listings if item.id == listing_id)
        listing.detail_status = "completed"
        listing.last_detail_crawl_job_id = str(detail_crawl_job_id)
        listing.detail_payload = dict(detail_payload or {})
        listing.published_job_id = published_job_id
        return listing

    def count_detail_statuses_for_detail_crawl_job(self, _db, *, detail_crawl_job_id, source_site=None):
        counts: dict[str, int] = {}
        for listing in self.listings:
            if listing.last_detail_crawl_job_id != str(detail_crawl_job_id):
                continue
            if source_site is not None and listing.source_site != source_site:
                continue
            counts[listing.detail_status] = counts.get(listing.detail_status, 0) + 1
        return counts

    def defer_identity_conflicts(
        self,
        _db,
        *,
        source_site,
        source_job_ids,
        statuses,
        error_message,
        auto_commit=True,
    ) -> int:
        requested = set(source_job_ids)
        eligible = set(statuses)
        updated = 0
        for listing in self.listings:
            if (
                listing.source_site == source_site
                and listing.source_job_id in requested
                and listing.detail_status in eligible
            ):
                listing.detail_status = "identity_conflict"
                listing.detail_error_message = error_message
                updated += 1
        if self.trace is not None:
            self.trace.append("defer_conflicts")
        return updated


class _FakeJobRepository:
    def __init__(
        self,
        existing_jobs: dict[str, SimpleNamespace] | None = None,
        *,
        trace: list[str] | None = None,
        fail_lookup: bool = False,
    ) -> None:
        self.existing_jobs = dict(existing_jobs or {})
        self.trace = trace
        self.fail_lookup = fail_lookup
        self.raise_on_error_calls: list[bool] = []

    def list_existing_jobs_by_source_ids(
        self,
        _db,
        *,
        source_site,
        source_job_ids,
        raise_on_error=False,
    ):
        if self.trace is not None:
            self.trace.append("published_lookup")
        self.raise_on_error_calls.append(bool(raise_on_error))
        if self.fail_lookup:
            raise RuntimeError("published lookup failed")
        return {
            source_job_id: self.existing_jobs[source_job_id]
            for source_job_id in source_job_ids
            if source_job_id in self.existing_jobs
        }


def test_stage_listing_batch_updates_listing_metrics():
    session = _FakeSession()
    crawl_job_id = str(uuid4())
    crawl_job_repository = _FakeCrawlJobRepository()
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=crawl_job_repository,
        crawl_job_listing_repository=_FakeCrawlJobListingRepository(),
        job_repository=_FakeJobRepository(),
    )

    result = runtime.stage_listing_batch(
        crawl_job_id=crawl_job_id,
        source_site="jobsdb",
        payloads=[
            {
                "source_job_id": "job-1",
                "source_url": "https://hk.jobsdb.com/job/job-1",
                "listing_payload": {"id": "job-1"},
            },
            {
                "source_job_id": "job-2",
                "source_url": "https://hk.jobsdb.com/job/job-2",
                "listing_payload": {"id": "job-2"},
            },
        ],
        skip_existing=False,
    )

    assert result.rows_staged == 2
    assert result.job_ids_seen == 2
    assert crawl_job_repository.jobs[crawl_job_id].metrics["listings_staged"] == 2
    assert crawl_job_repository.jobs[crawl_job_id].metrics["detail_pending"] == 2
    assert session.commits == 1
    assert session.closed is True


def test_load_detail_targets_marks_skip_existing_rows_completed():
    session = _FakeSession()
    source_listing_crawl_job_id = str(uuid4())
    detail_crawl_job_id = str(uuid4())
    listing_existing = _FakeListing(
        id=str(uuid4()),
        crawl_job_id=source_listing_crawl_job_id,
        source_site="offertoday",
        source_job_id="job-1",
        source_url="https://www.offertoday.com/hk/job/job-1",
    )
    listing_pending = _FakeListing(
        id=str(uuid4()),
        crawl_job_id=source_listing_crawl_job_id,
        source_site="offertoday",
        source_job_id="job-2",
        source_url="https://www.offertoday.com/hk/job/job-2",
    )
    crawl_job_repository = _FakeCrawlJobRepository()
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=crawl_job_repository,
        crawl_job_listing_repository=_FakeCrawlJobListingRepository([listing_existing, listing_pending]),
        job_repository=_FakeJobRepository(
            {
                "job-1": SimpleNamespace(
                    id=str(uuid4()),
                    raw_data={"jobId": "job-1"},
                )
            }
        ),
    )

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={
            "source_listing_crawl_job_id": source_listing_crawl_job_id,
            "detail_limit": 10,
            "detail_statuses": ["pending", "manual_action_required"],
            "skip_existing": True,
        },
        detail_crawl_job_id=detail_crawl_job_id,
    )

    assert result.selected_rows == 2
    assert result.skipped_existing_rows == 1
    assert result.target_rows == 1
    assert len(result.targets) == 1
    assert result.targets[0]["source_job_id"] == "job-2"
    assert listing_existing.detail_status == "completed"
    assert crawl_job_repository.jobs[detail_crawl_job_id].metrics["detail_selected_rows"] == 2
    assert crawl_job_repository.jobs[detail_crawl_job_id].metrics["detail_target_rows"] == 1
    assert crawl_job_repository.jobs[detail_crawl_job_id].metrics["detail_skipped_existing_rows"] == 1


def test_mark_started_clears_completion_without_wiping_started_at_on_completion():
    session = _FakeSession()
    recording_repo = _RecordingRuntimeRepository()
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=recording_repo,
        crawl_job_listing_repository=_FakeCrawlJobListingRepository(),
        job_repository=_FakeJobRepository(),
    )

    runtime.mark_started(
        crawl_job_id="crawl-job-1",
        source_site="jobsdb",
        payload={"phase": 1},
    )
    runtime.mark_completed(
        crawl_job_id="crawl-job-1",
        source_site="jobsdb",
        payload={"phase": 1},
    )

    assert recording_repo.calls[0]["started_at"] is not None
    assert recording_repo.calls[0]["completed_at"] is None
    assert recording_repo.calls[0]["error_message"] is None
    assert recording_repo.calls[1]["started_at"] is not None


def _offertoday_stage_payload(
    source_job_id: str,
    *,
    encrypted_job_id: str | None = None,
    search_family: str = "it_category",
    category_id: str = "101",
    category_name: str = "Information Technology",
    keyword: str = "python",
    page: int = 1,
) -> dict:
    encrypted_id = encrypted_job_id or f"enc-{source_job_id}"
    return {
        "source_job_id": source_job_id,
        "source_url": f"https://www.offertoday.com/hk/job/{encrypted_id}",
        "source_classification_id": category_id,
        "source_classification_name": category_name,
        "listing_page": page,
        "listing_payload": {
            "job_id": source_job_id,
            "encrypted_job_id": encrypted_id,
            "raw_data": {
                "jobId": source_job_id,
                "encryptJobId": encrypted_id,
            },
        },
        "search_family": search_family,
        "category_id": category_id,
        "category_name": category_name,
        "keyword": keyword,
        "page": page,
    }


def test_listing_batch_result_reports_true_created_rows_with_compatibility_alias():
    result = ListingBatchPersistResult(
        rows_created=1,
        created_source_job_ids=("new-1",),
        preexisting_staged_source_job_ids=("staged-1",),
        published_source_job_ids=("published-1",),
        job_ids_seen=3,
        skipped_existing=2,
    )

    assert result.rows_created == 1
    assert result.rows_staged == 1
    assert result.created_source_job_ids == ("new-1",)
    assert result.preexisting_staged_source_job_ids == ("staged-1",)
    assert result.published_source_job_ids == ("published-1",)
    assert result.job_ids_seen == 3
    assert result.skipped_existing == 2


def test_offertoday_stage_batch_locks_then_partitions_global_canonical_ids_and_records_event():
    trace: list[str] = []
    session = _FakeSession(trace)
    crawl_job_id = "current-crawl"
    historical = _FakeListing(
        id="historical-row",
        crawl_job_id="historical-crawl",
        source_site="offertoday",
        source_job_id="staged-1",
        source_url="https://www.offertoday.com/hk/job/old-encrypted-id",
        listing_payload={"preserved": True},
    )
    listing_repository = _FakeCrawlJobListingRepository([historical], trace=trace)
    crawl_job_repository = _FakeCrawlJobRepository(trace=trace)
    job_repository = _FakeJobRepository(
        {"published-1": SimpleNamespace(id="job-row-1")},
        trace=trace,
    )
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=crawl_job_repository,
        crawl_job_listing_repository=listing_repository,
        job_repository=job_repository,
    )

    result = runtime.stage_listing_batch(
        crawl_job_id=crawl_job_id,
        source_site="offertoday",
        payloads=[
            _offertoday_stage_payload("published-1", page=1),
            _offertoday_stage_payload("staged-1", page=2),
            _offertoday_stage_payload("new-1", page=3),
            _offertoday_stage_payload("new-1", keyword="duplicate", page=4),
        ],
        skip_existing=False,
    )

    assert trace[:3] == ["lock", "published_lookup", "staged_lookup"]
    assert trace.count("lock") == 1
    assert trace.count("upsert:new-1:created") == 1
    assert trace[-3:] == ["merge_metrics", "append_event", "commit"]
    assert job_repository.raise_on_error_calls == [True]
    assert result == ListingBatchPersistResult(
        rows_created=1,
        created_source_job_ids=("new-1",),
        preexisting_staged_source_job_ids=("staged-1",),
        published_source_job_ids=("published-1",),
        job_ids_seen=3,
        skipped_existing=2,
    )
    assert historical.source_url.endswith("old-encrypted-id")
    assert historical.listing_payload == {"preserved": True}
    assert crawl_job_repository.events == [
        {
            "crawl_job_id": crawl_job_id,
            "event_type": "crawl.listing_observed",
            "payload": {
                "source_site": "offertoday",
                "source_job_ids": ["published-1", "staged-1", "new-1"],
                "observations": [
                    {
                        "source_job_id": "published-1",
                        "classification": "published",
                        "search_family": "it_category",
                        "category_id": "101",
                        "category_name": "Information Technology",
                        "keyword": "python",
                        "page": 1,
                    },
                    {
                        "source_job_id": "staged-1",
                        "classification": "preexisting_staged_unpublished",
                        "search_family": "it_category",
                        "category_id": "101",
                        "category_name": "Information Technology",
                        "keyword": "python",
                        "page": 2,
                    },
                    {
                        "source_job_id": "new-1",
                        "classification": "newly_staged",
                        "search_family": "it_category",
                        "category_id": "101",
                        "category_name": "Information Technology",
                        "keyword": "python",
                        "page": 3,
                    },
                ],
                "published_source_job_ids": ["published-1"],
                "preexisting_staged_source_job_ids": ["staged-1"],
                "created_source_job_ids": ["new-1"],
                "rows_created": 1,
                "job_ids_seen": 3,
                "skipped_existing": 2,
            },
            "emitted_by": "offertoday-crawl",
            "auto_commit": False,
        }
    ]


def test_offertoday_stage_batch_rolls_back_when_strict_published_lookup_fails():
    session = _FakeSession()
    job_repository = _FakeJobRepository(fail_lookup=True)
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=_FakeCrawlJobRepository(),
        crawl_job_listing_repository=_FakeCrawlJobListingRepository(),
        job_repository=job_repository,
    )

    with pytest.raises(RuntimeError, match="published lookup failed"):
        runtime.stage_listing_batch(
            crawl_job_id="crawl-1",
            source_site="offertoday",
            payloads=[_offertoday_stage_payload("job-1")],
            skip_existing=False,
        )

    assert job_repository.raise_on_error_calls == [True]
    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closed is True


def test_offertoday_stage_batch_rolls_back_when_transactional_event_fails():
    session = _FakeSession()
    listing_repository = _FakeCrawlJobListingRepository()
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=_FakeCrawlJobRepository(fail_event=True),
        crawl_job_listing_repository=listing_repository,
        job_repository=_FakeJobRepository(),
    )

    with pytest.raises(RuntimeError, match="event write failed"):
        runtime.stage_listing_batch(
            crawl_job_id="crawl-1",
            source_site="offertoday",
            payloads=[_offertoday_stage_payload("job-1")],
            skip_existing=True,
        )

    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.parametrize("source_site", ["jobsdb", "ctgoodjobs"])
def test_non_offertoday_staging_keeps_batch_scoped_upsert_behavior(source_site):
    session = _FakeSession()
    historical = _FakeListing(
        id="historical-row",
        crawl_job_id="historical-crawl",
        source_site=source_site,
        source_job_id="shared-id",
        source_url="https://example.test/old",
    )
    listing_repository = _FakeCrawlJobListingRepository([historical])
    crawl_job_repository = _FakeCrawlJobRepository()
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=crawl_job_repository,
        crawl_job_listing_repository=listing_repository,
        job_repository=_FakeJobRepository(),
    )

    result = runtime.stage_listing_batch(
        crawl_job_id="current-crawl",
        source_site=source_site,
        payloads=[
            {
                "source_job_id": "shared-id",
                "source_url": "https://example.test/new",
                "listing_payload": {"id": "shared-id"},
            }
        ],
        skip_existing=False,
    )

    assert result.rows_created == 1
    assert result.created_source_job_ids == ("shared-id",)
    assert result.preexisting_staged_source_job_ids == ()
    assert len(listing_repository.listings) == 2
    assert crawl_job_repository.events == []


class _DialectSession:
    def __init__(self, dialect_name: str) -> None:
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))
        self.statements = []

    def get_bind(self):
        return self.bind

    def execute(self, statement):
        self.statements.append(statement)


def test_offertoday_advisory_lock_uses_transaction_scoped_postgresql_expression():
    repository = CrawlJobListingRepository()
    postgres_session = _DialectSession("postgresql")
    sqlite_session = _DialectSession("sqlite")

    repository.acquire_offertoday_staging_lock(postgres_session)
    repository.acquire_offertoday_staging_lock(sqlite_session)

    assert len(postgres_session.statements) == 1
    statement = postgres_session.statements[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert str(compiled) == (
        "SELECT pg_advisory_xact_lock(hashtext(%(hashtext_1)s)) "
        "AS pg_advisory_xact_lock_1"
    )
    assert compiled.params == {"hashtext_1": "job_scraper:offertoday:staging"}
    assert sqlite_session.statements == []


class _ExplodingJobQuerySession:
    def query(self, _model):
        raise RuntimeError("database unavailable")


def test_published_lookup_is_fail_soft_by_default_and_strict_when_requested():
    repository = JobRepository()
    session = _ExplodingJobQuerySession()

    assert repository.list_existing_jobs_by_source_ids(
        session,
        source_site="offertoday",
        source_job_ids=["job-1"],
    ) == {}
    with pytest.raises(RuntimeError, match="database unavailable"):
        repository.list_existing_jobs_by_source_ids(
            session,
            source_site="offertoday",
            source_job_ids=["job-1"],
            raise_on_error=True,
        )


def test_load_detail_targets_with_source_job_ids_is_global_and_ignores_batch_scope():
    session = _FakeSession()
    listings = [
        _FakeListing(
            id="row-1",
            crawl_job_id="batch-1",
            source_site="offertoday",
            source_job_id="job-1",
            source_url="https://example.test/job-1",
        ),
        _FakeListing(
            id="row-2",
            crawl_job_id="batch-2",
            source_site="offertoday",
            source_job_id="job-2",
            source_url="https://example.test/job-2",
            source_classification_id="118999",
        ),
    ]
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=_FakeCrawlJobRepository(),
        crawl_job_listing_repository=_FakeCrawlJobListingRepository(listings),
        job_repository=_FakeJobRepository(),
    )

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={
            "source_listing_crawl_job_id": "batch-1",
            "source_job_ids": ["job-2"],
            "category_ids": [118000],
            "detail_limit": 1,
        },
        detail_crawl_job_id="detail-1",
    )

    assert [target["listing_id"] for target in result.targets] == ["row-2"]


def test_load_detail_targets_with_explicit_empty_source_job_ids_loads_nothing():
    session = _FakeSession()
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=_FakeCrawlJobRepository(),
        crawl_job_listing_repository=_FakeCrawlJobListingRepository(
            [
                _FakeListing(
                    id="row-1",
                    crawl_job_id="batch-1",
                    source_site="offertoday",
                    source_job_id="job-1",
                    source_url="https://example.test/job-1",
                )
            ]
        ),
        job_repository=_FakeJobRepository(),
    )

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={
            "source_listing_crawl_job_id": "batch-1",
            "source_job_ids": [],
            "detail_limit": 0,
        },
        detail_crawl_job_id="detail-1",
    )

    assert result.selected_rows == 0
    assert result.target_rows == 0
    assert result.targets == []


def test_load_detail_targets_without_source_job_ids_preserves_batch_scope_for_other_sources():
    session = _FakeSession()
    listings = [
        _FakeListing(
            id="jobsdb-row-1",
            crawl_job_id="batch-1",
            source_site="jobsdb",
            source_job_id="job-1",
            source_url="https://example.test/job-1",
        ),
        _FakeListing(
            id="jobsdb-row-2",
            crawl_job_id="batch-2",
            source_site="jobsdb",
            source_job_id="job-2",
            source_url="https://example.test/job-2",
        ),
    ]
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=_FakeCrawlJobRepository(),
        crawl_job_listing_repository=_FakeCrawlJobListingRepository(listings),
        job_repository=_FakeJobRepository(),
    )

    result = runtime.load_detail_targets(
        source_site="jobsdb",
        request_payload={
            "source_listing_crawl_job_id": "batch-1",
            "detail_limit": 10,
        },
        detail_crawl_job_id="detail-1",
    )

    assert [target["listing_id"] for target in result.targets] == ["jobsdb-row-1"]


def test_identity_conflict_status_is_supported_but_not_retried_by_default():
    assert "identity_conflict" in SUPPORTED_DETAIL_STATUSES
    assert "identity_conflict" not in DEFAULT_DETAIL_RETRY_STATUSES


def test_defer_listing_identity_conflict_updates_only_retryable_rows_and_records_sanitized_event():
    trace: list[str] = []
    session = _FakeSession(trace)
    listings = [
        _FakeListing(
            id=f"row-{index}",
            crawl_job_id=f"batch-{index}",
            source_site="offertoday",
            source_job_id="job-1",
            source_url="https://example.test/job-1",
            detail_status=status,
        )
        for index, status in enumerate(
            ["pending", "failed", "manual_action_required", "completed", "skipped"],
            start=1,
        )
    ]
    crawl_job_repository = _FakeCrawlJobRepository(trace=trace)
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=crawl_job_repository,
        crawl_job_listing_repository=_FakeCrawlJobListingRepository(listings, trace=trace),
        job_repository=_FakeJobRepository(),
    )

    updated = runtime.defer_listing_identity_conflict(
        crawl_job_id="current-crawl",
        source_job_ids=[" job-1 ", "job-1", ""],
        encrypted_job_ids=[" enc-1 ", "enc-1", ""],
        reason=" one_encrypted_id_to_multiple_job_ids ",
    )

    assert updated == 3
    assert [listing.detail_status for listing in listings] == [
        "identity_conflict",
        "identity_conflict",
        "identity_conflict",
        "completed",
        "skipped",
    ]
    assert trace == ["lock", "defer_conflicts", "append_event", "commit"]
    assert crawl_job_repository.events == [
        {
            "crawl_job_id": "current-crawl",
            "event_type": "crawl.listing_identity_conflict",
            "payload": {
                "source_site": "offertoday",
                "source_job_ids": ["job-1"],
                "encrypted_job_ids": ["enc-1"],
                "reason": "one_encrypted_id_to_multiple_job_ids",
                "rows_deferred": 3,
            },
            "emitted_by": "offertoday-crawl",
            "auto_commit": False,
        }
    ]


def test_defer_listing_identity_conflict_rolls_back_event_failure():
    session = _FakeSession()
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=_FakeCrawlJobRepository(fail_event=True),
        crawl_job_listing_repository=_FakeCrawlJobListingRepository(),
        job_repository=_FakeJobRepository(),
    )

    with pytest.raises(RuntimeError, match="event write failed"):
        runtime.defer_listing_identity_conflict(
            crawl_job_id="current-crawl",
            source_job_ids=["job-1"],
            encrypted_job_ids=["enc-1"],
            reason="id_mismatch",
        )

    assert session.commits == 0
    assert session.rollbacks == 1
