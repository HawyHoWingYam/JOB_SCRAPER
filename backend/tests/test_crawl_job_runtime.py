from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.crawl_phases import DEFAULT_DETAIL_RETRY_STATUSES, SUPPORTED_DETAIL_STATUSES
from app.models.crawl_job import CrawlJob, CrawlJobEvent
from app.models.crawl_job_listing import CrawlJobListing
from app.models.crawl_run import CrawlRun
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.repositories.crawl_job_listing_repository import CrawlJobListingRepository
from app.repositories.job_repository import JobRepository
from app.services.crawl_job_runtime import CrawlJobRuntime, ListingBatchPersistResult
from app.sources.offertoday.search_space import OFFERTODAY_IT_CATEGORY_CODES


class _FakeSession:
    def __init__(self, trace: list[str] | None = None) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.trace = trace
        self._rollback_actions = []

    def register_rollback(self, action) -> None:
        self._rollback_actions.append(action)

    def commit(self) -> None:
        self.commits += 1
        self._rollback_actions.clear()
        if self.trace is not None:
            self.trace.append("commit")

    def rollback(self) -> None:
        self.rollbacks += 1
        for action in reversed(self._rollback_actions):
            action()
        self._rollback_actions.clear()
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
    detail_attempts: int = 0
    last_detail_crawl_job_id: str | None = None
    published_job_id: str | None = None
    detail_error_message: str | None = None
    detail_started_at: datetime | None = None
    detail_completed_at: datetime | None = None
    listing_rank: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.source_site == "offertoday" and not self.listing_payload:
            encrypted_job_id = f"enc-{self.source_job_id}"
            self.listing_payload = {
                "job_id": self.source_job_id,
                "encrypted_job_id": encrypted_job_id,
                "raw_data": {
                    "jobId": self.source_job_id,
                    "encryptJobId": encrypted_job_id,
                },
            }


class _FakeCrawlJobRepository:
    def __init__(self, *, trace: list[str] | None = None, fail_event: bool = False) -> None:
        self.jobs: dict[str, SimpleNamespace] = {}
        self.metric_patches: list[tuple[str, dict]] = []
        self.events: list[dict] = []
        self.identity_observations: list[dict] = []
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

    def list_offertoday_listing_identity_observations(self, _db):
        return deepcopy(self.identity_observations)


class _RecordingRuntimeRepository:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def record_runtime_event(self, _db, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace()


def test_runtime_merge_metrics_commits_and_closes_short_session():
    session = _FakeSession()
    repository = _FakeCrawlJobRepository()
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=repository,
        crawl_job_listing_repository=_FakeCrawlJobListingRepository(),
        job_repository=_FakeJobRepository(),
    )

    runtime.merge_metrics(
        crawl_job_id="detail-run",
        metrics_patch={"jobs_created": 3},
    )

    assert repository.jobs["detail-run"].metrics == {"jobs_created": 3}
    assert repository.metric_patches == [
        ("detail-run", {"jobs_created": 3})
    ]
    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed is True


def test_runtime_merge_metrics_rolls_back_and_closes_on_repository_failure():
    class _FailingMetricsRepository(_FakeCrawlJobRepository):
        def merge_metrics(self, *args, **kwargs):
            raise RuntimeError("injected metric merge failure")

    session = _FakeSession()
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=_FailingMetricsRepository(),
        crawl_job_listing_repository=_FakeCrawlJobListingRepository(),
        job_repository=_FakeJobRepository(),
    )

    with pytest.raises(RuntimeError, match="metric merge failure"):
        runtime.merge_metrics(
            crawl_job_id="detail-run",
            metrics_patch={"jobs_created": 3},
        )

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closed is True


class _FakeCrawlJobListingRepository:
    def __init__(
        self,
        listings: list[_FakeListing] | None = None,
        *,
        identity_history: list[_FakeListing] | None = None,
        trace: list[str] | None = None,
    ) -> None:
        self.listings: list[_FakeListing] = list(listings or [])
        self.identity_history: list[_FakeListing] = list(
            self.listings if identity_history is None else identity_history
        )
        self.trace = trace
        self.upsert_calls: list[dict] = []
        self.candidate_calls: list[dict] = []
        self.list_identity_history_calls = 0
        self.list_source_rows_calls = 0
        self.legacy_existing_id_lookup_calls = 0
        self.completed_listing_ids: list[str] = []
        self.identity_conflict_listing_ids: list[str] = []

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
        self.legacy_existing_id_lookup_calls += 1
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

    def list_source_rows_by_job_ids(
        self,
        _db,
        *,
        source_site,
        source_job_ids,
    ):
        self.list_source_rows_calls += 1
        if self.trace is not None:
            self.trace.append("staged_lookup")
        requested = set(source_job_ids)
        return [
            listing
            for listing in self.listings
            if listing.source_site == source_site
            and listing.source_job_id in requested
        ]

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
        self.upsert_calls.append(
            {
                "source_job_id": source_job_id,
                "listing_rank": listing_rank,
            }
        )
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
        limit=None,
        offset=0,
    ):
        self.candidate_calls.append(
            {
                "source_site": source_site,
                "source_listing_crawl_job_id": source_listing_crawl_job_id,
                "category_ids": list(category_ids or []),
                "statuses": None if statuses is None else list(statuses),
                "source_job_ids": None if source_job_ids is None else list(source_job_ids),
                "limit": limit,
                "offset": offset,
            }
        )
        normalized_statuses = set(statuses or ["pending", "failed", "manual_action_required"])
        normalized_source_job_ids = None if source_job_ids is None else set(source_job_ids)
        blocked_source_job_ids = {
            listing.source_job_id
            for listing in self.listings
            if listing.source_site == "offertoday"
            and listing.detail_status in {"terminal_unavailable", "identity_conflict"}
        }
        rows = [
            listing
            for listing in self.listings
            if listing.source_site == source_site
            and (
                normalized_source_job_ids is not None
                or source_listing_crawl_job_id is None
                or listing.crawl_job_id == str(source_listing_crawl_job_id)
            )
            and (
                normalized_source_job_ids is None
                or listing.source_job_id in normalized_source_job_ids
            )
            and (
                normalized_source_job_ids is not None
                or not category_ids
                or str(listing.source_classification_id) in {str(value) for value in category_ids}
            )
            and listing.detail_status in normalized_statuses
            and (
                source_site != "offertoday"
                or listing.source_job_id not in blocked_source_job_ids
            )
        ]
        priority = {
            "manual_action_required": 0,
            "failed": 1,
            "pending": 2,
        }
        rows.sort(
            key=lambda listing: (
                priority.get(listing.detail_status, 3),
                listing.listing_rank is None,
                listing.listing_rank or 0,
                listing.created_at,
            )
        )
        rows = rows[offset:]
        return rows if limit is None else rows[:limit]

    def list_offertoday_identity_history(self, _db):
        self.list_identity_history_calls += 1
        return sorted(
            (
                listing
                for listing in self.identity_history
                if listing.source_site == "offertoday"
            ),
            key=lambda listing: (listing.created_at, listing.id),
        )

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
        before = (
            listing.detail_status,
            listing.last_detail_crawl_job_id,
            listing.detail_payload,
            listing.published_job_id,
        )
        if hasattr(_db, "register_rollback"):
            def restore() -> None:
                (
                    listing.detail_status,
                    listing.last_detail_crawl_job_id,
                    listing.detail_payload,
                    listing.published_job_id,
                ) = before

            _db.register_rollback(restore)
        listing.detail_status = "completed"
        listing.last_detail_crawl_job_id = str(detail_crawl_job_id)
        listing.detail_payload = dict(detail_payload or {})
        listing.published_job_id = published_job_id
        self.completed_listing_ids.append(listing_id)
        return listing

    def mark_detail_running(
        self,
        _db,
        *,
        listing_id,
        detail_crawl_job_id,
        auto_commit=True,
    ):
        listing = next(item for item in self.listings if item.id == listing_id)
        before = (
            listing.detail_status,
            listing.detail_attempts,
            listing.last_detail_crawl_job_id,
            listing.detail_error_message,
        )
        if hasattr(_db, "register_rollback"):
            def restore() -> None:
                (
                    listing.detail_status,
                    listing.detail_attempts,
                    listing.last_detail_crawl_job_id,
                    listing.detail_error_message,
                ) = before

            _db.register_rollback(restore)
        listing.detail_status = "running"
        listing.detail_attempts += 1
        listing.last_detail_crawl_job_id = str(detail_crawl_job_id)
        listing.detail_error_message = None
        return listing

    def mark_detail_outcome(
        self,
        _db,
        *,
        listing_id,
        detail_crawl_job_id,
        status=None,
        error_message,
        detail_payload=None,
        detail_status=None,
        auto_commit=True,
    ):
        detail_status = status if status is not None else detail_status
        listing = next(item for item in self.listings if item.id == listing_id)
        before = (
            listing.detail_status,
            listing.last_detail_crawl_job_id,
            listing.detail_error_message,
            listing.detail_payload,
        )
        if hasattr(_db, "register_rollback"):
            def restore() -> None:
                (
                    listing.detail_status,
                    listing.last_detail_crawl_job_id,
                    listing.detail_error_message,
                    listing.detail_payload,
                ) = before

            _db.register_rollback(restore)
        listing.detail_status = detail_status
        listing.last_detail_crawl_job_id = str(detail_crawl_job_id)
        listing.detail_error_message = error_message
        if detail_payload is not None:
            listing.detail_payload = dict(detail_payload)
        return listing

    def mark_detail_identity_conflict(
        self,
        _db,
        *,
        listing_id,
        detail_crawl_job_id,
        error_message,
        auto_commit=True,
    ):
        listing = next(item for item in self.listings if item.id == listing_id)
        before = (
            listing.detail_status,
            listing.last_detail_crawl_job_id,
            listing.detail_error_message,
        )
        if hasattr(_db, "register_rollback"):
            def restore() -> None:
                (
                    listing.detail_status,
                    listing.last_detail_crawl_job_id,
                    listing.detail_error_message,
                ) = before

            _db.register_rollback(restore)
        listing.detail_status = "identity_conflict"
        listing.last_detail_crawl_job_id = str(detail_crawl_job_id)
        listing.detail_error_message = error_message
        self.identity_conflict_listing_ids.append(listing_id)
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
                    source_site="offertoday",
                    source_job_id="job-1",
                    title="Developer",
                    company_id=str(uuid4()),
                    description="Complete description",
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


