from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Literal

from app.job_intelligence.current_taxonomies.normalization import (
    normalize_exact_skill_key,
    normalize_skill_text,
)


_RULES_PATH = Path(__file__).resolve().parents[2] / "data" / "skill_curation_rules.json"


@dataclass(frozen=True)
class SkillCurationDisposition:
    kind: Literal["generic", "reject"]
    generic_tag: str | None = None
    rejection_reason: str | None = None


@lru_cache(maxsize=1)
def load_skill_curation_rules() -> dict[str, Any]:
    with _RULES_PATH.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    return payload if isinstance(payload, dict) else {}


def resolve_skill_curation(value: object) -> SkillCurationDisposition | None:
    key = normalize_exact_skill_key(value)
    if not key:
        return None
    rules = load_skill_curation_rules()
    generic_tags = {
        normalize_exact_skill_key(term): normalize_skill_text(term)
        for term in rules.get("generic_terms") or []
        if normalize_exact_skill_key(term) and normalize_skill_text(term)
    }
    generic_tags.update(
        {
            normalize_exact_skill_key(alias): normalize_skill_text(canonical_tag)
            for alias, canonical_tag in (rules.get("generic_aliases") or {}).items()
            if normalize_exact_skill_key(alias) and normalize_skill_text(canonical_tag)
        }
    )
    if generic_tag := generic_tags.get(key):
        return SkillCurationDisposition(kind="generic", generic_tag=generic_tag)
    suppressed = {
        normalize_exact_skill_key(term)
        for term in rules.get("suppressed_review_terms") or []
        if normalize_exact_skill_key(term)
    }
    if key in suppressed:
        return SkillCurationDisposition(
            kind="reject",
            rejection_reason="suppressed_generic_term",
        )
    return None


__all__ = [
    "SkillCurationDisposition",
    "load_skill_curation_rules",
    "resolve_skill_curation",
]
