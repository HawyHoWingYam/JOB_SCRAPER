from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.source_catalog.domain import payload_fingerprint


@dataclass(frozen=True)
class CatalogImpactAssessment:
    allowed: bool
    versioned_automation_count: int
    summary: dict[str, Any]

    @property
    def digest(self) -> str:
        return payload_fingerprint(
            {
                "allowed": self.allowed,
                "versioned_automation_count": self.versioned_automation_count,
                "summary": self.summary,
            }
        )


class CatalogImpactEvaluator(Protocol):
    def evaluate(
        self,
        *,
        operation: str,
        source_site: str,
        candidate_fingerprint: str | None,
        target_revision_id: str | None,
        base_active_revision_id: str | None,
    ) -> CatalogImpactAssessment: ...
