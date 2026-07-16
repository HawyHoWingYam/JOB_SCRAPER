import os
import threading
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.crawl_job import CrawlJob
from app.services.crawl_job_dispatch_service import (
    ActiveManualDetailCrawlConflict,
    CrawlJobDispatchResult,
    CrawlJobDispatchService,
)


class _CommitOnlyDispatchService(CrawlJobDispatchService):
    def dispatch_crawl_job(self, db, **kwargs):
        # Keep the source pacing row locked long enough for the competing
        # transaction to reach SELECT ... FOR UPDATE and wait.
        time.sleep(0.2)
        crawl_job = self.crawl_job_repository.create_crawl_job(
            db,
            source_site=kwargs["source_site"],
            trigger_type=kwargs["trigger_type"],
            request_payload=kwargs["request_payload"],
            requested_by=kwargs.get("requested_by"),
            status="queued",
            auto_commit=False,
        )
        db.commit()
        return CrawlJobDispatchResult(crawl_job=crawl_job, schedule_execution=None)


def test_same_source_detail_dispatch_is_serialized_by_postgres_row_lock():
    database_url = os.getenv("PACING_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("PACING_POSTGRES_TEST_URL is required for the race test")

    engine = create_engine(database_url)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        db.query(CrawlJob).delete()
        db.commit()

    barrier = threading.Barrier(2)
    outcomes = []

    def dispatch():
        db = session_factory()
        try:
            barrier.wait(timeout=5)
            result = _CommitOnlyDispatchService().dispatch_manual_crawl_job(
                db,
                source_site="jobsdb",
                crawl_phase="detail",
                category_ids=[],
                max_pages=1,
            )
            outcomes.append(("created", str(result.crawl_job.id)))
        except ActiveManualDetailCrawlConflict:
            db.rollback()
            outcomes.append(("conflict", None))
        finally:
            db.close()

    threads = [threading.Thread(target=dispatch) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert sorted(outcome for outcome, _ in outcomes) == ["conflict", "created"]
    engine.dispose()
