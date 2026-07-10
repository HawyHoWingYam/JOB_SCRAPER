from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ResearchMetadata:
    run_id: str
    experiment: str
    variant: str
    planner_version: str

    def to_request_payload(self) -> dict[str, Any]:
        return {
            "research": {
                "run_id": self.run_id,
                "experiment": self.experiment,
                "variant": self.variant,
                "planner_version": self.planner_version,
            }
        }


@dataclass(frozen=True, slots=True)
class ResearchRunStartInventory:
    published_job_ids: tuple[str, ...]
    staged_unpublished_job_ids: tuple[str, ...]
    data_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "published_job_ids": list(self.published_job_ids),
            "staged_unpublished_job_ids": list(self.staged_unpublished_job_ids),
            "data_hash": self.data_hash,
        }
