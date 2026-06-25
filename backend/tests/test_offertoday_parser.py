"""Tests for OfferToday parser module."""

from __future__ import annotations

from app.sources.offertoday.parsers import (
    build_offertoday_job_url,
    extract_encrypted_job_id,
    parse_offertoday_listing_response,
    parse_offertoday_detail_response,
)


class TestParseOffertodayListingResponse:
    def test_empty_response(self):
        result = parse_offertoday_listing_response({})
        assert result == []

    def test_no_result_list(self):
        result = parse_offertoday_listing_response({"code": 0, "data": {}})
        assert result == []

    def test_parses_single_job(self):
        response = {
            "code": 0,
            "data": {
                "resultList": [
                    {
                        "jobId": "abc123==",
                        "jobName": "Software Engineer",
                        "companyName": "Tech Corp",
                        "locationDesc": "Hong Kong",
                        "level3LocDesc": "Central",
                        "salaryDesc": "$30K-50K/月",
                        "jobTypeDesc": "全職",
                        "jobType": 1,
                        "experience": "3-5年",
                        "educationDesc": "學士",
                        "skills": ["Python", "Java"],
                        "skillList": [
                            {"code": "1", "name": "Python", "isCustom": False},
                        ],
                        "keywords": ["Python", "Django"],
                        "benefits": ["生日假"],
                        "workingDays": "5天/週",
                        "jobPostTime": "發布於06-15",
                        "jobFunctions": [{"code": "112000", "name": "工程師"}],
                        "locations": {"code": "HK101", "name": "香港"},
                        "activeStatus": "近3日活躍",
                        "bossName": "John",
                        "bossTitle": "HR Manager",
                        "brandLogo": "https://example.com/logo.png",
                    }
                ]
            },
        }
        jobs = parse_offertoday_listing_response(response)
        assert len(jobs) == 1
        job = jobs[0]

        assert job["source_site"] == "offertoday"
        assert job["encrypted_job_id"] == "abc123=="
        assert job["title"] == "Software Engineer"
        assert job["company_name"] == "Tech Corp"
        assert job["location"] == "Hong Kong"
        assert job["level3_location"] == "Central"
        assert job["salary_range"] == "$30K-50K/月"
        assert job["employment_type"] == "全職"
        assert job["experience"] == "3-5年"
        assert job["education"] == "學士"
        assert job["skills"] == ["Python", "Java"]
        assert job["benefits"] == ["生日假"]
        assert job["posted_at"] == "發布於06-15"

    def test_parses_salary_with_hk_prefix(self):
        response = {
            "code": 0,
            "data": {
                "resultList": [
                    {
                        "jobId": "xyz==",
                        "jobName": "Test",
                        "companyName": "Test Co",
                        "locationDesc": "Kowloon",
                        "salaryDesc": "HK $30K-50K/月",
                        "jobTypeDesc": "全職",
                    }
                ]
            },
        }
        jobs = parse_offertoday_listing_response(response)
        assert len(jobs) == 1
        # The listing parser keeps the raw salary desc; detail parser strips HK prefix
        assert "HK $30K-50K" in jobs[0]["salary_range"]


class TestParseOffertodayDetailResponse:
    def test_empty_response(self):
        result = parse_offertoday_detail_response({})
        assert result["encrypted_job_id"] == ""

    def test_parses_full_detail(self):
        response = {
            "code": 0,
            "data": {
                "jobId": "abc123==",
                "jobName": "Senior Developer",
                "jobDesc": "<p>Job description here</p>",
                "companyName": "Big Corp",
                "brandName": "Big Corp Brand",
                "brandLogo": "https://example.com/logo.png",
                "industry": {"code": 1024, "name": "IT"},
                "sizeDesc": "1000+名員工",
                "typeDesc": "上市公司",
                "locationDesc": "Hong Kong",
                "salaryDesc": "$50K-80K/月",
                "jobTypeDesc": "全職",
                "workExperienceDesc": "5-10年",
                "educationDesc": "碩士",
                "skills": ["Python", "AWS"],
                "benefits": ["雙糧", "醫療"],
                "workingDays": "5天/週",
                "workingModels": "混合辦公",
                "postDateDesc": "更新於06-17",
                "postDaysAgo": 6,
                "jobFunctions": [{"code": "112000", "name": "工程師"}],
                "locations": {"code": "HK101", "name": "香港"},
                "employType": {"code": 1, "name": "全職"},
                "addressVO": {
                    "latitude": 22.3089,
                    "longitude": 114.2635,
                },
                "bossName": "Jane",
                "bossTitle": "CTO",
                "workPermitList": ["香港永久居民"],
                "workPermitDesc": "僅香港永久居民",
            },
        }
        detail = parse_offertoday_detail_response(response)
        assert detail["encrypted_job_id"] == "abc123=="
        assert detail["title"] == "Senior Developer"
        assert detail["description_html"] == "<p>Job description here</p>"
        assert detail["description_text"] == "Job description here"
        assert detail["company_name"] == "Big Corp"
        assert detail["salary_range"] == "$50K-80K/月"
        assert detail["latitude"] == 22.3089
        assert detail["longitude"] == 114.2635

    def test_strips_hk_prefix_from_salary(self):
        response = {
            "code": 0,
            "data": {
                "jobId": "xyz==",
                "jobName": "Test",
                "salaryDesc": "HK $30K-50K/月",
            },
        }
        detail = parse_offertoday_detail_response(response)
        assert detail["salary_range"] == "$30K-50K/月"


class TestUtilityFunctions:
    def test_build_offertoday_job_url(self):
        url = build_offertoday_job_url("abc123==")
        assert url == "https://www.offertoday.com/hk/job/abc123=="

    def test_extract_encrypted_job_id_from_id(self):
        result = extract_encrypted_job_id("abc123==")
        assert result == "abc123=="

    def test_extract_encrypted_job_id_from_url(self):
        result = extract_encrypted_job_id("https://www.offertoday.com/hk/job/abc123==")
        assert result == "abc123=="

    def test_extract_encrypted_job_id_from_url_with_query(self):
        result = extract_encrypted_job_id(
            "https://www.offertoday.com/hk/job/abc123==?source=test"
        )
        assert result == "abc123=="
