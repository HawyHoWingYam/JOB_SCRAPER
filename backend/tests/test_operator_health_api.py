from __future__ import annotations

import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models import CrawlJob, CrawlJobListing
from app.repositories.crawl_job_listing_repository import CrawlJobListingRepository
import app.services.operator_health_service as service_module

if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


def _build_sqlite_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            CrawlJob.__table__,
            CrawlJobListing.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def _create_crawl_job(db, *, source_site: str = "jobsdb") -> CrawlJob:
    crawl_job = CrawlJob(
        id=uuid.uuid4(),
        source_site=source_site,
        trigger_type="manual",
        status="queued",
        request_payload={"source_site": source_site},
        requested_by="pytest",
    )
    db.add(crawl_job)
    db.commit()
    db.refresh(crawl_job)
    return crawl_job


def _workspace_temp_dir(name: str) -> Path:
    path = BACKEND_ROOT / "tests" / ".tmp_operator_health" / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def _base_freshness() -> dict:
    return {
        "jobs": {"total": 0, "newest_updated_at": None},
        "ai": {"total_jobs": 0, "enriched_jobs": 0, "pending_jobs": 0, "run_status_counts": {}},
        "skills": {"newest_mention_at": None},
        "embeddings": {
            "newest_updated_at": None,
            "total_embeddings": 0,
            "current_embeddings": 0,
            "missing_current_embeddings": 0,
        },
    }


def _healthy_scheduler() -> dict:
    return {
        "owner": "scheduler-worker",
        "worker_name": "scheduler-worker",
        "available": True,
        "manual_run_available": True,
        "heartbeat_status": "fresh",
        "reason": None,
    }


def _healthy_headed_runtime() -> dict:
    return {
        "configured": True,
        "browser_channel": "msedge",
        "browser_user_data_dir_configured": True,
        "browser_user_data_dir_exists": True,
        "lock_port": 47651,
        "worker_group": "crawl-headed-workers",
        "worker_status": "healthy",
        "reason": None,
    }


def test_summarize_detail_status_counts_groups_statuses_as_dict():
    db = _build_sqlite_session()
    try:
        listing_crawl_job = _create_crawl_job(db)
        detail_crawl_job = _create_crawl_job(db)
        repository = CrawlJobListingRepository()

        repository.upsert_listing(
            db,
            crawl_job_id=listing_crawl_job.id,
            source_site="jobsdb",
            source_job_id="1001",
            source_url="https://hk.jobsdb.com/job/1001",
            source_classification_id="6281",
            source_classification_name="ICT",
            listing_page=1,
            listing_rank=1,
            listing_payload={"title": "Pending"},
        )
        second, _ = repository.upsert_listing(
            db,
            crawl_job_id=listing_crawl_job.id,
            source_site="jobsdb",
            source_job_id="1002",
            source_url="https://hk.jobsdb.com/job/1002",
            source_classification_id="6281",
            source_classification_name="ICT",
            listing_page=1,
            listing_rank=2,
            listing_payload={"title": "Manual action"},
        )
        third, _ = repository.upsert_listing(
            db,
            crawl_job_id=listing_crawl_job.id,
            source_site="jobsdb",
            source_job_id="1003",
            source_url="https://hk.jobsdb.com/job/1003",
            source_classification_id="6281",
            source_classification_name="ICT",
            listing_page=1,
            listing_rank=3,
            listing_payload={"title": "Failed"},
        )

        repository.mark_detail_manual_action_required(
            db,
            listing_id=second.id,
            detail_crawl_job_id=detail_crawl_job.id,
            error_message="captcha",
        )
        repository.mark_detail_failed(
            db,
            listing_id=third.id,
            detail_crawl_job_id=detail_crawl_job.id,
            error_message="timeout",
        )

        counts = repository.summarize_detail_status_counts(db)

        assert counts == {
            "failed": 1,
            "manual_action_required": 1,
            "pending": 1,
        }
    finally:
        db.close()


