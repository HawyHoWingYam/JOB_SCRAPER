from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.sources.jobsdb import parsers


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "jobsdb"


def test_parse_jobsdb_search_response_matches_existing_transform_job_logic():
    payload = (FIXTURES / "search_response.json").read_text(encoding="utf-8")
    actual = parsers.parse_search_response(json.loads(payload))

    assert actual["total_count"] == 1
    assert actual["jobs"] == [
        {
            "external_id": "123456",
            "title": "Senior Data Analyst",
            "company_name": "ACME Ltd",
            "advertiser_id": "adv-1",
            "advertiser_name": "ACME Ltd",
            "bullet_points": ["Analyze data", "Build reports"],
            "location": "Hong Kong",
            "country_code": "HK",
            "salary_label": "HK$30,000 - HK$40,000",
            "listing_date": "2026-05-01T12:00:00+00:00",
            "listing_date_display": "1 May 2026",
            "teaser": "Build reports",
            "work_types": ["Full-time", "Permanent"],
            "work_arrangements": ["Hybrid"],
            "classification_id": "6281",
            "classification_name": "Information & Communication Technology",
            "logo_url": "https://example.com/logo.png",
        }
    ]


def test_parse_jobsdb_detail_page_matches_expected_contract():
    html = (FIXTURES / "detail_page.html").read_text(encoding="utf-8")
    actual = parsers.parse_detail_page(html, job_id="123456")

    assert actual == {
        "jobsdb_id": "123456",
        "title": "Senior Data Analyst",
        "abstract": "Build reports",
        "description_html": "<p>Build & analyze</p>",
        "classification_id": "6281",
        "classification": "Information & Communication Technology",
        "subclassification_id": "6282",
        "subclassification": "Data Science",
        "location": "Hong Kong",
        "work_type": "Full-time",
        "salary": "HK$30,000 - HK$40,000",
        "listing_date": "2026-05-01T12:00:00+00:00",
        "expiry_date": "2026-06-01T12:00:00+00:00",
        "is_expired": False,
        "advertiser_id": "adv-1",
        "advertiser_name": "ACME Ltd",
        "status": "ACTIVE",
        "scraped_at": actual["scraped_at"],
    }
