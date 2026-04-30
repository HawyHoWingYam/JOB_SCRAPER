"""Production CTgoodjobs list scraper (SSR HTML-first).

Parsing logic is extracted from the validated research probe implementation.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

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
_HREF_PATTERN = re.compile(
    r"href\s*=\s*(?P<q>[\"'])(?P<href>.*?)(?P=q)",
    re.IGNORECASE | re.DOTALL,
)


def category_page_url(base_url: str, *, page: int) -> str:
    if page <= 1:
        return base_url
    if "?" in base_url:
        return f"{base_url}&page={page}"
    return f"{base_url}?page={page}"


async def fetch_category_page_html(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 30.0,
) -> str:
    owned = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout_s, follow_redirects=True)
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text
    finally:
        if owned:
            await client.aclose()


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
    """Parse a CTgoodjobs category page into a stable list-summary payload."""

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