def test_load_detail_targets_retries_all_statuses_when_offertoday_job_is_partial():
    """A partial published row is not proof that any staging status is detail-complete."""
    session = _FakeSession()
    source_listing_crawl_job_id = str(uuid4())
    detail_crawl_job_id = str(uuid4())

    existing_job_ns = SimpleNamespace(
        id=str(uuid4()),
        source_site="offertoday",
        source_job_id="job-1",
        title="Developer",
        company_id=str(uuid4()),
        description="",
        raw_data={"jobId": "job-1"},
    )

    listing_pending = _FakeListing(
        id=str(uuid4()),
        crawl_job_id=source_listing_crawl_job_id,
        source_site="offertoday",
        source_job_id="job-1",
        source_url="https://www.offertoday.com/hk/job/job-1",
        detail_status="pending",
    )
    listing_failed = _FakeListing(
        id=str(uuid4()),
        crawl_job_id=source_listing_crawl_job_id,
        source_site="offertoday",
        source_job_id="job-2",
        source_url="https://www.offertoday.com/hk/job/job-2",
        detail_status="failed",
    )
    listing_manual = _FakeListing(
        id=str(uuid4()),
        crawl_job_id=source_listing_crawl_job_id,
        source_site="offertoday",
        source_job_id="job-3",
        source_url="https://www.offertoday.com/hk/job/job-3",
        detail_status="manual_action_required",
    )

    # All three source_job_ids exist in the jobs table.
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=_FakeCrawlJobRepository(),
        crawl_job_listing_repository=_FakeCrawlJobListingRepository(
            [listing_pending, listing_failed, listing_manual]
        ),
        job_repository=_FakeJobRepository(
            {
                "job-1": existing_job_ns,
                "job-2": existing_job_ns,
                "job-3": existing_job_ns,
            }
        ),
    )

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={
            "source_listing_crawl_job_id": source_listing_crawl_job_id,
            "detail_limit": 10,
            "detail_statuses": ["pending", "failed", "manual_action_required"],
            "skip_existing": True,
        },
        detail_crawl_job_id=detail_crawl_job_id,
    )

    assert result.selected_rows == 3
    assert result.skipped_existing_rows == 0
    assert result.target_rows == 3
    target_job_ids = {t["source_job_id"] for t in result.targets}
    assert target_job_ids == {"job-1", "job-2", "job-3"}
    assert listing_failed.detail_status == "failed"
    assert listing_manual.detail_status == "manual_action_required"
    assert listing_pending.detail_status == "pending"


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
    listing_rank: int | None = None,
) -> dict:
    encrypted_id = encrypted_job_id or f"enc-{source_job_id}"
    payload = {
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
    if listing_rank is not None:
        payload["listing_rank"] = listing_rank
    return payload


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


def test_offertoday_stage_batch_bulk_classifies_complete_repair_and_new():
    trace: list[str] = []
    session = _FakeSession(trace)
    crawl_job_id = "current-crawl"
    historical = _FakeListing(
        id="historical-row",
        crawl_job_id="historical-crawl",
        source_site="offertoday",
        source_job_id="staged-1",
        source_url="https://www.offertoday.com/hk/job/old-encrypted-id",
        listing_payload=_offertoday_stage_payload("staged-1")["listing_payload"],
    )
    listing_repository = _FakeCrawlJobListingRepository([historical], trace=trace)
    crawl_job_repository = _FakeCrawlJobRepository(trace=trace)
    job_repository = _FakeJobRepository(
        {"published-1": _published_job("published-1")},
        trace=trace,
    )
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=crawl_job_repository,
        crawl_job_listing_repository=listing_repository,
        job_repository=job_repository,
    )
    fallback_payload = _offertoday_stage_payload(
        "upgrade-1",
        encrypted_job_id="upgrade-1",
    )
    fallback_payload["listing_payload"] = {
        "job_id": "upgrade-1",
        "encrypted_job_id": "upgrade-1",
        "encrypted_job_id_source": "jobId_fallback",
        "raw_data": {"jobId": "upgrade-1"},
    }
    explicit_payload = _offertoday_stage_payload(
        "upgrade-1",
        encrypted_job_id="enc-upgrade-1",
    )
    explicit_payload["listing_payload"]["encrypted_job_id_source"] = "encryptJobId"

    result = runtime.stage_listing_batch(
        crawl_job_id=crawl_job_id,
        source_site="offertoday",
        payloads=[
            _offertoday_stage_payload("published-1", page=1),
            _offertoday_stage_payload("staged-1", page=2),
            _offertoday_stage_payload("new-1", page=3),
            _offertoday_stage_payload("new-1", keyword="duplicate", page=4),
            fallback_payload,
            explicit_payload,
        ],
        skip_existing=False,
    )

    assert trace[:3] == ["lock", "published_lookup", "staged_lookup"]
    assert trace.count("lock") == 1
    assert trace.count("published_lookup") == 1
    assert trace.count("staged_lookup") == 1
    assert listing_repository.list_source_rows_calls == 1
    assert listing_repository.legacy_existing_id_lookup_calls == 0
    assert trace.count("upsert:staged-1:created") == 1
    assert trace.count("upsert:new-1:created") == 1
    assert trace.count("upsert:upgrade-1:created") == 1
    assert trace[-3:] == ["merge_metrics", "append_event", "commit"]
    assert job_repository.raise_on_error_calls == [True]
    assert result == ListingBatchPersistResult(
        rows_created=3,
        created_source_job_ids=("staged-1", "new-1", "upgrade-1"),
        preexisting_staged_source_job_ids=(),
        published_source_job_ids=("published-1",),
        job_ids_seen=4,
        skipped_existing=1,
        complete_existing_source_job_ids=("published-1",),
        terminal_unavailable_source_job_ids=(),
        new_source_job_ids=("new-1", "upgrade-1"),
        repair_source_job_ids=("staged-1",),
        duplicate_source_job_ids=(),
    )
    assert historical.source_url.endswith("old-encrypted-id")
    event = crawl_job_repository.events[-1]
    assert event["event_type"] == "crawl.listing_observed"
    assert event["payload"]["complete_existing_source_job_ids"] == [
        "published-1"
    ]
    assert event["payload"]["repair_source_job_ids"] == ["staged-1"]
    assert event["payload"]["new_source_job_ids"] == ["new-1", "upgrade-1"]
    assert {
        observation["source_job_id"]: observation["classification"]
        for observation in event["payload"]["observations"]
    } == {
        "published-1": "complete_existing",
        "staged-1": "repair",
        "new-1": "new",
        "upgrade-1": "new",
    }
    current_rows = [
        row
        for row in listing_repository.listings
        if row.crawl_job_id == crawl_job_id
    ]
    assert {
        row.source_job_id: row.listing_payload["detail_target_kind"]
        for row in current_rows
    } == {
        "staged-1": "repair",
        "new-1": "new",
        "upgrade-1": "new",
    }


