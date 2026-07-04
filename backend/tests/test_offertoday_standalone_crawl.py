from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.crawl_job import CrawlJob, CrawlJobEvent
from scripts import offertoday_standalone_crawl as crawl_script


def _build_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CrawlJob.__table__,
            CrawlJobEvent.__table__,
        ],
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    db = session_factory()

    crawl_job = CrawlJob(
        id=uuid4(),
        source_site="offertoday",
        trigger_type="manual",
        status="running",
        request_payload={"crawl_phase": "listing", "crawl_mode": "headed"},
        queued_at=datetime(2026, 5, 27, 9, 0, tzinfo=UTC),
        started_at=datetime(2026, 5, 27, 9, 0, tzinfo=UTC),
        created_at=datetime(2026, 5, 27, 9, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 27, 9, 0, tzinfo=UTC),
    )
    db.add(crawl_job)
    db.commit()
    return db, crawl_job


def test_emit_listing_completed_checkpoint_writes_progress_event():
    db, crawl_job = _build_session()

    crawl_script._emit_listing_completed_checkpoint(
        db,
        crawl_job_id=crawl_job.id,
        sequence_no=4,
        payload={
            "phase": 1,
            "pages_processed": 1676,
            "job_ids_collected": 3001,
            "listings_staged": 3001,
            "detail_pending": 74,
            "search_families": ["it_category", "it_keyword", "it_hybrid"],
        },
    )

    event = db.query(CrawlJobEvent).one()
    assert event.event_type == "listing_completed"
    assert event.sequence_no == 4
    assert event.payload["job_ids_collected"] == 3001
    assert event.payload["detail_pending"] == 74
    assert event.payload["search_families"] == ["it_category", "it_keyword", "it_hybrid"]
    db.close()


@pytest.mark.asyncio
async def test_check_and_handle_waf_challenge_emits_event_and_waits_for_browser_verification(monkeypatch):
    db, crawl_job = _build_session()
    page = SimpleNamespace(
        url="https://www.offertoday.com/web/passport/cm/verify.html?callbackUrl=test",
    )
    sleep_calls: list[float] = []

    async def fake_wait_for_url(*args, **kwargs):
        page.url = "https://www.offertoday.com/hk/search"

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    page.wait_for_url = fake_wait_for_url
    monkeypatch.setattr(crawl_script.asyncio, "sleep", fake_sleep)

    handled = await crawl_script._check_and_handle_waf_challenge(
        page,
        headed=True,
        crawl_job_id=crawl_job.id,
        db=db,
    )

    events = db.query(CrawlJobEvent).order_by(CrawlJobEvent.sequence_no.asc()).all()
    assert handled is True
    assert events[0].event_type == "waf.challenge"
    assert events[0].payload["headed"] is True
    assert events[0].payload["challenge_url"].startswith("https://www.offertoday.com/web/passport/cm/verify.html")
    assert [item.event_type for item in events] == ["waf.challenge", "waf.challenge_cleared"]
    assert events[-1].payload["cleared_url"] == "https://www.offertoday.com/hk/search"
    assert sleep_calls
    db.close()
