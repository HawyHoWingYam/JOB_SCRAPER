from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
            "message": self.message,
            "instructions": list(self.instructions),
            "resume_context": dict(self.resume_context),
        }