def test_offertoday_stage_batch_partitions_terminal_incomplete_and_duplicate():
    session = _FakeSession()
    terminal = _FakeListing(
        id="terminal-history",
        crawl_job_id="old-crawl",
        source_site="offertoday",
        source_job_id="terminal-1",
        source_url="https://www.offertoday.com/hk/job/enc-terminal-1",
        detail_status="terminal_unavailable",
    )
    current_duplicate = _FakeListing(
        id="current-duplicate",
        crawl_job_id="current-crawl",
        source_site="offertoday",
        source_job_id="duplicate-1",
        source_url="https://www.offertoday.com/hk/job/enc-duplicate-1",
    )
    listing_repository = _FakeCrawlJobListingRepository(
        [terminal, current_duplicate]
    )
    complete = _published_job("complete-1")
    incomplete = _published_job("incomplete-1", description=None)
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=_FakeCrawlJobRepository(),
        crawl_job_listing_repository=listing_repository,
        job_repository=_FakeJobRepository(
            {
                "complete-1": complete,
                "incomplete-1": incomplete,
            }
        ),
    )

    result = runtime.stage_listing_batch(
        crawl_job_id="current-crawl",
        source_site="offertoday",
        payloads=[
            _offertoday_stage_payload("complete-1"),
            _offertoday_stage_payload("terminal-1"),
            _offertoday_stage_payload("incomplete-1"),
            _offertoday_stage_payload("new-1"),
            _offertoday_stage_payload("duplicate-1"),
        ],
        skip_existing=True,
    )

    assert result.complete_existing_source_job_ids == ("complete-1",)
    assert result.terminal_unavailable_source_job_ids == ("terminal-1",)
    assert result.repair_source_job_ids == ("incomplete-1",)
    assert result.new_source_job_ids == ("new-1",)
    assert result.duplicate_source_job_ids == ("duplicate-1",)
    assert result.created_source_job_ids == ("incomplete-1", "new-1")
    assert result.skipped_existing == 3
    current_rows = {
        row.source_job_id: row
        for row in listing_repository.listings
        if row.crawl_job_id == "current-crawl"
    }
    assert current_rows["incomplete-1"].listing_payload[
        "detail_target_kind"
    ] == "repair"
    assert current_rows["new-1"].listing_payload["detail_target_kind"] == "new"
    assert listing_repository.list_source_rows_calls == 1
    assert listing_repository.legacy_existing_id_lookup_calls == 0


def test_offertoday_stage_batch_historical_identity_conflict_rolls_back():
    session = _FakeSession()
    historical = _FakeListing(
        id="historical-conflict",
        crawl_job_id="old-crawl",
        source_site="offertoday",
        source_job_id="conflict-1",
        source_url="https://www.offertoday.com/hk/job/enc-old",
        listing_payload=_offertoday_stage_payload(
            "conflict-1",
            encrypted_job_id="enc-old",
        )["listing_payload"],
    )
    listing_repository = _FakeCrawlJobListingRepository([historical])
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=_FakeCrawlJobRepository(),
        crawl_job_listing_repository=listing_repository,
        job_repository=_FakeJobRepository(),
    )

    with pytest.raises(
        RuntimeError,
        match="OfferToday listing identity conflict: conflict-1",
    ) as exc_info:
        runtime.stage_listing_batch(
            crawl_job_id="current-crawl",
            source_site="offertoday",
            payloads=[
                _offertoday_stage_payload(
                    "conflict-1",
                    encrypted_job_id="enc-new",
                )
            ],
            skip_existing=False,
        )

    assert exc_info.value.source_job_ids == ("conflict-1",)
    assert listing_repository.upsert_calls == []
    assert session.commits == 0
    assert session.rollbacks == 1


def test_offertoday_stage_batches_assign_monotonic_run_global_listing_ranks():
    session = _FakeSession()
    listing_repository = _FakeCrawlJobListingRepository()
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=_FakeCrawlJobRepository(),
        crawl_job_listing_repository=listing_repository,
        job_repository=_FakeJobRepository(),
    )

    for page, source_job_ids in (
        (1, ("page-1-job-1", "page-1-job-2")),
        (2, ("page-2-job-1", "page-2-job-2")),
    ):
        runtime.stage_listing_batch(
            crawl_job_id="crawl-1",
            source_site="offertoday",
            payloads=[
                _offertoday_stage_payload(
                    source_job_id,
                    page=page,
                    listing_rank=page_local_rank,
                )
                for page_local_rank, source_job_id in enumerate(
                    source_job_ids,
                    start=1,
                )
            ],
            skip_existing=False,
        )

    assert listing_repository.upsert_calls == [
        {"source_job_id": "page-1-job-1", "listing_rank": 1},
        {"source_job_id": "page-1-job-2", "listing_rank": 2},
        {"source_job_id": "page-2-job-1", "listing_rank": 3},
        {"source_job_id": "page-2-job-2", "listing_rank": 4},
    ]


def test_non_offertoday_stage_batch_preserves_explicit_listing_rank():
    session = _FakeSession()
    listing_repository = _FakeCrawlJobListingRepository()
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=_FakeCrawlJobRepository(),
        crawl_job_listing_repository=listing_repository,
        job_repository=_FakeJobRepository(),
    )

    runtime.stage_listing_batch(
        crawl_job_id="crawl-1",
        source_site="jobsdb",
        payloads=[
            {
                "source_job_id": "job-1",
                "source_url": "https://hk.jobsdb.com/job/job-1",
                "listing_rank": 37,
                "listing_payload": {"id": "job-1"},
            }
        ],
        skip_existing=False,
    )

    assert listing_repository.upsert_calls == [
        {"source_job_id": "job-1", "listing_rank": 37}
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


def _detail_listing(
    listing_id: str,
    source_job_id: str,
    *,
    source_site: str = "offertoday",
    encrypted_job_id: str | None = None,
    status: str = "pending",
    rank: int | None = None,
    crawl_job_id: str = "batch-1",
    category_id: str | None = "118000",
    listing_payload: dict | None = None,
) -> _FakeListing:
    encrypted_job_id = encrypted_job_id or f"enc-{source_job_id}"
    if listing_payload is None:
        listing_payload = {
            "job_id": source_job_id,
            "encrypted_job_id": encrypted_job_id,
            "raw_data": {
                "jobId": source_job_id,
                "encryptJobId": encrypted_job_id,
            },
        }
    return _FakeListing(
        id=listing_id,
        crawl_job_id=crawl_job_id,
        source_site=source_site,
        source_job_id=source_job_id,
        source_url=f"https://example.test/job/{encrypted_job_id}",
        source_classification_id=category_id,
        listing_payload=listing_payload,
        detail_status=status,
        listing_rank=rank,
        created_at=datetime(2026, 7, 10, tzinfo=UTC)
        + timedelta(seconds=rank or 0),
    )


def _published_job(
    source_job_id: str,
    *,
    source_site: str = "offertoday",
    title: str = "Developer",
    description: str = "Complete description",
    company_id: str | None = "company-1",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"job-{source_job_id}",
        source_site=source_site,
        source_job_id=source_job_id,
        title=title,
        description=description,
        company_id=company_id,
        raw_data={"jobId": source_job_id, "description": description},
    )


def _detail_runtime(
    rows: list[_FakeListing],
    *,
    jobs: list[SimpleNamespace] | None = None,
    identity_history: list[_FakeListing] | None = None,
    fail_event: bool = False,
):
    session = _FakeSession()
    listing_repository = _FakeCrawlJobListingRepository(
        rows,
        identity_history=identity_history,
    )
    crawl_job_repository = _FakeCrawlJobRepository(fail_event=fail_event)
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=crawl_job_repository,
        crawl_job_listing_repository=listing_repository,
        job_repository=_FakeJobRepository(
            {job.source_job_id: job for job in (jobs or [])}
        ),
    )
    return runtime, listing_repository, crawl_job_repository, session


