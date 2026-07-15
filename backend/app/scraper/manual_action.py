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
        "content_anomaly",
        "ip_blocked",
        "waf_challenge",
    }
)

_DEFAULT_BLOCKED_URLS = {
    "ctgoodjobs": "https://jobs.ctgoodjobs.hk/jobs",
    "jobsdb": "https://hk.jobsdb.com/jobs",
    "offertoday": "https://www.offertoday.com/hk/search",
}

_SOURCE_DISPLAY_NAMES = {
    "ctgoodjobs": "CTGoodJobs",
    "jobsdb": "JobsDB",
    "offertoday": "OfferToday",
}

_CLASSIFICATION_CODES: dict[tuple[str, str], int] = {
    ("offertoday", "auth_expired"): 1002,
    ("offertoday", "ip_blocked"): -1000035,
}


def manual_action_source_display_name(source_site: str | None) -> str:
    normalized_source = str(source_site or "").strip().lower()
    return _SOURCE_DISPLAY_NAMES.get(
        normalized_source,
        str(source_site or "the job source").strip() or "the job source",
    )


def default_manual_action_code(
    source_site: str | None,
    classification: str | None,
) -> int | None:
    key = (
        str(source_site or "").strip().lower(),
        str(classification or "").strip().lower(),
    )
    return _CLASSIFICATION_CODES.get(key)


def default_session_recovery_message(
    source_site: str | None,
    classification: str,
) -> str:
    source_name = manual_action_source_display_name(source_site)
    normalized_classification = str(classification or "").strip().lower()
    if normalized_classification == "ip_blocked":
        return (
            f"{source_name} blocked the current public IP or network. Change the "
            f"public IP/network, confirm {source_name} is reachable, then resume "
            "this same crawl. Completed progress is preserved."
        )
    if normalized_classification == "auth_expired":
        return (
            f"The {source_name} browser session expired. Sign in again in the "
            "verification browser, then resume this same crawl."
        )
    if normalized_classification == "waf_challenge":
        return (
            f"{source_name} requires browser verification. Complete the challenge "
            "in the verification browser, then resume this same crawl."
        )
    if normalized_classification == "content_anomaly":
        return (
            f"{source_name} returned the same invalid page structure for consecutive "
            "jobs. Inspect the verification browser, resolve any challenge or site "
            "change, then resume this same crawl."
        )
    return f"{source_name} requires operator action before this crawl can resume."


def default_session_recovery_instructions(
    source_site: str | None,
    classification: str,
) -> list[str]:
    source_name = manual_action_source_display_name(source_site)
    normalized_classification = str(classification or "").strip().lower()
    if normalized_classification == "ip_blocked":
        return [
            "Change the public IP or switch to another allowed network.",
            (
                f"Confirm {source_name} is reachable, then resume this same crawl; "
                "completed progress is preserved."
            ),
        ]
    if normalized_classification == "auth_expired":
        return [
            f"Sign in to {source_name} in the verification browser.",
            f"Confirm the {source_name} page loads, then resume this same crawl.",
        ]
    if normalized_classification == "waf_challenge":
        return [
            f"Complete the {source_name} verification challenge in the browser.",
            f"Return to {source_name}, then resume this same crawl.",
        ]
    if normalized_classification == "content_anomaly":
        return [
            f"Inspect the current {source_name} page for a verification prompt or site change.",
            "Resolve the page issue, then resume this same crawl; completed jobs are preserved.",
        ]
    return ["Resolve the reported issue, then resume this same crawl."]


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
        resume_context.setdefault("classification", classification)

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

    code = normalized.get("code")
    if code is None:
        code = resume_context.get("code")
    if code is None:
        code = resume_context.get("api_code")
    if code is None:
        code = default_manual_action_code(normalized_source, classification)
    if code is not None:
        normalized["code"] = code
        resume_context.setdefault("code", code)
    if not normalized.get("message") and classification:
        normalized["message"] = default_session_recovery_message(
            normalized_source,
            classification,
        )
    instructions = normalized.get("instructions")
    if isinstance(instructions, tuple):
        instructions = list(instructions)
    if not isinstance(instructions, list) or not instructions:
        normalized["instructions"] = (
            default_session_recovery_instructions(
                normalized_source,
                classification,
            )
            if classification
            else []
        )
    else:
        normalized["instructions"] = list(instructions)

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
    classification: str | None = None
    code: int | str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.classification is None:
            inferred_classification = str(
                self.resume_context.get("classification") or ""
            ).strip().lower()
            self.classification = inferred_classification or None
        if self.code is None:
            self.code = self.resume_context.get("code")
        if self.code is None:
            self.code = self.resume_context.get("api_code")
        if self.code is None:
            self.code = default_manual_action_code(
                self.source_site,
                self.classification,
            )
        if (
            self.action_type == "human_verification"
            and self.classification in RESUMABLE_SESSION_CLASSIFICATIONS
        ):
            self.action_type = "session_recovery"
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
        resume_context = dict(self.resume_context)
        if self.classification:
            resume_context.setdefault("classification", self.classification)
        if self.code is not None:
            resume_context.setdefault("code", self.code)
        payload: dict[str, Any] = {
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
            "resume_context": resume_context,
        }
        if self.classification:
            payload["classification"] = self.classification
        if self.code is not None:
            payload["code"] = self.code
        if self.evidence:
            payload["evidence"] = dict(self.evidence)
        return payload


def build_session_recovery_manual_action(
    *,
    source_site: str,
    stage: str,
    blocked_url: str,
    classification: str,
    referer: str | None = None,
    code: int | str | None = None,
    evidence: dict[str, Any] | None = None,
    resume_context: dict[str, Any] | None = None,
    message: str | None = None,
    instructions: list[str] | None = None,
) -> ManualActionRequiredError:
    normalized_classification = str(classification or "").strip().lower()
    if normalized_classification not in RESUMABLE_SESSION_CLASSIFICATIONS:
        raise ValueError(
            "session recovery classification must be auth_expired, "
            "content_anomaly, ip_blocked, or waf_challenge"
        )
    resolved_code = (
        code
        if code is not None
        else default_manual_action_code(source_site, normalized_classification)
    )
    resolved_context = dict(resume_context or {})
    resolved_context.setdefault("classification", normalized_classification)
    if resolved_code is not None:
        resolved_context.setdefault("code", resolved_code)
    return ManualActionRequiredError(
        source_site=str(source_site or "").strip().lower(),
        stage=stage,
        blocked_url=blocked_url,
        referer=referer,
        message=(
            message
            or default_session_recovery_message(
                source_site,
                normalized_classification,
            )
        ),
        action_type="session_recovery",
        resume_context=resolved_context,
        instructions=(
            list(instructions)
            if instructions
            else default_session_recovery_instructions(
                source_site,
                normalized_classification,
            )
        ),
        classification=normalized_classification,
        code=resolved_code,
        evidence=dict(evidence or {}),
    )
