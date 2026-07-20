from __future__ import annotations

from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.source_catalog.domain import (
    CatalogNodeSnapshot,
    SourceQueryTarget,
    is_source_qualified_classification_id,
    payload_fingerprint,
)


SHA256_PATTERN = r"^[0-9a-f]{64}$"
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


class CrawlScopeRuleV1(FrozenContract):
    kind: Literal["exact", "subtree"]
    classification_id: str = Field(min_length=3, max_length=255)

    @field_validator("classification_id")
    @classmethod
    def require_source_qualified_identity(cls, value: str) -> str:
        source_site, separator, _token = value.partition(":")
        if not separator or not is_source_qualified_classification_id(
            value, source_site
        ):
            raise ValueError(
                "Source Classification identity must be exactly <source>:<token>"
            )
        return value


class AuthoredCrawlScopeV1(FrozenContract):
    version: Literal[1] = 1
    source_site: SourceSite
    reviewed_catalog_revision_id: UUID
    mode: Literal["all", "rules"]
    rules: tuple[CrawlScopeRuleV1, ...] = Field(default_factory=tuple)

    @field_validator("rules")
    @classmethod
    def stable_deduplicate_rules(
        cls, value: tuple[CrawlScopeRuleV1, ...]
    ) -> tuple[CrawlScopeRuleV1, ...]:
        rules: list[CrawlScopeRuleV1] = []
        seen: set[tuple[str, str]] = set()
        for rule in value:
            identity = (rule.kind, rule.classification_id)
            if identity not in seen:
                rules.append(rule)
                seen.add(identity)
        return tuple(rules)

    @model_validator(mode="after")
    def validate_scope_shape(self) -> AuthoredCrawlScopeV1:
        if self.mode == "all" and self.rules:
            raise ValueError("All scope cannot contain Exact/Subtree rules")
        if self.mode == "rules" and not self.rules:
            raise ValueError("Rules scope requires at least one Exact/Subtree rule")
        for rule in self.rules:
            if not is_source_qualified_classification_id(
                rule.classification_id, self.source_site
            ):
                raise ValueError(
                    "Every Source Classification identity must belong to source_site"
                )
        return self


class SelectedClassificationSnapshotV1(FrozenContract):
    version: Literal[1] = 1
    node_key: str = Field(min_length=1, max_length=255)
    classification_id: str = Field(min_length=3, max_length=255)
    native_label: str = Field(min_length=1, max_length=500)
    native_path: tuple[str, ...] = Field(min_length=1)
    query_semantics_hash: str = Field(pattern=SHA256_PATTERN)

    @classmethod
    def from_catalog_node(
        cls, node: CatalogNodeSnapshot
    ) -> SelectedClassificationSnapshotV1:
        if node.classification_id is None or node.query_semantics_hash is None:
            raise ValueError("Selected Source Classification is not queryable")
        return cls(
            node_key=node.node_key,
            classification_id=node.classification_id,
            native_label=node.native_label,
            native_path=node.native_path,
            query_semantics_hash=node.query_semantics_hash,
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
    crawl_mode: Literal["headed"] = "headed"


class OfferTodayQueryTargetParametersV1(FrozenContract):
    category_code: int = Field(ge=1, strict=True)
    endpoint: Literal["browse"] = "browse"
    keyword: Literal[""] = ""
    rcd_type: Literal[7] = 7


QueryTargetParametersV1: TypeAlias = (
    JobsDBQueryTargetParametersV1
    | CTgoodjobsQueryTargetParametersV1
    | OfferTodayQueryTargetParametersV1
)


class QueryTargetSnapshotV1(FrozenContract):
    version: Literal[1] = 1
    adapter: str = Field(min_length=1, max_length=255)
    classification_id: str = Field(min_length=3, max_length=255)
    parameters: QueryTargetParametersV1
    query_target_fingerprint: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_fingerprint(self) -> QueryTargetSnapshotV1:
        expected_parameter_type = {
            "jobsdb.classification": JobsDBQueryTargetParametersV1,
            "ctgoodjobs.category": CTgoodjobsQueryTargetParametersV1,
            "offertoday.category": OfferTodayQueryTargetParametersV1,
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
                "version": self.version,
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
        if target.version != 1:
            raise ValueError(f"Unsupported Query Target version: {target.version}")
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
    version: Literal[1] = 1
    source_site: SourceSite
    catalog_revision_id: UUID
    catalog_revision_fingerprint: str = Field(pattern=SHA256_PATTERN)
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
    version: Literal[1] = 1
    crawl_mode: Literal["headless", "headed"]
    page_depth: int = Field(ge=1, le=1000)
    run_page_cap: int = Field(ge=1, le=1_000_000_000)


class ListingWorkloadPreviewV1(FrozenContract):
    version: Literal[1] = 1
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


class DetailSettingsV1(FrozenContract):
    version: Literal[1] = 1
    crawl_mode: Literal["headless", "headed"]
    backlog_scope: DetailBacklogScopeV1
    limit: DetailRunLimitV1


class CrawlScopePreviewV1(FrozenContract):
    version: Literal[1] = 1
    resolved_scope: ResolvedRunScopeV1
    listing_workload: ListingWorkloadPreviewV1 | None = None


class CrawlScopeErrorPayloadV1(FrozenContract):
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)
    context: dict[str, JsonScalar] = Field(default_factory=dict)


class CrawlScopeImpactV1(FrozenContract):
    version: Literal[1] = 1
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
