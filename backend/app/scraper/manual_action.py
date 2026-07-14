from __future__ import annotations

import socket
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

RESUMABLE_SESSION_CLASSIFICATIONS = frozenset(
    {
        "auth_expired",
        "ip_blocked",
        "waf_challenge",
    }
)

_DEFAULT_BLOCKED_URLS = {
    "ctgoodjobs": "https://jobs.ctgoodjobs.hk/jobs",
    "jobsdb": "https://hk.jobsdb.com/jobs",
    "offertoday": "https://www.offertoday.com/hk/search",
}

_CLASSIFICATION_CODES: dict[str, int] = {
    "auth_expired": 1002,
    "ip_blocked": -1000035,
}

_CLASSIFICATION_MESSAGES = {
    "auth_expired": (
        "The OfferToday browser session expired. Sign in again in the verification "
        "browser, then resume this crawl."
    ),
    "ip_blocked": (
        "OfferToday blocked the current public IP. Change your IP or network, confirm "
        "OfferToday is reachable, then resume this crawl."
    ),
    "waf_challenge": (
        "OfferToday requires browser verification. Complete the challenge in the "
        "verification browser, then resume this crawl."
    ),
}

_CLASSIFICATION_INSTRUCTIONS = {
    "auth_expired": (
        "Sign in to OfferToday in the verification browser.",
        "Confirm the OfferToday search page loads, then resume the same crawl.",
    ),
    "ip_blocked": (
        "Change the public IP or switch to another allowed network.",
        "Confirm OfferToday is reachable, then resume the same crawl; completed progress is preserved.",
    ),
    "waf_challenge": (
        "Complete the OfferToday verification challenge in the browser.",
        "Return to the OfferToday search page, then resume the same crawl.",
    ),
}


def default_manual_action_blocked_url(source_site: str | None) -> str | None:
    normalized_source = str(source_site or "").strip().lower()
    return _DEFAULT_BLOCKED_URLS.get(normalized_source)


def resolve_manual_action_cdp_connect_host(configured_host: str | None) -> str:
    host = str(configured_host or "").strip() or "127.0.0.1"
    try:
        return socket.gethostbyname(host)
    except OSError:
        return host


def normalize_manual_action_payload(
    payload: dict[str, Any] | None,
    *,
    source_site: str,
    request_payload: dict[str, Any] | None = None,
    default_browser_channel: str | None = None,
    default_browser_profile_path: str | None = None,
) -> dict[str, Any]:
    """Project a complete manual-action contract, including legacy events."""

    normalized = dict(payload or {})
    normalized_source = str(
        normalized.get("source_site") or source_site or ""
    ).strip().lower()
    normalized["source_site"] = normalized_source

    resume_context = normalized.get("resume_context")
    if not isinstance(resume_context, dict) or not resume_context:
        resume_context = dict(request_payload or {})
    else:
        resume_context = dict(resume_context)
    normalized["resume_context"] = resume_context

    classification = str(
        normalized.get("classification")
        or resume_context.get("classification")
        or ""
    ).strip().lower()
    if classification:
        normalized["classification"] = classification

    action_type = str(normalized.get("action_type") or "").strip().lower()
    if not action_type:
        action_type = (
            "session_recovery"
            if classification in RESUMABLE_SESSION_CLASSIFICATIONS
            else "human_verification"
        )
        normalized["action_type"] = action_type

    resume_supported = normalized.get("resume_supported")
    if not isinstance(resume_supported, bool):
        resume_supported = (
            action_type in {"human_verification", "session_recovery"}
            and classification in RESUMABLE_SESSION_CLASSIFICATIONS
        )
    normalized["resume_supported"] = resume_supported

    if not normalized.get("stage"):
        normalized["stage"] = str(
            resume_context.get("crawl_phase") or "browser_session"
        ).strip()
    if not normalized.get("crawl_mode") and resume_context.get("crawl_mode"):
        normalized["crawl_mode"] = str(resume_context["crawl_mode"])
    if not normalized.get("blocked_url"):
        normalized["blocked_url"] = default_manual_action_blocked_url(
            normalized_source
        )

    if classification in _CLASSIFICATION_CODES and normalized.get("code") is None:
        normalized["code"] = _CLASSIFICATION_CODES[classification]
    if not normalized.get("message") and classification in _CLASSIFICATION_MESSAGES:
        normalized["message"] = _CLASSIFICATION_MESSAGES[classification]
    instructions = normalized.get("instructions")
    if not isinstance(instructions, list) or not instructions:
        normalized["instructions"] = list(
            _CLASSIFICATION_INSTRUCTIONS.get(classification, ())
        )

    if resume_supported:
        if not normalized.get("browser_channel") and default_browser_channel:
            normalized["browser_channel"] = default_browser_channel
        if (
            not normalized.get("browser_profile_path")
            and default_browser_profile_path
        ):
            normalized["browser_profile_path"] = default_browser_profile_path

    reuse_supported = normalized.get("reuse_open_browser_supported")
    if not isinstance(reuse_supported, bool):
        reuse_supported = bool(
            resume_supported
            and normalized.get("blocked_url")
            and normalized.get("browser_channel")
            and normalized.get("browser_profile_path")
        )
    if not resume_supported:
        reuse_supported = False
    normalized["reuse_open_browser_supported"] = reuse_supported

    preferred_strategy = normalized.get("preferred_resume_strategy")
    if preferred_strategy not in SUPPORTED_RESUME_STRATEGIES:
        preferred_strategy = (
            RESUME_STRATEGY_REUSE_OPEN_BROWSER
            if reuse_supported
            else RESUME_STRATEGY_FRESH_PROFILE
        )
    normalized["preferred_resume_strategy"] = preferred_strategy
    return normalized


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
