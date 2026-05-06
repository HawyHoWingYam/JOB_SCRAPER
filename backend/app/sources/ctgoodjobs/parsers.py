from __future__ import annotations

import html
import json
import re
from typing import Any

from app.scraper.ctgoodjobs.category_registry import CTGOODJOBS_BASE_URL


_TITLE_PATTERN = re.compile(r"<title>\s*(?P<title>.*?)\s*</title>", re.IGNORECASE | re.DOTALL)
_META_TAG_PATTERN = re.compile(r"<meta\b(?P<attrs>[^>]*)>", re.IGNORECASE)
_SCRIPT_JSON_LD_PATTERN = re.compile(
    r"<script\b(?P<attrs>[^>]*)>\s*(?P<json>.*?)\s*</script>",
    re.IGNORECASE | re.DOTALL,
)
_ATTR_PATTERN = re.compile(
    r"(?P<key>[^\s=/>]+)\s*=\s*(?P<value>\"[^\"]*\"|'[^']*'|[^\s>]+)",
    re.IGNORECASE,
)
_NEXT_F_PUSH_PATTERN = re.compile(
    r"self\.__next_f\.push\s*\(\s*\[\s*\d+\s*,\s*\"(?P<payload>.*?)\"\s*\]\s*\)\s*;?",
    re.DOTALL,
)


