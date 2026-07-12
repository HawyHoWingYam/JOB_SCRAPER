from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from app.sources.offertoday.detail_identity import resolve_offertoday_detail_identity
from app.sources.offertoday.listing_runner import OfferTodayListingCondition
from app.sources.offertoday.parsers import build_offertoday_job_url


def _ordered_distinct(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


@dataclass(frozen=True, slots=True)
class OfferTodayStagingReconciliation:
    rows_seen: int
    rows_created: int
    published_source_job_ids: tuple[str, ...]
    preexisting_staged_source_job_ids: tuple[str, ...]
    created_source_job_ids: tuple[str, ...]
    deferred_identity_conflict_ids: tuple[str, ...]

    @property
    def distinct_newly_staged(self) -> int:
        return len(self.created_source_job_ids)

    @property
    def staging_amplification_ratio(self) -> float | None:
        if self.distinct_newly_staged == 0:
            return 0.0 if self.rows_created == 0 else None
        return self.rows_created / self.distinct_newly_staged

    @property
    def staging_amplification_within_limit(self) -> bool:
        ratio = self.staging_amplification_ratio
        return ratio is not None and ratio <= 1.01

    def to_payload(self) -> dict[str, Any]:
        return {
            "rows_seen": self.rows_seen,
            "rows_created": self.rows_created,
            "published_source_job_ids": list(self.published_source_job_ids),
            "preexisting_staged_source_job_ids": list(
                self.preexisting_staged_source_job_ids
            ),
            "created_source_job_ids": list(self.created_source_job_ids),
            "deferred_identity_conflict_ids": list(self.deferred_identity_conflict_ids),
            "distinct_newly_staged": self.distinct_newly_staged,
            "staging_amplification_ratio": self.staging_amplification_ratio,
            "staging_amplification_within_limit": (
                self.staging_amplification_within_limit
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
    normalized_listing["encrypted_job_id_source"] = identity.encrypted_job_id_source

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
        self.rows_created = 0
        self.skipped_existing = 0
        self.created_source_job_ids: list[str] = []
        self.preexisting_staged_source_job_ids: list[str] = []
        self.published_source_job_ids: list[str] = []
        self.deferred_identity_conflict_ids: list[str] = []

    @property
    def reconciliation(self) -> OfferTodayStagingReconciliation:
        return OfferTodayStagingReconciliation(
            rows_seen=self.rows_seen,
            rows_created=self.rows_created,
            published_source_job_ids=_ordered_distinct(self.published_source_job_ids),
            preexisting_staged_source_job_ids=_ordered_distinct(
                self.preexisting_staged_source_job_ids
            ),
            created_source_job_ids=_ordered_distinct(self.created_source_job_ids),
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
        self.rows_staged += int(result.rows_staged)
        self.rows_created += int(result.rows_created)
        self.skipped_existing += int(result.skipped_existing)
        self.created_source_job_ids.extend(result.created_source_job_ids)
        self.preexisting_staged_source_job_ids.extend(
            result.preexisting_staged_source_job_ids
        )
        self.published_source_job_ids.extend(result.published_source_job_ids)

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


def _freeze_evidence(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_evidence(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_evidence(item) for item in value)
    return deepcopy(value)


@dataclass(frozen=True, slots=True)
class ResearchNoopStagedPage:
    condition: OfferTodayListingCondition
    page: int
    rows: tuple[MappingProxyType, ...]


@dataclass(frozen=True, slots=True)
class ResearchDeferredIdentityConflict:
    job_ids: tuple[str, ...]
    encrypted_job_ids: tuple[str, ...]
    reason: str


class ResearchNoopListingStagingSink:
    def __init__(self) -> None:
        self.would_stage_rows = 0
        self.stage_calls = 0
        self._staged_pages: list[ResearchNoopStagedPage] = []
        self._deferred_conflicts: list[ResearchDeferredIdentityConflict] = []

    @property
    def staged_pages(self) -> tuple[ResearchNoopStagedPage, ...]:
        return tuple(self._staged_pages)

    @property
    def deferred_conflicts(self) -> tuple[ResearchDeferredIdentityConflict, ...]:
        return tuple(self._deferred_conflicts)

    async def stage_page(
        self,
        *,
        condition: OfferTodayListingCondition,
        page: int,
        rows: list[dict[str, Any]],
    ) -> None:
        if type(page) is not int or page < 1:
            raise ValueError("page must be a positive exact integer")
        frozen_rows = tuple(_freeze_evidence(row) for row in rows)
        self.stage_calls += 1
        self.would_stage_rows += len(frozen_rows)
        self._staged_pages.append(
            ResearchNoopStagedPage(
                condition=condition,
                page=page,
                rows=frozen_rows,
            )
        )

    async def defer_identity_conflict(
        self,
        *,
        job_ids: tuple[str, ...],
        encrypted_job_ids: tuple[str, ...],
        reason: str,
    ) -> None:
        self._deferred_conflicts.append(
            ResearchDeferredIdentityConflict(
                job_ids=tuple(job_ids),
                encrypted_job_ids=tuple(encrypted_job_ids),
                reason=str(reason),
            )
        )
