"""Tests for the crawl-admin API endpoints."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import crawl_admin
from app.database import get_db


def _build_run():
    now = datetime.utcnow()
    return SimpleNamespace(
        id=uuid4(),
        crawl_job_id=uuid4(),
        source_site="offertoday",
        scrapyd_project="job_scraper_spiders",
        scrapyd_spider="offertoday",
        scrapyd_job_id=None,
        status="pending",
        pages_processed=0,
        listings_staged=0,
        details_completed=0,
        details_failed=0,
        created_at=now,
        started_at=None,
        completed_at=None,
        request_payload=None,
    )


# Test DB stub
def _make_fake_db():
    return SimpleNamespace(commit=lambda: None, flush=lambda: None)


class FakeScrapydClient:
    def __init__(self) -> None:
        self.next_job_id = "scrapyd-job-001"
        self.daemon_available = True

    def daemon_status(self) -> dict:
        if not self.daemon_available:
            raise ConnectionError("Scrapyd unavailable")
        return {
            "status": "ok",
            "node_name": "test-node",
            "pending": 1,
            "running": 1,
            "finished": 5,
        }

    def schedule(self, project: str, spider: str, **spider_args: str) -> str:
        return self.next_job_id

    def cancel(self, project: str, job_id: str) -> bool:
        return True


class FakeCrawlRunRepository:
    def __init__(self) -> None:
        self._runs: dict = {}
        self._id_counter = 0

    def create(self, db, *, crawl_run) -> object:
        self._runs[crawl_run.id] = crawl_run
        return crawl_run

    def get_by_id(self, db, run_id) -> object | None:
        return self._runs.get(run_id)

    def get_by_crawl_job_id(self, db, crawl_job_id) -> list:
        return [r for r in self._runs.values() if str(r.crawl_job_id) == str(crawl_job_id)]

    def list_by_source(self, db, source_site: str, limit: int = 20) -> list:
        if source_site:
            return [r for r in self._runs.values() if r.source_site == source_site][:limit]
        return list(self._runs.values())[:limit]

    def update_status(self, db, run_id, *, status) -> object | None:
        run = self._runs.get(run_id)
        if run:
            run.status = status
        return run

    def delete(self, db, run_id) -> bool:
        return self._runs.pop(run_id, None) is not None


# --- Test app setup ---


def _make_app(fake_repo: FakeCrawlRunRepository, fake_client: object | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(crawl_admin.router, prefix="/api/v1")

    # Override global dependencies
    crawl_admin._scrapyd_client = fake_client or FakeScrapydClient()
    crawl_admin._repo = fake_repo
    crawl_admin._projection._repository = fake_repo

    # Override DB dependency to return fake db
    fake_db = _make_fake_db()

    async def _override_db():
        return fake_db

    app.dependency_overrides[get_db] = _override_db
    return app


class TestCrawlAdminStatus:
    def test_status_returns_scrapyd_info(self) -> None:
        app = _make_app(FakeCrawlRunRepository())
        client = TestClient(app)
        resp = client.get("/api/v1/crawl-admin/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scrapyd_available"] is True
        assert data["scrapyd_node_name"] == "test-node"

    def test_status_scrapyd_unavailable(self) -> None:
        fake_client = FakeScrapydClient()
        fake_client.daemon_available = False
        app = _make_app(FakeCrawlRunRepository(), fake_client=fake_client)
        client = TestClient(app)
        resp = client.get("/api/v1/crawl-admin/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scrapyd_available"] is False


class TestCrawlAdminSchedule:
    def test_schedule_creates_run(self) -> None:
        fake_repo = FakeCrawlRunRepository()
        app = _make_app(fake_repo)
        client = TestClient(app)

        crawl_job_id = str(uuid4())
        resp = client.post(
            "/api/v1/crawl-admin/schedule",
            json={
                "crawl_job_id": crawl_job_id,
                "source_site": "offertoday",
                "scrapyd_spider": "offertoday",
            },
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["source_site"] == "offertoday"
        assert data["scrapyd_spider"] == "offertoday"
        assert data["scrapyd_job_id"] == "scrapyd-job-001"
        assert data["status"] == "pending"
        assert len(fake_repo._runs) == 1

    def test_schedule_invalid_no_body(self) -> None:
        app = _make_app(FakeCrawlRunRepository())
        client = TestClient(app)
        resp = client.post("/api/v1/crawl-admin/schedule", json={})
        assert resp.status_code == 422


class TestCrawlAdminCancel:
    def test_cancel_existing_run(self) -> None:
        fake_repo = FakeCrawlRunRepository()
        run = _build_run()
        run.scrapyd_job_id = "scrapyd-job-001"
        fake_repo._runs[run.id] = run

        app = _make_app(fake_repo)
        client = TestClient(app)

        resp = client.post(f"/api/v1/crawl-admin/cancel/{run.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"

    def test_cancel_not_found(self) -> None:
        app = _make_app(FakeCrawlRunRepository())
        client = TestClient(app)
        resp = client.post(f"/api/v1/crawl-admin/cancel/{uuid4()}")
        assert resp.status_code == 404


class TestCrawlAdminListRuns:
    def test_list_empty(self) -> None:
        app = _make_app(FakeCrawlRunRepository())
        client = TestClient(app)
        resp = client.get("/api/v1/crawl-admin/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_runs(self) -> None:
        fake_repo = FakeCrawlRunRepository()
        run1 = _build_run()
        run1.source_site = "offertoday"
        run2 = _build_run()
        run2.source_site = "jobsdb"
        fake_repo._runs[run1.id] = run1
        fake_repo._runs[run2.id] = run2

        app = _make_app(fake_repo)
        client = TestClient(app)

        resp = client.get("/api/v1/crawl-admin/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_list_filtered_by_source(self) -> None:
        fake_repo = FakeCrawlRunRepository()
        run1 = _build_run()
        run1.source_site = "offertoday"
        run2 = _build_run()
        run2.source_site = "jobsdb"
        fake_repo._runs[run1.id] = run1
        fake_repo._runs[run2.id] = run2

        app = _make_app(fake_repo)
        client = TestClient(app)

        resp = client.get("/api/v1/crawl-admin/runs?source_site=offertoday")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["source_site"] == "offertoday"


class TestCrawlAdminGetRun:
    def test_get_existing(self) -> None:
        fake_repo = FakeCrawlRunRepository()
        run = _build_run()
        fake_repo._runs[run.id] = run

        app = _make_app(fake_repo)
        client = TestClient(app)

        resp = client.get(f"/api/v1/crawl-admin/runs/{run.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(run.id)
        assert data["source_site"] == "offertoday"

    def test_get_not_found(self) -> None:
        app = _make_app(FakeCrawlRunRepository())
        client = TestClient(app)
        resp = client.get(f"/api/v1/crawl-admin/runs/{uuid4()}")
        assert resp.status_code == 404
