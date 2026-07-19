from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import re
from typing import Any
from uuid import UUID

from app.job_intelligence.foundation.hashing import canonical_json


_SKILL_CODE = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")


@dataclass(frozen=True)
class SkillExtractionContext:
    source: str = "ai-extraction"
    confidence: float | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("Skill extraction source is required")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("Skill extraction confidence must be between 0 and 1")


@dataclass(frozen=True)
class SkillMentionProjection:
    id: UUID
    raw_name: str
    normalized_key: str
    resolution: str
    skill_id: UUID | None = None
    skill_code: str | None = None
    skill_name: str | None = None
    candidate_id: UUID | None = None
    generic_tag: str | None = None
    rejection_reason: str | None = None


@dataclass(frozen=True)
class SkillExtractionResult:
    job_id: UUID
    taxonomy_revision_id: UUID
    mentions: tuple[SkillMentionProjection, ...]
    changed: bool


class SkillGovernanceReadError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class SkillCreateTarget:
    category_code: str
    technology_code: str
    stable_code: str
    name: str
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.category_code.strip() or not self.technology_code.strip():
            raise ValueError(
                "Skill create target requires Category and Technology codes"
            )
        if not _SKILL_CODE.fullmatch(self.stable_code):
            raise ValueError("Skill create target requires an explicit stable code")
        if not self.name.strip():
            raise ValueError("Skill create target name is required")
        if any(not alias.strip() for alias in self.aliases):
            raise ValueError("Skill create target aliases cannot be empty")

    def to_payload(self) -> dict[str, Any]:
        return {
            "category_code": self.category_code,
            "technology_code": self.technology_code,
            "stable_code": self.stable_code,
            "name": self.name,
            "aliases": list(self.aliases),
        }


def encode_skill_create_target(target: SkillCreateTarget) -> str:
    """Encode the complete create payload into DecisionCommand.target_id hashing."""

    return canonical_json(target.to_payload())


def decode_skill_create_target(value: str | None) -> SkillCreateTarget:
    if value is None:
        raise ValueError("create_skill requires a target payload")
    try:
        payload = json.loads(value)
        if not isinstance(payload, dict):
            raise TypeError
        aliases = payload.get("aliases") or []
        if not isinstance(aliases, list):
            raise TypeError
        return SkillCreateTarget(
            category_code=str(payload["category_code"]),
            technology_code=str(payload["technology_code"]),
            stable_code=str(payload["stable_code"]),
            name=str(payload["name"]),
            aliases=tuple(str(alias) for alias in aliases),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid create_skill target payload") from exc
