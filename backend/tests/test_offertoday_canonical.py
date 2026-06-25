"""Tests for OfferToday canonical job builder."""

from __future__ import annotations

from app.sources.contracts import build_offertoday_canonical_job


class TestBuildOffertodayCanonicalJob:
    def test_minimal_fields(self):
        job = build_offertoday_canonical_job(
            {
                "encrypted_job_id": "abc123==",
                "title": "Engineer",
                "company_name": "Co",
            }
        )
        assert job.source_site == "offertoday"
        assert job.source_job_id == "abc123=="
        assert job.source_url == "https://www.offertoday.com/hk/job/abc123=="
        assert job.title == "Engineer"
        assert job.company_name == "Co"
        assert job.source_classification_id is None
        assert job.source_subclassification_name is None

    def test_full_fields(self):
        job = build_offertoday_canonical_job(
            {
                "encrypted_job_id": "xyz789==",
                "title": "Senior Developer",
                "description_html": "<p>Details</p>",
                "company_name": "Tech Inc",
                "location": "Hong Kong",
                "salary_range": "$50K-80K/月",
                "employment_type": "全職",
                "posted_desc": "更新於06-17",
            }
        )
        assert job.title == "Senior Developer"
        assert job.description == "<p>Details</p>"
        assert job.company_name == "Tech Inc"
        assert job.location == "Hong Kong"
        assert job.salary_range == "$50K-80K/月"
        assert job.employment_type == "全職"

    def test_empty_encrypted_id(self):
        job = build_offertoday_canonical_job(
            {"encrypted_job_id": "", "title": "Test"}
        )
        assert job.source_job_id == ""
        assert job.source_url == "https://www.offertoday.com/hk/job/"
