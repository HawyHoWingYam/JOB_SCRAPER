from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.crawl_job_runtime import (
    CrawlJobRuntime,
    OfferTodayListingIdentityConflictError,
)


HISTORICAL_DETAIL_STATUSES = (
    "pending",
    "running",
    "completed",
    "failed",
    "skipped",
    "manual_action_required",
    "identity_conflict",
    "terminal_unavailable",
)


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        return None


class _ListingRepository:
    def __init__(
        self,
        *,
        source_rows: list[SimpleNamespace] | None = None,
        fail_existing_lookup: bool = False,
    ) -> None:
        self.rows: list[SimpleNamespace] = []
        self.source_rows = list(source_rows or [])
        self.fail_existing_lookup = fail_existing_lookup
        self.existing_lookup_calls: list[dict] = []

    def acquire_offertoday_staging_lock(self, _db) -> None:
        return None

    def list_existing_source_job_ids(self, _db, **kwargs):
        self.existing_lookup_calls.append(dict(kwargs))
        if self.fail_existing_lookup:
            raise RuntimeError("historical listing lookup failed")
        excluded_crawl_job_id = kwargs.get("exclude_crawl_job_id")
        source_job_ids = set(kwargs["source_job_ids"])
        return {
            row.source_job_id
            for row in [*self.source_rows, *self.rows]
            if row.source_site == kwargs["source_site"]
            and row.source_job_id in source_job_ids
            and row.crawl_job_id != excluded_crawl_job_id
        }

    def list_source_rows_by_job_ids(self, _db, **kwargs):
        source_job_ids = set(kwargs["source_job_ids"])
        return [
            row
            for row in [*self.source_rows, *self.rows]
            if row.source_site == kwargs["source_site"]
            and row.source_job_id in source_job_ids
        ]

    def get_max_listing_rank_for_crawl_job(self, _db, **_kwargs) -> int:
        return 0

    def upsert_listing(self, _db, **kwargs):
        for row in [*self.source_rows, *self.rows]:
            if (
                row.crawl_job_id == kwargs["crawl_job_id"]
                and row.source_site == kwargs["source_site"]
                and row.source_job_id == kwargs["source_job_id"]
            ):
                return row, "updated"
        row = SimpleNamespace(
            id=f"row-{len(self.rows) + 1}",
            detail_status="pending",
            **{
                key: value
                for key, value in kwargs.items()
                if key not in {"auto_commit"}
            },
        )
        self.rows.append(row)
        return row, "created"

    def count_detail_statuses(self, _db, **_kwargs):
        return {"pending": len(self.rows)}


class _DetailListingRepository:
    def __init__(self, row: SimpleNamespace) -> None:
        self.row = row
        self.completed: list[dict] = []

    def list_detail_candidates(self, _db, **_kwargs):
        return [self.row]

    def list_offertoday_identity_history(self, _db):
        return [self.row]

    def mark_detail_completed(self, _db, **kwargs) -> None:
        self.completed.append(dict(kwargs))
        self.row.detail_status = "completed"
        self.row.published_job_id = kwargs["published_job_id"]

    def count_detail_statuses_for_detail_crawl_job(self, _db, **_kwargs):
        return {"completed": 1}


class _CrawlJobRepository:
    def __init__(self, *, trigger_type: str = "manual") -> None:
        self.crawl_job = SimpleNamespace(
            id="listing-task",
            metrics={},
            trigger_type=trigger_type,
        )
        self.events: list[dict] = []

    def get_crawl_job_by_id(self, _db, _crawl_job_id):
        return self.crawl_job

    def merge_metrics(self, _db, *, metrics_patch, **_kwargs) -> None:
        self.crawl_job.metrics.update(metrics_patch)

    def append_event(self, _db, **kwargs) -> None:
        self.events.append(dict(kwargs))

    def list_offertoday_listing_identity_observations(self, _db):
        return []


class _JobRepository:
    def __init__(self, existing: dict[str, object] | None = None) -> None:
        self.existing = dict(existing or {})
        self.calls: list[dict] = []

    def list_existing_jobs_by_source_ids(self, _db, **kwargs):
        self.calls.append(dict(kwargs))
        return {
            source_job_id: self.existing[source_job_id]
            for source_job_id in kwargs["source_job_ids"]
            if source_job_id in self.existing
        }


