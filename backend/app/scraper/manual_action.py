from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias

RESUME_STRATEGY_FRESH_PROFILE = "fresh_profile"
RESUME_STRATEGY_REUSE_OPEN_BROWSER = "reuse_open_browser"
ResumeStrategy: TypeAlias = Literal["fresh_profile", "reuse_open_browser"]
SUPPORTED_RESUME_STRATEGIES: tuple[ResumeStrategy, ...] = (
    RESUME_STRATEGY_FRESH_PROFILE,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
)

# Resume requests without a body keep the pre-Task 2 behavior.
LEGACY_RESUME_STRATEGY_DEFAULT: ResumeStrategy = RESUME_STRATEGY_FRESH_PROFILE

# Manual-action payloads tell the UI/attach flow which path to suggest first.
PREFERRED_MANUAL_ACTION_RESUME_STRATEGY: ResumeStrategy = RESUME_STRATEGY_REUSE_OPEN_BROWSER


@dataclass
class ManualActionRequiredError(RuntimeError):
    source_site: str
    stage: str
    blocked_url: str
    message: str
    referer: str | None = None
    action_type: str = "human_verification"
    resume_context: dict[str, Any] = field(default_factory=dict)
    instructions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def to_payload(
        self,
        *,
        crawl_mode: str,
        browser_channel: str | None,
        browser_profile_path: str | None,
        resume_supported: bool = True,
        reuse_open_browser_supported: bool = True,
        preferred_resume_strategy: ResumeStrategy = PREFERRED_MANUAL_ACTION_RESUME_STRATEGY,
    ) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "source_site": self.source_site,
            "stage": self.stage,
            "blocked_url": self.blocked_url,
            "referer": self.referer,
            "crawl_mode": crawl_mode,
            "browser_channel": browser_channel,
            "browser_profile_path": browser_profile_path,
            "resume_supported": resume_supported,
            "reuse_open_browser_supported": reuse_open_browser_supported,
            "preferred_resume_strategy": preferred_resume_strategy,
            "message": self.message,
            "instructions": list(self.instructions),
            "resume_context": dict(self.resume_context),
        }
