from __future__ import annotations

import pytest

from app.services import crawl_job_dispatch_service
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService


class GuardedCrawlJobRepository:
    def create_crawl_job(self, *args, **kwargs):
        raise AssertionError("create_crawl_job() should not run when headed crawl availability fails")


def test_dispatch_manual_crawl_job_checks_headed_worker_availability_before_persisting(monkeypatch):
    def fail_headed_dispatch(**_kwargs):
        raise RuntimeError("headed worker offline")

    monkeypatch.setattr(
        crawl_job_dispatch_service,
        "ensure_headed_crawl_worker_available",
        fail_headed_dispatch,
        raising=False,
    )

    service = CrawlJobDispatchService(
        crawl_job_repository=GuardedCrawlJobRepository(),
    )

    with pytest.raises(RuntimeError, match="headed worker offline"):
        service.dispatch_manual_crawl_job(
            object(),
            source_site="jobsdb",
            crawl_phase="listing",
            crawl_mode="headed",
            category_ids=[1200],
            max_pages=3,
        )
