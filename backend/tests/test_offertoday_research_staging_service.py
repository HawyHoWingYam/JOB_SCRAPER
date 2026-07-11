from __future__ import annotations

from types import MappingProxyType

import pytest

from app.services.offertoday_research_staging_service import (
    ResearchNoopListingStagingSink,
)
from app.sources.offertoday.listing_runner import OfferTodayListingCondition


def condition() -> OfferTodayListingCondition:
    return OfferTodayListingCondition(
        search_family="runtime_smoke",
        category_id=118000,
        keyword="",
        endpoint="search",
        rcd_type=7,
    )


@pytest.mark.asyncio
async def test_noop_sink_records_immutable_evidence_without_database_dependency() -> None:
    sink = ResearchNoopListingStagingSink()
    rows = [{"job_id": "j1", "nested": {"rank": 1}}]

    assert await sink.stage_page(condition=condition(), page=1, rows=rows) is None
    assert (
        await sink.defer_identity_conflict(
            job_ids=("j1",),
            encrypted_job_ids=("e1", "e2"),
            reason="one_job_id_to_multiple_encrypted_ids",
        )
        is None
    )
    rows[0]["job_id"] = "mutated"
    rows[0]["nested"]["rank"] = 99

    assert sink.would_stage_rows == 1
    assert sink.stage_calls == 1
    assert len(sink.staged_pages) == 1
    assert sink.staged_pages[0].condition == condition()
    assert sink.staged_pages[0].page == 1
    assert sink.staged_pages[0].rows == (
        MappingProxyType(
            {"job_id": "j1", "nested": MappingProxyType({"rank": 1})}
        ),
    )
    assert len(sink.deferred_conflicts) == 1
    assert sink.deferred_conflicts[0].job_ids == ("j1",)
    assert sink.deferred_conflicts[0].encrypted_job_ids == ("e1", "e2")
    assert (
        sink.deferred_conflicts[0].reason
        == "one_job_id_to_multiple_encrypted_ids"
    )
    assert not hasattr(sink, "db")
    assert not hasattr(sink, "repository")

    with pytest.raises(TypeError):
        sink.staged_pages[0].rows[0]["job_id"] = "cannot-mutate"


@pytest.mark.asyncio
async def test_noop_sink_counts_every_stage_call_including_empty_page() -> None:
    sink = ResearchNoopListingStagingSink()

    await sink.stage_page(condition=condition(), page=1, rows=[])
    await sink.stage_page(
        condition=condition(),
        page=2,
        rows=[{"job_id": "j1"}, {"job_id": "j2"}],
    )

    assert sink.stage_calls == 2
    assert sink.would_stage_rows == 2
