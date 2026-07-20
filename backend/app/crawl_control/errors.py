from __future__ import annotations

from typing import Any

from app.crawl_control.contracts import CrawlScopeErrorPayloadV1, JsonScalar


class CrawlControlError(RuntimeError):
    """Stable versioned Crawl Control failure for APIs and run projections."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = dict(context or {})

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            **({"context": self.context} if self.context else {}),
        }

    def to_payload(self) -> CrawlScopeErrorPayloadV1:
        scalar_context: dict[str, JsonScalar] = {}
        for key, value in self.context.items():
            if value is None or isinstance(value, (str, int, float, bool)):
                scalar_context[str(key)] = value
            else:
                scalar_context[str(key)] = str(value)
        return CrawlScopeErrorPayloadV1(
            code=self.code,
            message=self.message,
            context=scalar_context,
        )


class ScopeRuleInvalidError(CrawlControlError):
    def __init__(
        self,
        message: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__("SCOPE_RULE_INVALID", message, context=context)


class ScopeReviewRequiredError(CrawlControlError):
    def __init__(
        self,
        message: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__("SCOPE_REVIEW_REQUIRED", message, context=context)


class WorkloadCapExceededError(CrawlControlError):
    def __init__(
        self,
        *,
        estimated_max_pages: int,
        run_page_cap: int,
        system_run_page_cap: int,
    ) -> None:
        super().__init__(
            "WORKLOAD_CAP_EXCEEDED",
            "Listing workload exceeds its reviewed aggregate cap",
            context={
                "estimated_max_pages": estimated_max_pages,
                "run_page_cap": run_page_cap,
                "system_run_page_cap": system_run_page_cap,
            },
        )


class AutomationNotFoundError(CrawlControlError):
    def __init__(self, automation_id: Any) -> None:
        super().__init__(
            "AUTOMATION_NOT_FOUND",
            "Automation was not found",
            context={"automation_id": str(automation_id)},
        )


class AutomationRevisionConflictError(CrawlControlError):
    def __init__(
        self,
        *,
        automation_id: Any,
        expected_revision: int,
        current_revision: int,
    ) -> None:
        super().__init__(
            "AUTOMATION_REVISION_CONFLICT",
            "Automation revision changed before this mutation",
            context={
                "automation_id": str(automation_id),
                "expected_revision": expected_revision,
                "current_revision": current_revision,
            },
        )


class AutomationTransitionInvalidError(CrawlControlError):
    def __init__(
        self,
        *,
        current_state: str,
        operation: str,
    ) -> None:
        super().__init__(
            "AUTOMATION_TRANSITION_INVALID",
            "Automation lifecycle transition is not allowed",
            context={
                "current_state": current_state,
                "operation": operation,
            },
        )


class AutomationDeleteReviewStaleError(CrawlControlError):
    def __init__(self, message: str) -> None:
        super().__init__("AUTOMATION_DELETE_REVIEW_STALE", message)
