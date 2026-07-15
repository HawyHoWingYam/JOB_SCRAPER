from __future__ import annotations

from types import SimpleNamespace

from app.services.crawl_job_runtime import CrawlJobRuntime


class _FakeDb:
    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


class _FakeCrawlJobRepository:
    def __init__(self) -> None:
        self.metrics_patch = None

    def merge_metrics(self, _db, *, metrics_patch, **_kwargs) -> None:
        self.metrics_patch = dict(metrics_patch)

    def get_crawl_job_by_id(self, *_args, **_kwargs):
        return SimpleNamespace(metrics={})


class _FakeListingRepository:
    def count_detail_statuses(self, *_args, **_kwargs):
        return {}

    def get_max_listing_rank_for_crawl_job(self, *_args, **_kwargs):
        return 0

    def upsert_listing(self, _db, **_kwargs):
        return SimpleNamespace(), "created"


def test_stage_listing_batch_tracks_raw_and_distinct_job_ids_separately() -> None:
    crawl_job_repository = _FakeCrawlJobRepository()
    runtime = CrawlJobRuntime(
        db_session_factory=_FakeDb,
        crawl_job_repository=crawl_job_repository,
        crawl_job_listing_repository=_FakeListingRepository(),
        job_repository=object(),
    )

    result = runtime.stage_listing_batch(
        crawl_job_id="crawl-task",
        source_site="jobsdb",
        payloads=[
            {"source_job_id": "job-1"},
            {"source_job_id": "job-1"},
            {"source_job_id": "  "},
            {},
        ],
        skip_existing=False,
    )

    assert result.raw_job_ids_seen == 2
    assert result.job_ids_seen == 1
    assert crawl_job_repository.metrics_patch["raw_job_ids_collected"] == 2
