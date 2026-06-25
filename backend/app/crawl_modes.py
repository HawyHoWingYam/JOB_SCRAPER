from __future__ import annotations

from typing import Optional


SUPPORTED_CRAWL_MODES = {"headless", "headed"}
DEFAULT_CRAWL_MODE_BY_SOURCE = {
    "jobsdb": "headed",
    "ctgoodjobs": "headed",
    "offertoday": "headless",
}
SUPPORTED_CRAWL_MODES_BY_SOURCE = {
    "jobsdb": ("headless", "headed"),
    "ctgoodjobs": ("headed",),
    "offertoday": ("headless", "headed"),
}
LEGACY_CRAWL_MODE_UPGRADES = {
    ("ctgoodjobs", "headless"): "headed",
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


def get_supported_crawl_modes(source_site: Optional[str]) -> tuple[str, ...]:
    normalized_source = normalize_source_site(source_site)
    return SUPPORTED_CRAWL_MODES_BY_SOURCE.get(
        normalized_source,
        tuple(sorted(SUPPORTED_CRAWL_MODES)),
    )


def resolve_crawl_mode(source_site: Optional[str], crawl_mode: Optional[str] = None) -> str:
    normalized_source = normalize_source_site(source_site)
    normalized_mode = normalize_crawl_mode(crawl_mode)
    if normalized_mode is not None:
        legacy_upgrade = LEGACY_CRAWL_MODE_UPGRADES.get((normalized_source, normalized_mode))
        if legacy_upgrade is not None:
            return legacy_upgrade
        if normalized_mode not in get_supported_crawl_modes(normalized_source):
            return DEFAULT_CRAWL_MODE_BY_SOURCE.get(normalized_source, normalized_mode)
        return normalized_mode
    return DEFAULT_CRAWL_MODE_BY_SOURCE.get(normalized_source, "headless")