def _expected_cohort_hash(source_job_ids: tuple[str, ...]) -> str:
    payload = json.dumps(
        source_job_ids,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_jobid_only_history_resolves_without_mutation_or_identity_conflict():
    payload = {
        "job_id": "j-1",
        "encrypted_job_id": "j-1",
        "encrypted_job_id_source": "jobId_fallback",
        "raw_data": {"jobId": "j-1"},
    }
    row = _detail_listing("row-1", "j-1", listing_payload=payload, rank=1)
    before = deepcopy(row.listing_payload)
    runtime, repository, _crawl_jobs, _session = _detail_runtime([row])

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 10},
        detail_crawl_job_id="detail-run-1",
    )

    assert result.identity_conflict_ids == ()
    assert result.targets[0]["identity"].job_id == "j-1"
    assert result.targets[0]["identity"].encrypted_job_id == "j-1"
    assert result.targets[0]["identity"].encrypted_job_id_source == (
        "jobId_fallback"
    )
    assert row.listing_payload == before
    assert repository.identity_conflict_listing_ids == []


def test_one_explicit_history_mapping_promotes_fallback_authority():
    fallback = _detail_listing(
        "fallback",
        "j-1",
        listing_payload={
            "job_id": "j-1",
            "encrypted_job_id": "j-1",
            "encrypted_job_id_source": "jobId_fallback",
            "raw_data": {"jobId": "j-1"},
        },
        rank=1,
    )
    explicit = _detail_listing(
        "explicit",
        "j-1",
        listing_payload={
            "job_id": "j-1",
            "encrypted_job_id": "enc-1",
            "encrypted_job_id_source": "encryptJobId",
            "raw_data": {"jobId": "j-1", "encryptJobId": "enc-1"},
        },
        rank=2,
    )
    runtime, _repository, _crawl_jobs, _session = _detail_runtime(
        [fallback, explicit]
    )

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 10},
        detail_crawl_job_id="detail-run-1",
    )

    assert result.identity_conflict_ids == ()
    assert result.targets[0]["identity"].encrypted_job_id == "enc-1"
    assert result.targets[0]["identity"].encrypted_job_id_source == "encryptJobId"


def test_unselected_invalid_history_does_not_block_unrelated_target():
    valid = _detail_listing(
        "valid",
        "j-1",
        listing_payload={
            "job_id": "j-1",
            "encrypted_job_id": "j-1",
            "encrypted_job_id_source": "jobId_fallback",
            "raw_data": {"jobId": "j-1"},
        },
        rank=1,
    )
    unrelated_invalid = _detail_listing(
        "invalid",
        "j-other",
        listing_payload={"raw_data": {"jobId": "j-other", "encryptJobId": []}},
        rank=2,
    )
    runtime, repository, _crawl_jobs, _session = _detail_runtime(
        [valid],
        identity_history=[valid, unrelated_invalid],
    )

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 10},
        detail_crawl_job_id="detail-run-1",
    )

    assert result.identity_conflict_ids == ()
    assert result.targets[0]["source_job_id"] == "j-1"
    assert repository.identity_conflict_listing_ids == []


def test_skipped_explicit_observation_promotes_fallback_without_rewriting_row():
    fallback_payload = {
        "job_id": "j-1",
        "encrypted_job_id": "j-1",
        "encrypted_job_id_source": "jobId_fallback",
        "raw_data": {"jobId": "j-1"},
    }
    fallback = _detail_listing(
        "fallback",
        "j-1",
        listing_payload=fallback_payload,
        rank=1,
    )
    before = deepcopy(fallback.listing_payload)
    runtime, _repository, crawl_jobs, _session = _detail_runtime([fallback])
    crawl_jobs.identity_observations = [
        {
            "source_job_id": "j-1",
            "job_id": "j-1",
            "encrypted_job_id": "enc-1",
            "encrypted_job_id_source": "encryptJobId",
        }
    ]

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 10},
        detail_crawl_job_id="detail-run-1",
    )

    assert result.identity_conflict_ids == ()
    assert result.targets[0]["identity"].encrypted_job_id == "enc-1"
    assert result.targets[0]["identity"].encrypted_job_id_source == "encryptJobId"
    assert fallback.listing_payload == before
    assert any(
        event["event_type"] == "crawl.detail_identity_provenance_upgraded"
        for event in crawl_jobs.events
    )


def test_detail_limit_applies_after_grouping_duplicate_rows():
    rows = [
        _detail_listing("row-1", "j-1", rank=1),
        _detail_listing("row-2", "j-1", rank=2),
        _detail_listing("row-3", "j-2", rank=3),
    ]
    runtime, repository, _crawl_jobs, _session = _detail_runtime(rows)

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 1, "skip_existing": False},
        detail_crawl_job_id="detail-run-1",
    )

    assert repository.candidate_calls[-1]["limit"] is None
    assert result.selected_rows == 3
    assert result.distinct_selected_ids == 2
    assert result.duplicate_rows == 1
    assert result.target_rows == 1
    assert result.targets[0]["source_job_id"] == "j-1"
    assert result.targets[0]["duplicate_listing_ids"] == ("row-2",)
    assert result.targets[0]["identity"].job_id == "j-1"
    assert result.fetch_cohort_source_job_ids == ("j-1",)
    assert result.fetch_cohort_hash == _expected_cohort_hash(("j-1",))


def test_explicit_unlimited_detail_cohort_keeps_every_current_crawl_target():
    rows = [
        _detail_listing(
            f"row-{index}",
            f"j-{index}",
            rank=index,
            crawl_job_id="current-crawl",
        )
        for index in range(1, 102)
    ]
    runtime, _repository, _crawl_jobs, _session = _detail_runtime(rows)

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={
            "source_listing_crawl_job_id": "current-crawl",
            "detail_limit": None,
        },
        detail_crawl_job_id="detail-run-1",
    )

    assert result.selected_rows == 101
    assert result.target_rows == 101
    assert len(result.fetch_cohort_source_job_ids) == 101


def test_detail_targets_preserve_new_and_repair_kinds_once_per_canonical_id():
    rows = [
        _detail_listing(
            "new-row",
            "j-new",
            rank=1,
            listing_payload={
                "job_id": "j-new",
                "encrypted_job_id": "enc-j-new",
                "encrypted_job_id_source": "encryptJobId",
                "detail_target_kind": "new",
                "raw_data": {"jobId": "j-new", "encryptJobId": "enc-j-new"},
            },
        ),
        _detail_listing(
            "repair-row",
            "j-repair",
            rank=2,
            listing_payload={
                "job_id": "j-repair",
                "encrypted_job_id": "enc-j-repair",
                "encrypted_job_id_source": "encryptJobId",
                "detail_target_kind": "repair",
                "raw_data": {
                    "jobId": "j-repair",
                    "encryptJobId": "enc-j-repair",
                },
            },
        ),
    ]
    runtime, _repository, _crawl_jobs, _session = _detail_runtime(rows)

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={
            "source_listing_crawl_job_id": "batch-1",
            "detail_limit": 10,
        },
        detail_crawl_job_id="detail-run-1",
    )

    assert result.new_detail_targets == 1
    assert result.repair_detail_targets == 1
    assert [target["detail_target_kind"] for target in result.targets] == [
        "new",
        "repair",
    ]


