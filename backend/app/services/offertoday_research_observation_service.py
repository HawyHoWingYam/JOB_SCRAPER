from __future__ import annotations

from typing import Any
from uuid import UUID

from app.repositories.crawl_job_repository import CrawlJobRepository
from app.sources.offertoday.listing_runner import (
    ListingConditionOutcome,
    ListingPageObservation,
    listing_observation_to_payload,
)
from app.sources.offertoday.research.contracts import (
    ResearchMetadata,
    ResearchRunStartInventory,
)


class OfferTodayResearchObservationService:
    def __init__(
        self,
        db,
        *,
        crawl_job_repository: CrawlJobRepository | None = None,
        crawl_job_id=None,
    ) -> None:
        self.db = db
        self.crawl_job_repository = crawl_job_repository or CrawlJobRepository()
        self.crawl_job_id = crawl_job_id

    def create_run(
        self,
        metadata: ResearchMetadata,
        *,
        run_start_inventory: ResearchRunStartInventory,
    ) -> UUID:
        crawl_job_id = UUID(metadata.run_id)
        request_payload = metadata.to_request_payload()
        request_payload["research"]["run_start_inventory"] = (
            run_start_inventory.to_dict()
        )
        crawl_job = self.crawl_job_repository.create_crawl_job(
            self.db,
            source_site="offertoday",
            trigger_type="research",
            request_payload=request_payload,
            status="running",
            crawl_job_id=crawl_job_id,
        )
        self.crawl_job_id = crawl_job.id
        return crawl_job.id

    async def record_page_attempt(
        self,
        observation: ListingPageObservation,
    ) -> None:
        self._append(
            "research.page_attempt",
            listing_observation_to_payload(observation),
        )

    async def record_condition_outcome(
        self,
        outcome: ListingConditionOutcome,
    ) -> None:
        event_type = (
            "research.condition_completed"
            if outcome.is_complete
            else "research.condition_incomplete"
        )
        self._append(event_type, listing_observation_to_payload(outcome))

    def record_run_summary(self, payload: dict[str, Any]) -> None:
        self._append(
            "research.run_summary",
            listing_observation_to_payload(payload),
        )

    def _append(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.crawl_job_id is None:
            raise ValueError("crawl_job_id is required before recording research events")
        self.crawl_job_repository.append_event(
            self.db,
            crawl_job_id=self.crawl_job_id,
            event_type=event_type,
            payload=payload,
            emitted_by="offertoday-research",
            auto_commit=True,
        )
