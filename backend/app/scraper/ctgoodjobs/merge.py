"""Merge CTgoodjobs list-level and detail-level records into one payload."""

from __future__ import annotations

from typing import Any


def _non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _choose(detail_job: dict[str, Any] | None, list_job: dict[str, Any] | None, key: str) -> Any:
    if isinstance(detail_job, dict):
        value = detail_job.get(key)
        if _non_empty(value):
            return value
    if isinstance(list_job, dict):
        value = list_job.get(key)
        if _non_empty(value):
            return value
    return None


def _namespaced_job_id(raw_job_id: str) -> str:
    raw = raw_job_id.strip()
    if raw.startswith("ctgoodjobs:"):
        return raw
    return f"ctgoodjobs:{raw}"


def _source_metadata_value(
    category: dict[str, Any] | None,
    detail_job: dict[str, Any] | None,
    list_job: dict[str, Any] | None,
    *,
    category_key: str,
    payload_key: str,
) -> Any:
    if isinstance(category, dict):
        value = category.get(category_key)
        if _non_empty(value):
            return value
    return _choose(detail_job, list_job, payload_key)


def merge_ctgoodjobs_job(
    *,
    category: dict[str, Any] | None,
    list_job: dict[str, Any] | None,
    detail_job: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge CTgoodjobs payloads.

    Rules:
    - Prefer detail fields when present, otherwise fall back to list.
    - Persisted job_id must be namespaced as ctgoodjobs:<raw>.
    - Always attach source metadata (source_site + source classification info).
    """

    raw_job_id = _choose(detail_job, list_job, "job_id")
    if not isinstance(raw_job_id, str) or not raw_job_id.strip():
        raise ValueError("CTgoodjobs merge requires job_id in either detail_job or list_job")

    source_classification_id = _source_metadata_value(
        category,
        detail_job,
        list_job,
        category_key="source_classification_id",
        payload_key="source_classification_id",
    )
    # Upstream category registries typically use `name`/`slug` keys.
    source_classification_name = _source_metadata_value(
        category,
        detail_job,
        list_job,
        category_key="name",
        payload_key="source_classification_name",
    )
    source_classification_slug = _source_metadata_value(
        category,
        detail_job,
        list_job,
        category_key="slug",
        payload_key="source_classification_slug",
    )

    merged: dict[str, Any] = {
        "source_site": "ctgoodjobs",
        "job_id": _namespaced_job_id(raw_job_id),
        "raw_source_job_id": raw_job_id.strip(),
        "url": _choose(detail_job, list_job, "url"),
        "title": _choose(detail_job, list_job, "title"),
        "company_id": _choose(detail_job, list_job, "company_id"),
        "company_name": _choose(detail_job, list_job, "company_name"),
        "company_url": _choose(detail_job, list_job, "company_url"),
        "posted_date": _choose(detail_job, list_job, "posted_date"),
        "expiry_date": _choose(detail_job, list_job, "expiry_date"),
        "employment_type": _choose(detail_job, list_job, "employment_type"),
        "salary_range": _choose(detail_job, list_job, "salary_range"),
        "experience_min_years": _choose(detail_job, list_job, "experience_min_years"),
        "experience_max_years": _choose(detail_job, list_job, "experience_max_years"),
        "description_html": _choose(detail_job, list_job, "description_html"),
        "description_text": _choose(detail_job, list_job, "description_text"),
        "location": _choose(detail_job, list_job, "location"),
        "source_classification_id": source_classification_id,
        "source_classification_name": source_classification_name,
        "source_classification_slug": source_classification_slug,
    }

    # Carry through raw payloads for debugging if present.
    raw_list = list_job.get("raw") if isinstance(list_job, dict) else None
    raw_detail = detail_job.get("raw") if isinstance(detail_job, dict) else None
    if raw_list is not None:
        merged["raw_list"] = raw_list
    if raw_detail is not None:
        merged["raw_detail"] = raw_detail

    return merged
