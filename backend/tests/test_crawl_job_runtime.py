from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import uuid4

from app.services.crawl_job_runtime import CrawlJobRuntime


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1

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
    def __init__(self) -> None:
        self.jobs: dict[str, SimpleNamespace] = {}
        self.metric_patches: list[tuple[str, dict]] = []

    def get_crawl_job_by_id(self, _db, crawl_job_id):
        return self.jobs.setdefault(crawl_job_id, SimpleNamespace(id=crawl_job_id, metrics={}))

    def merge_metrics(self, _db, *, crawl_job_id, metrics_patch, auto_commit=True):
        job = self.get_crawl_job_by_id(_db, crawl_job_id)
        merged = dict(job.metrics or {})
        merged.update(metrics_patch)
        job.metrics = merged
        self.metric_patches.append((str(crawl_job_id), dict(metrics_patch)))
        return job


class _RecordingRuntimeRepository:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def record_runtime_event(self, _db, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace()


class _FakeCrawlJobListingRepository:
    def __init__(self, listings: list[_FakeListing] | None = None) -> None:
        self.listings: list[_FakeListing] = list(listings or [])

    def get_max_listing_rank_for_crawl_job(self, _db, *, crawl_job_id, source_site=None) -> int:
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
        limit=100,
        offset=0,
    ):
        normalized_statuses = set(statuses or ["pending", "failed", "manual_action_required"])
        rows = [
            listing
            for listing in self.listings
            if listing.source_site == source_site
            and (source_listing_crawl_job_id is None or listing.crawl_job_id == str(source_listing_crawl_job_id))
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


class _FakeJobRepository:
    def __init__(self, existing_jobs: dict[str, SimpleNamespace] | None = None) -> None:
        self.existing_jobs = dict(existing_jobs or {})

    def list_existing_jobs_by_source_ids(self, _db, *, source_site, source_job_ids):
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
