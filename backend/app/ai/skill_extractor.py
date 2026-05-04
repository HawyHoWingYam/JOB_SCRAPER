"""
Skill Extractor Service

Extracts technical skills from job descriptions using LLM.
"""

import logging
from typing import Optional, Dict, Any, List

from app.ai.llm_client import LLMUpstreamError, get_llm_client

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """Extract technical skills from this job description.

Job Title: {title}
Description:
{description}

Taxonomy guidance:
{taxonomy_context}

Instructions:
1. Extract 5-15 specific technical skills mentioned or implied
2. Include: programming languages, frameworks, tools, platforms
3. Normalize names (e.g., "JS" → "JavaScript", "K8s" → "Kubernetes")
4. Exclude soft skills (communication, teamwork, etc.)
5. Prefer `match_existing` only for concrete tools, platforms, frameworks, and technologies
6. If a term appears in the review-only list, leave it unresolved instead of forcing an existing match
7. If a term appears in the suppressed list, do not emit it as a skill unless it is clearly a concrete product/tool
8. Use `create_new` only when the existing taxonomy slice clearly does not fit

Respond with JSON only:
{{"skills": ["skill1", "skill2", ...], "taxonomy_decisions": [{{"skill": "skill1", "action": "match_existing|create_new", "category": "L1", "technology": "L2", "existing_skill": "L3 or null"}}], "confidence": 0.0-1.0}}
"""


class SkillExtractor:
    """Extracts skills from job descriptions using LLM."""

    def __init__(self):
        self.llm = get_llm_client()

    def build_extraction_prompt(
        self,
        title: str,
        description: str,
        taxonomy_candidates: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the skill extraction prompt with taxonomy candidate guidance."""
        prompt = EXTRACTION_PROMPT.format(
            title=title,
            description=description[:2000] if description else "No description",
            taxonomy_context=self._format_taxonomy_context(taxonomy_candidates),
        )
        return prompt

    async def extract(
        self,
        title: str,
        description: str,
        taxonomy_candidates: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Extract skills from a job posting."""
        prompt = self.build_extraction_prompt(title, description, taxonomy_candidates)

        try:
            result = await self.llm.generate_json(prompt)
        except LLMUpstreamError as e:
            logger.error(f"Skill extraction upstream error: {e}")
            raise
        except Exception as e:
            logger.error(f"Skill extraction error: {e}")
            return {"skills": [], "confidence": 0.0, "error": True}

        try:
            skills = result.get("skills", [])

            # Normalize and deduplicate
            skills = self._normalize_skills(skills)
            result["skills"] = skills
            return result
        except Exception as e:
            logger.error(f"Skill extraction post-processing error: {e}")
            return {"skills": [], "confidence": 0.0, "error": True}

    def _format_taxonomy_context(
        self, taxonomy_candidates: Optional[Dict[str, Any]]
    ) -> str:
        """Format a candidate slice so the LLM can prefer existing taxonomy nodes."""
        if not taxonomy_candidates:
            return (
                "No candidate slice was provided.\n"
                "Default to conservative matching and create_new only when necessary."
            )

        categories = taxonomy_candidates.get("existing_categories", [])
        technologies = taxonomy_candidates.get("existing_technologies", [])
        skills = taxonomy_candidates.get("existing_skills", [])

        return (
            f"Inferred category hint: {taxonomy_candidates.get('category_hint', 'Unknown')}\n"
            f"Inferred technology hint: {taxonomy_candidates.get('technology_hint', 'Unknown')}\n"
            f"Existing categories:\n{self._format_candidates(categories)}\n"
            f"Existing technologies:\n{self._format_candidates(technologies)}\n"
            f"Existing skills:\n{self._format_candidates(skills)}\n"
            f"Review-only terms:\n{self._format_candidates(taxonomy_candidates.get('review_only_terms', []))}\n"
            f"Suppressed broad terms:\n{self._format_candidates(taxonomy_candidates.get('suppressed_review_terms', []))}"
        )

    def _format_candidates(self, values: List[str]) -> str:
        """Render a candidate list for prompt inclusion."""
        if not values:
            return "- None"
        return "\n".join(f"- {value}" for value in values)

    def _normalize_skills(self, skills: List[str]) -> List[str]:
        """Normalize and deduplicate skills."""
        normalized = []
        seen = set()

        for skill in skills:
            if isinstance(skill, dict):
                skill = skill.get("skill") or skill.get("name") or ""
            skill = skill.strip()
            if skill and skill.lower() not in seen:
                seen.add(skill.lower())
                normalized.append(skill)

        return normalized[:15]  # Limit to 15 skills

    async def extract_batch(
        self, jobs: List[Dict], on_progress: Optional[callable] = None
    ) -> List[Dict[str, Any]]:
        """Extract skills from multiple jobs."""
        results = []
        for i, job in enumerate(jobs):
            result = await self.extract(job.get("title", ""), job.get("description", ""))
            results.append(result)
            if on_progress:
                on_progress(i + 1, len(jobs))
        return results


_extractor: Optional[SkillExtractor] = None

def get_skill_extractor() -> SkillExtractor:
    """Get singleton SkillExtractor instance."""
    global _extractor
    if _extractor is None:
        _extractor = SkillExtractor()
    return _extractor
