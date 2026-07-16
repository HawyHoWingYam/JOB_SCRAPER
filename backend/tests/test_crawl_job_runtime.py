from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.crawl_cancellation_token import CrawlCancellationToken
from app.services.crawl_job_cancellation_service import CrawlJobCancellationService
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService


class _Db:
    def commit(self) -> None:
        return None

    def refresh(self, _row) -> None:
        return None

    def expire_all(self) -> None:
        return None


class _CrawlRepository:
    def __init__(self, job) -> None:
        self.job = job
        self.events: list[dict] = []

    def get_crawl_job_by_id_for_update(self, _db, _crawl_job_id):
        return self.job

    def get_crawl_job_by_id(self, _db, _crawl_job_id):
        return self.job

    def append_event(self, _db, **kwargs) -> None:
        self.events.append(kwargs)


class _ExecutionRepository:
    @staticmethod
    def get_latest_active_for_job(_db, _crawl_job_id, *, for_update=False):
        assert for_update is True
        return None


class _Launcher:
    def __init__(self, job) -> None:
        self.job = job
        self.cancel_requests = 0
        self.acknowledgements = 0

    def request_cancel(self, *, crawl_job_id) -> bool:
        self.cancel_requests += 1
        return False

    def acknowledge_without_execution(self, *, crawl_job_id, reason) -> bool:
        self.acknowledgements += 1
        self.job.status = "cancelled"
        return True


def _service(job):
    repository = _CrawlRepository(job)
    launcher = _Launcher(job)
    service = CrawlJobDispatchService(
        crawl_job_repository=repository,
        execution_launcher=launcher,
    )
    service.execution_repository = _ExecutionRepository()
    return service, repository, launcher


def test_queued_cancel_without_execution_is_acknowledged_immediately() -> None:
    job = SimpleNamespace(
        id="job-id",
        status="queued",
        trigger_type="manual",
        schedule_id=None,
        completed_at=None,
        error_message=None,
        source_site="jobsdb",
        request_payload={"crawl_phase": "detail", "crawl_mode": "headed"},
    )
    service, repository, launcher = _service(job)

    result = service.cancel_crawl_job(_Db(), crawl_job_id=job.id)

    assert result.status == "cancelled"
    assert launcher.acknowledgements == 1
    assert [event["event_type"] for event in repository.events] == [
        "crawl.cancel_requested"
    ]


def test_repeated_cancel_recovers_cancelling_job_without_execution() -> None:
    job = SimpleNamespace(
        id="job-id",
        status="cancelling",
        trigger_type="manual",
        schedule_id=None,
        error_message="operator cancelled",
    )
    service, _repository, launcher = _service(job)

    result = service.cancel_crawl_job(_Db(), crawl_job_id=job.id)

    assert result.status == "cancelled"
    assert launcher.cancel_requests == 1
    assert launcher.acknowledgements == 1


def test_schedule_backed_task_is_not_cancellable() -> None:
    job = SimpleNamespace(
        id="job-id",
        status="running",
        trigger_type="schedule",
        schedule_id="schedule-id",
    )
    service, _repository, _launcher = _service(job)

    with pytest.raises(RuntimeError, match="cannot be cancelled"):
        service.cancel_crawl_job(_Db(), crawl_job_id=job.id)


@pytest.mark.asyncio
async def test_cancellation_sleep_checks_in_at_most_one_second_slices(
    monkeypatch,
) -> None:
    token = CrawlCancellationToken(crawl_job_id=None)
    checks: list[None] = []
    sleeps: list[float] = []
    token.raise_if_cancelled = lambda: checks.append(None)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(
        "app.services.crawl_cancellation_token.asyncio.sleep", fake_sleep
    )

    await token.sleep(2.4)

    assert sleeps == [1.0, 1.0, pytest.approx(0.4)]
    assert len(checks) == 4


def test_acknowledgement_preserves_metrics_marks_listing_partial_and_orders_events() -> (
    None
):
    job = SimpleNamespace(
        id="job-id",
        status="cancelling",
        source_site="jobsdb",
        request_payload={"crawl_phase": "listing"},
        metrics={"job_ids_collected": 42},
        completed_at=None,
        error_message=None,
    )
    repository = _CrawlRepository(job)
    service = CrawlJobCancellationService(
        session_factory=lambda: _CancellationDb(),
        crawl_job_repository=repository,
    )
    service._release_running_detail_rows = lambda *_args, **_kwargs: [
        {"listing_id": "listing-id", "after_status": "pending"}
    ]

    assert service.acknowledge_cancelled(
        crawl_job_id=job.id,
        execution_generation="generation-id",
    )

    assert job.status == "cancelled"
    assert job.metrics == {
        "job_ids_collected": 42,
        "listing_completed": False,
        "listing_partial": True,
    }
    assert [event["event_type"] for event in repository.events] == [
        "crawl.cancelled",
        "crawl.detail_cancelled_recovered",
    ]


class _CancellationDb:
    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None
