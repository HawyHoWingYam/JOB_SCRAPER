from __future__ import annotations

from typing import Optional


SUPPORTED_CRAWL_MODES = {"headless", "headed"}
DEFAULT_CRAWL_MODE_BY_SOURCE = {
    "jobsdb": "headed",
    "ctgoodjobs": "headless",
}


def normalize_source_site(source_site: Optional[str]) -> str:
    return (source_site or "").strip().lower() or "jobsdb"


def normalize_crawl_mode(crawl_mode: Optional[str]) -> Optional[str]:
    if crawl_mode is None:
        return None
    normalized = str(crawl_mode).strip().lower()
    if not normalized:
        return None
    if normalized not in SUPPORTED_CRAWL_MODES:
        raise ValueError(f"Unsupported crawl_mode: {crawl_mode}")
    return normalized


def resolve_crawl_mode(source_site: Optional[str], crawl_mode: Optional[str] = None) -> str:
    normalized_source = normalize_source_site(source_site)
    normalized_mode = normalize_crawl_mode(crawl_mode)
    if normalized_mode is not None:
        return normalized_mode
    return DEFAULT_CRAWL_MODE_BY_SOURCE.get(normalized_source, "headless")
