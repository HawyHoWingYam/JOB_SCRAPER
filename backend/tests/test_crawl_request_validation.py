import sys
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.crawl_job import CrawlJobCreateRequest
from app.schemas.schedule import ScheduleCreateSchema
from app.services.crawl_request_validation import validate_crawl_request


def test_validate_listing_request_requires_categories():
    with pytest.raises(ValueError, match="listing runs require category_ids"):
        validate_crawl_request(
            source_site="jobsdb",
            crawl_phase="listing",
            crawl_mode=None,
            category_ids=None,
            source_listing_crawl_job_id=None,
        )


def test_validate_detail_request_accepts_source_listing_batch_without_categories():
    result = validate_crawl_request(
        source_site="jobsdb",
        crawl_phase="detail",
        crawl_mode=None,
        category_ids=None,
        source_listing_crawl_job_id=uuid4(),
    )

    assert result.source_site == "jobsdb"
    assert result.crawl_phase == "detail"
    assert result.crawl_mode == "headed"


def test_validate_ctgoodjobs_requires_string_categories():
    with pytest.raises(ValueError, match="CTGoodJobs category_ids must be strings"):
        validate_crawl_request(
            source_site="ctgoodjobs",
            crawl_phase="listing",
            crawl_mode=None,
            category_ids=[1200],
            source_listing_crawl_job_id=None,
        )


def test_schedule_category_ids_reject_float_without_coercion():
    with pytest.raises(ValidationError):
        ScheduleCreateSchema(
            name="bad category",
            cron_expression="0 2 * * *",
            source_site="jobsdb",
            crawl_phase="listing",
            category_ids=[1.0],
        )


def test_crawl_job_category_ids_reject_bool_without_coercion():
    with pytest.raises(ValidationError):
        CrawlJobCreateRequest(
            source_site="jobsdb",
            crawl_phase="listing",
            category_ids=[True],
        )
