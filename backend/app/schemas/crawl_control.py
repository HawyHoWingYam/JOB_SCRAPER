from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.crawl_control.automation_contracts import (
    AutomationConfigurationV1,
    AutomationLifecycleState,
    AutomationProjectionV1,
)
from app.crawl_control.contracts import (
    AuthoredCrawlScopeV1,
    FrozenContract,
    ListingSettingsV1,
    SHA256_PATTERN,
)
from app.crawl_control.dispatch_plan_contracts import DispatchPlanSnapshotV1
from app.crawl_control.task_control_board_contracts import (
    CrawlControlRunProjectionV1,
)


class CrawlScopePreviewRequestV1(FrozenContract):
    scope: AuthoredCrawlScopeV1
    listing_settings: ListingSettingsV1 | None = None


class AutomationCreateRequestV1(FrozenContract):
    configuration: AutomationConfigurationV1
    initial_state: Literal["active", "paused"] = "paused"


class AutomationUpdateRequestV1(FrozenContract):
    expected_revision: int = Field(ge=1)
    configuration: AutomationConfigurationV1


class AutomationRevisionRequestV1(FrozenContract):
    expected_revision: int = Field(ge=1)


class AutomationRestoreRequestV1(AutomationRevisionRequestV1):
    activate: bool = False


class AutomationPermanentDeleteRequestV1(AutomationRevisionRequestV1):
    review_token: str = Field(min_length=20)


class AutomationListResponseV1(FrozenContract):
    items: tuple[AutomationProjectionV1, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    source_site: str | None = None
    lifecycle_state: AutomationLifecycleState | None = None


class DispatchPlanDispatchRequestV1(FrozenContract):
    confirmation_token: str | None = Field(default=None, min_length=20)
    expected_plan_fingerprint: str = Field(
        pattern=SHA256_PATTERN,
    )


class DispatchPlanDispatchResponseV1(FrozenContract):
    plan: DispatchPlanSnapshotV1
    run: CrawlControlRunProjectionV1
