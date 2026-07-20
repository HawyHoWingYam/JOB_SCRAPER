from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator
from uuid import UUID

from app.crawl_control.contracts import (
    QueryTargetSnapshotV1,
    SelectedClassificationSnapshotV1,
)
from app.crawl_control.dispatch_plan_contracts import ExecutionAuthorityV1
from app.crawl_control.errors import (
    DispatchPlanStaleError,
    ListingRunPageCapExceededError,
)
from app.crawl_control.scope_service import evaluate_listing_workload


@dataclass(frozen=True, slots=True)
class ListingRuntimeTarget:
    selected_classification: SelectedClassificationSnapshotV1
    query_target: QueryTargetSnapshotV1

    @property
    def classification_id(self) -> str:
        return self.query_target.classification_id


@dataclass(frozen=True, slots=True)
class ListingRuntimePlan:
    crawl_job_id: UUID
    dispatch_plan_id: UUID
    dispatch_plan_fingerprint: str
    source_site: str
    catalog_revision_id: UUID
    catalog_revision_fingerprint: str
    crawl_mode: str
    page_depth: int
    run_page_cap: int
    targets: tuple[ListingRuntimeTarget, ...]

    def __post_init__(self) -> None:
        if not self.targets:
            raise ValueError("Listing runtime requires at least one Query Target")
        if any(
            target.selected_classification.classification_id
            != target.query_target.classification_id
            for target in self.targets
        ):
            raise ValueError(
                "Listing runtime classification and Query Target identities differ"
            )
        target_fingerprints = {
            target.query_target.query_target_fingerprint
            for target in self.targets
        }
        if len(target_fingerprints) != len(self.targets):
            raise ValueError("Listing runtime Query Targets must be unique")
        if self.page_depth < 1 or self.run_page_cap < 1:
            raise ValueError("Listing runtime page limits must be positive")
        if self.estimated_max_pages > self.run_page_cap:
            raise ValueError(
                "Listing runtime estimate exceeds its reviewed aggregate cap"
            )

    @property
    def query_target_count(self) -> int:
        return len(self.targets)

    @property
    def estimated_max_pages(self) -> int:
        return self.query_target_count * self.page_depth

    def iter_target_pages(self) -> Iterator[tuple[ListingRuntimeTarget, int]]:
        for target in self.targets:
            for page in range(1, self.page_depth + 1):
                yield target, page

    def new_request_budget(self) -> ListingRequestBudget:
        return ListingRequestBudget(
            dispatch_plan_id=self.dispatch_plan_id,
            run_page_cap=self.run_page_cap,
        )

    def audit_payload(self) -> dict[str, object]:
        return {
            "dispatch_plan_id": str(self.dispatch_plan_id),
            "dispatch_plan_fingerprint": self.dispatch_plan_fingerprint,
            "catalog_revision_id": str(self.catalog_revision_id),
            "catalog_revision_fingerprint": self.catalog_revision_fingerprint,
            "query_target_count": self.query_target_count,
            "page_depth": self.page_depth,
            "estimated_max_pages": self.estimated_max_pages,
            "run_page_cap": self.run_page_cap,
            "request_payload_authoritative": False,
        }


@dataclass(slots=True)
class ListingRequestBudget:
    dispatch_plan_id: UUID
    run_page_cap: int
    requested_pages: int = 0

    def claim(self) -> int:
        next_count = self.requested_pages + 1
        if next_count > self.run_page_cap:
            raise ListingRunPageCapExceededError(
                plan_id=self.dispatch_plan_id,
                requested_pages=next_count,
                run_page_cap=self.run_page_cap,
            )
        self.requested_pages = next_count
        return self.requested_pages


def build_listing_runtime_plan(
    authority: ExecutionAuthorityV1,
    *,
    expected_source_site: str,
) -> ListingRuntimePlan:
    snapshot = authority.dispatch_plan
    content = snapshot.content
    expected_source = str(expected_source_site or "").strip().lower()
    if content.source_site != expected_source:
        raise DispatchPlanStaleError(
            "Dispatch Plan source does not match the selected worker",
            plan_id=snapshot.plan_id,
            reason="worker_source_mismatch",
        )
    if content.crawl_phase != "listing" or content.listing_settings is None:
        raise DispatchPlanStaleError(
            "Dispatch Plan is not a listing execution authority",
            plan_id=snapshot.plan_id,
            reason="runtime_authority_adapter_required",
        )

    evaluate_listing_workload(
        content.resolved_scope,
        content.listing_settings,
        enforce=True,
    )
    expected_adapter = {
        "jobsdb": "jobsdb.classification",
        "ctgoodjobs": "ctgoodjobs.category",
        "offertoday": "offertoday.category",
    }[content.source_site]
    if any(
        target.adapter != expected_adapter
        for target in content.resolved_scope.query_targets
    ):
        raise DispatchPlanStaleError(
            "Dispatch Plan Query Target adapter does not match its source",
            plan_id=snapshot.plan_id,
            reason="query_target_adapter_mismatch",
        )
    selected_by_id = {
        item.classification_id: item
        for item in content.resolved_scope.selected_classifications
    }
    targets = tuple(
        ListingRuntimeTarget(
            selected_classification=selected_by_id[target.classification_id],
            query_target=target,
        )
        for target in content.resolved_scope.query_targets
    )
    return ListingRuntimePlan(
        crawl_job_id=authority.crawl_job_id,
        dispatch_plan_id=snapshot.plan_id,
        dispatch_plan_fingerprint=snapshot.plan_fingerprint,
        source_site=content.source_site,
        catalog_revision_id=content.catalog_revision_id,
        catalog_revision_fingerprint=(
            content.resolved_scope.catalog_revision_fingerprint
        ),
        crawl_mode=content.listing_settings.crawl_mode,
        page_depth=content.listing_settings.page_depth,
        run_page_cap=content.listing_settings.run_page_cap,
        targets=targets,
    )
