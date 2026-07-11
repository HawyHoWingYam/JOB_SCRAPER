from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from app.sources.offertoday.listing_runner import OfferTodayListingCondition


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