def _parse_tag_attributes(attrs: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for match in _ATTR_PATTERN.finditer(attrs):
        key = match.group("key").strip().lower()
        raw_value = match.group("value").strip()
        if raw_value.startswith(("\"", "'")) and raw_value.endswith(("\"", "'")):
            raw_value = raw_value[1:-1]
        parsed[key] = raw_value
    return parsed


def _extract_title(page_html: str) -> str | None:
    match = _TITLE_PATTERN.search(page_html)
    if not match:
        return None
    title = match.group("title")
    return title.strip() if isinstance(title, str) and title.strip() else None


def _extract_meta_content(page_html: str, name: str) -> str | None:
    needle = name.strip().lower()
    for match in _META_TAG_PATTERN.finditer(page_html):
        attrs = _parse_tag_attributes(match.group("attrs"))
        meta_name = attrs.get("name", "").strip().lower()
        if meta_name != needle:
            continue
        content = attrs.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


def _find_item_list_json(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        payload_type = payload.get("@type")
        if payload_type == "ItemList":
            return payload
        if isinstance(payload_type, list) and "ItemList" in payload_type:
            return payload
        graph = payload.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                found = _find_item_list_json(item)
                if found is not None:
                    return found
        return None
    if isinstance(payload, list):
        for item in payload:
            found = _find_item_list_json(item)
            if found is not None:
                return found
        return None
    return None


def _extract_item_list_json(page_html: str) -> dict[str, Any] | None:
    for match in _SCRIPT_JSON_LD_PATTERN.finditer(page_html):
        attrs = _parse_tag_attributes(match.group("attrs"))
        if attrs.get("type", "").strip().lower() != "application/ld+json":
            continue
        raw = match.group("json").strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        found = _find_item_list_json(obj)
        if found is not None:
            return found
    return None


def _job_id_from_url(url: str) -> str | None:
    match = re.search(r"/job/(?P<job_id>\d+)(?:/|$)", url)
    if not match:
        return None
    return match.group("job_id")


def _extract_job_urls_from_json_ld(item_list_json: dict[str, Any]) -> list[str]:
    elements = item_list_json.get("itemListElement")
    if not isinstance(elements, list):
        return []
    urls: list[str] = []
    seen: set[str] = set()
    for element in elements:
        if not isinstance(element, dict):
            continue
        url = element.get("url")
        if not isinstance(url, str) or not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _extract_job_urls_from_html(page_html: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"href\s*=\s*(?P<q>[\"'])(?P<href>.*?)(?P=q)", page_html, re.IGNORECASE | re.DOTALL):
        href = match.group("href").strip()
        if not href:
            continue
        normalized: str | None = None
        if href.startswith("/job/"):
            normalized = f"{CTGOODJOBS_BASE_URL}{href}"
        elif href.startswith(f"{CTGOODJOBS_BASE_URL}/job/"):
            normalized = href
        if normalized is None or _job_id_from_url(normalized) is None or normalized in seen:
            continue
        seen.add(normalized)
        urls.append(normalized)
    return urls


def _extract_job_urls(page_html: str, item_list_json: dict[str, Any] | None) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    if item_list_json is not None:
        for url in _extract_job_urls_from_json_ld(item_list_json):
            if url in seen:
                continue
            seen.add(url)
            merged.append(url)
    for url in _extract_job_urls_from_html(page_html):
        if url in seen:
            continue
        seen.add(url)
        merged.append(url)
    return merged


def _decode_rendered_text(value: str) -> str:
    try:
        decoded = json.loads(f'"{value}"')
    except json.JSONDecodeError:
        decoded = value
    return html.unescape(decoded)


def _decode_next_f_payload_json(payload_text: str) -> Any | None:
    candidate = payload_text.strip()
    match = re.match(r"^\d+:(?P<body>.*)$", candidate, re.DOTALL)
    if match:
        candidate = match.group("body").strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _find_detail_payload_container(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        if isinstance(payload.get("jobContent"), dict):
            return payload
        for value in payload.values():
            found = _find_detail_payload_container(value)
            if found is not None:
                return found
        return None
    if isinstance(payload, list):
        for item in payload:
            found = _find_detail_payload_container(item)
            if found is not None:
                return found
    return None


def _extract_json_object_after_marker(payload_text: str, marker: str) -> dict[str, Any] | None:
    start = payload_text.find(marker)
    if start < 0:
        return None
    brace_start = payload_text.find("{", start)
    if brace_start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(brace_start, len(payload_text)):
        ch = payload_text[i]
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                snippet = payload_text[brace_start : i + 1]
                try:
                    obj = json.loads(snippet)
                except json.JSONDecodeError:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


def _extract_detail_payload(page_html: str) -> dict[str, Any] | None:
    for match in _NEXT_F_PUSH_PATTERN.finditer(page_html):
        payload_text = _decode_rendered_text(match.group("payload"))
        payload_obj = _decode_next_f_payload_json(payload_text)
        detail_payload = _find_detail_payload_container(payload_obj)
        if detail_payload is not None:
            return detail_payload
        extracted = _extract_json_object_after_marker(payload_text, '"jobContent"')
        if extracted is None:
            continue
        if isinstance(extracted.get("jobId"), str):
            return {"jobContent": extracted}
        job_content = extracted.get("jobContent")
        if isinstance(job_content, dict):
            return extracted
    return None


def _find_job_posting_json(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        if payload.get("@type") == "JobPosting":
            return payload
        for value in payload.values():
            found = _find_job_posting_json(value)
            if found is not None:
                return found
        return None
    if isinstance(payload, list):
        for item in payload:
            found = _find_job_posting_json(item)
            if found is not None:
                return found
    return None


def _extract_job_posting_json(page_html: str) -> dict[str, Any] | None:
    for match in _SCRIPT_JSON_LD_PATTERN.finditer(page_html):
        attrs = _parse_tag_attributes(match.group("attrs"))
        if attrs.get("type", "").strip().lower() != "application/ld+json":
            continue
        try:
            parsed = json.loads(html.unescape(match.group("json").strip()))
        except json.JSONDecodeError:
            continue
        found = _find_job_posting_json(parsed)
        if found is not None:
            return found
    return None


def _join_names(items: Any) -> str | None:
    if not isinstance(items, list) or not items:
        return None
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return ", ".join(names) if names else None


def _salary_value(salary_obj: Any) -> str | None:
    if not isinstance(salary_obj, dict):
        return None
    value = salary_obj.get("salaryValue")
    raw: Any
    if isinstance(value, dict):
        raw = value.get("value")
    else:
        raw = value
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, (int, float)):
        return str(raw)
    return None


def _first_salary_value(items: Any) -> str | None:
    if not isinstance(items, list) or not items:
        return None
    for item in items:
        value = _salary_value(item)
        if value is not None:
            return value
    return None


def _job_posting_salary_value(job_posting: dict[str, Any] | None) -> str | None:
    if not isinstance(job_posting, dict):
        return None
    base_salary = job_posting.get("baseSalary")
    if not isinstance(base_salary, dict):
        return None
    value = base_salary.get("value")
    if isinstance(value, dict):
        raw = value.get("value")
    else:
        raw = value
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, (int, float)):
        return str(raw)
    return None


def _job_posting_employment_type(job_posting: dict[str, Any] | None) -> str | None:
    if not isinstance(job_posting, dict):
        return None
    raw = job_posting.get("employmentType")
    if isinstance(raw, list):
        values = [str(item).strip() for item in raw if str(item).strip()]
    elif isinstance(raw, str):
        values = re.findall(r"[A-Z_]+", raw)
        if not values and raw.strip():
            values = [raw.strip()]
    else:
        values = []
    normalized = {
        "FULL_TIME": "Full-time",
        "PART_TIME": "Part-time",
        "CONTRACTOR": "Contract",
        "TEMPORARY": "Temporary",
        "INTERN": "Internship",
        "OTHER": "Other",
    }
    labels = [normalized.get(value, value.replace("_", " ").title()) for value in values]
    return ", ".join(labels) if labels else None


def _experience_years_from_name(value: Any) -> tuple[int | None, int | None]:
    if not isinstance(value, str):
        return None, None
    numbers = [int(match) for match in re.findall(r"\d+", value)]
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    return None, None


def _extract_experience_name_from_page(page_html: str) -> str | None:
    for match in _NEXT_F_PUSH_PATTERN.finditer(page_html):
        payload_text = _decode_rendered_text(match.group("payload"))
        matched = re.search(
            r'"experiences"\s*:\s*\{[^{}]*"name"\s*:\s*"(?P<name>[^"]+)"',
            payload_text,
        )
        if matched:
            return html.unescape(matched.group("name"))
    return None


def _job_posting_description(job_posting: dict[str, Any] | None) -> str | None:
    if not isinstance(job_posting, dict):
        return None
    description = job_posting.get("description")
    return description.strip() if isinstance(description, str) and description.strip() else None


def _job_posting_location(job_posting: dict[str, Any] | None) -> str | None:
    if not isinstance(job_posting, dict):
        return None
    locations = job_posting.get("jobLocation")
    if not isinstance(locations, list):
        locations = [locations] if isinstance(locations, dict) else []
    names: list[str] = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        address = location.get("address")
        if not isinstance(address, dict):
            continue
        for key in ("addressLocality", "streetAddress", "addressRegion"):
            value = address.get(key)
            if isinstance(value, str) and value.strip():
                names.append(value.strip())
                break
    return ", ".join(names) if names else None


def _coverage(result: dict[str, Any], required_fields: list[str]) -> dict[str, int]:
    present = 0
    for key in required_fields:
        value = result.get(key)
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        present += 1
    return {"required_total": len(required_fields), "required_present": present}


def _has_description(result: dict[str, Any]) -> bool:
    description_html = result.get("description_html")
    if isinstance(description_html, str) and description_html.strip():
        return True
    description_text = result.get("description_text")
    return isinstance(description_text, str) and description_text.strip() != ""


def parse_category_page(
    page_html: str,
    *,
    category_slug: str,
    source_classification_id: str,
    source_classification_name: str,
    page: int,
    url: str,
) -> dict[str, Any]:
    errors: list[str] = []
    item_list = _extract_item_list_json(page_html)
    if item_list is None:
        errors.append("missing_item_list_json_ld")
        total_count = None
    else:
        num = item_list.get("numberOfItems")
        total_count = num if isinstance(num, int) else None
        if total_count is None:
            errors.append("missing_number_of_items")

    json_ld_title = item_list.get("name") if isinstance(item_list, dict) else None
    title = json_ld_title if isinstance(json_ld_title, str) and json_ld_title.strip() else None
    if title is None:
        title = _extract_title(page_html)
    if title is None:
        errors.append("missing_title")
        title = ""

    json_ld_description = item_list.get("description") if isinstance(item_list, dict) else None
    description = (
        json_ld_description
        if isinstance(json_ld_description, str) and json_ld_description.strip()
        else None
    )
    if description is None:
        description = _extract_meta_content(page_html, "description")
    if description is None:
        description = ""

    job_urls = _extract_job_urls(page_html, item_list)
    job_ids: list[str] = []
    seen_ids: set[str] = set()
    for job_url in job_urls:
        job_id = _job_id_from_url(job_url)
        if job_id is None or job_id in seen_ids:
            continue
        seen_ids.add(job_id)
        job_ids.append(job_id)

    return {
        "source_site": "ctgoodjobs",
        "source_classification_id": source_classification_id,
        "source_classification_name": source_classification_name,
        "category_slug": category_slug,
        "page": page,
        "url": url,
        "title": title,
        "description": description,
        "total_count": total_count,
        "job_urls": job_urls,
        "job_ids": job_ids,
        "errors": errors,
    }


def parse_detail_page(
    page_html: str,
    *,
    source_classification_id: str,
    source_classification_name: str,
    source_classification_slug: str,
    url: str,
) -> dict[str, Any]:
    errors: list[str] = []
    detail_payload = _extract_detail_payload(page_html)
    job_content = (
        detail_payload.get("jobContent")
        if isinstance(detail_payload, dict) and isinstance(detail_payload.get("jobContent"), dict)
        else None
    )
    job_posting = _extract_job_posting_json(page_html)
    if job_content is None:
        errors.append("missing_job_content")
        job_content = {}

    basic_info: dict[str, Any] = {}
    if isinstance(job_content.get("basicInfo"), dict):
        basic_info = job_content["basicInfo"]
    elif isinstance(detail_payload, dict):
        candidate_basic_info = detail_payload.get("basicInfo")
        if isinstance(candidate_basic_info, dict):
            basic_info = candidate_basic_info

    job_id = job_content.get("jobId") if isinstance(job_content.get("jobId"), str) else None
    if job_id is None:
        job_id = _job_id_from_url(url)

    title = job_content.get("jobTitle") if isinstance(job_content.get("jobTitle"), str) else None
    if title is None:
        title = _extract_title(page_html)

    company_id = job_content.get("companyId") if isinstance(job_content.get("companyId"), str) else None
    company_name = (
        job_content.get("companyName") if isinstance(job_content.get("companyName"), str) else None
    )
    company_url = (
        job_content.get("companyUrl") if isinstance(job_content.get("companyUrl"), str) else None
    )
    posted_date = (
        job_content.get("startPostDate")
        if isinstance(job_content.get("startPostDate"), str)
        else None
    )
    expiry_date = (
        job_content.get("endPostDate") if isinstance(job_content.get("endPostDate"), str) else None
    )
    employment_type = (
        _join_names(job_content.get("workTypes"))
        or _join_names(basic_info.get("empTypes"))
        or _job_posting_employment_type(job_posting)
    )
    salary_range = (
        _salary_value(job_content.get("salary"))
        or _first_salary_value(basic_info.get("salaries"))
        or _job_posting_salary_value(job_posting)
    )
    experience = job_content.get("experience") if isinstance(job_content.get("experience"), dict) else {}
    experience_min_years = experience.get("from") if isinstance(experience.get("from"), int) else None
    experience_max_years = experience.get("to") if isinstance(experience.get("to"), int) else None
    if experience_min_years is None and experience_max_years is None:
        basic_experience = basic_info.get("experiences")
        if isinstance(basic_experience, dict):
            experience_min_years, experience_max_years = _experience_years_from_name(
                basic_experience.get("name")
            )
    if experience_min_years is None and experience_max_years is None:
        experience_min_years, experience_max_years = _experience_years_from_name(
            _extract_experience_name_from_page(page_html)
        )

    description_html = (
        job_content.get("jobDescription") if isinstance(job_content.get("jobDescription"), str) else None
    )
    if description_html is None:
        description_html = _job_posting_description(job_posting)

    description_text = _extract_meta_content(page_html, "description")
    location = _join_names(job_content.get("jobLocations")) or _join_names(job_content.get("locations"))
    if location is None:
        location = _job_posting_location(job_posting)
    if location is None and isinstance(description_text, str):
        loc_match = re.search(r"\bLocated in\s+(?P<location>[^,.;]+)", description_text)
        if loc_match:
            location = loc_match.group("location").strip()

    result: dict[str, Any] = {
        "source_site": "ctgoodjobs",
        "url": url,
        "job_id": job_id,
        "title": title,
        "company_id": company_id,
        "company_name": company_name,
        "company_url": company_url,
        "posted_date": posted_date,
        "expiry_date": expiry_date,
        "employment_type": employment_type,
        "salary_range": salary_range,
        "experience_min_years": experience_min_years,
        "experience_max_years": experience_max_years,
        "description_html": description_html,
        "description_text": description_text,
        "location": location,
        "source_classification_id": source_classification_id,
        "source_classification_name": source_classification_name,
        "source_classification_slug": source_classification_slug,
        "errors": errors,
    }

    required = [
        "job_id",
        "title",
        "company_id",
        "company_name",
        "company_url",
        "posted_date",
        "expiry_date",
        "location",
        "employment_type",
        "salary_range",
        "experience_min_years",
        "experience_max_years",
        "source_classification_id",
        "source_classification_name",
        "source_classification_slug",
    ]
    coverage = _coverage(result, required)
    coverage["required_total"] += 1
    if _has_description(result):
        coverage["required_present"] += 1
    result["field_coverage"] = coverage
    return result