class _FailingJobRepository(_JobRepository):
    def list_existing_jobs_by_source_ids(self, _db, **kwargs):
        self.calls.append(dict(kwargs))
        raise RuntimeError("published Job lookup failed")


def _payload(source_job_id: str, *, source_site: str) -> dict:
    listing_payload = {}
    if source_site == "offertoday":
        listing_payload = {
            "jobId": source_job_id,
            "encryptJobId": f"encrypted-{source_job_id}",
        }
    return {
        "source_job_id": source_job_id,
        "source_url": f"https://example.test/{source_site}/{source_job_id}",
        "source_classification_id": f"{source_site}:classification",
        "source_classification_name": "Classification",
        "listing_page": 1,
        "listing_payload": listing_payload,
    }


def _listing_row(
    source_job_id: str,
    *,
    source_site: str,
    crawl_job_id: str = "historical-task",
    detail_status: str = "pending",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"{crawl_job_id}-{source_site}-{source_job_id}",
        crawl_job_id=crawl_job_id,
        source_site=source_site,
        source_job_id=source_job_id,
        detail_status=detail_status,
        listing_payload=_payload(
            source_job_id,
            source_site=source_site,
        )["listing_payload"],
    )


def _runtime(
    *,
    job_repository,
    listing_repository: _ListingRepository | None = None,
    trigger_type: str = "manual",
):
    session = _Session()
    listing_repository = listing_repository or _ListingRepository()
    crawl_job_repository = _CrawlJobRepository(trigger_type=trigger_type)
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=crawl_job_repository,
        crawl_job_listing_repository=listing_repository,
        job_repository=job_repository,
    )
    return runtime, session, listing_repository, crawl_job_repository


@pytest.mark.parametrize(
    ("source_site", "detail_status"),
    [
        (source_site, detail_status)
        for source_site in ("jobsdb", "ctgoodjobs", "offertoday")
        for detail_status in HISTORICAL_DETAIL_STATUSES
        if not (
            source_site == "offertoday"
            and detail_status == "identity_conflict"
        )
    ],
)
def test_manual_listing_skips_identity_owned_by_historical_task(
    source_site: str,
    detail_status: str,
) -> None:
    listing_repository = _ListingRepository(
        source_rows=[
            _listing_row(
                "historical",
                source_site=source_site,
                detail_status=detail_status,
            )
        ]
    )
    runtime, session, listing_repository, crawl_job_repository = _runtime(
        job_repository=_JobRepository(),
        listing_repository=listing_repository,
    )

    result = runtime.stage_listing_batch(
        crawl_job_id="listing-task",
        source_site=source_site,
        payloads=[
            _payload("historical", source_site=source_site),
            _payload("new", source_site=source_site),
        ],
        skip_existing=False,
    )

    assert listing_repository.existing_lookup_calls == [
        {
            "source_site": source_site,
            "source_job_ids": ["historical", "new"],
            "exclude_crawl_job_id": "listing-task",
        }
    ]
    assert result.historical_source_job_ids == ("historical",)
    assert result.created_source_job_ids == ("new",)
    assert result.skipped_existing == 1
    assert [row.source_job_id for row in listing_repository.rows] == ["new"]
    assert crawl_job_repository.crawl_job.metrics["jobs_skipped_existing"] == 1
    assert session.commits == 1
    assert session.rollbacks == 0


def test_offertoday_historical_identity_conflict_remains_a_hard_stop() -> None:
    listing_repository = _ListingRepository(
        source_rows=[
            _listing_row(
                "historical",
                source_site="offertoday",
                detail_status="identity_conflict",
            )
        ]
    )
    runtime, session, listing_repository, _crawl_job_repository = _runtime(
        job_repository=_JobRepository(),
        listing_repository=listing_repository,
    )

    with pytest.raises(OfferTodayListingIdentityConflictError):
        runtime.stage_listing_batch(
            crawl_job_id="listing-task",
            source_site="offertoday",
            payloads=[_payload("historical", source_site="offertoday")],
            skip_existing=False,
        )

    assert listing_repository.rows == []
    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.parametrize("source_site", ["jobsdb", "ctgoodjobs", "offertoday"])
