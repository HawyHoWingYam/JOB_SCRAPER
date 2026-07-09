"""Pure parsing functions for OfferToday API responses.

OfferToday uses a REST API:
- Listing: POST /wapi/geek/recommend/list (or search/list)
  Request: {"page":1, "pageSize":10, ...filters}
  Response: {"code":0, "data":{"resultList":[...]}}
- Detail: GET /wapi/geek/recommend/jobDetail?id={encryptedJobId}&...
  Response: {"code":0, "data":{...jobDetail}}

The API requires specific headers: api-language=zh_HK, x-requested-with=XMLHttpRequest,
and cookies (acw_tc for WAF). Job IDs are base64-encrypted strings.
"""

from __future__ import annotations

from typing import Any

from app.sources.offertoday.quality import clean_description_text, normalize_tag_terms

OFFERTODOAY_JOB_URL_TEMPLATE = "https://www.offertoday.com/hk/job/{encrypted_job_id}"

# Employment type mapping
EMPLOYMENT_TYPE_MAP: dict[int, str] = {
    1: "全職",
    2: "兼職",
    3: "實習",
}


def parse_offertoday_listing_response(response_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse the listing/search API response into a list of raw job dicts."""
    data = response_data.get("data") or {}
    result_list = data.get("resultList") or []
    parsed = []
    for raw_job in result_list:
        parsed.append(_parse_listing_job(raw_job))
    return parsed


def _parse_listing_job(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert a single listing API item into the internal raw dict."""
    job_id = str(raw.get("jobId") or "").strip()
    encrypted_job_id = str(raw.get("encryptJobId") or job_id).strip()
    return {
        "source_site": "offertoday",
        "job_id": job_id,
        "encrypted_job_id": encrypted_job_id,
        "title": str(raw.get("jobName") or "").strip(),
        "company_name": str(raw.get("companyName") or "").strip(),
        "location": str(raw.get("locationDesc") or "").strip(),
        "level3_location": str(raw.get("level3LocDesc") or "").strip(),
        "salary_range": str(raw.get("salaryDesc") or "").strip(),
        "employment_type": str(raw.get("jobTypeDesc") or "").strip(),
        "experience": str(raw.get("experience") or "").strip(),
        "education": str(raw.get("educationDesc") or "").strip(),
        "skills": raw.get("skills") or [],
        "skill_list": raw.get("skillList") or [],
        "keywords": raw.get("keywords") or [],
        "benefits": raw.get("benefits") or [],
        "working_days": str(raw.get("workingDays") or "").strip(),
        "posted_at": str(raw.get("jobPostTime") or "").strip(),
        "job_functions": raw.get("jobFunctions") or [],
        "locations_tree": raw.get("locations") or {},
        "employ_type_code": raw.get("jobType"),
        "active_status": str(raw.get("activeStatus") or "").strip(),
        "recruiter_name": str(raw.get("bossName") or "").strip(),
        "recruiter_title": str(raw.get("bossTitle") or "").strip(),
        "company_logo": str(raw.get("brandLogo") or "").strip(),
        "raw_data": dict(raw),
    }


def parse_offertoday_detail_response(response_data: dict[str, Any]) -> dict[str, Any]:
    """Parse the job detail API response into a dict."""
    data = response_data.get("data") or {}
    job_id = str(data.get("jobId") or "").strip()
    encrypted_job_id = str(data.get("encryptJobId") or job_id).strip()
    description_html = str(data.get("jobDesc") or "").strip()
    description_text = clean_description_text(_strip_html(description_html))
    blocked_terms = {
        str(value).strip() for value in (data.get("benefits") or []) if str(value).strip()
    }
    return {
        "source_site": "offertoday",
        "job_id": job_id,
        "encrypted_job_id": encrypted_job_id,
        "title": str(data.get("jobName") or "").strip(),
        "description_html": description_html,
        "description_text": description_text,
        "company_name": str(data.get("companyName") or "").strip(),
        "company_brand": str(data.get("brandName") or "").strip(),
        "company_logo": str(data.get("brandLogo") or "").strip(),
        "company_industry": str(
            (data.get("industry") or {}).get("name") or ""
        ).strip(),
        "company_size": str(data.get("sizeDesc") or "").strip(),
        "company_type": str(data.get("typeDesc") or "").strip(),
        "location": str(data.get("locationDesc") or "").strip(),
        "salary_range": str(data.get("salaryDesc") or "").strip().removeprefix("HK "),
        "employment_type": str(data.get("jobTypeDesc") or "").strip(),
        "experience": str(data.get("workExperienceDesc") or "").strip(),
        "education": str(data.get("educationDesc") or "").strip(),
        "skills": normalize_tag_terms(data.get("skills") or [], blocked_terms=blocked_terms),
        "skill_list": normalize_tag_terms(
            data.get("skillList") or [],
            blocked_terms=blocked_terms,
        ),
        "keywords": normalize_tag_terms(data.get("keywords") or [], blocked_terms=blocked_terms),
        "benefits": data.get("benefits") or [],
        "working_days": str(data.get("workingDays") or "").strip(),
        "working_model": str(data.get("workingModels") or "").strip(),
        "posted_desc": str(data.get("postDateDesc") or "").strip(),
        "posted_days_ago": data.get("postDaysAgo"),
        "job_functions": data.get("jobFunctions") or [],
        "locations_tree": data.get("locations") or {},
        "employ_type": (data.get("employType") or {}).get("name"),
        "address": data.get("addressVO") or {},
        "latitude": (data.get("addressVO") or {}).get("latitude"),
        "longitude": (data.get("addressVO") or {}).get("longitude"),
        "recruiter_name": str(data.get("bossName") or "").strip(),
        "recruiter_title": str(data.get("bossTitle") or "").strip(),
        "work_permit_list": data.get("workPermitList") or [],
        "work_permit_desc": str(data.get("workPermitDesc") or "").strip(),
        "raw_data": dict(data),
    }


def _strip_html(html_content: str) -> str:
    """Crude HTML-to-text stripping. Keeps paragraph breaks."""
    import re as _re

    text = _re.sub(r"<br\s*/?>", "\n", html_content)
    text = _re.sub(r"</p>", "\n", text)
    text = _re.sub(r"</li>", "\n", text)
    text = _re.sub(r"<[^>]+>", "", text)
    text = _re.sub(r"\n\s*\n", "\n", text)
    text = _re.sub(r"&nbsp;", " ", text)
    text = _re.sub(r"&amp;", "&", text)
    text = _re.sub(r"&lt;", "<", text)
    text = _re.sub(r"&gt;", ">", text)
    text = _re.sub(r"&quot;", '"', text)
    return text.strip()


def extract_encrypted_job_id(job_url_or_id: str) -> str:
    """Extract the encrypted job ID from a full URL or just return it."""
    job_url_or_id = job_url_or_id.strip()
    if "/hk/job/" in job_url_or_id:
        return job_url_or_id.rsplit("/hk/job/", 1)[-1].split("?")[0].split("#")[0]
    return job_url_or_id


def build_offertoday_job_url(encrypted_job_id: str) -> str:
    """Build the canonical job URL for OfferToday."""
    return OFFERTODOAY_JOB_URL_TEMPLATE.format(encrypted_job_id=encrypted_job_id)
