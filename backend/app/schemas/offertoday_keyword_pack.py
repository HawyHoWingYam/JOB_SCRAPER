from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.crawl_control.contracts import FrozenContract, SHA256_PATTERN


class OfferTodayKeywordCsvPreviewRequestV1(FrozenContract):
    csv_content: str = Field(max_length=2_000_000)


class OfferTodayKeywordCsvConfirmRequestV1(FrozenContract):
    confirmation_token: str = Field(min_length=20)
    csv_hash: str = Field(pattern=SHA256_PATTERN)


class OfferTodayKeywordEntryV1(FrozenContract):
    id: str
    classification_id: str
    classification_label: str
    keyword: str
    normalized_keyword: str
    enabled: bool
    notes: str
    updated_at: datetime
    last_new_job_ids: int | None = None
    last_duplicate_rate: float | None = None
    last_run_at: datetime | None = None


class OfferTodayKeywordPackListV1(FrozenContract):
    items: tuple[OfferTodayKeywordEntryV1, ...]
    enabled_counts: dict[str, int]
    catalog_fingerprint: str = Field(pattern=SHA256_PATTERN)
    catalog_updated_at: datetime | None = None


class OfferTodayKeywordCsvPreviewV1(FrozenContract):
    valid: bool
    csv_hash: str = Field(pattern=SHA256_PATTERN)
    errors: tuple[dict[str, Any], ...]
    warnings: tuple[dict[str, Any], ...]
    diff: tuple[dict[str, Any], ...]
    resulting_enabled_counts: dict[str, int]
    workload_impact: dict[str, Any]
    confirmation_token: str | None = None
    expires_at: datetime | None = None


class OfferTodayKeywordCsvConfirmV1(FrozenContract):
    added: int = Field(ge=0)
    updated: int = Field(ge=0)
    disabled: int = Field(ge=0)
    csv_hash: str = Field(pattern=SHA256_PATTERN)
    resulting_enabled_counts: dict[str, int]


__all__ = [
    "OfferTodayKeywordCsvConfirmRequestV1",
    "OfferTodayKeywordCsvConfirmV1",
    "OfferTodayKeywordCsvPreviewRequestV1",
    "OfferTodayKeywordCsvPreviewV1",
    "OfferTodayKeywordEntryV1",
    "OfferTodayKeywordPackListV1",
]