def test_scheduled_listing_does_not_skip_historical_identity(
    source_site: str,
) -> None:
    listing_repository = _ListingRepository(
        source_rows=[_listing_row("historical", source_site=source_site)]
    )
    runtime, _session, listing_repository, _crawl_job_repository = _runtime(
        job_repository=_JobRepository(),
        listing_repository=listing_repository,
        trigger_type="schedule",
    )

    result = runtime.stage_listing_batch(
        crawl_job_id="listing-task",
        source_site=source_site,
        payloads=[_payload("historical", source_site=source_site)],
        skip_existing=False,
    )

    assert listing_repository.existing_lookup_calls == []
    assert result.historical_source_job_ids == ()
    assert result.created_source_job_ids == ("historical",)


@pytest.mark.parametrize("source_site", ["jobsdb", "ctgoodjobs", "offertoday"])
def test_manual_listing_historical_lookup_is_source_aware(
    source_site: str,
) -> None:
    other_source = "ctgoodjobs" if source_site == "jobsdb" else "jobsdb"
    listing_repository = _ListingRepository(
        source_rows=[_listing_row("shared", source_site=other_source)]
    )
    runtime, _session, listing_repository, _crawl_job_repository = _runtime(
        job_repository=_JobRepository(),
        listing_repository=listing_repository,
    )

    result = runtime.stage_listing_batch(
        crawl_job_id="listing-task",
        source_site=source_site,
        payloads=[_payload("shared", source_site=source_site)],
        skip_existing=False,
    )

    assert result.historical_source_job_ids == ()
    assert result.created_source_job_ids == ("shared",)


@pytest.mark.parametrize("source_site", ["jobsdb", "ctgoodjobs", "offertoday"])
def test_manual_listing_current_task_row_is_not_historical(
    source_site: str,
) -> None:
    listing_repository = _ListingRepository(
        source_rows=[
            _listing_row(
                "current",
                source_site=source_site,
                crawl_job_id="listing-task",
            )
        ]
    )
    runtime, _session, listing_repository, _crawl_job_repository = _runtime(
        job_repository=_JobRepository(),
        listing_repository=listing_repository,
    )

    result = runtime.stage_listing_batch(
        crawl_job_id="listing-task",
        source_site=source_site,
        payloads=[_payload("current", source_site=source_site)],
        skip_existing=False,
    )

    assert result.historical_source_job_ids == ()
    assert result.created_source_job_ids == ()


@pytest.mark.parametrize("source_site", ["jobsdb", "ctgoodjobs", "offertoday"])
def test_manual_listing_fails_closed_when_historical_lookup_fails(
    source_site: str,
) -> None:
    listing_repository = _ListingRepository(fail_existing_lookup=True)
    runtime, session, listing_repository, _crawl_job_repository = _runtime(
        job_repository=_JobRepository(),
        listing_repository=listing_repository,
    )

    with pytest.raises(RuntimeError, match="historical listing lookup failed"):
        runtime.stage_listing_batch(
            crawl_job_id="listing-task",
            source_site=source_site,
            payloads=[_payload("candidate", source_site=source_site)],
            skip_existing=False,
        )

    assert listing_repository.rows == []
    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.parametrize("source_site", ["jobsdb", "ctgoodjobs"])
def test_stage_listing_batch_skips_published_jobs_even_for_legacy_false_payload(
    source_site: str,
) -> None:
    existing = SimpleNamespace(
        source_site=source_site,
        source_job_id="existing",
        raw_data={},
    )
    job_repository = _JobRepository({"existing": existing})
    runtime, session, listing_repository, crawl_job_repository = _runtime(
        job_repository=job_repository
    )

    result = runtime.stage_listing_batch(
        crawl_job_id="listing-task",
        source_site=source_site,
        payloads=[
            _payload("existing", source_site=source_site),
            _payload("new", source_site=source_site),
        ],
        skip_existing=False,
    )

    assert job_repository.calls == [
        {
            "source_site": source_site,
            "source_job_ids": ["existing", "new"],
            "raise_on_error": True,
        }
    ]
    assert result.published_source_job_ids == ("existing",)
    assert result.created_source_job_ids == ("new",)
    assert result.skipped_existing == 1
    assert [row.source_job_id for row in listing_repository.rows] == ["new"]
    assert crawl_job_repository.crawl_job.metrics["jobs_skipped_existing"] == 1
    assert session.commits == 1
    assert session.rollbacks == 0


