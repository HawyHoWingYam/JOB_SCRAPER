from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.source_classifications.domain import (
    SourceQueryTarget,
    is_source_qualified_classification_id,
    payload_fingerprint,
)


SHA256_PATTERN = r"^[0-9a-f]{64}$"
LISTING_TECHNICAL_RUN_PAGE_CAP = 1_000_000_000
SourceSite: TypeAlias = Literal["jobsdb", "ctgoodjobs", "offertoday"]
JsonScalar: TypeAlias = str | int | float | bool | None
ScopeImpactReasonCode: TypeAlias = Literal[
    "SCOPE_BASELINE_INVALID",
    "SCOPE_REFERENCE_MISSING",
    "SCOPE_CAPABILITY_CHANGED",
    "SCOPE_QUERY_SEMANTICS_CHANGED",
    "SCOPE_ALIAS_DEDUPLICATION_CHANGED",
    "SCOPE_WORKLOAD_CAP_EXCEEDED",
    "SCOPE_RESOLUTION_FAILED",
]

class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthoredCrawlScopeV1(FrozenContract):
    source_site: SourceSite
    mode: Literal["all", "selected"]
    classification_ids: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("classification_ids")
    @classmethod
    def stable_deduplicate_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_scope_shape(self) -> AuthoredCrawlScopeV1:
        if self.mode == "all" and self.classification_ids:
            raise ValueError("All scope cannot contain selected classifications")
        if self.mode == "selected" and not self.classification_ids:
            raise ValueError("Selected scope requires at least one classification")
        for classification_id in self.classification_ids:
            if not is_source_qualified_classification_id(
                classification_id, self.source_site
            ):
                raise ValueError(
                    "Every Source Classification identity must belong to source_site"
                )
        return self


class SelectedClassificationSnapshotV1(FrozenContract):
    node_key: str = Field(min_length=1, max_length=255)
    classification_id: str = Field(min_length=3, max_length=255)
    native_label: str = Field(min_length=1, max_length=500)
    native_path: tuple[str, ...] = Field(min_length=1)
    query_semantics_hash: str = Field(pattern=SHA256_PATTERN)

    @classmethod
    def from_registry_row(cls, row) -> SelectedClassificationSnapshotV1:
        query_semantics_hash = payload_fingerprint(
            {
                "classification_id": row.classification_id,
                "native_id": row.native_id,
                "query_metadata": dict(row.query_metadata or {}),
            }
        )
        return cls(
            node_key=row.classification_id,
            classification_id=row.classification_id,
            native_label=row.label,
            native_path=(row.label,),
            query_semantics_hash=query_semantics_hash,
        )


class JobsDBQueryTargetParametersV1(FrozenContract):
    native_id: int = Field(ge=1, strict=True)


class CTgoodjobsQueryTargetParametersV1(FrozenContract):
    native_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        strict=True,
    )
    url_path: str = Field(
        max_length=2048,
        pattern=r"^/jobs/jobs-in-[a-z0-9]+(?:-[a-z0-9]+)*$",
        strict=True,
    )
    crawl_mode: Literal["headless", "headed"] = "headed"


class OfferTodayQueryTargetParametersV1(FrozenContract):
    category_code: int = Field(ge=1, strict=True)
    endpoint: Literal["browse"] = "browse"
    keyword: Literal[""] = ""
    rcd_type: Literal[7] = 7


class OfferTodayKeywordQueryTargetParametersV1(FrozenContract):
    category_code: int = Field(ge=1, strict=True)
    search_family: Literal["classification_keyword_sweep"]
    endpoint: Literal["search"]
    keyword: str = Field(
        min_length=1,
        max_length=1,
        pattern=r"^[A-Z0-9]$",
        strict=True,
    )
    rcd_type: None = None


QueryTargetParametersV1: TypeAlias = (
    JobsDBQueryTargetParametersV1
    | CTgoodjobsQueryTargetParametersV1
    | OfferTodayQueryTargetParametersV1
    | OfferTodayKeywordQueryTargetParametersV1
)


