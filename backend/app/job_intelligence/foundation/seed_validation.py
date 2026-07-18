from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal


SeedSeverity = Literal["error", "warning"]


@dataclass(frozen=True)
class SeedIssue:
    """One stable, addressable problem in governed seed content."""

    json_path: str
    code: str
    message: str
    related_id: str | None = None
    severity: SeedSeverity = "error"

    def to_payload(self) -> dict[str, str | None]:
        return {
            "json_path": self.json_path,
            "code": self.code,
            "message": self.message,
            "related_id": self.related_id,
            "severity": self.severity,
        }


SeedRule = Callable[[Mapping[str, Any]], Iterable[SeedIssue]]


@dataclass(frozen=True)
class ValidationReport:
    """A complete deterministic report; validation never stops at one issue."""

    issues: tuple[SeedIssue, ...]

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_payload(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [issue.to_payload() for issue in self.issues],
        }


class SeedValidator:
    """Run domain-owned seed rules and normalize their combined report."""

    @staticmethod
    def validate(
        document: Mapping[str, Any],
        rules: Sequence[SeedRule],
    ) -> ValidationReport:
        issues = [issue for rule in rules for issue in rule(document)]
        return ValidationReport(
            issues=tuple(
                sorted(
                    issues,
                    key=lambda issue: (
                        issue.json_path,
                        issue.code,
                        issue.related_id or "",
                        issue.message,
                        issue.severity,
                    ),
                )
            )
        )
