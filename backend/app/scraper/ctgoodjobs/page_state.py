from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any


_UNAVAILABLE_MARKERS: tuple[tuple[str, str], ...] = (
    ("job not found", "job_not_found"),
    ("this job is no longer available", "job_no_longer_available"),
    ("this job has expired", "job_expired"),
    ("position is no longer available", "position_no_longer_available"),
    ("職位已截止", "job_closed_zh"),
    ("職位已下架", "job_removed_zh"),
    ("找不到此職位", "job_not_found_zh"),
    ("職位不存在", "job_missing_zh"),
)

_UNAVAILABLE_STATE_TOKENS = (
    "job-not-found",
    "job_not_found",
    "job-expired",
    "job_expired",
    "job-removed",
    "job_removed",
    "job-unavailable",
    "job_unavailable",
)


class _TopLevelPageStateParser(HTMLParser):
    """Collect text only from elements explicitly labelled as page state."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capture_depth = 0
        self.fragments: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if self._capture_depth:
            self._capture_depth += 1
            return
        attributes = {name.lower(): str(value or "").lower() for name, value in attrs}
        state_values = " ".join(
            attributes.get(name, "")
            for name in ("data-page-state", "data-status", "id", "class")
        )
        is_explicit_state = any(token in state_values for token in _UNAVAILABLE_STATE_TOKENS)
        is_alert_state = attributes.get("role") == "alert" and tag in {
            "div",
            "main",
            "section",
        }
        if is_explicit_state or is_alert_state:
            self._capture_depth = 1

    def handle_endtag(self, _tag: str) -> None:
        if self._capture_depth:
            self._capture_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._capture_depth and data.strip():
            self.fragments.append(data.strip())


def _explicit_page_state_text(html: str | None) -> str:
    parser = _TopLevelPageStateParser()
    try:
        parser.feed(str(html or "")[:65_536])
    except (ValueError, AssertionError):
        return ""
    return " ".join(parser.fragments)


@dataclass(frozen=True, slots=True)
class CTGoodJobsTerminalUnavailableEvidence:
    reason: str
    status_code: int | None
    final_url: str

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "classification": "terminal_unavailable",
            "reason": self.reason,
            "final_url": self.final_url,
        }
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        return payload


class CTGoodJobsTerminalUnavailableError(RuntimeError):
    def __init__(self, *, reason: str, url: str, status_code: int | None) -> None:
        super().__init__(f"CTGoodJobs detail is unavailable ({reason}) url={url}")
        self.reason = reason
        self.url = url
        self.status_code = status_code

    @classmethod
    def from_evidence(
        cls,
        evidence: CTGoodJobsTerminalUnavailableEvidence,
    ) -> "CTGoodJobsTerminalUnavailableError":
        return cls(
            reason=evidence.reason,
            url=evidence.final_url,
            status_code=evidence.status_code,
        )


def classify_ctgoodjobs_detail_page(
    *,
    status_code: int | None,
    final_url: str | None,
    title: str | None,
    html: str | None,
) -> CTGoodJobsTerminalUnavailableEvidence | None:
    """Classify only explicit top-level CTGoodJobs unavailable evidence."""

    normalized_status = status_code if type(status_code) is int else None
    normalized_url = str(final_url or "").strip()
    if normalized_status in {404, 410}:
        return CTGoodJobsTerminalUnavailableEvidence(
            reason=f"http_status_{normalized_status}",
            status_code=normalized_status,
            final_url=normalized_url,
        )

    # Inspect only the document title and explicitly labelled page-state
    # containers. Arbitrary body or job-description text must not decide expiry.
    searchable = "\n".join(
        value.lower()
        for value in (
            str(title or ""),
            _explicit_page_state_text(html),
        )
        if value
    )
    for marker, reason in _UNAVAILABLE_MARKERS:
        if marker in searchable:
            return CTGoodJobsTerminalUnavailableEvidence(
                reason=reason,
                status_code=normalized_status,
                final_url=normalized_url,
            )
    return None
