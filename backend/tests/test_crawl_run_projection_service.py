"""Tests for the CrawlRun projection service."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.crawl_run_projection_service import CrawlRunProjectionService


class FakeCrawlRunRepository:
    def __init__(self) -> None:
        self._runs: dict = {}

    def create(self, db, *, crawl_run) -> object:
        self._runs[crawl_run.id] = crawl_run
        return crawl_run

    def get_by_id(self, db, run_id) -> object | None:
        return self._runs.get(run_id)

    def update_status(self, db, run_id, *, status) -> object | None:
        run = self._runs.get(run_id)
        if run:
            run.status = status
        return run

    def update_progress(self, db, run_id, **kwargs) -> object | None:
        run = self._runs.get(run_id)
        if run is None:
            return None
        for key, value in kwargs.items():
            setattr(run, key, value)
        return run


class FakeDB:
    def __init__(self) -> None:
        self.flush_called = False

    def flush(self) -> None:
        self.flush_called = True

    def add(self, obj: object) -> None:
        pass


class TestCrawlRunProjectionService:
    def setup_method(self) -> None:
        self.repo = FakeCrawlRunRepository()
        self.service = CrawlRunProjectionService(repository=self.repo)
        self.db = FakeDB()

    def test_create_run(self) -> None:
        run = self.service.create_run(
            self.db,
            crawl_job_id=uuid4(),
            source_site="offertoday",
            scrapyd_spider="offertoday",
            scrapyd_job_id="scrapyd-abc",
        )
        assert run.source_site == "offertoday"
        assert run.scrapyd_job_id == "scrapyd-abc"
        assert run.status == "pending"
        assert run.pages_processed is None or run.pages_processed == 0
        assert run.listings_staged is None or run.listings_staged == 0

    def test_create_run_with_payload(self) -> None:
        run = self.service.create_run(
            self.db,
            crawl_job_id=uuid4(),
            source_site="jobsdb",
            scrapyd_spider="jobsdb",
            request_payload={"max_pages": 5, "category_ids": ["6281"]},
        )
        import json

        assert run.request_payload is not None
        payload = json.loads(run.request_payload)
        assert payload["max_pages"] == 5

    def test_mark_started(self) -> None:
        run = self.service.create_run(self.db, crawl_job_id=uuid4(), source_site="test", scrapyd_spider="test")
        run_id = run.id
        self.repo._runs[run_id] = run

        updated = self.service.mark_started(self.db, run_id)
        assert updated is not None
        assert updated.status == "running"

    def test_mark_started_not_found(self) -> None:
        result = self.service.mark_started(self.db, uuid4())
        assert result is None

    def test_mark_completed(self) -> None:
        run = self.service.create_run(self.db, crawl_job_id=uuid4(), source_site="test", scrapyd_spider="test")
        run.status = "running"
        run_id = run.id
        self.repo._runs[run_id] = run

        updated = self.service.mark_completed(self.db, run_id)
        assert updated is not None
        assert updated.status == "completed"

    def test_mark_failed(self) -> None:
        run = self.service.create_run(self.db, crawl_job_id=uuid4(), source_site="test", scrapyd_spider="test")
        run.status = "running"
        run_id = run.id
        self.repo._runs[run_id] = run

        updated = self.service.mark_failed(self.db, run_id)
        assert updated is not None
        assert updated.status == "failed"

    def test_mark_cancelled(self) -> None:
        run = self.service.create_run(self.db, crawl_job_id=uuid4(), source_site="test", scrapyd_spider="test")
        run.status = "running"
        run_id = run.id
        self.repo._runs[run_id] = run

        updated = self.service.mark_cancelled(self.db, run_id)
        assert updated is not None
        assert updated.status == "cancelled"

    def test_update_progress(self) -> None:
        run = self.service.create_run(self.db, crawl_job_id=uuid4(), source_site="test", scrapyd_spider="test")
        run_id = run.id
        self.repo._runs[run_id] = run

        updated = self.service.update_progress(
            self.db,
            run_id,
            pages_processed=10,
            listings_staged=50,
            details_completed=20,
            details_failed=2,
        )
        assert updated is not None
        assert updated.pages_processed == 10
        assert updated.listings_staged == 50
        assert updated.details_completed == 20
        assert updated.details_failed == 2

    def test_full_lifecycle(self) -> None:
        """Simulate a full crawl run lifecycle."""
        run = self.service.create_run(
            self.db,
            crawl_job_id=uuid4(),
            source_site="offertoday",
            scrapyd_spider="offertoday",
        )
        run_id = run.id
        self.repo._runs[run_id] = run

        assert run.status == "pending"

        self.service.mark_started(self.db, run_id)
        assert self.repo._runs[run_id].status == "running"

        self.service.update_progress(self.db, run_id, pages_processed=5, listings_staged=25)
        assert self.repo._runs[run_id].pages_processed == 5

        self.service.update_progress(self.db, run_id, details_completed=10)
        assert self.repo._runs[run_id].details_completed == 10

        self.service.mark_completed(self.db, run_id)
        assert self.repo._runs[run_id].status == "completed"