def test_complete_job_reconciles_all_duplicates_before_limit_and_records_event():
    rows = [
        _detail_listing("row-1", "j-complete", status="pending", rank=1),
        _detail_listing("row-2", "j-complete", status="failed", rank=2),
        _detail_listing("row-3", "j-fetch", status="pending", rank=3),
    ]
    complete_job = _published_job("j-complete")
    runtime, repository, crawl_jobs, session = _detail_runtime(
        rows,
        jobs=[complete_job],
    )

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 1, "skip_existing": True},
        detail_crawl_job_id="detail-run-1",
    )

    expected_records = [
        {
            "listing_id": "row-2",
            "source_job_id": "j-complete",
            "before_status": "failed",
            "after_status": "completed",
            "published_job_id": "job-j-complete",
        },
        {
            "listing_id": "row-1",
            "source_job_id": "j-complete",
            "before_status": "pending",
            "after_status": "completed",
            "published_job_id": "job-j-complete",
        },
    ]
    assert repository.completed_listing_ids == ["row-2", "row-1"]
    assert result.reconciled_rows == result.skipped_existing_rows == 2
    assert result.reconciled_source_job_ids == ("j-complete",)
    assert result.reconciliation_records == tuple(expected_records)
    assert result.fetch_cohort_source_job_ids == ("j-fetch",)
    assert result.fetch_cohort_hash == _expected_cohort_hash(("j-fetch",))
    assert [target["source_job_id"] for target in result.targets] == ["j-fetch"]
    assert crawl_jobs.events[-1] == {
        "crawl_job_id": "detail-run-1",
        "event_type": "crawl.detail_reconciled",
        "payload": {"records": expected_records},
        "emitted_by": "crawl-runtime",
        "auto_commit": False,
    }
    assert session.commits == 1


def test_reconciliation_event_failure_rolls_back_all_duplicate_transitions():
    rows = [
        _detail_listing("row-1", "j-complete", status="pending", rank=1),
        _detail_listing("row-2", "j-complete", status="failed", rank=2),
    ]
    runtime, _repository, crawl_jobs, session = _detail_runtime(
        rows,
        jobs=[_published_job("j-complete")],
        fail_event=True,
    )

    with pytest.raises(RuntimeError, match="event write failed"):
        runtime.load_detail_targets(
            source_site="offertoday",
            request_payload={"detail_limit": 1, "skip_existing": True},
            detail_crawl_job_id="detail-run-1",
        )

    assert [row.detail_status for row in rows] == ["pending", "failed"]
    assert crawl_jobs.events == []
    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_job_id", " "),
        ("title", ""),
        ("description", None),
        ("company_id", None),
    ],
)
def test_incomplete_offertoday_job_remains_a_fetch_target(field, value):
    row = _detail_listing("row-1", "j-partial", rank=1)
    partial_job = _published_job("j-partial")
    setattr(partial_job, field, value)
    runtime, repository, _crawl_jobs, _session = _detail_runtime(
        [row],
        jobs=[partial_job],
    )
    runtime.job_repository.existing_jobs["j-partial"] = partial_job

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 1, "skip_existing": True},
        detail_crawl_job_id="detail-run-1",
    )

    assert [target["source_job_id"] for target in result.targets] == ["j-partial"]
    assert repository.completed_listing_ids == []


def test_complete_offertoday_job_normalizes_source_site_for_reconciliation():
    row = _detail_listing("row-1", "j-complete", rank=1)
    complete_job = _published_job("j-complete", source_site=" OfferToday ")
    runtime, repository, _crawl_jobs, _session = _detail_runtime(
        [row],
        jobs=[complete_job],
    )

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 1, "skip_existing": True},
        detail_crawl_job_id="detail-run-1",
    )

    assert result.targets == []
    assert result.reconciled_source_job_ids == ("j-complete",)
    assert repository.completed_listing_ids == ["row-1"]


def test_authoritative_row_priority_is_manual_then_failed_then_pending():
    rows = [
        _detail_listing("pending", "j-1", status="pending", rank=1),
        _detail_listing("failed", "j-1", status="failed", rank=2),
        _detail_listing(
            "manual",
            "j-1",
            status="manual_action_required",
            rank=3,
        ),
    ]
    runtime, _repository, _crawl_jobs, _session = _detail_runtime(rows)

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 1},
        detail_crawl_job_id="detail-run-1",
    )

    assert result.targets[0]["listing_id"] == "manual"
    assert result.targets[0]["duplicate_listing_ids"] == ("failed", "pending")


def test_batch_scope_keeps_leaf_keyword_and_hybrid_rows():
    rows = [
        _detail_listing(
            "leaf",
            "j-leaf",
            category_id="118005",
            crawl_job_id="batch-1",
            rank=1,
        ),
        _detail_listing(
            "keyword",
            "j-keyword",
            category_id=None,
            crawl_job_id="batch-1",
            rank=2,
        ),
        _detail_listing(
            "hybrid",
            "j-hybrid",
            category_id=None,
            crawl_job_id="batch-1",
            rank=3,
            listing_payload={
                "job_id": "j-hybrid",
                "encrypted_job_id": "enc-j-hybrid",
                "encrypted_job_id_source": "encryptJobId",
                "search_family": "it_hybrid",
                "detail_target_kind": "new",
                "raw_data": {
                    "jobId": "j-hybrid",
                    "encryptJobId": "enc-j-hybrid",
                },
            },
        ),
        _detail_listing(
            "other",
            "j-other",
            category_id="118000",
            crawl_job_id="batch-2",
            rank=4,
        ),
    ]
    runtime, repository, _crawl_jobs, _session = _detail_runtime(rows)

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={
            "source_listing_crawl_job_id": "batch-1",
            "category_ids": [118000],
            "detail_limit": 10,
        },
        detail_crawl_job_id="detail-run-1",
    )

    assert repository.candidate_calls[-1]["category_ids"] == []
    assert {target["source_job_id"] for target in result.targets} == {
        "j-hybrid",
        "j-leaf",
        "j-keyword",
    }


def test_unbound_offertoday_detail_scope_keeps_expanded_category_filter():
    rows = [
        _detail_listing("root", "j-root", category_id="118000", rank=1),
        _detail_listing("leaf", "j-leaf", category_id="118005", rank=2),
        _detail_listing("keyword", "j-keyword", category_id=None, rank=3),
        _detail_listing("other", "j-other", category_id="999999", rank=4),
    ]
    runtime, repository, _crawl_jobs, _session = _detail_runtime(rows)

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"category_ids": [118000], "detail_limit": 10},
        detail_crawl_job_id="detail-run-1",
    )

    assert repository.candidate_calls[-1]["source_listing_crawl_job_id"] is None
    assert repository.candidate_calls[-1]["category_ids"] == list(
        OFFERTODAY_IT_CATEGORY_CODES
    )
    assert {target["source_job_id"] for target in result.targets} == {
        "j-root",
        "j-leaf",
    }


def test_changed_encrypted_id_defers_every_selected_duplicate():
    rows = [
        _detail_listing("row-1", "j-1", encrypted_job_id="enc-a", rank=1),
        _detail_listing("row-2", "j-1", encrypted_job_id="enc-b", rank=2),
    ]
    runtime, repository, crawl_jobs, _session = _detail_runtime(rows)

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 10},
        detail_crawl_job_id="detail-run-1",
    )

    expected_evidence = {
        "source_job_id": "j-1",
        "encrypted_job_ids": ["enc-a", "enc-b"],
        "reverse_peer_job_ids": [],
        "reason": "multiple_explicit_encrypted_ids",
    }
    assert result.targets == []
    assert result.fetch_cohort_source_job_ids == ()
    assert result.fetch_cohort_hash == _expected_cohort_hash(())
    assert result.identity_conflict_ids == ("j-1",)
    assert result.identity_conflict_evidence == (expected_evidence,)
    assert repository.identity_conflict_listing_ids == ["row-1", "row-2"]
    assert [row.detail_status for row in rows] == [
        "identity_conflict",
        "identity_conflict",
    ]
    assert crawl_jobs.events[-1]["event_type"] == "crawl.detail_identity_conflict"
    assert crawl_jobs.events[-1]["payload"] == {"conflicts": [expected_evidence]}


