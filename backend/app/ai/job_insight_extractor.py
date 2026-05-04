"""
Job Insight Extractor

Unified extractor that requests a single JSON payload from the LLM containing:
- source-bounded taxonomy classification guidance
- skill taxonomy candidate guidance
- a concise summary
- explicit experience extraction fields
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.ai.llm_client import LLMUpstreamError, get_llm_client

logger = logging.getLogger(__name__)


INSIGHT_PROMPT = """You are a careful job-posting analyst.

You MUST return JSON only, matching the schema at the end of this prompt.

**1) Source-Bounded Taxonomy Guidance**
Source classification (strong prior):
- L1 source category: __SOURCE_CLASSIFICATION_NAME__
- Source subcategory: __SOURCE_SUBCLASSIFICATION_NAME__

Allowed taxonomy boundary:
__TAXONOMY_CONTEXT__

Rules:
- `classification.source_path_decision` MUST be the safest valid L1/L2/L3 path inside the allowed boundary.
- Prefer existing taxonomy nodes. Use `create_new` only when the candidate slice clearly does not fit.
- Use the provided default path when ambiguous.
- Keep `classification.reasoning` brief and concrete.

**2) Skill Taxonomy Candidate Guidance**
Use this candidate slice to prefer matching existing skills and naming consistently.
Existing categories:
__EXISTING_CATEGORIES__

Existing technologies:
__EXISTING_TECHNOLOGIES__

Existing skills:
__EXISTING_SKILLS__

Review-only technical terms from this context:
__REVIEW_ONLY_TERMS__

Suppressed broad technical terms from this context:
__SUPPRESSED_REVIEW_TERMS__

Rules:
- Extract only technical / hard skills (languages, frameworks, tools, platforms).
- Exclude soft skills.
- Normalize common abbreviations (e.g., JS -> JavaScript, K8s -> Kubernetes).
- Prefer `match_existing` only for concrete tools, platforms, frameworks, and technologies.
- If a term appears in the review-only list, mark it as `kind=technical` and `resolution=unresolved`.
- If a term appears in the suppressed list, do not emit it as a skill unless the posting clearly names a concrete product/tool instead.
- Do not force broad infrastructure, architecture, platform, or discipline terms into an existing skill.
- Use `kind=generic` with `resolution=drop` only for non-technical process/collaboration terms.

**3) Summary Instructions**
Write a concise 2-3 sentence summary. Focus on responsibilities, impact, and the core requirements.
Do not mention the taxonomy or that you are an AI.

**4) Experience Extraction Rules (explicit fields required)**
Extract experience into:
- `experience_level`: one of
  - not_specified
  - internship
  - entry_level
  - junior_level
  - mid_level
  - senior_level
  - lead_level
  - manager_level
  - director_level
  - executive_level

And numeric bounds:
- `experience_min_years`: integer years or null
- `experience_max_years`: integer years or null

