from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ListingStageDecision:
    should_stage: bool
    is_new_job: bool
    skipped_existing: bool


def resolve_listing_stage_decision(*, already_in_db: bool, skip_existing: bool) -> ListingStageDecision:
    if already_in_db and skip_existing:
        return ListingStageDecision(
            should_stage=False,
            is_new_job=False,
            skipped_existing=True,
        )

    return ListingStageDecision(
        should_stage=True,
        is_new_job=not already_in_db,
        skipped_existing=False,
    )
