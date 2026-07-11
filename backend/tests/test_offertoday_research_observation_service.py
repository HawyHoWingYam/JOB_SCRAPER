from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType, SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.services.offertoday_research_observation_service import (
    OfferTodayResearchObservationService,
)
from app.sources.offertoday.listing_runner import (
    ListingConditionOutcome,
    ListingPageObservation,
    ListingRowEvidence,
    OfferTodayIdentityPair,
    OfferTodayListingCondition,
)
from app.sources.offertoday.research.contracts import (
    ResearchMetadata,
    ResearchRunStartInventory,
)


RUN_ID = UUID("11111111-1111-1111-1111-111111111111")


class SummaryState(StrEnum):
    COMPLETE = "complete"


@dataclass(frozen=True)
class SummaryEvidence:
    evidence_id: UUID
    state: SummaryState


class FakeCrawlJobRepository:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.events: list[dict] = []

    def create_crawl_job(self, db, **kwargs):
        self.created.append({"db": db, **kwargs})
        return SimpleNamespace(id=kwargs["crawl_job_id"])

    def append_event(self, db, **kwargs):
        self.events.append({"db": db, **kwargs})
        return SimpleNamespace(sequence_no=len(self.events))


def research_metadata() -> ResearchMetadata:
    return ResearchMetadata(
        run_id=str(RUN_ID),
        experiment="foundation-fixture",
        variant="saved-responses",
        planner_version="test-sha",
    )


def run_start_inventory() -> ResearchRunStartInventory:
    return ResearchRunStartInventory(
        published_job_ids=("j-published-1", "j-published-2"),
        staged_unpublished_job_ids=("j-staged-1", "j-staged-2"),
        data_hash="inventory-hash",
    )


def listing_observation() -> ListingPageObservation:
    return ListingPageObservation(
        condition_id="condition-1",
        search_family="category",
        category_id=118000,
        keyword="data engineer",
        endpoint="search",
        rcd_type=7,
        page=2,
        attempt=3,
        request_fingerprint="request-sha",
        classification="success",
        api_code=0,
        reported_total=12,
        has_more=True,
        row_count=1,
        missing_job_id_count=0,
        missing_encrypted_job_id_count=0,
        id_pairs=(OfferTodayIdentityPair("j-1", "enc-1"),),
        rows=(
            ListingRowEvidence(
                job_id="j-1",
                encrypted_job_id="enc-1",
                title="Data Engineer",
                job_function_codes=("118000", "118005"),
                title_language="en",
                api_language="zh_HK",
            ),
        ),
        identity_issues=(),
        identity_conflicts=(),
        latency_ms=27,
        session_mode="saved-response",
        retry_reason=None,
        stop_reason=None,
    )


def condition_outcome(*, is_complete: bool) -> ListingConditionOutcome:
    return ListingConditionOutcome(
        condition=OfferTodayListingCondition(
            search_family="category",
            category_id=118000,
            keyword="data engineer",
            endpoint="search",
            rcd_type=7,
        ),
        pages_observed=2,
        stop_reason=("natural_exhaustion" if is_complete else "attempts_exhausted"),
        is_complete=is_complete,
    )


def test_research_metadata_request_payload_is_exact() -> None:
    assert research_metadata().to_request_payload() == {
        "research": {
            "run_id": str(RUN_ID),
            "experiment": "foundation-fixture",
            "variant": "saved-responses",
            "planner_version": "test-sha",
        }
    }


def test_plan2_metadata_adds_parent_and_exact_request_budget() -> None:
    metadata = ResearchMetadata(
        run_id="22222222-2222-2222-2222-222222222222",
        experiment="runtime-smoke",
        variant="search-rcdtype-7-fresh-headless",
        planner_version="def456",
        plan=2,
        parent_artifact_hash="a" * 64,
        request_budget={"listing": 1, "detail": 20},
    )

    assert metadata.to_request_payload()["research"] == {
        "run_id": metadata.run_id,
        "experiment": "runtime-smoke",
        "variant": "search-rcdtype-7-fresh-headless",
        "planner_version": "def456",
        "plan": 2,
        "parent_artifact_hash": "a" * 64,
        "request_budget": {"detail": 20, "listing": 1},
    }