def test_count_detail_statuses_preserves_filtered_behavior():
    db = _build_sqlite_session()
    try:
        jobsdb_job = _create_crawl_job(db, source_site="jobsdb")
        ct_job = _create_crawl_job(db, source_site="ctgoodjobs")
        detail_crawl_job = _create_crawl_job(db)
        repository = CrawlJobListingRepository()

        repository.upsert_listing(
            db,
            crawl_job_id=jobsdb_job.id,
            source_site="jobsdb",
            source_job_id="2001",
            source_url="https://hk.jobsdb.com/job/2001",
            source_classification_id="6281",
            source_classification_name="ICT",
            listing_page=1,
            listing_rank=1,
            listing_payload={"title": "Pending jobsdb"},
        )
        manual, _ = repository.upsert_listing(
            db,
            crawl_job_id=jobsdb_job.id,
            source_site="jobsdb",
            source_job_id="2002",
            source_url="https://hk.jobsdb.com/job/2002",
            source_classification_id="6282",
            source_classification_name="Data",
            listing_page=1,
            listing_rank=2,
            listing_payload={"title": "Manual jobsdb"},
        )
        other, _ = repository.upsert_listing(
            db,
            crawl_job_id=ct_job.id,
            source_site="ctgoodjobs",
            source_job_id="3001",
            source_url="https://jobs.ctgoodjobs.hk/job/3001",
            source_classification_id="ctgoodjobs:021",
            source_classification_name="IT",
            listing_page=1,
            listing_rank=1,
            listing_payload={"title": "Pending ct"},
        )
        repository.mark_detail_manual_action_required(
            db,
            listing_id=manual.id,
            detail_crawl_job_id=detail_crawl_job.id,
            error_message="captcha",
        )
        repository.mark_detail_failed(
            db,
            listing_id=other.id,
            detail_crawl_job_id=detail_crawl_job.id,
            error_message="timeout",
        )

        counts = repository.count_detail_statuses(
            db,
            source_site="jobsdb",
            source_listing_crawl_job_id=jobsdb_job.id,
            category_ids=["6281", "6282"],
        )

        assert counts == {
            "manual_action_required": 1,
            "pending": 1,
        }
    finally:
        db.close()


def test_build_operator_health_summary_returns_exact_approved_contract():
    generated_at = datetime(2026, 5, 22, 3, 4, 5, tzinfo=timezone.utc)
    missing_profile_dir = BACKEND_ROOT / "tests" / ".tmp_operator_health" / "missing-profile"
    if missing_profile_dir.exists():
        shutil.rmtree(missing_profile_dir)
    queue_summary = {
        "stream.job.ingest": {"group": "ingest-workers", "length": 12, "pending": 0, "lag": 0, "consumers": 1},
        "stream.job.lifecycle:enrichment-workers": {
            "group": "enrichment-workers",
            "length": 9,
            "pending": 0,
            "lag": 0,
            "consumers": 1,
        },
        "stream.job.embedding": {"group": "embedding-workers", "length": 5, "pending": 0, "lag": 0, "consumers": 1},
        "stream.crawl.commands.headed": {
            "group": "crawl-headed-workers",
            "length": 4,
            "pending": 0,
            "lag": 0,
            "consumers": 1,
        },
    }

    summary = service_module.build_operator_health_summary(
        queue_summary_loader=lambda: queue_summary,
        detail_status_counts_loader=lambda: {
            "pending": 11,
            "failed": 3,
            "manual_action_required": 2,
            "completed": 7,
        },
        outbox_counts_loader=lambda: {"pending": 4, "failed": 1},
        freshness_loader=lambda: {
            "jobs": {"total": 20, "newest_updated_at": "2026-05-22T02:50:00+00:00"},
            "ai": {
                "total_jobs": 20,
                "enriched_jobs": 15,
                "pending_jobs": 5,
                "run_status_counts": {"queued": 6, "failed": 1},
            },
            "skills": {"newest_mention_at": "2026-05-22T02:45:00+00:00"},
            "embeddings": {
                "newest_updated_at": "2026-05-22T02:40:00+00:00",
                "total_embeddings": 18,
                "current_embeddings": 17,
                "missing_current_embeddings": 3,
            },
        },
        scheduler_status_loader=lambda: {
            "owner": "scheduler-worker",
            "worker_name": "scheduler-worker",
            "available": False,
            "manual_run_available": True,
            "heartbeat_status": "stale",
            "last_heartbeat_at": "2026-05-22T02:55:00+00:00",
            "last_reconcile_at": "2026-05-22T02:54:00+00:00",
            "active_schedule_count": 3,
            "registered_job_count": 3,
            "reason": "scheduler_worker_stale",
        },
        headed_runtime_loader=lambda: {
            "configured": False,
            "browser_channel": "msedge",
            "browser_user_data_dir_configured": True,
            "browser_user_data_dir_exists": False,
            "lock_port": 47651,
            "worker_group": "crawl-headed-workers",
            "worker_status": "misconfigured",
            "reason": "browser_user_data_dir_missing",
            "ignored": "extra",
        },
        dead_letter_count_loader=lambda: 2,
        generated_at=generated_at,
    )

    assert summary["status"] == "degraded"
    assert summary["generated_at"] == "2026-05-22T03:04:05+00:00"
    assert summary["scheduler"]["heartbeat_status"] == "stale"
    assert summary["headed_runtime"] == {
        "configured": False,
        "browser_channel": "msedge",
        "browser_user_data_dir_configured": True,
        "browser_user_data_dir_exists": False,
        "lock_port": 47651,
        "worker_group": "crawl-headed-workers",
        "worker_status": "misconfigured",
        "reason": "browser_user_data_dir_missing",
    }
    assert summary["backlogs"] == {
        "pending_detail_rows": 11,
        "failed_detail_rows": 3,
        "manual_action_detail_rows": 2,
        "outbox_pending": 4,
        "outbox_failed": 1,
        "dead_letter_count": 2,
        "missing_current_embeddings": 3,
        "ai_backlog_jobs": 6,
    }
    assert summary["freshness"]["crawl_job_listings"]["manual_action_required"] == 2
    assert "stream.job.ingest.dead_letter has 2 messages" in summary["issues"]
    assert "crawl_job_listings has 2 manual-action detail rows" in summary["issues"]
    assert any("scheduler-worker heartbeat is stale" in issue for issue in summary["issues"])
    assert "headed browser user data dir does not exist" in summary["issues"]
    assert missing_profile_dir.exists() is False


