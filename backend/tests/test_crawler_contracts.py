"""Crawler contract regression tests.

Freezes the current parser behavior for OfferToday, JobsDB, and CTGoodJobs
into test evidence before migration to the Scrapy platform.

Required canonical fields for every source:
  - source_site, source_job_id, source_url, title, company_name,
    description_text, source_classification_id
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "crawler"


# ── Helpers ──────────────────────────────────────────────────────────


def _load_fixture(name: str) -> str | dict:
    path = FIXTURES / name
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return path.read_text(encoding="utf-8")


# ── OfferToday Listing ───────────────────────────────────────────────


class TestOffertodayListingContract:
    def setup_method(self) -> None:
        from app.sources.offertoday.parsers import (
            parse_offertoday_listing_response,
        )

        self.parse = parse_offertoday_listing_response

    def test_parses_listing_fixture(self) -> None:
        raw = _load_fixture("offertoday_listing_response.json")
        jobs = self.parse(raw)
        assert isinstance(jobs, list)
        assert len(jobs) > 0, "Should parse at least one job"

    def test_required_fields(self) -> None:
        raw = _load_fixture("offertoday_listing_response.json")
        jobs = self.parse(raw)
        assert len(jobs) >= 1
        for job in jobs:
            assert job["source_site"] == "offertoday"
            assert isinstance(job["encrypted_job_id"], str) and len(job["encrypted_job_id"]) > 0
            assert isinstance(job["title"], str) and len(job["title"]) > 0
            assert isinstance(job["company_name"], str) and len(job["company_name"]) > 0
            assert "salary_range" in job
            assert "location" in job
            assert "employment_type" in job

    def test_listing_count(self) -> None:
        raw = _load_fixture("offertoday_listing_response.json")
        jobs = self.parse(raw)
        assert len(jobs) == 2

    def test_first_job_content(self) -> None:
        raw = _load_fixture("offertoday_listing_response.json")
        jobs = self.parse(raw)
        job = jobs[0]
        assert job["encrypted_job_id"] == "abc123=="
        assert job["title"] == "Software Engineer"
        assert job["company_name"] == "Tech Corp"
        assert job["location"] == "Hong Kong"
        assert job["salary_range"] == "$30K-50K/月"
        assert job["employment_type"] == "全職"

    def test_second_job_hk_salary_prefix(self) -> None:
        raw = _load_fixture("offertoday_listing_response.json")
        jobs = self.parse(raw)
        job = jobs[1]
        assert job["encrypted_job_id"] == "xyz789=="
        assert job["title"] == "Data Analyst"
        # Listing parser keeps raw salary desc; "HK $" prefix is preserved
        assert "HK $" in job["salary_range"]


# ── OfferToday Detail ────────────────────────────────────────────────


class TestOffertodayDetailContract:
    def setup_method(self) -> None:
        from app.sources.offertoday.parsers import (
            parse_offertoday_detail_response,
        )

        self.parse = parse_offertoday_detail_response

    def test_parses_detail_fixture(self) -> None:
        raw = _load_fixture("offertoday_detail_response.json")
        detail = self.parse(raw)
        assert isinstance(detail, dict)
        assert len(detail["encrypted_job_id"]) > 0

    def test_required_fields(self) -> None:
        raw = _load_fixture("offertoday_detail_response.json")
        detail = self.parse(raw)
        assert detail["source_site"] == "offertoday"
        assert detail["encrypted_job_id"] == "abc123=="
        assert detail["title"] == "Senior Developer"
        assert detail["company_name"] == "Big Corp"
        assert len(detail["description_text"]) > 0

    def test_salary_strips_hk_prefix(self) -> None:
        raw = _load_fixture("offertoday_detail_response.json")
        detail = self.parse(raw)
        # Detail parser strips "HK " prefix
        assert "HK " not in detail["salary_range"]
        assert detail["salary_range"] == "$50K-80K/月"

    def test_description_fields(self) -> None:
        raw = _load_fixture("offertoday_detail_response.json")
        detail = self.parse(raw)
        assert "<p>Job description here</p>" in detail["description_html"]
        assert detail["description_text"] == "Job description here"

    def test_location_fields(self) -> None:
        raw = _load_fixture("offertoday_detail_response.json")
        detail = self.parse(raw)
        assert detail["location"] == "Hong Kong"
        assert detail["latitude"] == 22.3089
        assert detail["longitude"] == 114.2635

    def test_company_fields(self) -> None:
        raw = _load_fixture("offertoday_detail_response.json")
        detail = self.parse(raw)
        assert detail["company_brand"] == "Big Corp Brand"
        assert detail["company_size"] == "1000+名員工"
        assert detail["company_type"] == "上市公司"
        assert detail["company_industry"] == "IT"

    def test_job_functions(self) -> None:
        raw = _load_fixture("offertoday_detail_response.json")
        detail = self.parse(raw)
        assert len(detail["job_functions"]) == 1
        assert detail["job_functions"][0]["code"] == "112000"
        assert detail["job_functions"][0]["name"] == "工程師"

    def test_geo_coordinates(self) -> None:
        raw = _load_fixture("offertoday_detail_response.json")
        detail = self.parse(raw)
        assert detail["latitude"] == 22.3089
        assert detail["longitude"] == 114.2635


# ── OfferToday Canonical ─────────────────────────────────────────────


class TestOffertodayCanonicalContract:
    def test_minimal_listing_to_canonical(self) -> None:
        from app.sources.contracts import build_offertoday_canonical_job

        raw = _load_fixture("offertoday_listing_response.json")
        from app.sources.offertoday.parsers import (
            parse_offertoday_listing_response,
        )

        jobs = parse_offertoday_listing_response(raw)
        assert len(jobs) >= 1
        canonical = build_offertoday_canonical_job(jobs[0])
        assert canonical.source_site == "offertoday"
        assert canonical.source_job_id == "abc123=="
        assert canonical.source_url == "https://www.offertoday.com/hk/job/abc123=="
        assert canonical.title == "Software Engineer"
        assert canonical.company_name == "Tech Corp"

    def test_detail_to_canonical(self) -> None:
        from app.sources.contracts import build_offertoday_canonical_job

        raw = _load_fixture("offertoday_detail_response.json")
        from app.sources.offertoday.parsers import (
            parse_offertoday_detail_response,
        )

        detail = parse_offertoday_detail_response(raw)
        canonical = build_offertoday_canonical_job(detail)
        assert canonical.source_site == "offertoday"
        assert canonical.source_job_id == "abc123=="
        assert canonical.title == "Senior Developer"
        assert canonical.description is not None
        assert "job description" in canonical.description.lower()

    def test_required_canonical_fields_present(self) -> None:
        from app.sources.contracts import build_offertoday_canonical_job

        raw = _load_fixture("offertoday_listing_response.json")
        from app.sources.offertoday.parsers import (
            parse_offertoday_listing_response,
        )

        jobs = parse_offertoday_listing_response(raw)
        for job in jobs:
            canonical = build_offertoday_canonical_job(job)
            assert canonical.source_site == "offertoday"
            assert isinstance(canonical.source_job_id, str)
            assert isinstance(canonical.source_url, str) and canonical.source_url.startswith("http")
            assert isinstance(canonical.title, str)
            assert isinstance(canonical.company_name, str) or canonical.company_name is None


# ── JobsDB Detail Contract ───────────────────────────────────────────


class TestJobsdbDetailContract:
    def test_parses_detail_fixture(self) -> None:
        from app.sources.jobsdb.parsers import parse_detail_page

        html = _load_fixture("jobsdb_detail_page.html")
        result = parse_detail_page(html, job_id="test-123-abc")
        assert isinstance(result, dict)
        assert result["jobsdb_id"] == "test-123-abc"

    def test_required_fields(self) -> None:
        from app.sources.jobsdb.parsers import parse_detail_page

        html = _load_fixture("jobsdb_detail_page.html")
        result = parse_detail_page(html, job_id="test-123-abc")
        assert result["jobsdb_id"] == "test-123-abc"
        assert result["title"] == "Software Engineer"
        assert result["advertiser_name"] == "Tech Corp"
        assert result["description_html"] is not None
        assert result["classification_id"] == 6281
        assert result["classification"] == "IT / Software Development"

    def test_detail_content(self) -> None:
        from app.sources.jobsdb.parsers import parse_detail_page

        html = _load_fixture("jobsdb_detail_page.html")
        result = parse_detail_page(html, job_id="test-123-abc")
        assert result["location"] == "Hong Kong"
        assert result["work_type"] == "Full-time"
        assert result["is_expired"] is False

    def test_canonical_from_detail(self) -> None:
        from app.sources.jobsdb.parsers import parse_detail_page
        from app.sources.contracts import build_jobsdb_canonical_job

        html = _load_fixture("jobsdb_detail_page.html")
        result = parse_detail_page(html, job_id="test-123-abc")
        source_url = "https://hk.jobsdb.com/hk/en/job/test-123-abc"
        canonical = build_jobsdb_canonical_job(result, source_url=source_url)
        assert canonical.source_site == "jobsdb"
        assert canonical.source_job_id == "test-123-abc"
        assert canonical.source_url == source_url
        assert canonical.title == "Software Engineer"
        assert canonical.company_name == "Tech Corp"
        assert canonical.source_classification_id == 6281
        assert canonical.source_classification_name == "IT / Software Development"


# ── CTGoodJobs Detail Contract ───────────────────────────────────────


class TestCtgoodjobsDetailContract:
    def test_parses_detail_fixture(self) -> None:
        from app.sources.ctgoodjobs.parsers import parse_detail_page

        html = _load_fixture("ctgoodjobs_detail_page.html")
        result = parse_detail_page(
            html,
            source_classification_id="39000000",
            source_classification_name="IT",
            source_classification_slug="it",
            url="https://www.ctgoodjobs.hk/job/78901234",
        )
        assert isinstance(result, dict)
        assert result["job_id"] == "78901234"

    def test_required_fields(self) -> None:
        from app.sources.ctgoodjobs.parsers import parse_detail_page

        html = _load_fixture("ctgoodjobs_detail_page.html")
        result = parse_detail_page(
            html,
            source_classification_id="39000000",
            source_classification_name="IT",
            source_classification_slug="it",
            url="https://www.ctgoodjobs.hk/job/78901234",
        )
        assert result["source_site"] == "ctgoodjobs"
        assert result["job_id"] == "78901234"
        assert result["title"] == "Software Engineer"
        assert result["company_name"] == "Tech Corp"
        assert result["description_html"] is not None
        assert result["source_classification_id"] == "39000000"
        assert result["source_classification_name"] == "IT"

    def test_detail_content(self) -> None:
        from app.sources.ctgoodjobs.parsers import parse_detail_page

        html = _load_fixture("ctgoodjobs_detail_page.html")
        result = parse_detail_page(
            html,
            source_classification_id="39000000",
            source_classification_name="IT",
            source_classification_slug="it",
            url="https://www.ctgoodjobs.hk/job/78901234",
        )
        assert result["location"] is not None
        assert result["salary_range"] is not None
        assert result["employment_type"] is not None
        assert result["posted_date"] == "2026-06-10"

    def test_canonical_from_detail(self) -> None:
        from app.sources.ctgoodjobs.parsers import parse_detail_page
        from app.sources.contracts import build_ctgoodjobs_canonical_job

        html = _load_fixture("ctgoodjobs_detail_page.html")
        result = parse_detail_page(
            html,
            source_classification_id="39000000",
            source_classification_name="IT",
            source_classification_slug="it",
            url="https://www.ctgoodjobs.hk/job/78901234",
        )
        canonical = build_ctgoodjobs_canonical_job(result)
        assert canonical.source_site == "ctgoodjobs"
        assert canonical.source_job_id == "78901234"
        assert canonical.title == "Software Engineer"
        assert canonical.company_name == "Tech Corp"
        assert canonical.source_classification_id == "39000000"
        assert canonical.source_classification_name == "IT"