@pytest.mark.parametrize("plan", [True, 0, -1, 1.5])
def test_research_metadata_rejects_invalid_plan(plan) -> None:
    with pytest.raises(ValueError, match="positive exact integer"):
        ResearchMetadata(
            run_id=str(RUN_ID),
            experiment="runtime-smoke",
            variant="fixture",
            planner_version="test-sha",
            plan=plan,
        )


@pytest.mark.parametrize("parent_hash", ["A" * 64, "a" * 63, "not-a-hash"])
def test_research_metadata_rejects_invalid_parent_artifact_hash(
    parent_hash: str,
) -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        ResearchMetadata(
            run_id=str(RUN_ID),
            experiment="runtime-smoke",
            variant="fixture",
            planner_version="test-sha",
            parent_artifact_hash=parent_hash,
        )


@pytest.mark.parametrize(
    "request_budget",
    [
        {"": 1},
        {"   ": 1},
        {1: 1},
        {"listing": True},
        {"listing": -1},
        {"listing": 1.5},
    ],
)
def test_research_metadata_rejects_invalid_request_budget(request_budget) -> None:
    with pytest.raises(ValueError, match="request budget"):
        ResearchMetadata(
            run_id=str(RUN_ID),
            experiment="runtime-smoke",
            variant="fixture",
            planner_version="test-sha",
            request_budget=request_budget,
        )


def test_run_start_inventory_converts_id_tuples_to_lists() -> None:
    assert run_start_inventory().to_dict() == {
        "published_job_ids": ["j-published-1", "j-published-2"],
        "staged_unpublished_job_ids": ["j-staged-1", "j-staged-2"],
        "data_hash": "inventory-hash",
    }


def test_create_run_uses_metadata_uuid_and_research_crawl_contract() -> None:
    db = object()
    repository = FakeCrawlJobRepository()
    service = OfferTodayResearchObservationService(
        db=db,
        crawl_job_repository=repository,
    )

    created_id = service.create_run(
        research_metadata(),
        run_start_inventory=run_start_inventory(),
    )

    assert created_id == RUN_ID
    assert service.crawl_job_id == RUN_ID
    assert repository.created == [
        {
            "db": db,
            "source_site": "offertoday",
            "trigger_type": "research",
            "request_payload": {
                "research": {
                    "run_id": str(RUN_ID),
                    "experiment": "foundation-fixture",
                    "variant": "saved-responses",
                    "planner_version": "test-sha",
                    "run_start_inventory": {
                        "published_job_ids": ["j-published-1", "j-published-2"],
                        "staged_unpublished_job_ids": ["j-staged-1", "j-staged-2"],
                        "data_hash": "inventory-hash",
                    },
                }
            },
            "status": "running",
            "crawl_job_id": RUN_ID,
        }
    ]