def test_reverse_collision_same_encrypted_id_for_two_canonical_ids_defers_both_groups():
    rows = [
        _detail_listing("row-1", "j-1", encrypted_job_id="enc-shared", rank=1),
        _detail_listing("row-2", "j-2", encrypted_job_id="enc-shared", rank=2),
    ]
    runtime, repository, _crawl_jobs, _session = _detail_runtime(rows)

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 10},
        detail_crawl_job_id="detail-run-1",
    )

    assert result.targets == []
    assert result.identity_conflict_ids == ("j-1", "j-2")
    assert result.identity_conflict_evidence == (
        {
            "source_job_id": "j-1",
            "encrypted_job_ids": ["enc-shared"],
            "reverse_peer_job_ids": ["j-2"],
            "reason": "reverse_collision",
        },
        {
            "source_job_id": "j-2",
            "encrypted_job_ids": ["enc-shared"],
            "reverse_peer_job_ids": ["j-1"],
            "reason": "reverse_collision",
        },
    )
    assert repository.identity_conflict_listing_ids == ["row-1", "row-2"]


def test_completed_history_mapping_change_defers_new_pending_row():
    rows = [
        _detail_listing(
            "old",
            "j-1",
            encrypted_job_id="enc-a",
            status="completed",
            rank=1,
            crawl_job_id="old-batch",
        ),
        _detail_listing(
            "new",
            "j-1",
            encrypted_job_id="enc-b",
            status="pending",
            rank=2,
            crawl_job_id="new-batch",
        ),
    ]
    runtime, repository, _crawl_jobs, _session = _detail_runtime(rows)

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 10},
        detail_crawl_job_id="detail-run-1",
    )

    assert result.targets == []
    assert result.identity_conflict_ids == ("j-1",)
    assert repository.identity_conflict_listing_ids == ["new"]
    assert rows[0].detail_status == "completed"
    assert rows[1].detail_status == "identity_conflict"


def test_malformed_group_does_not_suppress_valid_promoted_fallback_group():
    bad = _detail_listing(
        "bad",
        "j-bad",
        listing_payload={"encrypted_job_id": ""},
        rank=1,
    )
    good_fallback = _detail_listing(
        "good-fallback",
        "j-good",
        listing_payload={
            "job_id": "j-good",
            "encrypted_job_id": "j-good",
            "encrypted_job_id_source": "jobId_fallback",
            "raw_data": {"jobId": "j-good"},
        },
        rank=2,
    )
    good_explicit = _detail_listing(
        "good-explicit",
        "j-good",
        listing_payload={
            "job_id": "j-good",
            "encrypted_job_id": "enc-good",
            "encrypted_job_id_source": "encryptJobId",
            "raw_data": {"jobId": "j-good", "encryptJobId": "enc-good"},
        },
        rank=3,
    )
    rows = [bad, good_fallback, good_explicit]
    before = [deepcopy(row.listing_payload) for row in rows]
    runtime, repository, crawl_jobs, _session = _detail_runtime(rows)

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 10},
        detail_crawl_job_id="detail-run-1",
    )

    expected_evidence = {
        "source_job_id": "j-bad",
        "encrypted_job_ids": [],
        "reverse_peer_job_ids": [],
        "reason": "unusable_identity_evidence",
    }
    assert result.identity_conflict_ids == ("j-bad",)
    assert result.identity_conflict_evidence == (expected_evidence,)
    assert repository.identity_conflict_listing_ids == ["bad"]
    assert [target["source_job_id"] for target in result.targets] == ["j-good"]
    assert result.targets[0]["identity"].encrypted_job_id == "enc-good"
    assert result.targets[0]["identity"].encrypted_job_id_source == "encryptJobId"
    assert result.fetch_cohort_source_job_ids == ("j-good",)
    assert result.selected_rows == 3
    assert result.distinct_selected_ids == 2
    assert result.duplicate_rows == 1
    assert result.target_rows == 1
    assert bad.detail_status == "identity_conflict"
    assert good_fallback.detail_status == "pending"
    assert good_explicit.detail_status == "pending"
    assert [row.listing_payload for row in rows] == before
    assert crawl_jobs.events[-2]["event_type"] == "crawl.detail_identity_conflict"
    assert crawl_jobs.events[-2]["payload"] == {"conflicts": [expected_evidence]}
    assert crawl_jobs.events[-1]["event_type"] == (
        "crawl.detail_identity_provenance_upgraded"
    )


def test_identity_conflict_does_not_suppress_otherwise_valid_batch_targets():
    rows = [
        _detail_listing("bad-a", "j-bad", encrypted_job_id="enc-a", rank=1),
        _detail_listing("bad-b", "j-bad", encrypted_job_id="enc-b", rank=2),
        _detail_listing("valid", "j-valid", encrypted_job_id="enc-v", rank=3),
    ]
    runtime, repository, _crawl_jobs, _session = _detail_runtime(rows)

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 10},
        detail_crawl_job_id="detail-run-1",
    )

    assert [target["source_job_id"] for target in result.targets] == ["j-valid"]
    assert result.fetch_cohort_source_job_ids == ("j-valid",)
    assert result.identity_conflict_ids == ("j-bad",)
    assert repository.identity_conflict_listing_ids == ["bad-a", "bad-b"]
    assert rows[0].detail_status == "identity_conflict"
    assert rows[1].detail_status == "identity_conflict"
    assert rows[2].detail_status == "pending"


def test_missing_identity_is_durable_conflict_and_event_failure_rolls_back():
    row = _detail_listing(
        "bad",
        "j-bad",
        listing_payload={"encrypted_job_id": ""},
        rank=1,
    )
    runtime, _repository, _crawl_jobs, session = _detail_runtime(
        [row],
        fail_event=True,
    )

    with pytest.raises(RuntimeError, match="event write failed"):
        runtime.load_detail_targets(
            source_site="offertoday",
            request_payload={"detail_limit": 10},
            detail_crawl_job_id="detail-run-1",
        )

    assert row.detail_status == "pending"
    assert session.commits == 0
    assert session.rollbacks == 1


def test_non_offertoday_keeps_generic_reconciliation_without_identity_history():
    row = _detail_listing(
        "row-1",
        "jobsdb-1",
        source_site="jobsdb",
        rank=1,
    )
    generic_partial_job = _published_job(
        "jobsdb-1",
        source_site="jobsdb",
        description="",
        company_id=None,
    )
    runtime, repository, _crawl_jobs, _session = _detail_runtime(
        [row],
        jobs=[generic_partial_job],
    )

    result = runtime.load_detail_targets(
        source_site="jobsdb",
        request_payload={"detail_limit": 1, "skip_existing": True},
        detail_crawl_job_id="detail-run-1",
    )

    assert result.targets == []
    assert result.reconciled_rows == 1
    assert result.identity_conflict_ids == ()
    assert repository.list_identity_history_calls == 0


def test_offertoday_status_metrics_include_terminal_and_identity_conflict_rows():
    rows = [
        _detail_listing(
            "terminal",
            "j-terminal",
            status="terminal_unavailable",
            crawl_job_id="batch-1",
            rank=1,
        ),
        _detail_listing(
            "conflict",
            "j-conflict",
            status="identity_conflict",
            crawl_job_id="batch-1",
            rank=2,
        ),
    ]
    runtime, repository, crawl_jobs, _session = _detail_runtime(rows)

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={
            "source_listing_crawl_job_id": "batch-1",
            "detail_limit": 10,
        },
        detail_crawl_job_id="detail-run-1",
    )

    assert result.targets == []
    assert repository.list_identity_history_calls == 0
    metrics = crawl_jobs.jobs["batch-1"].metrics
    assert metrics["detail_terminal_unavailable"] == 1
    assert metrics["detail_identity_conflict"] == 1


