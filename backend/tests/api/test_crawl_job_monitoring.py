from __future__ import annotations

from app.api.crawl_jobs import _build_crawl_request_created_log_message


def test_build_crawl_request_created_log_message_includes_request_and_batch_context():
    message = _build_crawl_request_created_log_message(
        request_id="req-1",
        source_site="jobsdb",
        crawl_job_id="crawl-1",
        crawl_phase="detail",
        crawl_mode="headed",
        max_pages=3,
        category_count=1,
        source_listing_crawl_job_id="listing-batch-9",
    )

    assert message == (
        "SCRAPE_REQUEST_CREATED request_id=req-1 source=jobsdb crawl_job_id=crawl-1 "
        "phase=detail mode=headed max_pages=3 categories=1 "
        "source_listing_crawl_job_id=listing-batch-9"
    )
