from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.sources.contracts import CanonicalScrapedJob


@dataclass(frozen=True)
class CrawlProgressEvent:
    event_type: str
    crawl_job_id: str
    source_site: str
    payload: dict[str, Any]


__all__ = ["CanonicalScrapedJob", "CrawlProgressEvent"]

