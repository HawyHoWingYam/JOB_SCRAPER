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
