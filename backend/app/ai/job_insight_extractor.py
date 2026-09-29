"""
Job Insight Extractor

Unified extractor that requests a single JSON payload from the LLM containing:
- skill taxonomy candidate guidance
- a concise summary
- explicit experience extraction fields
- a ranking over frozen Related Jobs candidates
"""

from __future__ import annotations

import logging
import json
import re
from typing import Any, Dict, List, Optional

from app.ai.llm_client import LLMUpstreamError, get_llm_client

logger = logging.getLogger(__name__)


class JobInsightValidationError(ValueError):
    """The provider returned JSON that violates the unified Job contract."""


INSIGHT_PROMPT = """You are a careful job-posting analyst.

You MUST return JSON only, matching the schema at the end of this prompt.

**1) Skill Taxonomy Candidate Guidance**
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

Role extraction mode:
__ROLE_MODE__

Additional role-specific guidance:
__ROLE_MODE_GUIDANCE__

Rules:
- Extract only technical / hard skills (languages, frameworks, tools, platforms).
- Aim for 3-20 technical skills when the posting clearly supports that many.
- Never invent skills just to reach a minimum count; if fewer than 3 concrete skills are evidenced, return fewer.
- Exclude soft skills.
- Normalize common abbreviations (e.g., JS -> JavaScript, K8s -> Kubernetes).
- Prefer `match_existing` only for concrete tools, platforms, frameworks, and technologies.
- If a term appears in the review-only list, use `disposition=unresolved`.
- If a term appears in the suppressed list, do not emit it as a skill unless the posting clearly names a concrete product/tool instead.
- Do not force broad infrastructure, architecture, platform, or discipline terms into an existing skill.
- Use exactly one disposition for every emitted term:
  - `match_existing`: an exact active Skill from the supplied list; put its stable code in `existing_skill`.
  - `unresolved`: an evidenced technical term that cannot be mapped safely.
  - `generic`: a broad activity or workplace concept that is not a governed Skill.
  - `rejected`: unsupported, incidental, or otherwise insufficient evidence.
- Never create or propose a new governed Skill.

**2) Summary Instructions**
Write a concise 2-3 sentence summary. Focus on responsibilities, impact, and the core requirements.
Do not mention the taxonomy or that you are an AI.

**3) Experience Extraction Rules (explicit fields required)**
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

**4) Related Jobs Ranking**
Select zero to five Jobs only from this frozen candidate list:
__RELATED_JOBS_CANDIDATES__

Rules:
- Use the exact candidate `id` as `job_id`.
- Never invent a Job ID or repeat one.
- Return the most relevant Jobs first.
- Give one concise reason grounded in the role and requirements.
- If there are no suitable candidates, return an empty list.

Job Title: __TITLE__
Job Description (first 2000 chars):
__DESCRIPTION__

Respond with JSON only (no markdown, no extra keys):
{{
  "summary": "",
  "skills": [
    {
      "name": "",
      "disposition": "match_existing|unresolved|generic|rejected",
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
  "related_jobs": [
    {
      "job_id": "",
      "reason": ""
    }
  ],
  "confidence": 0.0
}}
""".replace(
    "{{", "{"
).replace(
    "}}", "}"
)


