from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType, SimpleNamespace

import pytest
from app.services.offertoday_research_staging_service import (
    OfferTodayReconciledListingStagingSink,
    ResearchNoopListingStagingSink,
    build_offertoday_listing_staging_payload,
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


def test_production_staging_payload_preserves_canonical_identity_and_provenance() -> (
    None
):
    raw_data = {"jobId": "canonical-1", "encryptJobId": "encrypted-1"}

    payload = build_offertoday_listing_staging_payload(
        {
            "job_id": "canonical-1",
            "encrypted_job_id": "encrypted-1",
            "title": "Data Engineer",
            "raw_data": raw_data,
        },
        condition=SimpleNamespace(
            search_family="it_category",
            category_id=118001,
            keyword="python",
        ),
        page=3,
        rank=7,
    )

    assert payload == {
        "source_job_id": "canonical-1",
        "source_url": "https://www.offertoday.com/hk/job/encrypted-1",
        "source_classification_id": "118001",
        "source_classification_name": "it_category",
        "listing_page": 3,
        "listing_rank": 7,
        "listing_payload": {
            "job_id": "canonical-1",
            "encrypted_job_id": "encrypted-1",
            "encrypted_job_id_source": "encryptJobId",
            "title": "Data Engineer",
            "raw_data": raw_data,
        },
        "search_family": "it_category",
        "category_id": "118001",
        "category_name": "it_category",
        "keyword": "python",
        "page": 3,
    }


class FakeReconciledRuntime:
    def __init__(self) -> None:
        self.stage_calls: list[dict] = []
        self.defer_calls: list[dict] = []

    def stage_listing_batch(self, **kwargs):
        self.stage_calls.append(dict(kwargs))
        return SimpleNamespace(
            rows_staged=1,
            rows_created=1,
            skipped_existing=0,
            created_source_job_ids=("canonical-1",),
            preexisting_staged_source_job_ids=(),
            published_source_job_ids=(),
            job_ids_seen=1,
        )

    def defer_listing_identity_conflict(self, **kwargs):
        self.defer_calls.append(dict(kwargs))


@pytest.mark.asyncio
async def test_reconciled_sink_preserves_production_stage_and_conflict_calls() -> None:
    runtime = FakeReconciledRuntime()
    sink = OfferTodayReconciledListingStagingSink(
        crawl_runtime=runtime,
        crawl_job_id="crawl-1",
        skip_existing=False,
    )

    await sink.stage_page(
        condition=condition(),
        page=1,
        rows=[
            {
                "job_id": "canonical-1",
                "encrypted_job_id": "encrypted-1",
                "raw_data": {
                    "jobId": "canonical-1",
                    "encryptJobId": "encrypted-1",
                },
            }
        ],
    )
    await sink.defer_identity_conflict(
        job_ids=("canonical-1",),
        encrypted_job_ids=("encrypted-1",),
        reason="id_mismatch",
    )

    assert runtime.stage_calls[0]["crawl_job_id"] == "crawl-1"
    assert runtime.stage_calls[0]["source_site"] == "offertoday"
    assert runtime.stage_calls[0]["skip_existing"] is False
    assert runtime.stage_calls[0]["payloads"][0]["source_job_id"] == "canonical-1"
    assert sink.rows_created == sink.rows_staged == 1
    assert sink.created_source_job_ids == ["canonical-1"]
    assert runtime.defer_calls == [
        {
            "crawl_job_id": "crawl-1",
            "source_job_ids": ("canonical-1",),
            "encrypted_job_ids": ("encrypted-1",),
            "reason": "id_mismatch",
        }
    ]


class GlobalReconciliationRuntime:
    def __init__(self) -> None:
        self.staged_ids: set[str] = set()
        self.calls: list[dict] = []

    def stage_listing_batch(self, **kwargs):
        self.calls.append(dict(kwargs))
        observed_ids = tuple(
            dict.fromkeys(payload["source_job_id"] for payload in kwargs["payloads"])
        )
        preexisting = tuple(
            source_job_id
            for source_job_id in observed_ids
            if source_job_id in self.staged_ids
        )
        created = tuple(
            source_job_id
            for source_job_id in observed_ids
            if source_job_id not in self.staged_ids
        )
        self.staged_ids.update(created)
        return SimpleNamespace(
            rows_staged=len(created),
            rows_created=len(created),
            skipped_existing=len(preexisting),
            created_source_job_ids=created,
            preexisting_staged_source_job_ids=preexisting,
            published_source_job_ids=(),
            job_ids_seen=len(observed_ids),
        )

    def defer_listing_identity_conflict(self, **_kwargs):
        return None


def listing_row(job_id: str) -> dict:
    return {
        "job_id": job_id,
        "encrypted_job_id": job_id,
        "encrypted_job_id_source": "jobId_fallback",
        "raw_data": {"jobId": job_id},
    }


@pytest.mark.asyncio
async def test_reconciled_sink_is_globally_at_most_once_across_conditions_and_runs() -> (
    None
):
    runtime = GlobalReconciliationRuntime()
    first_run = OfferTodayReconciledListingStagingSink(
        crawl_runtime=runtime,
        crawl_job_id="run-1",
    )
    await first_run.stage_page(
        condition=condition(),
        page=1,
        rows=[listing_row("shared")],
    )
    await first_run.stage_page(
        condition=replace(condition(), category_id=112000),
        page=1,
        rows=[listing_row("shared")],
    )
    second_run = OfferTodayReconciledListingStagingSink(
        crawl_runtime=runtime,
        crawl_job_id="run-2",
    )
    await second_run.stage_page(
        condition=condition(),
        page=1,
        rows=[listing_row("shared")],
    )

    assert all(call["skip_existing"] is True for call in runtime.calls)
    assert first_run.reconciliation.to_payload() == {
        "rows_seen": 2,
        "rows_created": 1,
        "published_source_job_ids": [],
        "preexisting_staged_source_job_ids": ["shared"],
        "created_source_job_ids": ["shared"],
        "deferred_identity_conflict_ids": [],
        "distinct_newly_staged": 1,
        "staging_amplification_ratio": 1.0,
        "staging_amplification_within_limit": True,
    }
    assert second_run.reconciliation.to_payload() == {
        "rows_seen": 1,
        "rows_created": 0,
        "published_source_job_ids": [],
        "preexisting_staged_source_job_ids": ["shared"],
        "created_source_job_ids": [],
        "deferred_identity_conflict_ids": [],
        "distinct_newly_staged": 0,
        "staging_amplification_ratio": 0.0,
        "staging_amplification_within_limit": True,
    }


@pytest.mark.asyncio
async def test_reconciled_sink_rejects_created_row_amplification() -> None:
    runtime = FakeReconciledRuntime()
    sink = OfferTodayReconciledListingStagingSink(
        crawl_runtime=runtime,
        crawl_job_id="run-1",
    )
    runtime.stage_listing_batch = lambda **_kwargs: SimpleNamespace(
        rows_staged=2,
        rows_created=2,
        skipped_existing=0,
        created_source_job_ids=("canonical-1",),
        preexisting_staged_source_job_ids=(),
        published_source_job_ids=(),
        job_ids_seen=1,
    )

    await sink.stage_page(
        condition=condition(),
        page=1,
        rows=[listing_row("canonical-1")],
    )

    assert sink.reconciliation.staging_amplification_ratio == 2.0
    assert sink.reconciliation.staging_amplification_within_limit is False


@pytest.mark.asyncio
async def test_noop_sink_records_immutable_evidence_without_database_dependency() -> (
    None
):
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
        MappingProxyType({"job_id": "j1", "nested": MappingProxyType({"rank": 1})}),
    )
    assert len(sink.deferred_conflicts) == 1
    assert sink.deferred_conflicts[0].job_ids == ("j1",)
    assert sink.deferred_conflicts[0].encrypted_job_ids == ("e1", "e2")
    assert sink.deferred_conflicts[0].reason == "one_job_id_to_multiple_encrypted_ids"
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
