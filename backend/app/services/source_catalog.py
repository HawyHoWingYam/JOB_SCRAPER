from __future__ import annotations

from typing import Any

from app.crawl_modes import get_supported_crawl_modes, resolve_crawl_mode

SOURCE_LABELS = {
    "jobsdb": "JobsDB",
    "ctgoodjobs": "CTgoodjobs",
    "offertoday": "OfferToday",
}

SOURCE_CATEGORY_ID_TYPES = {
    "jobsdb": "integer",
    "ctgoodjobs": "string",
    "offertoday": "integer",
}

SOURCE_DEFAULT_MAX_PAGES = {
    "jobsdb": 3,
    "ctgoodjobs": 3,
    "offertoday": 50,
}


def list_supported_source_sites() -> tuple[str, ...]:
    return tuple(SOURCE_LABELS.keys())


def is_supported_source_site(source_site: str | None) -> bool:
    return str(source_site or "").strip().lower() in SOURCE_LABELS


def resolve_default_max_pages(source_site: str | None) -> int:
    normalized = str(source_site or "").strip().lower()
    return SOURCE_DEFAULT_MAX_PAGES.get(normalized, 3)


def build_source_catalog() -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for source_site in list_supported_source_sites():
        payload[source_site] = {
            "key": source_site,
            "label": SOURCE_LABELS[source_site],
            "category_id_type": SOURCE_CATEGORY_ID_TYPES[source_site],
            "supported_crawl_modes": list(get_supported_crawl_modes(source_site)),
            "default_crawl_mode": resolve_crawl_mode(source_site, None),
            "default_max_pages": resolve_default_max_pages(source_site),
        }
    return payload