class JobInsightExtractor:
    """Unified extractor that returns the complete current Job insight."""

    _DESCRIPTION_CONTEXT_LIMIT = 3200
    _DESCRIPTION_PREFIX_CHARS = 1200
    _DESCRIPTION_TAIL_CHARS = 600
    _SECTION_LINE_BUDGET = 8
    _SECTION_HEADING_PATTERN = re.compile(
        r"\b(requirement|requirements|qualification|qualifications|skill|skills|tool|tools|technology|technologies|preferred|experience)\b",
        re.IGNORECASE,
    )

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
    _ALLOWED_SKILL_DISPOSITIONS = {
        "match_existing",
        "unresolved",
        "generic",
        "rejected",
    }
    _RELATED_JOB_LIMIT = 5
    _RELATED_JOB_REASON_LIMIT = 300

    def __init__(self):
        self.llm = None

    def build_prompt(
        self,
        *,
        title: str,
        description: str,
        skill_taxonomy_candidates: Optional[Dict[str, Any]] = None,
        related_jobs_candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        skill_taxonomy_candidates = skill_taxonomy_candidates or {}
        replacements = {
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
            "__ROLE_MODE__": str(
                skill_taxonomy_candidates.get("role_mode") or "technical_heavy"
            ),
            "__ROLE_MODE_GUIDANCE__": str(
                skill_taxonomy_candidates.get("role_mode_guidance")
                or "No additional role-specific guidance."
            ),
            "__TITLE__": title,
            "__DESCRIPTION__": self._build_description_context(description),
            "__RELATED_JOBS_CANDIDATES__": self._format_related_jobs_candidates(
                related_jobs_candidates or []
            ),
        }

        prompt = INSIGHT_PROMPT
        for key, value in replacements.items():
            prompt = prompt.replace(key, str(value))

        return prompt

    def _build_description_context(self, description: str) -> str:
        text = str(description or "").strip()
        if not text:
            return "No description"
        if len(text) <= self._DESCRIPTION_CONTEXT_LIMIT:
            return text

        segments: list[str] = []
        seen: set[str] = set()

        def add_segment(value: str) -> None:
            cleaned = value.strip()
            if not cleaned or cleaned in seen:
                return
            seen.add(cleaned)
            segments.append(cleaned)

        add_segment(text[: self._DESCRIPTION_PREFIX_CHARS])

        lines = [line.rstrip() for line in text.splitlines()]
        for index, line in enumerate(lines):
            if not self._SECTION_HEADING_PATTERN.search(line):
                continue

            chunk = [line.strip()]
            for candidate in lines[index + 1 : index + 1 + self._SECTION_LINE_BUDGET]:
                stripped = candidate.strip()
                if not stripped:
                    break
                if (
                    chunk
                    and stripped == stripped.upper()
                    and len(stripped.split()) <= 6
                    and self._SECTION_HEADING_PATTERN.search(stripped)
                ):
                    break
                chunk.append(stripped)
            add_segment("\n".join(chunk))

        add_segment(text[-self._DESCRIPTION_TAIL_CHARS :])

        context = "\n\n".join(segments)
        if len(context) <= self._DESCRIPTION_CONTEXT_LIMIT:
            return context
        return context[: self._DESCRIPTION_CONTEXT_LIMIT].rstrip()

    async def extract(
        self,
        *,
        title: str,
        description: str,
        skill_taxonomy_candidates: Optional[Dict[str, Any]] = None,
        related_jobs_candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Make exactly one LLM JSON request and return a normalized payload with safe defaults.

        Return shape:
        - summary: str | None
        - skills: list[dict]
        - experience: {experience_level, experience_min_years, experience_max_years, summary, evidence}
        - related_jobs: list[{job_id, reason}]
        """
        prompt = self.build_prompt(
            title=title,
            description=description,
            skill_taxonomy_candidates=skill_taxonomy_candidates,
            related_jobs_candidates=related_jobs_candidates,
        )

        result: Dict[str, Any]
        try:
            result = await self._get_llm().generate_json(prompt)
        except LLMUpstreamError:
            raise
        except Exception as exc:
            logger.error("Unified insight extraction failed for '%s': %s", title, exc)
            raise

        self.validate_result(
            result,
            skill_taxonomy_candidates=skill_taxonomy_candidates or {},
            related_jobs_candidates=related_jobs_candidates or [],
        )
        summary = result.get("summary")
        assert isinstance(summary, str)
        summary = summary.strip()

        skills = self._normalize_skills(result.get("skills"))
        experience = self._normalize_experience(result.get("experience"))
        related_jobs = self._normalize_related_jobs(result.get("related_jobs"))

        return {
            "summary": summary,
            "skills": skills,
            "experience": experience,
            "related_jobs": related_jobs,
            "confidence": self._coerce_confidence(result.get("confidence")),
        }

    def _get_llm(self):
        if self.llm is None:
            self.llm = get_llm_client()
        return self.llm

    def validate_result(
        self,
        result: object,
        *,
        skill_taxonomy_candidates: Dict[str, Any],
        related_jobs_candidates: List[Dict[str, Any]],
    ) -> None:
        if not isinstance(result, dict):
            raise JobInsightValidationError("Job insight response must be an object")
        required = {"summary", "skills", "experience", "related_jobs"}
        missing = sorted(required.difference(result))
        if missing:
            raise JobInsightValidationError(
                f"Job insight response is missing required sections: {', '.join(missing)}"
            )
        if not isinstance(result["summary"], str) or not result["summary"].strip():
            raise JobInsightValidationError("summary must be a non-empty string")
        if not isinstance(result["skills"], list):
            raise JobInsightValidationError("skills must be a list")
        if not isinstance(result["experience"], dict):
            raise JobInsightValidationError("experience must be an object")
        if not isinstance(result["related_jobs"], list):
            raise JobInsightValidationError("related_jobs must be a list")

        experience = result["experience"]
        experience_fields = {
            "experience_level",
            "experience_min_years",
            "experience_max_years",
            "summary",
            "evidence",
        }
        missing_experience = sorted(experience_fields.difference(experience))
        if missing_experience:
            raise JobInsightValidationError(
                "experience is missing required fields: "
                + ", ".join(missing_experience)
            )
        level = experience["experience_level"]
        if level not in self._ALLOWED_EXPERIENCE_LEVELS:
            raise JobInsightValidationError("experience.experience_level is invalid")
        for field_name in ("experience_min_years", "experience_max_years"):
            value = experience[field_name]
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise JobInsightValidationError(
                    f"experience.{field_name} must be a non-negative integer or null"
                )
        minimum = experience["experience_min_years"]
        maximum = experience["experience_max_years"]
        if minimum is not None and maximum is not None and maximum < minimum:
            raise JobInsightValidationError(
                "experience.experience_max_years cannot be below the minimum"
            )
        if experience["summary"] is not None and not isinstance(
            experience["summary"], str
        ):
            raise JobInsightValidationError(
                "experience.summary must be a string or null"
            )
        evidence = experience["evidence"]
        if (
            not isinstance(evidence, list)
            or len(evidence) > 3
            or any(not isinstance(item, str) for item in evidence)
        ):
            raise JobInsightValidationError(
                "experience.evidence must be a list of at most three strings"
            )

        allowed_skill_codes = {
            str(code).strip()
            for code in skill_taxonomy_candidates.get("assignable_skill_codes", [])
            if str(code).strip()
        }

        for index, raw in enumerate(result["skills"]):
            if not isinstance(raw, dict):
                raise JobInsightValidationError(f"skills[{index}] must be an object")
            name = str(raw.get("name") or raw.get("skill") or "").strip()
            disposition = str(raw.get("disposition") or "").strip().lower()
            if not name:
                raise JobInsightValidationError(f"skills[{index}].name is required")
            if disposition not in self._ALLOWED_SKILL_DISPOSITIONS:
                raise JobInsightValidationError(
                    f"skills[{index}].disposition is invalid"
                )
            existing_skill = str(raw.get("existing_skill") or "").strip()
            if disposition == "match_existing":
                if not existing_skill:
                    raise JobInsightValidationError(
                        f"skills[{index}].existing_skill is required for match_existing"
                    )
                if existing_skill not in allowed_skill_codes:
                    raise JobInsightValidationError(
                        f"skills[{index}].existing_skill is not an active assignable Skill code"
                    )

        allowed_ids = {
            str(candidate.get("id") or "").strip()
            for candidate in related_jobs_candidates
            if isinstance(candidate, dict) and str(candidate.get("id") or "").strip()
        }
        if len(result["related_jobs"]) > self._RELATED_JOB_LIMIT:
            raise JobInsightValidationError(
                f"related_jobs may contain at most {self._RELATED_JOB_LIMIT} items"
            )
        seen_ids: set[str] = set()
        for index, raw in enumerate(result["related_jobs"]):
            if not isinstance(raw, dict):
                raise JobInsightValidationError(
                    f"related_jobs[{index}] must be an object"
                )
            job_id = str(raw.get("job_id") or "").strip()
            reason = str(raw.get("reason") or "").strip()
            if job_id not in allowed_ids:
                raise JobInsightValidationError(
                    f"related_jobs[{index}].job_id is outside the frozen candidate set"
                )
            if job_id in seen_ids:
                raise JobInsightValidationError(
                    f"related_jobs[{index}].job_id is duplicated"
                )
            if not reason or len(reason) > self._RELATED_JOB_REASON_LIMIT:
                raise JobInsightValidationError(
                    f"related_jobs[{index}].reason must contain 1-"
                    f"{self._RELATED_JOB_REASON_LIMIT} characters"
                )
            seen_ids.add(job_id)

    def _format_candidates(self, values: Any) -> str:
        if not isinstance(values, list):
            return "- None"
        if not values:
            return "- None"
        return "\n".join(f"- {str(value)}" for value in values if str(value).strip())

    def _format_related_jobs_candidates(self, values: Any) -> str:
        if not isinstance(values, list) or not values:
            return "- None"
        return (
            "\n".join(
                f"- {json.dumps(value, default=str, sort_keys=True)}"
                for value in values
                if isinstance(value, dict)
            )
            or "- None"
        )

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
                item = {"name": skill}
                for key in (
                    "disposition",
                    "existing_skill",
                    "evidence",
                    "decision_reason",
                ):
                    value = str(raw.get(key) or "").strip()
                    if value:
                        item[key] = value.lower() if key == "disposition" else value
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

        return normalized[:20]

    def _normalize_related_jobs(self, value: Any) -> List[Dict[str, str]]:
        if not isinstance(value, list):
            return []
        normalized: List[Dict[str, str]] = []
        for raw in value:
            if not isinstance(raw, dict):
                continue
            job_id = str(raw.get("job_id") or "").strip()
            reason = str(raw.get("reason") or "").strip()
            if job_id and reason:
                normalized.append({"job_id": job_id, "reason": reason})
        return normalized

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


_insight_extractor: Optional[JobInsightExtractor] = None


def get_job_insight_extractor() -> JobInsightExtractor:
    """Get singleton JobInsightExtractor instance."""
    global _insight_extractor
    if _insight_extractor is None:
        _insight_extractor = JobInsightExtractor()
    return _insight_extractor