class QueryTargetSnapshotV1(FrozenContract):
    adapter: str = Field(min_length=1, max_length=255)
    classification_id: str = Field(min_length=3, max_length=255)
    parameters: QueryTargetParametersV1
    query_target_fingerprint: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_fingerprint(self) -> QueryTargetSnapshotV1:
        expected_parameter_type = {
            "jobsdb.classification": JobsDBQueryTargetParametersV1,
            "ctgoodjobs.category": CTgoodjobsQueryTargetParametersV1,
            "offertoday.category": (
                OfferTodayQueryTargetParametersV1,
                OfferTodayKeywordQueryTargetParametersV1,
            ),
        }.get(self.adapter)
        if expected_parameter_type is None or not isinstance(
            self.parameters, expected_parameter_type
        ):
            raise ValueError(
                "Query Target parameters do not match a public adapter contract"
            )
        parameters = self.parameters.model_dump(mode="json")
        expected = payload_fingerprint(
            {
                "adapter": self.adapter,
                "classification_id": self.classification_id,
                **parameters,
            }
        )
        if self.query_target_fingerprint != expected:
            raise ValueError("Query Target fingerprint does not match its payload")
        return self

    @classmethod
    def from_source_target(cls, target: SourceQueryTarget) -> QueryTargetSnapshotV1:
        return cls(
            adapter=target.adapter,
            classification_id=target.classification_id,
            parameters=dict(target.payload),
            query_target_fingerprint=target.fingerprint,
        )

    @property
    def parameter_payload(self) -> dict[str, JsonScalar]:
        return self.parameters.model_dump(mode="json")


class CrawlScopeWarningV1(FrozenContract):
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)
    context: dict[str, JsonScalar] = Field(default_factory=dict)


