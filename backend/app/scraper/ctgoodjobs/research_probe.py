"""Research-only CTgoodjobs scraping probes.

This module intentionally does not import database, scheduler, or enrichment services.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass
from typing import Any


CTGOODJOBS_BASE_URL = "https://jobs.ctgoodjobs.hk"
CTGOODJOBS_SEARCH_API_URL = "https://api01.ctgoodjobs.hk/job/api/jobs/search"


class HttpxHtmlClient:
    """Small HTML client wrapper used by the research probe.

    Defined here to keep the probe orchestrator decoupled from the rest of the app.
    """

    def __init__(self, *, timeout_s: float = 20.0):
        import httpx

        self._httpx = httpx
        self._client = httpx.Client(timeout=timeout_s, follow_redirects=True)

    def get(self, url: str) -> Any:
        return self._client.get(url)

    def post(self, url: str, *, headers: dict[str, str] | None = None, json: Any = None) -> Any:
        return self._client.post(url, headers=headers, json=json)

    def close(self) -> None:
        self._client.close()


def _response_text(response: Any) -> str:
    text = getattr(response, "text", "")
    return text if isinstance(text, str) else ""


def _response_status(response: Any) -> int | None:
    status_code = getattr(response, "status_code", None)
    return status_code if isinstance(status_code, int) else None


def _category_url(category_slug: str) -> str:
    return f"{CTGOODJOBS_BASE_URL}/jobs/jobs-in-{category_slug}"


def _category_page_url(base_url: str, *, page: int) -> str:
    if page <= 1:
        return base_url
    if "?" in base_url:
        return f"{base_url}&page={page}"
    return f"{base_url}?page={page}"


def _mapping_report(registry: list[CTGoodJobsCategory]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    debt: list[dict[str, Any]] = []

    for category in registry:
        status = category.mapping_status
        by_status[status] = by_status.get(status, 0) + 1
        if status != "clean_match":
            debt.append(
                {
                    "source_classification_id": category.source_classification_id,
                    "category_slug": category.slug,
                    "category_name": category.name,
                    "mapping_status": status,
                    "mapping_notes": category.mapping_notes,
                }
            )

    return {
        "total_categories": len(registry),
        "counts_by_status": by_status,
        "taxonomy_debt": debt,
    }


def run_research_probe(
    *,
    categories: list[str],
    max_pages: int,
    details_per_category: int,
    html_client: Any | None = None,
    api_client: Any | None = None,
    enable_api_probe: bool = False,
) -> dict[str, Any]:
    """Orchestrate a minimal, side-effect-free scrape probe and return a JSON report.

    This intentionally avoids importing database, scheduler, or enrichment modules.
    """

    owned_html_client = None
    if html_client is None:
        owned_html_client = HttpxHtmlClient()
        html_client = owned_html_client

    owned_api_client = None
    if enable_api_probe and api_client is None:
        if hasattr(html_client, "post"):
            api_client = html_client
        else:
            owned_api_client = HttpxHtmlClient()
            api_client = owned_api_client

    report: dict[str, Any] = {
        "run_metadata": {
            "source_site": "ctgoodjobs",
            "categories": list(categories),
            "max_pages": max_pages,
            "details_per_category": details_per_category,
            "enable_api_probe": enable_api_probe,
        },
        "category_registry": [],
        "category_results": [],
        "detail_results": [],
        "taxonomy_mapping_report": {},
        "api_probe_report": [],
        "playwright_diagnostics_report": [],
        "anti_scrape_report": [],
        "errors": [],
    }

    try:
        registry_url = f"{CTGOODJOBS_BASE_URL}/jobs"
        try:
            registry_resp = html_client.get(registry_url)
        except Exception as exc:  # noqa: BLE001 - probe must not throw
            report["errors"].append(
                {
                    "type": "registry_fetch_failed",
                    "url": registry_url,
                    "exception_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            return report

        registry_html = _response_text(registry_resp)
        registry = parse_category_registry(registry_html)
        report["category_registry"] = [category.to_dict() for category in registry]
        report["taxonomy_mapping_report"] = _mapping_report(registry)

        registry_by_slug = {category.slug: category for category in registry}

        for category_slug in categories:
            category = registry_by_slug.get(category_slug)
            if category is None:
                report["errors"].append(
                    {"type": "category_not_found", "category_slug": category_slug}
                )
                continue

            details_fetched_for_category = 0

            for page in range(1, max_pages + 1):
                base_category_url = category.url or _category_url(category_slug)
                page_url = _category_page_url(base_category_url, page=page)
                try:
                    resp = html_client.get(page_url)
                except Exception as exc:  # noqa: BLE001 - probe must not throw
                    report["errors"].append(
                        {
                            "type": "category_fetch_failed",
                            "category_slug": category_slug,
                            "page": page,
                            "url": page_url,
                            "exception_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )
                    continue
                if _response_status(resp) not in (None, 200):
                    report["errors"].append(
                        {
                            "type": "category_page_failed",
                            "category_slug": category_slug,
                            "page": page,
                            "url": page_url,
                            "status_code": _response_status(resp),
                        }
                    )
                    continue

                parsed = parse_category_page(
                    _response_text(resp),
                    category_slug=category_slug,
                    source_classification_id=category.source_classification_id,
                    source_classification_name=category.name,
                    page=page,
                    url=page_url,
                )
                report["category_results"].append(parsed)

                job_urls = parsed.get("job_urls")
                if not isinstance(job_urls, list):
                    continue

                if details_per_category <= 0:
                    continue

                remaining_for_category = details_per_category - details_fetched_for_category
                if remaining_for_category <= 0:
                    continue

                for job_url in job_urls:
                    if details_fetched_for_category >= details_per_category:
                        break
                    try:
                        detail_resp = html_client.get(job_url)
                    except Exception as exc:  # noqa: BLE001 - probe must not throw
                        report["errors"].append(
                            {
                                "type": "detail_fetch_failed",
                                "category_slug": category_slug,
                                "url": job_url,
                                "exception_type": type(exc).__name__,
                                "error": str(exc),
                            }
                        )
                        continue
                    if _response_status(detail_resp) not in (None, 200):
                        report["errors"].append(
                            {
                                "type": "detail_page_failed",
                                "category_slug": category_slug,
                                "url": job_url,
                                "status_code": _response_status(detail_resp),
                            }
                        )
                        continue

                    detail = parse_detail_page(
                        _response_text(detail_resp),
                        source_classification_id=category.source_classification_id,
                        source_classification_name=category.name,
                        source_classification_slug=category.slug,
                        url=job_url,
                    )
                    report["detail_results"].append(detail)
                    details_fetched_for_category += 1

        if enable_api_probe and api_client is not None:
            for category_slug in categories:
                category = registry_by_slug.get(category_slug)
                if category is None:
                    continue
                api_result = probe_search_api(
                    api_client,
                    page=1,
                    page_size=14,
                    jobcatarea_ids=[category.ctgoodjobs_id],
                    referer=category.url,
                )
                if isinstance(api_result, dict):
                    api_result = {**api_result, "category_slug": category_slug}
                report["api_probe_report"].append(api_result)
                if not api_result.get("ok", False):
                    report["anti_scrape_report"].append(
                        {
                            "signal": "api_probe_failed",
                            "category_slug": category_slug,
                            "status_code": api_result.get("status_code"),
                            "exception_type": api_result.get("exception_type"),
                        }
                    )

        return report
    finally:
        if owned_html_client is not None:
            try:
                owned_html_client.close()
            except Exception:
                pass
        if owned_api_client is not None and owned_api_client is not owned_html_client:
            try:
                owned_api_client.close()
            except Exception:
                pass

def build_search_api_payload(
    *,
    page: int,
    page_size: int,
    jobcatarea_ids: list[str],
) -> dict[str, Any]:
    """Construct the jobs search API payload from browser-captured DevTools shape."""

    return {
        "pagingInputs": {
            "page": str(page),
            "pageSize": str(page_size),
            "pageOneSize": str(page_size),
        },
        "sort": 2,
        "searchTypeId": "Y",
        "jobcatareaIds": list(jobcatarea_ids),
        "jobIds": [],
        "companyIds": [],
        "industryIds": [],
        "employmentTypeIds": [],
        "locationIds": [],
        "educationIds": [],
        "gradeIds": [],
        "channelIds": [],
        "boostedCompanyIds": [],
        "boostedJobIds": [],
    }


def build_api_headers(
    *,
    referer: str,
    sid: str = "",
    visitor_id: str = "",
) -> dict[str, str]:
    """Build the minimal browser-captured header set used by the API probe.

    These values are derived from captured browser traffic and tuned for probes,
    not a universal requirement for all clients.
    """

    return {
        "Accept": "*/*",
        "Channel-Id": "001",
        "Content-Type": "application/json",
        "Device": "m",
        "Lang": "en-US",
        "Login": "false",
        "Origin": CTGOODJOBS_BASE_URL,
        "Sid": sid,
        "Referer": referer,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
        "Visitor-Id": visitor_id,
    }


def _join_api_names(value: Any) -> str | None:
    if not isinstance(value, list) or not value:
        return None

    names: list[str] = []
    for item in value:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            raw = item.get("name")
            name = raw.strip() if isinstance(raw, str) else ""
        else:
            name = ""
        if name:
            names.append(name)

    if not names:
        return None
    return ", ".join(names)

def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _join_locations(value: Any) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    parts: list[str] = []
    for item in value:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            raw = item.get("name")
            name = raw.strip() if isinstance(raw, str) else ""
        else:
            name = ""
        if name:
            parts.append(name)
    if not parts:
        return None
    return ", ".join(parts)


def parse_search_api_response(payload: Any) -> dict[str, Any]:
    """Parse CTgoodjobs jobs/search API response into a stable, probe-friendly shape."""

    if not isinstance(payload, dict):
        return {"jobs_total": None, "title": None, "description": None, "jobs_returned": 0, "jobs": [], "errors": ["payload_not_dict"]}

    errors: list[str] = []
    status_code = payload.get("statusCode")
    if status_code != 1:
        errors.append("api_status_not_success")

    data_raw = payload.get("data")
    if not isinstance(data_raw, dict):
        errors.append("missing_data")
        data: dict[str, Any] = {}
    else:
        data = data_raw

    meta_raw = data.get("meta")
    if not isinstance(meta_raw, dict):
        errors.append("missing_meta")
        meta: dict[str, Any] = {}
    else:
        meta = meta_raw

    jobs_total = meta.get("jobsTotal") if isinstance(meta.get("jobsTotal"), int) else None
    meta_title = meta.get("title") if isinstance(meta.get("title"), str) else None
    description = meta.get("desc") if isinstance(meta.get("desc"), str) else None
    jobs_returned = data.get("total") if isinstance(data.get("total"), int) else None

    parsed_jobs: list[dict[str, Any]] = []
    raw_jobs = data.get("jobs")
    if raw_jobs is not None and not isinstance(raw_jobs, list):
        errors.append("jobs_not_list")
    if isinstance(raw_jobs, list):
        for job in raw_jobs:
            if not isinstance(job, dict):
                continue

            job_id = job.get("jobId") if isinstance(job.get("jobId"), str) else None
            title = job.get("jobTitle") if isinstance(job.get("jobTitle"), str) else None
            url = job.get("url") if isinstance(job.get("url"), str) else None
            company_id = job.get("companyId") if isinstance(job.get("companyId"), str) else None
            company_name = (
                job.get("companyName") if isinstance(job.get("companyName"), str) else None
            )
            company_url = job.get("companyUrl") if isinstance(job.get("companyUrl"), str) else None

            publish_time = job.get("publishTime") if isinstance(job.get("publishTime"), dict) else {}
            posted_date = publish_time.get("date") if isinstance(publish_time.get("date"), str) else None
            posted_timestamp = (
                publish_time.get("timestamp")
                if isinstance(publish_time.get("timestamp"), str)
                else None
            )
            valid_through = job.get("validThrough") if isinstance(job.get("validThrough"), dict) else {}
            expiry_date = valid_through.get("date") if isinstance(valid_through.get("date"), str) else None
            expiry_timestamp = (
                valid_through.get("timestamp")
                if isinstance(valid_through.get("timestamp"), str)
                else None
            )

            salary = job.get("salary") if isinstance(job.get("salary"), dict) else {}
            salary_range = (
                salary.get("salaryValue") if isinstance(salary.get("salaryValue"), str) else None
            )
            salary_min = _as_float(salary.get("salaryFrom"))
            salary_max = _as_float(salary.get("salaryTo"))
            salary_period = (
                salary.get("salaryMonthHour")
                if isinstance(salary.get("salaryMonthHour"), str)
                else None
            )

            experience = job.get("experience") if isinstance(job.get("experience"), dict) else {}
            experience_min_years = (
                experience.get("from") if isinstance(experience.get("from"), int) else None
            )
            experience_max_years = (
                experience.get("to") if isinstance(experience.get("to"), int) else None
            )

            employment_type = _join_api_names(job.get("empTypes"))
            career_level = _join_api_names(job.get("careerLevels"))
            highlights = job.get("highlights") if isinstance(job.get("highlights"), list) else []
            location = _join_locations(job.get("locations"))

            parsed_jobs.append(
                {
                    "job_id": job_id,
                    "title": title,
                    "url": url,
                    "company_id": company_id,
                    "company_name": company_name,
                    "company_url": company_url,
                    "posted_date": posted_date,
                    "posted_timestamp": posted_timestamp,
                    "expiry_date": expiry_date,
                    "expiry_timestamp": expiry_timestamp,
                    "employment_type": employment_type,
                    "career_level": career_level,
                    "salary_range": salary_range,
                    "salary_min": salary_min,
                    "salary_max": salary_max,
                    "salary_period": salary_period,
                    "experience_min_years": experience_min_years,
                    "experience_max_years": experience_max_years,
                    "highlights": highlights,
                    "location": location,
                    "raw": job,
                }
            )

    return {
        "jobs_total": jobs_total,
        "title": meta_title,
        "description": description,
        "jobs_returned": jobs_returned if isinstance(jobs_returned, int) else len(parsed_jobs),
        "jobs": parsed_jobs,
        "errors": errors,
    }


def probe_search_api(
    client: Any,
    *,
    page: int,
    page_size: int,
    jobcatarea_ids: list[str],
    referer: str,
    sid: str = "",
    visitor_id: str = "",
) -> dict[str, Any]:
    """Best-effort API probe; never raises, always returns a recording-friendly dict."""

    request_body = build_search_api_payload(page=page, page_size=page_size, jobcatarea_ids=jobcatarea_ids)
    request_headers = build_api_headers(referer=referer, sid=sid, visitor_id=visitor_id)

    try:
        response = client.post(
            CTGOODJOBS_SEARCH_API_URL,
            headers=request_headers,
            json=request_body,
        )
    except Exception as exc:  # noqa: BLE001 - probe must not throw
        return {
            "ok": False,
            "status_code": None,
            "exception_type": type(exc).__name__,
            "error": str(exc),
            "url": CTGOODJOBS_SEARCH_API_URL,
            "request_body": request_body,
        }

    status_code = getattr(response, "status_code", None)
    try:
        raw_payload = response.json()
    except Exception as exc:  # noqa: BLE001 - probe must not throw
        return {
            "ok": False,
            "status_code": status_code,
            "exception_type": type(exc).__name__,
            "error": str(exc),
            "url": CTGOODJOBS_SEARCH_API_URL,
            "request_body": request_body,
        }

    parsed = parse_search_api_response(raw_payload)
    first_job_id: str | None = None
    jobs = parsed.get("jobs")
    if isinstance(jobs, list) and jobs and isinstance(jobs[0], dict):
        first_job_id = jobs[0].get("job_id") if isinstance(jobs[0].get("job_id"), str) else None

    parse_errors = parsed.get("errors") if isinstance(parsed, dict) else None
    ok = (
        status_code == 200
        and isinstance(raw_payload, dict)
        and raw_payload.get("statusCode") == 1
        and isinstance(parse_errors, list)
        and len(parse_errors) == 0
    )
    return {
        "ok": ok,
        "status_code": status_code,
        "url": CTGOODJOBS_SEARCH_API_URL,
        "request_body": request_body,
        "response_sample": raw_payload,
        "parsed": parsed,
        "first_job_id": first_job_id,
    }


@dataclass(frozen=True)
class CategoryMapping:
    proposed_internal_domain: str
    mapping_status: str
    mapping_notes: str


@dataclass(frozen=True)
class CTGoodJobsCategory:
    source_site: str
    source_classification_id: str
    ctgoodjobs_id: str
    name: str
    slug: str
    url: str
    child_count: int
    proposed_internal_domain: str
    mapping_status: str
    mapping_notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CTGOODJOBS_CATEGORY_MAPPINGS: dict[str, CategoryMapping] = {
    "ctgoodjobs:001": CategoryMapping("Accounting", "clean_match", "Strong fit"),
    "ctgoodjobs:048": CategoryMapping(
        "Administration & Office Support", "clean_match", "Strong fit"
    ),
    "ctgoodjobs:007": CategoryMapping(
        "Banking & Financial Services", "clean_match", "Strong fit"
    ),
    "ctgoodjobs:004": CategoryMapping(
        "Construction", "conservative_match", "May overlap Engineering and Real Estate"
    ),
    "ctgoodjobs:013": CategoryMapping(
        "Design & Architecture",
        "conservative_match",
        "CT category is broader and may include non-architecture design",
    ),
    "ctgoodjobs:052": CategoryMapping(
        "Retail & Consumer Products",
        "taxonomy_debt",
        "Could be retail, marketing, technology, or operations",
    ),
    "ctgoodjobs:041": CategoryMapping(
        "Education & Training", "clean_match", "Strong fit"
    ),
    "ctgoodjobs:015": CategoryMapping("Engineering", "clean_match", "Strong fit"),
    "ctgoodjobs:010": CategoryMapping(
        "Community Services & Development",
        "taxonomy_debt",
        "May need a dedicated public-sector domain or policy",
    ),
    "ctgoodjobs:017": CategoryMapping(
        "Healthcare & Medical",
        "taxonomy_debt",
        "Beauty care does not cleanly fit medical",
    ),
    "ctgoodjobs:018": CategoryMapping(
        "Hospitality & Tourism", "clean_match", "Name differs but meaning aligns"
    ),
    "ctgoodjobs:002": CategoryMapping(
        "Human Resources & Recruitment", "clean_match", "Strong fit"
    ),
    "ctgoodjobs:021": CategoryMapping(
        "Information & Communication Technology", "clean_match", "Strong fit"
    ),
    "ctgoodjobs:022": CategoryMapping(
        "Insurance & Superannuation", "clean_match", "Strong fit for Hong Kong context"
    ),
    "ctgoodjobs:025": CategoryMapping(
        "Manufacturing, Transport & Logistics",
        "conservative_match",
        "Internal domain merges manufacturing/logistics",
    ),
    "ctgoodjobs:051": CategoryMapping(
        "Manufacturing, Transport & Logistics",
        "conservative_match",
        "Internal domain is broader",
    ),
    "ctgoodjobs:026": CategoryMapping(
        "Marketing & Communications", "clean_match", "Strong fit"
    ),
    "ctgoodjobs:003": CategoryMapping(
        "Advertising, Arts & Media", "clean_match", "Strong fit"
    ),
    "ctgoodjobs:027": CategoryMapping(
        "Healthcare & Medical", "clean_match", "Strong fit"
    ),
    "ctgoodjobs:028": CategoryMapping(
        "Manufacturing, Transport & Logistics",
        "taxonomy_debt",
        "Could map to retail, supply chain, or procurement",
    ),
    "ctgoodjobs:039": CategoryMapping(
        "Community Services & Development", "clean_match", "Strong fit"
    ),
    "ctgoodjobs:029": CategoryMapping(
        "General", "taxonomy_debt", "Too ambiguous for source-guided enrichment"
    ),
    "ctgoodjobs:049": CategoryMapping(
        "Consulting & Strategy",
        "taxonomy_debt",
        "Too broad; could include legal, accounting, consulting",
    ),
    "ctgoodjobs:032": CategoryMapping(
        "Real Estate & Property", "clean_match", "Strong fit"
    ),
    "ctgoodjobs:037": CategoryMapping(
        "Retail & Consumer Products", "clean_match", "Strong fit"
    ),
    "ctgoodjobs:038": CategoryMapping(
        "Sales", "conservative_match", "Contains customer service and business development"
    ),
    "ctgoodjobs:043": CategoryMapping(
        "Hospitality & Tourism", "conservative_match", "Shares domain with hotel/catering"
    ),
}


_NEXT_F_PUSH_PATTERN = re.compile(
    r"self\.__next_f\.push\s*\(\s*\[\s*\d+\s*,\s*\"(?P<payload>.*?)\"\s*\]\s*\)\s*;?",
    re.DOTALL,
)

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
_HREF_PATTERN = re.compile(
    r"href\s*=\s*(?P<q>[\"'])(?P<href>.*?)(?P=q)",
    re.IGNORECASE | re.DOTALL,
)


def _decode_rendered_text(value: str) -> str:
    # The payload captured from `self.__next_f.push([1,"..."])` is a JS/JSON-string-like
    # fragment with backslash escapes (e.g. `\\"`). Decoding via `unicode_escape` can
    # corrupt non-ASCII (e.g. Chinese). Instead, interpret it as a JSON string literal.
    try:
        decoded = json.loads(f'"{value}"')
    except json.JSONDecodeError:
        decoded = value
    return html.unescape(decoded)


def _extract_title(page_html: str) -> str | None:
    match = _TITLE_PATTERN.search(page_html)
    if not match:
        return None
    return html.unescape(match.group("title").strip())


def _parse_tag_attributes(attrs_text: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _ATTR_PATTERN.finditer(attrs_text):
        key = match.group("key").strip().lower()
        raw_value = match.group("value").strip()
        if raw_value and raw_value[0] in {"'", '"'} and raw_value[-1] == raw_value[0]:
            value = raw_value[1:-1]
        else:
            value = raw_value
        attrs[key] = value
    return attrs


def _extract_meta_content(page_html: str, name: str) -> str | None:
    wanted = name.lower()
    for match in _META_TAG_PATTERN.finditer(page_html):
        attrs = _parse_tag_attributes(match.group("attrs"))
        if attrs.get("name", "").strip().lower() != wanted:
            continue
        content = attrs.get("content")
        if not isinstance(content, str):
            continue
        return html.unescape(content.strip())
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
        script_type = attrs.get("type", "").strip().lower()
        if script_type != "application/ld+json":
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

    for match in _HREF_PATTERN.finditer(page_html):
        href = match.group("href").strip()
        if not href:
            continue

        normalized: str | None = None
        if href.startswith("/job/"):
            normalized = f"{CTGOODJOBS_BASE_URL}{href}"
        elif href.startswith(f"{CTGOODJOBS_BASE_URL}/job/"):
            normalized = href

        if normalized is None:
            continue
        if _job_id_from_url(normalized) is None:
            continue
        if normalized in seen:
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


def _extract_json_object_after_marker(payload_text: str, marker: str) -> dict[str, Any] | None:
    """Best-effort extraction of a JSON object immediately after a marker within text.

    Designed for payloads like: {"jobContent":{...}}
    """

    start = payload_text.find(marker)
    if start < 0:
        return None

    # Find the opening '{' for the object after marker, then scan for its matching close.
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


def _find_jobcats_container(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        if isinstance(payload.get("jobcats"), list):
            return payload
        for value in payload.values():
            found = _find_jobcats_container(value)
            if found is not None:
                return found
        return None

    if isinstance(payload, list):
        for item in payload:
            found = _find_jobcats_container(item)
            if found is not None:
                return found

    return None


def _find_job_content_container(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        job_content = payload.get("jobContent")
        if isinstance(job_content, dict):
            return job_content
        for value in payload.values():
            found = _find_job_content_container(value)
            if found is not None:
                return found
        return None

    if isinstance(payload, list):
        for item in payload:
            found = _find_job_content_container(item)
            if found is not None:
                return found

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


def _decode_next_f_payload_json(payload_text: str) -> Any | None:
    candidate = payload_text.strip()
    match = re.match(r"^\d+:(?P<body>.*)$", candidate, re.DOTALL)
    if match:
        candidate = match.group("body").strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
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

        # Our marker-based extraction returns the object after "jobContent":, which is the
        # job content dictionary itself.
        if isinstance(extracted.get("jobId"), str):
            return {"jobContent": extracted}

        job_content = extracted.get("jobContent")
        if isinstance(job_content, dict):
            return extracted
    return None


def _extract_job_content(page_html: str) -> dict[str, Any] | None:
    detail_payload = _extract_detail_payload(page_html)
    if not isinstance(detail_payload, dict):
        return None
    job_content = detail_payload.get("jobContent")
    return job_content if isinstance(job_content, dict) else None


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
    if not names:
        return None
    return ", ".join(names)


def _salary_value(salary_obj: Any) -> str | None:
    if not isinstance(salary_obj, dict):
        return None
    value = salary_obj.get("salaryValue")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _first_salary_value(items: Any) -> str | None:
    if not isinstance(items, list):
        return None
    for item in items:
        value = _salary_value(item)
        if value:
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
    basic_info = {}
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
        job_content.get("jobDescription")
        if isinstance(job_content.get("jobDescription"), str)
        else None
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

def parse_category_registry(page_html: str) -> list[CTGoodJobsCategory]:
    categories: list[CTGoodJobsCategory] = []
    index_by_key: dict[tuple[str, str], int] = {}

    for match in _NEXT_F_PUSH_PATTERN.finditer(page_html):
        payload_text = _decode_rendered_text(match.group("payload"))
        payload_obj = _decode_next_f_payload_json(payload_text)
        if payload_obj is None:
            continue

        container = _find_jobcats_container(payload_obj)
        if container is None:
            continue

        jobcats = container.get("jobcats")
        if not isinstance(jobcats, list):
            continue

        for category in jobcats:
            if not isinstance(category, dict):
                continue

            raw_id = category.get("id")
            if not isinstance(raw_id, str):
                continue
            id_match = re.match(r"^(?P<id>[^_]+)_jc$", raw_id)
            if not id_match:
                continue

            total = category.get("total")
            name = category.get("name")
            slug = category.get("nameForUrl")
            if not isinstance(total, int) or not isinstance(name, str) or not isinstance(slug, str):
                continue

            ctgoodjobs_id = id_match.group("id")
            dedupe_key = (ctgoodjobs_id, slug)
            existing_index = index_by_key.get(dedupe_key)

            source_id = f"ctgoodjobs:{ctgoodjobs_id}"
            mapping = CTGOODJOBS_CATEGORY_MAPPINGS.get(
                source_id,
                CategoryMapping("General", "taxonomy_debt", "No reviewed mapping exists"),
            )
            parsed = CTGoodJobsCategory(
                source_site="ctgoodjobs",
                source_classification_id=source_id,
                ctgoodjobs_id=ctgoodjobs_id,
                name=name,
                slug=slug,
                url=f"{CTGOODJOBS_BASE_URL}/jobs/jobs-in-{slug}",
                child_count=total,
                proposed_internal_domain=mapping.proposed_internal_domain,
                mapping_status=mapping.mapping_status,
                mapping_notes=mapping.mapping_notes,
            )

            if existing_index is None:
                index_by_key[dedupe_key] = len(categories)
                categories.append(parsed)
                continue

            # When a duplicate category exists for the same (id, slug), prefer the English
            # record if we can detect it. In practice CTgoodjobs often provides both
            # Chinese and English names with the same id/slug.
            existing = categories[existing_index]
            existing_is_english = existing.name.isascii()
            parsed_is_english = parsed.name.isascii()
            if not existing_is_english and parsed_is_english:
                categories[existing_index] = parsed

    return categories
