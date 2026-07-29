from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID


TaxonomyKind = Literal["company_industry", "skill"]


@dataclass(frozen=True)
class CurrentTaxonomyNode:
    taxonomy: TaxonomyKind
    code: str
    parent_code: str | None
    level: str
    labels: dict[str, str]
    order: int
    is_assignable: bool
    is_active: bool = True

    def to_payload(self) -> dict[str, Any]:
        return {
            "taxonomy": self.taxonomy,
            "code": self.code,
            "parent_code": self.parent_code,
            "level": self.level,
            "labels": dict(self.labels),
            "order": self.order,
            "is_assignable": self.is_assignable,
            "is_active": self.is_active,
        }


@dataclass(frozen=True)
class CurrentTaxonomyAlias:
    taxonomy: TaxonomyKind
    node_code: str
    alias: str
    normalized_alias: str

    def to_payload(self) -> dict[str, str]:
        return {
            "taxonomy": self.taxonomy,
            "node_code": self.node_code,
            "alias": self.alias,
            "normalized_alias": self.normalized_alias,
        }


@dataclass(frozen=True)
class CurrentTaxonomySnapshot:
    taxonomy: TaxonomyKind
    nodes: tuple[CurrentTaxonomyNode, ...]
    aliases: tuple[CurrentTaxonomyAlias, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "taxonomy": self.taxonomy,
            "nodes": [node.to_payload() for node in self.nodes],
            "aliases": [alias.to_payload() for alias in self.aliases],
        }


@dataclass(frozen=True)
class CurrentCompanyIndustryInput:
    taxonomy_code: str
    method: str
    provenance: dict[str, object]
    evidence_hash: str
    breadcrumb: dict[str, object]
    is_primary: bool
    primary_basis: str | None
    captured_at: datetime


@dataclass(frozen=True)
class ReplaceCurrentCompanyIndustriesCommand:
    company_id: UUID
    assignments: tuple[CurrentCompanyIndustryInput, ...]


@dataclass(frozen=True)
class CurrentJobSkillInput:
    skill_code: str
    source: str
    confidence: float | None
    provenance: dict[str, object]
    mention_count: int
    updated_at: datetime


@dataclass(frozen=True)
class ReplaceCurrentJobSkillsCommand:
    job_id: UUID
    skills: tuple[CurrentJobSkillInput, ...]