def _database_listing(
    source_site: str,
    source_job_id: str,
    *,
    status: str,
    rank: int,
    crawl_job_id=None,
    category_id: str | None = "118000",
) -> CrawlJobListing:
    encrypted_job_id = f"enc-{source_job_id}"
    return CrawlJobListing(
        id=uuid4(),
        crawl_job_id=crawl_job_id or uuid4(),
        source_site=source_site,
        source_job_id=source_job_id,
        source_url=f"https://example.test/job/{encrypted_job_id}",
        source_classification_id=category_id,
        listing_rank=rank,
        listing_payload={
            "jobId": source_job_id,
            "encryptJobId": encrypted_job_id,
        },
        detail_status=status,
        created_at=datetime(2026, 7, 10, tzinfo=UTC) + timedelta(seconds=rank),
        updated_at=datetime(2026, 7, 10, tzinfo=UTC) + timedelta(seconds=rank),
    )


def test_repository_lists_all_offertoday_identity_history_in_creation_order():
    engine = create_engine("sqlite://")
    CrawlJobListing.__table__.create(engine)
    rows = [
        _database_listing("offertoday", "later", status="completed", rank=2),
        _database_listing("jobsdb", "ignored", status="pending", rank=0),
        _database_listing("offertoday", "earlier", status="failed", rank=1),
    ]
    with Session(engine) as db:
        db.add_all(rows)
        db.commit()

        history = CrawlJobListingRepository().list_offertoday_identity_history(db)

    assert [row.source_job_id for row in history] == ["earlier", "later"]
    assert [row.detail_status for row in history] == ["failed", "completed"]


def test_crawl_job_repository_lists_crawl_tasks_in_stable_queue_order():
    engine = create_engine("sqlite://")
    CrawlJob.__table__.create(engine)
    CrawlRun.__table__.create(engine)
    newest_time = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    older_time = newest_time - timedelta(hours=1)
    oldest_time = newest_time - timedelta(hours=2)
    newest_high_id = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
    newest_low_id = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
    older_id = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    oldest_id = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")

    with Session(engine) as db:
        db.add_all(
            [
                CrawlJob(
                    id=older_id,
                    source_site="offertoday",
                    trigger_type="manual",
                    status="completed",
                    request_payload={},
                    queued_at=older_time,
                    created_at=older_time,
                    updated_at=newest_time + timedelta(hours=3),
                ),
                CrawlJob(
                    id=newest_low_id,
                    source_site="offertoday",
                    trigger_type="manual",
                    status="running",
                    request_payload={},
                    queued_at=newest_time,
                    created_at=newest_time,
                    updated_at=oldest_time,
                ),
                CrawlJob(
                    id=oldest_id,
                    source_site="jobsdb",
                    trigger_type="manual",
                    status="completed",
                    request_payload={},
                    queued_at=oldest_time,
                    created_at=oldest_time,
                    updated_at=newest_time + timedelta(hours=4),
                ),
                CrawlJob(
                    id=newest_high_id,
                    source_site="offertoday",
                    trigger_type="manual",
                    status="queued",
                    request_payload={},
                    queued_at=newest_time,
                    created_at=newest_time,
                    updated_at=oldest_time,
                ),
            ]
        )
        db.commit()

        repository = CrawlJobRepository()
        first_page, first_total = repository.list_crawl_task_page(
            db,
            page=1,
            page_size=2,
            status=None,
            source_site=None,
            crawl_mode=None,
        )
        second_page, second_total = repository.list_crawl_task_page(
            db,
            page=2,
            page_size=2,
            status=None,
            source_site=None,
            crawl_mode=None,
        )

    assert first_total == second_total == 4
    assert [row.id for row in first_page] == [newest_high_id, newest_low_id]
    assert [row.id for row in second_page] == [older_id, oldest_id]