class ResolvedRunScopeV1(FrozenContract):
    source_site: SourceSite
    authored_scope: AuthoredCrawlScopeV1
    selected_classifications: tuple[SelectedClassificationSnapshotV1, ...]
    classification_expansion_hash: str = Field(pattern=SHA256_PATTERN)
    query_targets: tuple[QueryTargetSnapshotV1, ...]
    query_target_count: int = Field(ge=1)
    warnings: tuple[CrawlScopeWarningV1, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_snapshot_consistency(self) -> ResolvedRunScopeV1:
        if self.authored_scope.source_site != self.source_site:
            raise ValueError("Resolved and Authored Crawl Scope sources differ")
        if self.query_target_count != len(self.query_targets):
            raise ValueError("query_target_count does not match Query Targets")
        selected_ids = {
            item.classification_id for item in self.selected_classifications
        }
        target_ids = {item.classification_id for item in self.query_targets}
        if selected_ids != target_ids:
            raise ValueError(
                "Selected Source Classifications and Query Targets differ"
            )
        if any(
            not is_source_qualified_classification_id(item, self.source_site)
            for item in selected_ids
        ):
            raise ValueError("Resolved Source Classification belongs to another source")
        expected_expansion_hash = payload_fingerprint(
            [
                {
                    "node_key": item.node_key,
                    "classification_id": item.classification_id,
                    "query_semantics_hash": item.query_semantics_hash,
                }
                for item in self.selected_classifications
            ]
        )
        if self.classification_expansion_hash != expected_expansion_hash:
            raise ValueError(
                "Classification expansion hash does not match selected snapshots"
            )
        return self

    @property
    def fingerprint(self) -> str:
        return contract_fingerprint(self)


class ListingSettingsV1(FrozenContract):
    crawl_mode: Literal["headless", "headed"]
    page_depth: int = Field(ge=1)
    run_page_cap: int = Field(ge=1, le=LISTING_TECHNICAL_RUN_PAGE_CAP)


class ListingWorkloadPreviewV1(FrozenContract):
    query_target_count: int = Field(ge=1)
    page_depth: int = Field(ge=1)
    estimated_max_pages: int = Field(ge=1)
    run_page_cap: int = Field(ge=1)
    system_run_page_cap: int = Field(ge=1)
    within_operator_cap: bool
    within_system_cap: bool

    @model_validator(mode="after")
    def validate_workload_math(self) -> ListingWorkloadPreviewV1:
        if self.estimated_max_pages != self.query_target_count * self.page_depth:
            raise ValueError("Listing workload estimate is inconsistent")
        if self.within_operator_cap != (
            self.estimated_max_pages <= self.run_page_cap
        ):
            raise ValueError("Operator-cap result is inconsistent")
        if self.within_system_cap != (
            self.estimated_max_pages <= self.system_run_page_cap
        ):
            raise ValueError("System-cap result is inconsistent")
        return self

    @property
    def dispatchable(self) -> bool:
        return self.within_operator_cap and self.within_system_cap


class SourceBacklogScopeV1(FrozenContract):
    kind: Literal["source_backlog"] = "source_backlog"


class CrawlScopeBacklogScopeV1(FrozenContract):
    kind: Literal["crawl_scope"] = "crawl_scope"
    scope: AuthoredCrawlScopeV1


class ListingBatchBacklogScopeV1(FrozenContract):
    kind: Literal["listing_batch"] = "listing_batch"
    source_listing_crawl_job_id: UUID


DetailBacklogScopeV1: TypeAlias = Annotated[
    SourceBacklogScopeV1
    | CrawlScopeBacklogScopeV1
    | ListingBatchBacklogScopeV1,
    Field(discriminator="kind"),
]


class EntireSnapshotDetailLimitV1(FrozenContract):
    kind: Literal["entire_snapshot"] = "entire_snapshot"


class StopAfterDetailLimitV1(FrozenContract):
    kind: Literal["stop_after"] = "stop_after"
    detail_run_cap: int = Field(ge=1, le=1_000_000_000)


DetailRunLimitV1: TypeAlias = Annotated[
    EntireSnapshotDetailLimitV1 | StopAfterDetailLimitV1,
    Field(discriminator="kind"),
]


class DetailBacklogSnapshotV1(FrozenContract):
    """Finite eligible detail membership reviewed into one Dispatch Plan."""

    cutoff_at: datetime
    eligible_target_count: int = Field(ge=0)
    selected_target_count: int = Field(ge=0)
    selected_row_count: int = Field(ge=0)
    absolute_safety_cap: int = Field(ge=1)
    membership_fingerprint: str = Field(pattern=SHA256_PATTERN)

    @field_validator("cutoff_at")
    @classmethod
    def require_aware_cutoff(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Detail backlog snapshot cutoff must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_snapshot_counts(self) -> DetailBacklogSnapshotV1:
        if self.selected_target_count > self.eligible_target_count:
            raise ValueError(
                "Detail snapshot cannot select more targets than were eligible"
            )
        if self.selected_target_count > self.absolute_safety_cap:
            raise ValueError("Detail snapshot exceeds the absolute safety cap")
        if self.selected_row_count < self.selected_target_count:
            raise ValueError(
                "Detail snapshot row membership cannot be smaller than its targets"
            )
        return self


class DetailSettingsV1(FrozenContract):
    crawl_mode: Literal["headless", "headed"]
    backlog_scope: DetailBacklogScopeV1
    limit: DetailRunLimitV1
    backlog_snapshot: DetailBacklogSnapshotV1 | None = None

    @model_validator(mode="after")
    def validate_snapshot_limit(self) -> DetailSettingsV1:
        snapshot = self.backlog_snapshot
        if snapshot is None:
            return self
        if self.limit.kind == "entire_snapshot":
            if snapshot.selected_target_count != snapshot.eligible_target_count:
                raise ValueError(
                    "Entire-snapshot detail runs must freeze every eligible target"
                )
        elif snapshot.selected_target_count > self.limit.detail_run_cap:
            raise ValueError(
                "Detail snapshot exceeds the reviewed complete-run cap"
            )
        return self


class CrawlScopePreviewV1(FrozenContract):
    resolved_scope: ResolvedRunScopeV1
    listing_workload: ListingWorkloadPreviewV1 | None = None


class CrawlScopeErrorPayloadV1(FrozenContract):
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)
    context: dict[str, JsonScalar] = Field(default_factory=dict)


class CrawlScopeImpactV1(FrozenContract):
    status: Literal["compatible", "scope_review_required"]
    authored_scope: AuthoredCrawlScopeV1
    before: ResolvedRunScopeV1 | None
    after: ResolvedRunScopeV1 | None
    before_listing_workload: ListingWorkloadPreviewV1 | None = None
    after_listing_workload: ListingWorkloadPreviewV1 | None = None
    reason_codes: tuple[ScopeImpactReasonCode, ...] = Field(default_factory=tuple)
    blocking_errors: tuple[CrawlScopeErrorPayloadV1, ...] = Field(
        default_factory=tuple
    )

    @model_validator(mode="after")
    def validate_impact_shape(self) -> CrawlScopeImpactV1:
        if self.status == "compatible":
            if self.reason_codes or self.blocking_errors or self.after is None:
                raise ValueError(
                    "Compatible impact cannot contain blocking reasons or errors"
                )
        elif not self.reason_codes:
            raise ValueError("Scope review impact requires at least one reason")
        return self


def contract_fingerprint(contract: BaseModel) -> str:
    return payload_fingerprint(contract.model_dump(mode="json"))