Rules:
- If the posting does not specify experience (or it's unclear), set:
  - experience_level = not_specified
  - experience_min_years = null
  - experience_max_years = null
  - experience.summary = null
  - experience.evidence = []
- If you see "X-Y years", set min=X, max=Y.
- If you see "X+ years", set min=X, max=null.
- Never output negative years.
- Output integers only (no strings).
- `summary` should be a short user-facing sentence.
- `evidence` should contain 0-3 short supporting snippets from the posting.

Job Title: __TITLE__
Job Description (first 2000 chars):
__DESCRIPTION__

Respond with JSON only (no markdown, no extra keys):
{{
  "classification": {{
    "confidence": 0.0,
    "reasoning": "",
    "source_path_decision": {{
      "domain": "",
      "category": "",
      "subcategory": "",
      "resolution": "match_existing|fallback_default_path|create_new"
    }},
    "final_taxonomy_decision": {{
      "domain": "",
      "category": "",
      "subcategory": "",
      "resolution": "match_existing|fallback_default_path|create_new"
    }},
    "taxonomy_decision": {{
      "domain": "",
      "category": "",
      "subcategory": "",
      "resolution": "match_existing|fallback_default_path|create_new"
    }},
    "compatibility_category": "",
    "cross_domain": false,
    "cross_domain_confidence": 1.0,
    "cross_domain_reason": ""
  }},
  "summary": "",
  "skills": [
    {
      "name": "",
      "kind": "technical|generic|reject",
      "resolution": "match_existing|create_new|unresolved|drop",
      "category": "",
      "technology": "",
      "existing_skill": "",
      "evidence": ""
    }
  ],
  "experience": {{
    "experience_level": "not_specified",
    "experience_min_years": null,
    "experience_max_years": null,
    "summary": null,
    "evidence": []
  }},
  "confidence": 0.0
}}
""".replace("{{", "{").replace("}}", "}")


class JobInsightExtractor:
    """Unified extractor that returns classification, skills, summary, and experience."""

    _ALLOWED_EXPERIENCE_LEVELS = {
        "not_specified",
        "internship",
        "entry_level",
        "junior_level",
        "mid_level",
        "senior_level",
        "lead_level",
        "manager_level",
        "director_level",
        "executive_level",
    }

    def __init__(self):
        self.llm = get_llm_client()

    def build_prompt(
        self,
        *,
        title: str,
        description: str,
        taxonomy_candidates: Optional[Dict[str, Any]] = None,
        skill_taxonomy_candidates: Optional[Dict[str, Any]] = None,
    ) -> str:
        taxonomy_candidates = taxonomy_candidates or {}
        skill_taxonomy_candidates = skill_taxonomy_candidates or {}
        replacements = {
            "__SOURCE_CLASSIFICATION_NAME__": taxonomy_candidates.get(
                "source_classification_name", "Unknown"
            ),
            "__SOURCE_SUBCLASSIFICATION_NAME__": (
                taxonomy_candidates.get("source_subclassification_name", "Unknown")
                or "Unknown"
            ),
            "__TAXONOMY_CONTEXT__": self._format_taxonomy_context(taxonomy_candidates),
            "__EXISTING_CATEGORIES__": self._format_candidates(
                skill_taxonomy_candidates.get("existing_categories", [])
            ),
            "__EXISTING_TECHNOLOGIES__": self._format_candidates(
                skill_taxonomy_candidates.get("existing_technologies", [])
            ),
            "__EXISTING_SKILLS__": self._format_candidates(
                skill_taxonomy_candidates.get("existing_skills", [])
            ),
            "__REVIEW_ONLY_TERMS__": self._format_candidates(
                skill_taxonomy_candidates.get("review_only_terms", [])
            ),
            "__SUPPRESSED_REVIEW_TERMS__": self._format_candidates(
                skill_taxonomy_candidates.get("suppressed_review_terms", [])
            ),
            "__TITLE__": title,
            "__DESCRIPTION__": (description or "No description")[:2000],
        }

        prompt = INSIGHT_PROMPT
        for key, value in replacements.items():
            prompt = prompt.replace(key, str(value))

        return prompt

    async def extract(
        self,
        *,
        title: str,
        description: str,
        taxonomy_candidates: Optional[Dict[str, Any]] = None,
        skill_taxonomy_candidates: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make exactly one LLM JSON request and return a normalized payload with safe defaults.

        Return shape:
        - classification: dict (may be empty)
        - summary: str | None
        - skills: list[dict]
        - experience: {experience_level, experience_min_years, experience_max_years, summary, evidence}
        """
        prompt = self.build_prompt(
            title=title,
            description=description,
            taxonomy_candidates=taxonomy_candidates,
            skill_taxonomy_candidates=skill_taxonomy_candidates,
        )

        result: Dict[str, Any]
        try:
            result = await self.llm.generate_json(prompt)
        except LLMUpstreamError:
            raise
        except Exception as exc:
            logger.error("Unified insight extraction failed for '%s': %s", title, exc)
            raise

        classification = result.get("classification")
        classification = self._normalize_classification(
            classification,
            taxonomy_candidates,
        )

        summary = result.get("summary")
        if not isinstance(summary, str):
            summary = None

        skills = self._normalize_skills(result.get("skills"))
        experience = self._normalize_experience(result.get("experience"))

        return {
            "classification": classification,
            "summary": summary,
            "skills": skills,
            "experience": experience,
            "confidence": self._coerce_confidence(result.get("confidence")),
        }

    def _format_taxonomy_context(self, taxonomy_candidates: Dict[str, Any]) -> str:
        if not taxonomy_candidates:
            return (
                "Allowed domains:\n- Unknown\n"
                "Allowed categories:\n- Unknown\n"
                "Allowed subcategories:\n- Unknown\n"
                "Default path:\n- Unknown / Unknown / Unknown\n"
                "Do not leave the allowed domain boundary."
            )

        default_path = taxonomy_candidates.get("default_path") or [
            "Unknown",
            "Unknown",
            "Unknown",
        ]
        return (
            f"Allowed domains:\n{self._format_candidates(taxonomy_candidates.get('allowed_domains', []))}\n"
            f"Allowed categories:\n{self._format_candidates(taxonomy_candidates.get('allowed_categories', []))}\n"
            f"Allowed subcategories:\n{self._format_candidates(taxonomy_candidates.get('allowed_subcategories', []))}\n"
            f"Default path:\n- {' / '.join(default_path)}\n"
            "Do not leave the allowed domain boundary."
        )

    def _normalize_classification(
        self,
        classification: Any,
        taxonomy_candidates: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(classification, dict):
            return self._default_classification(taxonomy_candidates)

        source_decision = classification.get("source_path_decision")
        final_decision = classification.get("final_taxonomy_decision")
        if not (
            self._is_complete_decision(source_decision)
            and self._is_complete_decision(final_decision)
        ):
            return self._default_classification(taxonomy_candidates)

        normalized = dict(classification)
        normalized["source_path_decision"] = dict(source_decision)
        normalized["final_taxonomy_decision"] = dict(final_decision)
        taxonomy_decision = classification.get("taxonomy_decision")
        if not self._is_complete_decision(taxonomy_decision):
            taxonomy_decision = final_decision
        normalized["taxonomy_decision"] = dict(taxonomy_decision)
        normalized["compatibility_category"] = (
            classification.get("compatibility_category")
            or self._build_compatibility_category(final_decision)
        )
        normalized["cross_domain"] = bool(classification.get("cross_domain", False))
        normalized["cross_domain_confidence"] = self._coerce_confidence(
            classification.get("cross_domain_confidence")
        )
        normalized["cross_domain_reason"] = (
            classification.get("cross_domain_reason") or ""
        )
        normalized["confidence"] = self._coerce_confidence(
            classification.get("confidence")
        )
        normalized["reasoning"] = (
            classification.get("reasoning")
            if isinstance(classification.get("reasoning"), str)
            else ""
        )
        return normalized

    def _format_candidates(self, values: Any) -> str:
        if not isinstance(values, list):
            return "- None"
        if not values:
            return "- None"
        return "\n".join(f"- {str(value)}" for value in values if str(value).strip())

    def _normalize_skills(self, skills_value: Any) -> List[Dict[str, Any]]:
        if not isinstance(skills_value, list):
            return []

        normalized: List[Dict[str, Any]] = []
        seen = set()

        for raw in skills_value:
            skill = ""
            item: Dict[str, Any] = {}
            if isinstance(raw, dict):
                skill = str(raw.get("skill") or raw.get("name") or "").strip()
                item = {
                    "name": skill,
                    "kind": str(raw.get("kind") or "").strip().lower() or None,
                    "resolution": str(raw.get("resolution") or "").strip().lower() or None,
                    "category": str(raw.get("category") or "").strip() or None,
                    "technology": str(raw.get("technology") or "").strip() or None,
                    "existing_skill": str(raw.get("existing_skill") or "").strip() or None,
                    "evidence": str(raw.get("evidence") or "").strip() or None,
                }
            elif isinstance(raw, str):
                skill = raw.strip()
                item = {"name": skill}
            else:
                continue

            if not skill:
                continue
            key = skill.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(item)

        return normalized[:30]

    def _normalize_experience(self, value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            return {
                "experience_level": "not_specified",
                "experience_min_years": None,
                "experience_max_years": None,
                "summary": None,
                "evidence": [],
            }

        level_raw = value.get("experience_level")
        level = (
            str(level_raw).strip().lower()
            if isinstance(level_raw, (str, int, float))
            else ""
        )
        if level not in self._ALLOWED_EXPERIENCE_LEVELS:
            level = "not_specified"

        min_years = self._coerce_years(value.get("experience_min_years"))
        max_years = self._coerce_years(value.get("experience_max_years"))

        # Be conservative for inconsistent bounds.
        if min_years is not None and max_years is not None and min_years > max_years:
            min_years = None
            max_years = None
        if level == "not_specified":
            min_years = None
            max_years = None

        return {
            "experience_level": level,
            "experience_min_years": min_years,
            "experience_max_years": max_years,
            "summary": self._normalize_summary(value.get("summary")),
            "evidence": self._normalize_evidence(value.get("evidence")),
        }

    def _coerce_years(self, value: Any) -> Optional[int]:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, str):
            text = value.strip()
            if text.isdigit():
                years = int(text)
                return years if years >= 0 else None
        return None

    def _normalize_summary(self, value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    def _normalize_evidence(self, value: Any) -> List[str]:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return []

        normalized: List[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            cleaned = item.strip()
            if cleaned:
                normalized.append(cleaned)
        return normalized[:3]

    def _coerce_confidence(self, value: Any) -> Optional[float]:
        if isinstance(value, bool):
            return None
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return None

    def _default_classification(
        self,
        taxonomy_candidates: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        default_path = list((taxonomy_candidates or {}).get("default_path") or [])
        while len(default_path) < 3:
            default_path.append(None)
        decision = {
            "domain": default_path[0],
            "category": default_path[1],
            "subcategory": default_path[2],
            "resolution": "fallback_default_path",
        }
        return {
            "confidence": 0.0,
            "reasoning": "Missing or invalid classification",
            "source_path_decision": dict(decision),
            "final_taxonomy_decision": dict(decision),
            "taxonomy_decision": dict(decision),
            "compatibility_category": self._build_compatibility_category(decision),
            "cross_domain": False,
            "cross_domain_confidence": 0.0,
            "cross_domain_reason": "",
        }

    def _is_complete_decision(self, value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        return all(
            isinstance(value.get(field), str) and value.get(field).strip()
            for field in ("domain", "category", "subcategory", "resolution")
        )

    def _build_compatibility_category(self, decision: Dict[str, Any]) -> Optional[str]:
        parts = [
            decision.get("domain"),
            decision.get("category"),
            decision.get("subcategory"),
        ]
        if not all(parts):
            return None
        return " / ".join(parts)


_insight_extractor: Optional[JobInsightExtractor] = None


def get_job_insight_extractor() -> JobInsightExtractor:
    """Get singleton JobInsightExtractor instance."""
    global _insight_extractor
    if _insight_extractor is None:
        _insight_extractor = JobInsightExtractor()
    return _insight_extractor