def test_build_operator_health_summary_marks_queue_backlog_as_critical():
    summary = service_module.build_operator_health_summary(
        queue_summary_loader=lambda: {
            "stream.job.ingest": {"group": "ingest-workers", "length": 15, "pending": 4, "lag": 8, "consumers": 1},
        },
        detail_status_counts_loader=lambda: {},
        outbox_counts_loader=lambda: {},
        freshness_loader=_base_freshness,
        scheduler_status_loader=_healthy_scheduler,
        headed_runtime_loader=_healthy_headed_runtime,
        dead_letter_count_loader=lambda: 0,
    )

    assert summary["status"] == "critical"
    assert "stream.job.ingest group ingest-workers lag is 8" in summary["issues"]
    assert "stream.job.ingest group ingest-workers has 4 pending messages" in summary["issues"]


def test_build_operator_health_summary_with_only_pending_detail_rows_is_not_healthy():
    summary = service_module.build_operator_health_summary(
        queue_summary_loader=lambda: {},
        detail_status_counts_loader=lambda: {"pending": 2},
        outbox_counts_loader=lambda: {},
        freshness_loader=_base_freshness,
        scheduler_status_loader=_healthy_scheduler,
        headed_runtime_loader=_healthy_headed_runtime,
        dead_letter_count_loader=lambda: 0,
    )

    assert summary["status"] == "degraded"
    assert "crawl_job_listings has 2 pending detail rows" in summary["issues"]


def test_build_operator_health_summary_with_only_outbox_pending_is_not_healthy():
    summary = service_module.build_operator_health_summary(
        queue_summary_loader=lambda: {},
        detail_status_counts_loader=lambda: {},
        outbox_counts_loader=lambda: {"pending": 3},
        freshness_loader=_base_freshness,
        scheduler_status_loader=_healthy_scheduler,
        headed_runtime_loader=_healthy_headed_runtime,
        dead_letter_count_loader=lambda: 0,
    )

    assert summary["status"] == "degraded"
    assert "event_outbox has 3 pending rows" in summary["issues"]


def test_build_operator_health_summary_surfaces_loader_failure_as_degraded_issue():
    summary = service_module.build_operator_health_summary(
        queue_summary_loader=lambda: (_ for _ in ()).throw(RuntimeError("redis offline")),
        detail_status_counts_loader=lambda: {},
        outbox_counts_loader=lambda: {},
        freshness_loader=_base_freshness,
        scheduler_status_loader=_healthy_scheduler,
        headed_runtime_loader=_healthy_headed_runtime,
        dead_letter_count_loader=lambda: 0,
    )

    assert summary["status"] == "degraded"
    assert "operator dependency queue_summaries unavailable: redis offline" in summary["issues"]