def test_offertoday_skips_incomplete_published_job_instead_of_staging_repair() -> None:
    existing = SimpleNamespace(
        id="published-id",
        source_site="offertoday",
        source_job_id="existing",
        title="",
        description="",
        company_id=None,
        raw_data={"jobId": "existing", "encryptJobId": "encrypted-existing"},
    )
    job_repository = _JobRepository({"existing": existing})
    runtime, _session, listing_repository, _crawl_job_repository = _runtime(
        job_repository=job_repository
    )

    result = runtime.stage_listing_batch(
        crawl_job_id="listing-task",
        source_site="offertoday",
        payloads=[_payload("existing", source_site="offertoday")],
        skip_existing=False,
    )

    assert result.published_source_job_ids == ("existing",)
    assert result.complete_existing_source_job_ids == ()
    assert result.repair_source_job_ids == ()
    assert result.created_source_job_ids == ()
    assert result.skipped_existing == 1
    assert listing_repository.rows == []


@pytest.mark.parametrize("source_site", ["jobsdb", "ctgoodjobs", "offertoday"])
def test_stage_listing_batch_fails_closed_when_published_job_lookup_fails(
    source_site: str,
) -> None:
    job_repository = _FailingJobRepository()
    runtime, session, listing_repository, _crawl_job_repository = _runtime(
        job_repository=job_repository
    )

    with pytest.raises(RuntimeError, match="published Job lookup failed"):
        runtime.stage_listing_batch(
            crawl_job_id="listing-task",
            source_site=source_site,
            payloads=[_payload("candidate", source_site=source_site)],
            skip_existing=False,
        )

    assert job_repository.calls[0]["raise_on_error"] is True
    assert listing_repository.rows == []
    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.parametrize("source_site", ["jobsdb", "ctgoodjobs", "offertoday"])
def test_detail_loader_reconciles_published_jobs_even_for_legacy_false_payload(
    source_site: str,
) -> None:
    listing_payload = (
        {"jobId": "existing", "encryptJobId": "encrypted-existing"}
        if source_site == "offertoday"
        else {}
    )
    row = SimpleNamespace(
        id="listing-row",
        crawl_job_id="listing-task",
        source_site=source_site,
        source_job_id="existing",
        source_url=f"https://example.test/{source_site}/existing",
        source_classification_id=None,
        source_classification_name=None,
        listing_payload=listing_payload,
        detail_payload={},
        detail_status="pending",
        published_job_id=None,
    )
    existing = SimpleNamespace(
        id="published-id",
        source_site=source_site,
        source_job_id="existing",
        title="",
        description="",
        company_id=None,
        raw_data=listing_payload,
    )
    session = _Session()
    listing_repository = _DetailListingRepository(row)
    crawl_job_repository = _CrawlJobRepository()
    job_repository = _JobRepository({"existing": existing})
    runtime = CrawlJobRuntime(
        lambda: session,
        crawl_job_repository=crawl_job_repository,
        crawl_job_listing_repository=listing_repository,
        job_repository=job_repository,
    )

    result = runtime.load_detail_targets(
        source_site=source_site,
        request_payload={
            "crawl_phase": "detail",
            "detail_scope": "global" if source_site == "offertoday" else "",
            "detail_statuses": ["pending"],
            "skip_existing": False,
        },
        detail_crawl_job_id="detail-task",
    )

    assert job_repository.calls == [
        {
            "source_site": source_site,
            "source_job_ids": ["existing"],
            "raise_on_error": True,
        }
    ]
    assert result.target_rows == 0
    assert result.reconciled_rows == 1
    assert result.reconciled_source_job_ids == ("existing",)
    assert listing_repository.completed[0]["published_job_id"] == "published-id"
    assert session.commits == 1
    assert session.rollbacks == 0
