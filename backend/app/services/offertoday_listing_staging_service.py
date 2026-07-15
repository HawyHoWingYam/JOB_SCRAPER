from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.sources.offertoday.detail_identity import resolve_offertoday_detail_identity
from app.sources.offertoday.parsers import build_offertoday_job_url


def _ordered_distinct(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


@dataclass(frozen=True, slots=True)
class OfferTodayStagingReconciliation:
    rows_seen: int
    rows_created: int
    complete_existing_source_job_ids: tuple[str, ...]
    terminal_unavailable_source_job_ids: tuple[str, ...]
    new_source_job_ids: tuple[str, ...]
    repair_source_job_ids: tuple[str, ...]
    duplicate_source_job_ids: tuple[str, ...]
    deferred_identity_conflict_ids: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "rows_seen": self.rows_seen,
            "rows_created": self.rows_created,
            "complete_existing_source_job_ids": list(
                self.complete_existing_source_job_ids
            ),
            "terminal_unavailable_source_job_ids": list(
                self.terminal_unavailable_source_job_ids
            ),
            "new_source_job_ids": list(self.new_source_job_ids),
            "repair_source_job_ids": list(self.repair_source_job_ids),
            "duplicate_source_job_ids": list(self.duplicate_source_job_ids),
            "deferred_identity_conflict_ids": list(
                self.deferred_identity_conflict_ids
            ),
        }


def build_offertoday_listing_staging_payload(
    parsed_row: dict[str, Any],
    *,
    condition: Any,
    page: int,
    rank: int,
) -> dict[str, Any]:
    normalized_listing = dict(parsed_row or {})
    identity = resolve_offertoday_detail_identity(
        source_job_id=normalized_listing.get("job_id"),
        listing_payload=normalized_listing,
    )
    normalized_listing["job_id"] = identity.job_id
    normalized_listing["encrypted_job_id"] = identity.encrypted_job_id
    normalized_listing["encrypted_job_id_source"] = (
        identity.encrypted_job_id_source
    )
    raw_data = normalized_listing.get("raw_data")
    normalized_listing["raw_data"] = (
        dict(raw_data) if isinstance(raw_data, dict) else {}
    )

    category_id = getattr(condition, "category_id", None)
    search_family = str(getattr(condition, "search_family", "") or "").strip()
    keyword = str(getattr(condition, "keyword", "") or "")
    return {
        "source_job_id": identity.job_id,
        "source_url": build_offertoday_job_url(identity.encrypted_job_id),
        "source_classification_id": (
            str(category_id) if category_id is not None else None
        ),
        "source_classification_name": search_family or None,
        "listing_page": int(page),
        "listing_rank": int(rank),
        "listing_payload": normalized_listing,
        "search_family": search_family or None,
        "category_id": str(category_id) if category_id is not None else None,
        "category_name": search_family or None,
        "keyword": keyword or None,
        "page": int(page),
    }


class OfferTodayReconciledListingStagingSink:
    def __init__(
        self,
        *,
        crawl_runtime: Any,
        crawl_job_id: Any,
        skip_existing: bool = True,
    ) -> None:
        self.crawl_runtime = crawl_runtime
        self.crawl_job_id = crawl_job_id
        self.skip_existing = bool(skip_existing)
        self.rows_staged = 0
        self.rows_seen = 0
        self.raw_job_ids_collected = 0
        self.rows_created = 0
        self.skipped_existing = 0
        self.stage_calls = 0
        self.created_source_job_ids: list[str] = []
        self.complete_existing_source_job_ids: list[str] = []
        self.terminal_unavailable_source_job_ids: list[str] = []
        self.new_source_job_ids: list[str] = []
        self.repair_source_job_ids: list[str] = []
        self.duplicate_source_job_ids: list[str] = []
        self.deferred_identity_conflict_ids: list[str] = []

    @property
    def reconciliation(self) -> OfferTodayStagingReconciliation:
        return OfferTodayStagingReconciliation(
            rows_seen=self.rows_seen,
            rows_created=self.rows_created,
            complete_existing_source_job_ids=_ordered_distinct(
                self.complete_existing_source_job_ids
            ),
            terminal_unavailable_source_job_ids=_ordered_distinct(
                self.terminal_unavailable_source_job_ids
            ),
            new_source_job_ids=_ordered_distinct(self.new_source_job_ids),
            repair_source_job_ids=_ordered_distinct(self.repair_source_job_ids),
            duplicate_source_job_ids=_ordered_distinct(
                self.duplicate_source_job_ids
            ),
            deferred_identity_conflict_ids=_ordered_distinct(
                self.deferred_identity_conflict_ids
            ),
        )

    async def stage_page(
        self,
        *,
        condition: Any,
        page: int,
        rows: list[dict[str, Any]],
    ) -> None:
        self.stage_calls += 1
        payloads = [
            build_offertoday_listing_staging_payload(
                parsed_row,
                condition=condition,
                page=page,
                rank=index,
            )
            for index, parsed_row in enumerate(rows, start=1)
        ]
        result = self.crawl_runtime.stage_listing_batch(
            crawl_job_id=self.crawl_job_id,
            source_site="offertoday",
            payloads=payloads,
            skip_existing=self.skip_existing,
        )
        self.rows_seen += int(result.job_ids_seen)
        self.raw_job_ids_collected += int(
            getattr(result, "raw_job_ids_seen", 0) or 0
        )
        self.rows_staged += int(result.rows_staged)
        self.rows_created += int(result.rows_created)
        self.skipped_existing += int(result.skipped_existing)
        self.created_source_job_ids.extend(result.created_source_job_ids)
        self.complete_existing_source_job_ids.extend(
            getattr(result, "complete_existing_source_job_ids", ())
        )
        self.terminal_unavailable_source_job_ids.extend(
            getattr(result, "terminal_unavailable_source_job_ids", ())
        )
        self.new_source_job_ids.extend(
            getattr(result, "new_source_job_ids", result.created_source_job_ids)
        )
        self.repair_source_job_ids.extend(
            getattr(result, "repair_source_job_ids", ())
        )
        self.duplicate_source_job_ids.extend(
            getattr(result, "duplicate_source_job_ids", ())
        )

    async def defer_identity_conflict(
        self,
        *,
        job_ids: tuple[str, ...],
        encrypted_job_ids: tuple[str, ...],
        reason: str,
    ) -> None:
        self.deferred_identity_conflict_ids.extend(str(value) for value in job_ids)
        self.crawl_runtime.defer_listing_identity_conflict(
            crawl_job_id=self.crawl_job_id,
            source_job_ids=tuple(job_ids),
            encrypted_job_ids=tuple(encrypted_job_ids),
            reason=reason,
        )