def test_build_operator_health_summary_with_empty_scheduler_payload_is_degraded():
    summary = service_module.build_operator_health_summary(
        queue_summary_loader=lambda: {},
        detail_status_counts_loader=lambda: {},
        outbox_counts_loader=lambda: {},
        freshness_loader=_base_freshness,
        scheduler_status_loader=lambda: {},
        headed_runtime_loader=_healthy_headed_runtime,
        dead_letter_count_loader=lambda: 0,
    )

    assert summary["status"] == "degraded"
    assert summary["workers"]["scheduler-worker"]["status"] == "unknown"
    assert "scheduler-worker status payload is incomplete" in summary["issues"]


def test_build_operator_health_summary_with_scheduler_missing_available_is_degraded():
    summary = service_module.build_operator_health_summary(
        queue_summary_loader=lambda: {},
        detail_status_counts_loader=lambda: {},
        outbox_counts_loader=lambda: {},
        freshness_loader=_base_freshness,
        scheduler_status_loader=lambda: {"heartbeat_status": "fresh"},
        headed_runtime_loader=_healthy_headed_runtime,
        dead_letter_count_loader=lambda: 0,
    )

    assert summary["status"] == "degraded"
    assert summary["workers"]["scheduler-worker"]["status"] == "unknown"
    assert "scheduler-worker status payload is incomplete" in summary["issues"]


def test_build_operator_health_summary_with_scheduler_missing_heartbeat_is_degraded():
    summary = service_module.build_operator_health_summary(
        queue_summary_loader=lambda: {},
        detail_status_counts_loader=lambda: {},
        outbox_counts_loader=lambda: {},
        freshness_loader=_base_freshness,
        scheduler_status_loader=lambda: {"available": True},
        headed_runtime_loader=_healthy_headed_runtime,
        dead_letter_count_loader=lambda: 0,
    )

    assert summary["status"] == "degraded"
    assert summary["workers"]["scheduler-worker"]["status"] == "unknown"
    assert "scheduler-worker status payload is incomplete" in summary["issues"]

def test_build_operator_health_summary_with_scheduler_unavailable_fresh_heartbeat_is_not_fresh():
    summary = service_module.build_operator_health_summary(
        queue_summary_loader=lambda: {},
        detail_status_counts_loader=lambda: {},
        outbox_counts_loader=lambda: {},
        freshness_loader=_base_freshness,
        scheduler_status_loader=lambda: {"available": False, "heartbeat_status": "fresh", "reason": "scheduler_worker_paused"},
        headed_runtime_loader=_healthy_headed_runtime,
        dead_letter_count_loader=lambda: 0,
    )

    assert summary["status"] == "degraded"
    assert summary["workers"]["scheduler-worker"]["status"] == "unavailable"
    assert summary["workers"]["scheduler-worker"]["status"] != "fresh"
    assert "scheduler-worker status is scheduler_worker_paused" in summary["issues"]


def test_build_operator_health_summary_surfaces_missing_consumer_group():
    summary = service_module.build_operator_health_summary(
        queue_summary_loader=lambda: {
            "stream.job.ingest": {
                "group": "ingest-workers",
                "length": 5,
                "pending": 0,
                "lag": 0,
                "consumers": 0,
                "reason": "consumer_group_missing",
                "worker_name": "ingest-worker",
            }
        },
        detail_status_counts_loader=lambda: {},
        outbox_counts_loader=lambda: {},
        freshness_loader=_base_freshness,
        scheduler_status_loader=_healthy_scheduler,
        headed_runtime_loader=_healthy_headed_runtime,
        dead_letter_count_loader=lambda: 0,
    )

    assert summary["status"] == "degraded"
    assert summary["workers"]["ingest-worker"]["status"] == "unavailable"
    assert "stream.job.ingest group ingest-workers is missing" in summary["issues"]


def test_build_headed_runtime_summary_reports_exact_contract():
    profile_dir = _workspace_temp_dir("profile")
    try:
        summary = service_module.build_headed_runtime_summary(
            SimpleNamespace(
                jobsdb_headed_browser_channel="chrome",
                jobsdb_headed_browser_user_data_dir=str(profile_dir),
                jobsdb_headed_worker_lock_port=49000,
            ),
            worker_summary={
                "group": "crawl-headed-workers",
                "pending": 0,
                "lag": 0,
            },
        )

        assert summary == {
            "configured": True,
            "browser_channel": "chrome",
            "browser_user_data_dir_configured": True,
            "browser_user_data_dir_exists": True,
            "lock_port": 49000,
            "worker_group": "crawl-headed-workers",
            "worker_status": "healthy",
            "reason": None,
        }
    finally:
        shutil.rmtree(profile_dir.parent, ignore_errors=True)

