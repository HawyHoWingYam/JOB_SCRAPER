from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _CurrentTaxonomySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CurrentTaxonomyNodeSchema(_CurrentTaxonomySchema):
    code: str
    parent_code: str | None
    level: str
    labels: dict[str, str]
    order: int
    is_assignable: bool


class CurrentTaxonomyTreeSchema(_CurrentTaxonomySchema):
    taxonomy: Literal["skill"]
    nodes: list[CurrentTaxonomyNodeSchema]


class CurrentJobSkillSchema(_CurrentTaxonomySchema):
    code: str
    name: str
    source: str
    confidence: float | None
    provenance: dict[str, Any]
    mention_count: int


class CurrentJobSkillStateSchema(_CurrentTaxonomySchema):
    job_id: UUID
    skills: list[CurrentJobSkillSchema]


__all__ = [
    "CurrentJobSkillSchema",
    "CurrentJobSkillStateSchema",
    "CurrentTaxonomyNodeSchema",
    "CurrentTaxonomyTreeSchema",
]
