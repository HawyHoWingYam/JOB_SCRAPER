"""Skill normalization and governance for hierarchical taxonomy."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from difflib import SequenceMatcher
from sqlalchemy.orm import Session

from app.models import Skill, SkillCategory, SkillReviewCandidate, SkillTechnology


def _data_path(filename: str) -> Path:
    return Path(__file__).resolve().parents[1] / "data" / filename


class SkillNormalizer:
    def __init__(self, db: Session):
        self.db = db
        self._rules = self._load_rules()
        self._skill_cache: Dict[str, uuid.UUID] = {}
        self._normalized_skill_cache: Dict[str, uuid.UUID] = {}
        self._load_cache()

    def _load_rules(self) -> Dict[str, Any]:
        path = _data_path("skill_curation_rules.json")
        with path.open() as f:
            rules = json.load(f)

        generic_terms = rules.get("generic_terms", [])
        generic_terms_canonical_lookup = {}
        for term in generic_terms:
            canonical_label = self._normalize_unicode(str(term))
            lookup_key = self._normalize_lookup_key(canonical_label)
            if lookup_key:
                generic_terms_canonical_lookup[lookup_key] = canonical_label
        rules["generic_terms_lookup"] = set(generic_terms_canonical_lookup)
        rules["generic_terms_canonical_lookup"] = generic_terms_canonical_lookup

        alias_map = {}
        for raw_key, canonical_name in rules.get("canonical_aliases", {}).items():
            alias_map[self._normalize_lookup_key(raw_key)] = canonical_name
        rules["canonical_alias_lookup"] = alias_map

        technical_hints = rules.get("technical_hint_keywords", [])
        rules["technical_hint_keywords"] = [str(value).lower() for value in technical_hints]
        return rules

    def _load_cache(self):
        """Load all skills with aliases into memory cache."""
        self._skill_cache.clear()
        self._normalized_skill_cache.clear()

        skills = self.db.query(Skill).all()
        for skill in skills:
            self._cache_skill_name(skill.name, skill.id)
            if skill.aliases:
                for alias in skill.aliases:
                    self._cache_skill_name(alias, skill.id)

    def _cache_skill_name(self, value: str, skill_id: uuid.UUID) -> None:
        key = value.lower().strip()
        if key:
            self._skill_cache[key] = skill_id

        normalized_key = self._normalize_lookup_key(value)
        if normalized_key:
            self._normalized_skill_cache[normalized_key] = skill_id

    def _normalize_lookup_key(self, value: str) -> str:
        text = self._normalize_unicode(value).lower().strip()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def normalize_review_candidate_key(self, value: str) -> str:
        text = self._normalize_unicode(value).lower().strip()
        text = re.sub(r"[^a-z0-9+#./\-\s]+", " ", text)
        text = re.sub(r"\s*([+#./-])\s*", r"\1", text)
        return re.sub(r"\s+", " ", text).strip()

    def normalize_generic_tag_key(self, value: str) -> str:
        return self._normalize_lookup_key(value)

    def _normalize_unicode(self, value: str) -> str:
        text = str(value or "").strip()
        for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
            text = text.replace(dash, "-")
        return re.sub(r"\s+", " ", text)

    def _canonicalize_name(self, name: str) -> str:
        normalized = self._normalize_unicode(name)
        alias_lookup = self._rules.get("canonical_alias_lookup", {})
        alias_hit = alias_lookup.get(self._normalize_lookup_key(normalized))
        return alias_hit or normalized

    def canonicalize_generic_tag(self, value: str) -> Optional[str]:
        return self._rules.get("generic_terms_canonical_lookup", {}).get(
            self.normalize_generic_tag_key(value)
        )

    def _coerce_payload(self, extracted_skill: Any) -> Dict[str, Any]:
        if isinstance(extracted_skill, dict):
            name = (
                extracted_skill.get("normalized_name")
                or extracted_skill.get("name")
                or extracted_skill.get("skill")
                or extracted_skill.get("raw_name")
                or ""
            )
            payload = dict(extracted_skill)
            payload["name"] = str(name).strip()
            return payload

        if isinstance(extracted_skill, str):
            return {"name": extracted_skill.strip()}

        return {"name": ""}

    def _find_cached_skill(self, name: str) -> Optional[Skill]:
        raw_key = name.lower().strip()
        skill_id = self._skill_cache.get(raw_key)
        if skill_id is None:
            normalized_key = self._normalize_lookup_key(name)
            skill_id = self._normalized_skill_cache.get(normalized_key)
        if skill_id is None:
            return None
        return self.db.query(Skill).filter_by(id=skill_id).first()

    def resolve_extracted_skill(self, extracted_skill: Any) -> Dict[str, Any]:
        """
        Convert a raw extracted skill into one governed action.

        Actions:
        - match_existing
        - generic_tag
        - review_candidate
        - reject
        """
        payload = self._coerce_payload(extracted_skill)
        raw_name = payload.get("name", "")
        if not raw_name:
            return {"action": "reject", "reason": "empty_name"}

        canonical_name = self._canonicalize_name(raw_name)
        kind = str(payload.get("kind") or "").strip().lower()
        generic_label = self.canonicalize_generic_tag(canonical_name)
        if kind == "generic" or generic_label is not None:
            generic_tag = generic_label or canonical_name
            return {
                "action": "generic_tag",
                "generic_tag": generic_tag,
                "generic_tag_key": self.normalize_generic_tag_key(generic_tag),
            }

        existing_skill = self._find_cached_skill(canonical_name)
        if existing_skill is None and payload.get("existing_skill"):
            hinted_name = self._canonicalize_name(str(payload["existing_skill"]))
            existing_skill = self._find_cached_skill(hinted_name)

        if existing_skill is None:
            existing_skill = self._fuzzy_match(canonical_name)

        if existing_skill is not None:
            return {
                "action": "match_existing",
                "skill_id": existing_skill.id,
                "skill_name": existing_skill.name,
                "technology_id": existing_skill.technology_id,
                "category_id": existing_skill.technology.category_id,
            }

        if self._looks_technical(canonical_name, payload):
            return {
                "action": "review_candidate",
                "raw_name": raw_name,
                "normalized_name": canonical_name,
                "suggested_category": payload.get("category"),
                "suggested_technology": payload.get("technology"),
            }

        return {
            "action": "generic_tag",
            "generic_tag": canonical_name,
            "generic_tag_key": self.normalize_generic_tag_key(canonical_name),
        }

    def _is_generic_term(self, name: str) -> bool:
        return self._normalize_lookup_key(name) in self._rules.get("generic_terms_lookup", set())

    def _looks_technical(self, name: str, payload: Dict[str, Any]) -> bool:
        resolution = str(payload.get("resolution") or "").strip().lower()
        if resolution in {"match_existing", "create_new", "unresolved"}:
            return True

        kind = str(payload.get("kind") or "").strip().lower()
        if kind == "technical":
            return True

        lowered = name.lower()
        return any(
            keyword in lowered for keyword in self._rules.get("technical_hint_keywords", [])
        )

    def _fuzzy_match(self, name: str) -> Optional[Skill]:
        """Find a high-confidence fuzzy match among normalized names only."""
        normalized_name = self._normalize_lookup_key(name)
        if not normalized_name:
            return None

        best_ratio = 0.0
        best_id = None

        for cached_name, skill_id in self._normalized_skill_cache.items():
            ratio = SequenceMatcher(None, normalized_name, cached_name).ratio()
            if ratio > 0.93 and ratio > best_ratio:
                best_ratio = ratio
                best_id = skill_id

        if best_id is None:
            return None
        return self.db.query(Skill).filter_by(id=best_id).first()

    def register_review_candidate(
        self,
        *,
        raw_name: str,
        normalized_name: str,
        job_id: Optional[uuid.UUID] = None,
        suggested_category: Optional[str] = None,
        suggested_technology: Optional[str] = None,
    ) -> SkillReviewCandidate:
        normalized_lookup = self.normalize_review_candidate_key(normalized_name or raw_name)
        if not normalized_lookup:
            normalized_lookup = self._normalize_lookup_key(normalized_name or raw_name)
        candidate = (
            self.db.query(SkillReviewCandidate)
            .filter_by(normalized_name=normalized_lookup)
            .first()
        )
        if candidate is None:
            candidate = SkillReviewCandidate(
                raw_name=raw_name,
                normalized_name=normalized_lookup,
                suggested_category=suggested_category,
                suggested_technology=suggested_technology,
                first_seen_job_id=job_id,
                last_seen_job_id=job_id,
            )
            self.db.add(candidate)
            self.db.flush()
            return candidate

        candidate.raw_name = raw_name
        candidate.last_seen_job_id = job_id
        if suggested_category:
            candidate.suggested_category = suggested_category
        if suggested_technology:
            candidate.suggested_technology = suggested_technology
        self.db.flush()
        return candidate

    def normalize_skill(self, name: str) -> Tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
        """
        Legacy compatibility wrapper.

        This path is now governed and will only return an existing skill match.
        """
        decision = self.resolve_extracted_skill(name)
        if decision["action"] != "match_existing":
            raise ValueError(f"Skill '{name}' could not be normalized safely")
        return (
            decision["skill_id"],
            decision["technology_id"],
            decision["category_id"],
        )

    def _infer_hierarchy(self, name: str) -> Tuple[str, str]:
        """Infer category and technology from skill name."""
        name_lower = name.lower()

        if any(x in name_lower for x in ["react", "vue", "angular", "svelte", "next"]):
            return ("Frontend", "JavaScript")
        if any(x in name_lower for x in ["css", "sass", "tailwind", "bootstrap"]):
            return ("Frontend", "CSS")
        if "typescript" in name_lower:
            return ("Frontend", "TypeScript")

        if any(x in name_lower for x in ["django", "flask", "fastapi"]):
            return ("Backend", "Python")
        if any(x in name_lower for x in ["express", "nest"]):
            return ("Backend", "Node.js")
        if any(x in name_lower for x in ["spring", "hibernate"]):
            return ("Backend", "Java")

        if any(x in name_lower for x in ["postgres", "mysql", "sql"]):
            return ("Database", "SQL")
        if any(x in name_lower for x in ["mongo", "redis"]):
            return ("Database", "NoSQL")

        if any(x in name_lower for x in ["docker", "kubernetes", "k8s"]):
            return ("DevOps", "Containers")

        return ("Other", "General")

    def get_taxonomy_candidate_slice(self, name: str, limit: int = 10) -> dict:
        """Return a focused taxonomy slice to guide AI skill extraction decisions."""
        category_hint, technology_hint = self._infer_hierarchy(name)
        categories = self.db.query(SkillCategory).all()

        hinted_category = self.db.query(SkillCategory).filter_by(name=category_hint).first()
        if hinted_category:
            technologies = self.db.query(SkillTechnology).filter_by(
                category_id=hinted_category.id
            ).all()
        else:
            technologies = self.db.query(SkillTechnology).all()

        hinted_technology = None
        if hinted_category:
            hinted_technology = self.db.query(SkillTechnology).filter_by(
                category_id=hinted_category.id,
                name=technology_hint,
            ).first()

        if hinted_technology:
            skills = self.db.query(Skill).filter_by(
                technology_id=hinted_technology.id
            ).all()
        else:
            skills = self.db.query(Skill).all()

        return {
            "category_hint": category_hint,
            "technology_hint": technology_hint,
            "existing_categories": [category.name for category in categories[:limit]],
            "existing_technologies": [technology.name for technology in technologies[:limit]],
            "existing_skills": [skill.name for skill in skills[:limit]],
        }

    def get_skill_hierarchy(self, skill_id: uuid.UUID) -> dict:
        """Return full hierarchy path for a skill."""
        skill = self.db.query(Skill).filter_by(id=skill_id).first()
        if not skill:
            return {}

        return {
            "skill": skill.name,
            "technology": skill.technology.name,
            "category": skill.technology.category.name,
        }


_normalizer_instance = None


def get_skill_normalizer(db: Session) -> SkillNormalizer:
    """Get or create skill normalizer singleton."""
    global _normalizer_instance
    if _normalizer_instance is None:
        _normalizer_instance = SkillNormalizer(db)
    return _normalizer_instance
