from __future__ import annotations

import json
import re
from html import unescape
from typing import Any

from app.utils.time import utc_now


def _transform_job(raw_job: dict[str, Any]) -> dict[str, Any]:
    advertiser = raw_job.get("advertiser", {})
    locations = raw_job.get("locations", [{}])
    classifications = raw_job.get("classifications", [{}])
    work_arrangements = raw_job.get("workArrangements", {}).get("data", [])
    branding = raw_job.get("branding", {})

    return {
        "external_id": raw_job.get("id"),
        "title": raw_job.get("title"),
        "company_name": raw_job.get("companyName"),
        "advertiser_id": advertiser.get("id"),
        "advertiser_name": advertiser.get("description"),
        "bullet_points": raw_job.get("bulletPoints", []),
        "location": locations[0].get("label") if locations else None,
        "country_code": locations[0].get("countryCode") if locations else None,
        "salary_label": raw_job.get("salaryLabel"),
        "listing_date": raw_job.get("listingDate"),
        "listing_date_display": raw_job.get("listingDateDisplay"),
        "teaser": raw_job.get("teaser"),
        "work_types": raw_job.get("workTypes", []),
        "work_arrangements": [
            arr.get("label", {}).get("text")
            for arr in work_arrangements
            if arr.get("label", {}).get("text")
        ],
        "classification_id": (
            classifications[0].get("classification", {}).get("id")
            if classifications else None
        ),
        "classification_name": (
            classifications[0].get("classification", {}).get("description")
            if classifications else None
        ),
        "logo_url": branding.get("serpLogoUrl"),
    }


def parse_search_response(payload: dict[str, Any]) -> dict[str, Any]:
    jobs = payload.get("data") or []
    transformed = [_transform_job(job) for job in jobs if isinstance(job, dict)]
    return {
        "total_count": payload.get("totalCount", 0),
        "jobs": transformed,
        "raw_data": payload,
    }


def _extract_redux_data(page_html: str) -> dict[str, Any] | None:
    marker = "window.SEEK_REDUX_DATA"
    start_idx = page_html.find(marker)
    if start_idx == -1:
        return None

    brace_start = page_html.find("{", start_idx)
    if brace_start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False
    end_idx = brace_start

    for i, char in enumerate(page_html[brace_start:], brace_start):
        if escape_next:
            escape_next = False
            continue

        if char == "\\" and in_string:
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if not in_string:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end_idx = i + 1
                    break

    if depth != 0:
        return None

    try:
        return json.loads(page_html[brace_start:end_idx])
    except json.JSONDecodeError:
        return None


def parse_detail_redux_data(redux_data: dict[str, Any], job_id: str) -> dict[str, Any] | None:
    try:
        job_details_container = redux_data.get("jobdetails", {})
        result = job_details_container.get("result", {})
        job = result.get("job", {})

        if not job or not isinstance(job, dict):
            return None

        tracking = job.get("tracking", {})
        classification_info = tracking.get("classificationInfo", {})
        content_html = job.get("content", "")
        listed_at = job.get("listedAt", {})
        listing_date = listed_at.get("dateTimeUtc") if isinstance(listed_at, dict) else None
        expires_at = job.get("expiresAt", {})
        expiry_date = expires_at.get("dateTimeUtc") if isinstance(expires_at, dict) else None
        work_types = job.get("workTypes", {})
        work_type = work_types.get("label", "") if isinstance(work_types, dict) else ""
        location = job.get("location", {})
        location_label = location.get("label", "") if isinstance(location, dict) else ""
        advertiser = job.get("advertiser", {})
        advertiser_id = advertiser.get("id", "") if isinstance(advertiser, dict) else ""
        advertiser_name = advertiser.get("name", "") if isinstance(advertiser, dict) else ""

        return {
            "jobsdb_id": job_id,
            "title": job.get("title", ""),
            "abstract": job.get("abstract", ""),
            "description_html": unescape(content_html) if content_html else "",
            "classification_id": classification_info.get("classificationId"),
            "classification": classification_info.get("classification"),
            "subclassification_id": classification_info.get("subClassificationId"),
            "subclassification": classification_info.get("subClassification"),
            "location": location_label,
            "work_type": work_type,
            "salary": job.get("salary"),
            "listing_date": listing_date,
            "expiry_date": expiry_date,
            "is_expired": job.get("isExpired", False),
            "advertiser_id": advertiser_id,
            "advertiser_name": advertiser_name,
            "status": job.get("status", ""),
            "scraped_at": utc_now().isoformat(),
        }
    except (KeyError, TypeError):
        return None


def parse_detail_page(page_html: str, *, job_id: str) -> dict[str, Any] | None:
    redux_data = _extract_redux_data(page_html)
    if not redux_data:
        return None
    return parse_detail_redux_data(redux_data, job_id)