def test_crawl_job_repository_lists_offertoday_identity_observations_in_order():
    engine = create_engine("sqlite://")
    CrawlJob.__table__.create(engine)
    CrawlJobEvent.__table__.create(engine)
    offertoday_id = uuid4()
    jobsdb_id = uuid4()
    with Session(engine) as db:
        db.add_all(
            [
                CrawlJob(
                    id=offertoday_id,
                    source_site="offertoday",
                    trigger_type="manual",
                    status="completed",
                    request_payload={},
                ),
                CrawlJob(
                    id=jobsdb_id,
                    source_site="jobsdb",
                    trigger_type="manual",
                    status="completed",
                    request_payload={},
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                CrawlJobEvent(
                    crawl_job_id=offertoday_id,
                    sequence_no=1,
                    event_type="crawl.listing_observed",
                    payload={
                        "observations": [
                            {
                                "source_job_id": "j-1",
                                "job_id": "j-1",
                                "encrypted_job_id": "j-1",
                                "encrypted_job_id_source": "jobId_fallback",
                            }
                        ]
                    },
                ),
                CrawlJobEvent(
                    crawl_job_id=jobsdb_id,
                    sequence_no=1,
                    event_type="crawl.listing_observed",
                    payload={"observations": [{"source_job_id": "ignore"}]},
                ),
            ]
        )
        db.commit()

        observations = (
            CrawlJobRepository().list_offertoday_listing_identity_observations(db)
        )

    assert observations == [
        {
            "source_job_id": "j-1",
            "job_id": "j-1",
            "encrypted_job_id": "j-1",
            "encrypted_job_id_source": "jobId_fallback",
        }
    ]


def test_repository_identity_conflict_transition_participates_in_caller_transaction():
    engine = create_engine("sqlite://")
    CrawlJobListing.__table__.create(engine)
    row = _database_listing("offertoday", "j-1", status="pending", rank=1)
    row_id = row.id
    detail_crawl_job_id = uuid4()
    with Session(engine) as db:
        db.add(row)
        db.commit()

        transitioned = CrawlJobListingRepository().mark_detail_identity_conflict(
            db,
            listing_id=row_id,
            detail_crawl_job_id=detail_crawl_job_id,
            error_message="mapping conflict",
            auto_commit=False,
        )

        assert transitioned.detail_status == "identity_conflict"
        assert transitioned.last_detail_crawl_job_id == detail_crawl_job_id
        assert transitioned.detail_error_message == "mapping conflict"
        assert transitioned.detail_completed_at is not None
        db.rollback()
        restored = db.get(CrawlJobListing, row_id)
        assert restored.detail_status == "pending"
        assert restored.last_detail_crawl_job_id is None
        assert restored.detail_error_message is None


def test_repository_explicit_ids_override_scope_and_use_status_priority():
    engine = create_engine("sqlite://")
    CrawlJobListing.__table__.create(engine)
    batch_1 = uuid4()
    batch_2 = uuid4()
    rows = [
        _database_listing(
            "jobsdb",
            "pending",
            status="pending",
            rank=1,
            crawl_job_id=batch_1,
        ),
        _database_listing(
            "jobsdb",
            "failed",
            status="failed",
            rank=2,
            crawl_job_id=batch_1,
        ),
        _database_listing(
            "jobsdb",
            "manual",
            status="manual_action_required",
            rank=3,
            crawl_job_id=batch_2,
            category_id="999999",
        ),
    ]
    with Session(engine) as db:
        db.add_all(rows)
        db.commit()

        selected = CrawlJobListingRepository().list_detail_candidates(
            db,
            source_site="jobsdb",
            source_listing_crawl_job_id=batch_1,
            category_ids=[118000],
            statuses=["pending", "failed", "manual_action_required"],
            source_job_ids=["pending", "failed", "manual"],
            limit=None,
        )

    assert [row.source_job_id for row in selected] == ["manual", "failed", "pending"]


def test_repository_candidate_order_uses_id_as_final_tie_breaker():
    engine = create_engine("sqlite://")
    CrawlJobListing.__table__.create(engine)
    lower_id = UUID("aaaaaaaa-0000-0000-0000-000000000001")
    higher_id = UUID("bbbbbbbb-0000-0000-0000-000000000002")
    higher_row = _database_listing(
        "jobsdb",
        "higher-id",
        status="pending",
        rank=1,
    )
    lower_row = _database_listing(
        "jobsdb",
        "lower-id",
        status="pending",
        rank=1,
    )
    higher_row.id = higher_id
    lower_row.id = lower_id

    with Session(engine) as db:
        db.add_all([higher_row, lower_row])
        db.commit()

        selected = CrawlJobListingRepository().list_detail_candidates(
            db,
            source_site="jobsdb",
            statuses=["pending"],
            limit=None,
        )

    assert [row.id for row in selected] == [lower_id, higher_id]


@pytest.mark.parametrize("blocking_status", ["terminal_unavailable", "identity_conflict"])
def test_repository_offertoday_historical_blocker_excludes_pending_sibling(
    blocking_status,
):
    engine = create_engine("sqlite://")
    CrawlJobListing.__table__.create(engine)
    rows = [
        _database_listing(
            "offertoday",
            "j-1",
            status=blocking_status,
            rank=1,
        ),
        _database_listing("offertoday", "j-1", status="pending", rank=2),
        _database_listing("jobsdb", "j-1", status=blocking_status, rank=3),
        _database_listing("jobsdb", "j-1", status="pending", rank=4),
    ]
    with Session(engine) as db:
        db.add_all(rows)
        db.commit()
        repository = CrawlJobListingRepository()

        offertoday_rows = repository.list_detail_candidates(
            db,
            source_site="offertoday",
            limit=None,
        )
        jobsdb_rows = repository.list_detail_candidates(
            db,
            source_site="jobsdb",
            limit=None,
        )

    assert offertoday_rows == []
    assert [row.detail_status for row in jobsdb_rows] == ["pending"]


def test_terminal_unavailable_is_supported_but_not_retried_by_default():
    assert "terminal_unavailable" in SUPPORTED_DETAIL_STATUSES
    assert "terminal_unavailable" not in DEFAULT_DETAIL_RETRY_STATUSES


@pytest.mark.parametrize(
    "detail_status",
    [
        "failed",
        "manual_action_required",
        "terminal_unavailable",
        "identity_conflict",
    ],
)
def test_repository_mark_detail_outcome_is_transactional_and_does_not_increment_attempts(
    detail_status,
):
    engine = create_engine("sqlite://")
    CrawlJobListing.__table__.create(engine)
    row = _database_listing(
        "offertoday",
        "j-outcome",
        status="running",
        rank=1,
    )
    row.detail_attempts = 2
    row_id = row.id
    detail_crawl_job_id = uuid4()

    with Session(engine) as db:
        db.add(row)
        db.commit()

        transitioned = CrawlJobListingRepository().mark_detail_outcome(
            db,
            listing_id=row_id,
            detail_crawl_job_id=detail_crawl_job_id,
            detail_status=detail_status,
            error_message="classified outcome",
            detail_payload={"code": 2520},
            auto_commit=False,
        )

        assert transitioned.detail_status == detail_status
        assert transitioned.detail_attempts == 2
        assert transitioned.last_detail_crawl_job_id == detail_crawl_job_id
        assert transitioned.detail_error_message == "classified outcome"
        assert transitioned.detail_payload == {"code": 2520}
        db.rollback()
        restored = db.get(CrawlJobListing, row_id)
        assert restored.detail_status == "running"
        assert restored.detail_attempts == 2
        assert restored.last_detail_crawl_job_id is None


def test_repository_mark_detail_outcome_rejects_noncanonical_status():
    engine = create_engine("sqlite://")
    CrawlJobListing.__table__.create(engine)
    row = _database_listing("offertoday", "j-invalid", status="running", rank=1)
    row_id = row.id

    with Session(engine) as db:
        db.add(row)
        db.commit()

        with pytest.raises(ValueError, match="detail outcome status"):
            CrawlJobListingRepository().mark_detail_outcome(
                db,
                listing_id=row_id,
                detail_crawl_job_id=uuid4(),
                detail_status="completed",
                error_message="must be rejected",
                auto_commit=False,
            )

        db.rollback()
        assert db.get(CrawlJobListing, row_id).detail_status == "running"


def test_repository_and_runtime_outcome_helpers_accept_status_keyword_contract():
    rows = [_detail_listing("authoritative", "j-1", rank=1)]
    runtime, _repository, _crawl_jobs, session = _detail_runtime(rows)

    runtime.transition_detail_outcome(
        session,
        listing_ids=("authoritative",),
        detail_crawl_job_id="detail-run",
        status="failed",
        error_message="classified failure",
    )

    assert rows[0].detail_status == "failed"


def test_runtime_no_commit_detail_helpers_fan_out_without_duplicate_attempts():
    rows = [
        _detail_listing("authoritative", "j-1", rank=1),
        _detail_listing("duplicate", "j-1", rank=2),
    ]
    runtime, _repository, crawl_jobs, session = _detail_runtime(rows)

    running = runtime.transition_detail_running(
        session,
        listing_id="authoritative",
        detail_crawl_job_id="detail-run",
    )

    assert running.id == "authoritative"
    assert session.commits == 0
    assert rows[0].detail_status == "running"
    assert rows[0].detail_attempts == 1
    assert rows[1].detail_status == "pending"
    assert rows[1].detail_attempts == 0
    session.commit()

    completed = runtime.transition_detail_completed(
        session,
        listing_ids=("authoritative", "duplicate"),
        detail_crawl_job_id="detail-run",
        detail_payload={"jobId": "j-1"},
        published_job_id="published-j-1",
    )

    assert [listing.id for listing in completed] == ["authoritative", "duplicate"]
    assert session.commits == 1
    assert [row.detail_status for row in rows] == ["completed", "completed"]
    assert [row.detail_attempts for row in rows] == [1, 0]
    assert all(row.published_job_id == "published-j-1" for row in rows)
    session.rollback()
    assert [row.detail_status for row in rows] == ["running", "pending"]

    outcomes = runtime.transition_detail_outcome(
        session,
        listing_ids=("authoritative", "duplicate"),
        detail_crawl_job_id="detail-run",
        detail_status="terminal_unavailable",
        error_message="code=2520",
        detail_payload={"code": 2520},
    )

    assert [listing.id for listing in outcomes] == ["authoritative", "duplicate"]
    assert session.commits == 1
    assert [row.detail_status for row in rows] == [
        "terminal_unavailable",
        "terminal_unavailable",
    ]
    assert [row.detail_attempts for row in rows] == [1, 0]
    assert crawl_jobs.jobs["detail-run"].metrics[
        "detail_run_terminal_unavailable"
    ] == 2


@pytest.mark.parametrize(
    ("transition", "terminal_status"),
    [("completed", "completed"), ("outcome", "terminal_unavailable")],
)
def test_duplicate_group_terminal_transition_prevents_pending_sibling_reload(
    transition,
    terminal_status,
):
    rows = [
        _detail_listing("authoritative", "j-1", rank=1),
        _detail_listing("duplicate", "j-1", rank=2),
    ]
    runtime, repository, _crawl_jobs, session = _detail_runtime(rows)

    if transition == "completed":
        runtime.transition_detail_completed(
            session,
            listing_ids=("authoritative", "duplicate"),
            detail_crawl_job_id="detail-run",
            detail_payload={"jobId": "j-1"},
            published_job_id="published-j-1",
        )
    else:
        runtime.transition_detail_outcome(
            session,
            listing_ids=("authoritative", "duplicate"),
            detail_crawl_job_id="detail-run",
            detail_status=terminal_status,
            error_message="terminal",
        )
    session.commit()

    reloaded = repository.list_detail_candidates(
        session,
        source_site="offertoday",
        source_listing_crawl_job_id="batch-1",
        statuses=DEFAULT_DETAIL_RETRY_STATUSES,
        limit=None,
    )

    assert reloaded == []
    assert [row.detail_status for row in rows] == [terminal_status, terminal_status]
