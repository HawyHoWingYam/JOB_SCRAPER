from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal


AccessBlockClassification = Literal["ip_blocked", "waf_challenge"]

_IP_BLOCK_MARKERS: tuple[tuple[str, str], ...] = (
    ("ip address has been blocked", "ip_address_blocked"),
    ("your ip has been blocked", "ip_blocked"),
    ("current ip has been blocked", "current_ip_blocked"),
    ("ip access is blocked", "ip_access_blocked"),
    ("access from this ip", "access_from_ip"),
    ("too many requests", "too_many_requests"),
    ("rate limit exceeded", "rate_limit_exceeded"),
    ("rate limit has been reached", "rate_limit_reached"),
    ("you have exceeded the rate limit", "rate_limit_exceeded"),
    ("abnormal access behavior", "abnormal_access_behavior"),
    ("unusual traffic from your computer network", "unusual_network_traffic"),
    ("access denied", "access_denied"),
    ("当前ip", "current_ip_zh"),
    ("ip存在异常", "abnormal_ip_zh"),
    ("访问过于频繁", "rate_limit_zh"),
    ("请求过于频繁", "too_many_requests_zh"),
)

_WAF_CHALLENGE_MARKERS: tuple[tuple[str, str], ...] = (
    ("just a moment", "cloudflare_just_a_moment"),
    ("cf-challenge", "cloudflare_challenge"),
    ("challenges.cloudflare.com", "cloudflare_host"),
    ("/cdn-cgi/challenge-platform", "cloudflare_platform"),
    ("challenge-platform", "challenge_platform"),
    ("__cf_chl_", "cloudflare_state"),
    ("verify you are human", "human_verification"),
    ("confirm you are human", "human_confirmation"),
    ("complete the security check", "security_check"),
)


@dataclass(frozen=True, slots=True)
class PublicAccessEvidence:
    classification: AccessBlockClassification
    status_code: int | None
    final_url: str | None
    reason: str

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "classification": self.classification,
            "reason": self.reason,
        }
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        if self.final_url:
            payload["final_url"] = self.final_url
        return payload


def classify_public_access_evidence(
    *,
    status_code: int | None = None,
    final_url: str | None = None,
    title: str | None = None,
    text: str | None = None,
    headers: Mapping[str, Any] | None = None,
) -> PublicAccessEvidence | None:
    """Classify only positive public-page IP or WAF evidence.

    Network exceptions, DNS failures, timeouts, parser failures, and auth state
    are deliberately absent from this boundary and therefore remain non-IP.
    Cloudflare's explicit ``cf-mitigated: challenge`` response header is strong
    WAF evidence and takes precedence over a generic 403 status.
    The returned reason is a compact marker identifier; response bodies are
    never retained.
    """

    normalized_status = (
        status_code
        if isinstance(status_code, int) and not isinstance(status_code, bool)
        else None
    )
    normalized_url = str(final_url or "").strip() or None
    normalized_headers = {
        str(key).strip().lower(): str(value).strip().lower()
        for key, value in (headers or {}).items()
        if str(key).strip()
    }
    if normalized_headers.get("cf-mitigated") == "challenge":
        return PublicAccessEvidence(
            classification="waf_challenge",
            status_code=normalized_status,
            final_url=normalized_url,
            reason="cloudflare_mitigated_challenge",
        )
    if normalized_status in {403, 429}:
        return PublicAccessEvidence(
            classification="ip_blocked",
            status_code=normalized_status,
            final_url=normalized_url,
            reason=f"http_status_{normalized_status}",
        )

    searchable = "\n".join(
        value.lower()
        for value in (
            str(title or ""),
            str(final_url or ""),
            str(text or ""),
        )
        if value
    )
    for marker, reason in _IP_BLOCK_MARKERS:
        if marker in searchable:
            return PublicAccessEvidence(
                classification="ip_blocked",
                status_code=normalized_status,
                final_url=normalized_url,
                reason=reason,
            )

    for marker, reason in _WAF_CHALLENGE_MARKERS:
        if marker in searchable:
            return PublicAccessEvidence(
                classification="waf_challenge",
                status_code=normalized_status,
                final_url=normalized_url,
                reason=reason,
            )
    return None