@pytest.mark.asyncio
async def test_observation_sink_writes_ordered_minimal_events() -> None:
    db = object()
    repository = FakeCrawlJobRepository()
    crawl_job_id = uuid4()
    service = OfferTodayResearchObservationService(
        db=db,
        crawl_job_repository=repository,
        crawl_job_id=crawl_job_id,
    )

    await service.record_page_attempt(listing_observation())
    await service.record_condition_outcome(condition_outcome(is_complete=True))
    await service.record_condition_outcome(condition_outcome(is_complete=False))
    service.record_run_summary(
        {"is_complete": False, "stop_reason": "condition_incomplete"}
    )

    assert [event["event_type"] for event in repository.events] == [
        "research.page_attempt",
        "research.condition_completed",
        "research.condition_incomplete",
        "research.run_summary",
    ]
    assert repository.events[0]["payload"] == {
        "condition_id": "condition-1",
        "search_family": "category",
        "category_id": 118000,
        "keyword": "data engineer",
        "endpoint": "search",
        "rcd_type": 7,
        "page": 2,
        "attempt": 3,
        "request_fingerprint": "request-sha",
        "classification": "success",
        "api_code": 0,
        "reported_total": 12,
        "has_more": True,
        "row_count": 1,
        "missing_job_id_count": 0,
        "missing_encrypted_job_id_count": 0,
        "id_pairs": [{"job_id": "j-1", "encrypted_job_id": "enc-1"}],
        "rows": [
            {
                "job_id": "j-1",
                "encrypted_job_id": "enc-1",
                "title": "Data Engineer",
                "job_function_codes": ["118000", "118005"],
                "title_language": "en",
                "api_language": "zh_HK",
            }
        ],
        "identity_issues": [],
        "identity_conflicts": [],
        "latency_ms": 27,
        "session_mode": "saved-response",
        "retry_reason": None,
        "stop_reason": None,
    }
    assert repository.events[1]["payload"] == {
        "condition": {
            "search_family": "category",
            "category_id": 118000,
            "keyword": "data engineer",
            "endpoint": "search",
            "rcd_type": 7,
        },
        "pages_observed": 2,
        "stop_reason": "natural_exhaustion",
        "is_complete": True,
    }
    assert repository.events[2]["payload"]["is_complete"] is False
    assert repository.events[3]["payload"] == {
        "is_complete": False,
        "stop_reason": "condition_incomplete",
    }
    assert all(event["db"] is db for event in repository.events)
    assert all(event["crawl_job_id"] == crawl_job_id for event in repository.events)
    assert all(event["emitted_by"] == "offertoday-research" for event in repository.events)
    assert all(event["auto_commit"] is True for event in repository.events)
    assert "headers" not in repository.events[0]["payload"]
    assert "cookie" not in repository.events[0]["payload"]


def test_recording_requires_a_crawl_job_id() -> None:
    service = OfferTodayResearchObservationService(
        db=object(),
        crawl_job_repository=FakeCrawlJobRepository(),
    )

    with pytest.raises(ValueError, match="crawl_job_id"):
        service.record_run_summary({"is_complete": False})


def test_run_summary_uses_shared_recursive_json_serializer() -> None:
    repository = FakeCrawlJobRepository()
    crawl_job_id = uuid4()
    nested_id = UUID("22222222-2222-2222-2222-222222222222")
    service = OfferTodayResearchObservationService(
        db=object(),
        crawl_job_repository=repository,
        crawl_job_id=crawl_job_id,
    )

    service.record_run_summary(
        {
            "run_id": RUN_ID,
            "state": SummaryState.COMPLETE,
            "evidence": SummaryEvidence(nested_id, SummaryState.COMPLETE),
            "items": [
                SummaryEvidence(RUN_ID, SummaryState.COMPLETE),
                MappingProxyType({"nested_id": nested_id}),
            ],
        }
    )

    event = repository.events[0]
    assert event["event_type"] == "research.run_summary"
    assert event["payload"] == {
        "run_id": str(RUN_ID),
        "state": "complete",
        "evidence": {"evidence_id": str(nested_id), "state": "complete"},
        "items": [
            {"evidence_id": str(RUN_ID), "state": "complete"},
            {"nested_id": str(nested_id)},
        ],
    }
    assert event["crawl_job_id"] == crawl_job_id
    assert event["emitted_by"] == "offertoday-research"
    assert event["auto_commit"] is True


def test_create_run_rejects_invalid_run_uuid() -> None:
    repository = FakeCrawlJobRepository()
    service = OfferTodayResearchObservationService(
        db=object(),
        crawl_job_repository=repository,
    )

    with pytest.raises(ValueError):
        service.create_run(
            ResearchMetadata(
                run_id="not-a-uuid",
                experiment="fixture",
                variant="invalid",
                planner_version="test-sha",
            ),
            run_start_inventory=run_start_inventory(),
        )

    assert repository.created == []
