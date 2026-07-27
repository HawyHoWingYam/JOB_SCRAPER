from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.job_intelligence.foundation.hashing import json_payload


@dataclass(frozen=True)
class Provenance:
    """Revision-free evidence describing how one current value was captured."""

    method: str
    evidence_refs: tuple[Mapping[str, Any], ...]
    captured_at: datetime
    source_site: str | None = None
    mapping_id: str | None = None
    model_provider: str | None = None
    model_name: str | None = None

    def __post_init__(self) -> None:
        if not self.method.strip():
            raise ValueError("Provenance method is required")
        if self.captured_at.tzinfo is None:
            raise ValueError("Provenance capture time must include a timezone")

    def to_payload(self) -> dict[str, Any]:
        return json_payload(
            {
                "method": self.method,
                "source_site": self.source_site,
                "mapping_id": self.mapping_id,
                "evidence_refs": self.evidence_refs,
                "model_provider": self.model_provider,
                "model_name": self.model_name,
                "captured_at": self.captured_at,
            }
        )


__all__ = ["Provenance"]
