"""
Job Classifier Service

Classifies jobs into a source-bounded taxonomy using LLM.
"""

import logging
from typing import Optional, Dict, Any, List

from app.ai.llm_client import LLMUpstreamError, get_llm_client

logger = logging.getLogger(__name__)

CLASSIFICATION_PROMPT = """Analyze this job posting and classify it conservatively.

Source classification:
- L1 source category: {source_classification_name}
- Source subcategory: {source_subclassification_name}

Allowed taxonomy boundary:
{taxonomy_context}

Job Title: {title}
Job Description (first 1500 chars):
{description}

Instructions:
1. `source_path_decision` must be the safest valid L1/L2/L3 path inside the allowed taxonomy boundary
2. `source_path_decision` must use the provided default path when the role is ambiguous
3. `final_taxonomy_decision` should be the best overall L1/L2/L3 path for the actual job function, even if it crosses domains
4. Set `cross_domain` to true only when `final_taxonomy_decision` should leave the source domain
5. Set `cross_domain_confidence` between 0.0 and 1.0
6. Prefer existing taxonomy nodes over inventing a new one
7. Keep reasoning brief and concrete
{conservative_guidance}

Respond with JSON only:
{{"confidence": 0.0-1.0, "reasoning": "brief explanation", "source_path_decision": {{"domain": "L1", "category": "L2", "subcategory": "L3", "resolution": "match_existing|fallback_default_path|create_new"}}, "final_taxonomy_decision": {{"domain": "L1", "category": "L2", "subcategory": "L3", "resolution": "match_existing|fallback_default_path|create_new"}}, "cross_domain": true, "cross_domain_confidence": 0.0-1.0, "cross_domain_reason": "brief explanation"}}
"""


class JobClassifier:
    """Classifies jobs into a source-bounded taxonomy."""

    def __init__(self):
        self.llm = get_llm_client()

    def build_classification_prompt(
        self,
        title: str,
        description: str,
        taxonomy_candidates: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the job classification prompt with source-bounded taxonomy guidance."""
        candidates = taxonomy_candidates or {}
        return CLASSIFICATION_PROMPT.format(
            source_classification_name=candidates.get(
                "source_classification_name", "Unknown"
            ),
            source_subclassification_name=candidates.get(
                "source_subclassification_name", "Unknown"
            )
            or "Unknown",
            taxonomy_context=self._format_taxonomy_context(candidates),
            title=title,
            description=description[:1500] if description else "No description",
            conservative_guidance=self._format_conservative_guidance(candidates),
        )

    async def classify(
        self,
        title: str,
        description: str,
        taxonomy_candidates: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Classify a single job into a source-bounded taxonomy path."""
        prompt = self.build_classification_prompt(
            title,
            description,
            taxonomy_candidates=taxonomy_candidates,
        )

        try:
            result = await self.llm.generate_json(prompt)
        except LLMUpstreamError as e:
            logger.error(f"Classification upstream error for '{title}': {e}")
            raise
        except Exception as e:
            logger.error(f"Classification error for '{title}': {e}")
            return self._fallback_result(
                taxonomy_candidates=taxonomy_candidates,
                reason=f"Classification failed: {str(e)}",
                error=True,
            )

        try:
            return self._validate_taxonomy_decision(
                result,
                taxonomy_candidates=taxonomy_candidates,
            )
        except Exception as e:
            logger.error(f"Classification validation error for '{title}': {e}")
            return self._fallback_result(
                taxonomy_candidates=taxonomy_candidates,
                reason=f"Classification validation failed: {str(e)}",
                error=True,
            )

    def _validate_taxonomy_decision(
        self,
        result: Dict[str, Any],
        taxonomy_candidates: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Clamp invalid LLM outputs to the allowed taxonomy boundary."""
        candidates = taxonomy_candidates or {}
        legacy_decision = result.get("taxonomy_decision") or {}
        source_decision = result.get("source_path_decision") or legacy_decision
        final_decision = result.get("final_taxonomy_decision")

        if not source_decision and not final_decision:
            return self._fallback_result(
                taxonomy_candidates=candidates,
                reason=result.get("reasoning", "Missing taxonomy decision"),
            )

        validated_source = self._validate_source_path(source_decision, candidates)
        validated_final = self._normalize_final_path(
            final_decision or validated_source,
            fallback_decision=validated_source,
        )
        cross_domain = result.get("cross_domain")
        if cross_domain is None:
            cross_domain = validated_source["domain"] != validated_final["domain"]

        validated = dict(result)
        validated["source_path_decision"] = validated_source
        validated["final_taxonomy_decision"] = validated_final
        validated["taxonomy_decision"] = dict(validated_final)
        validated["cross_domain"] = bool(cross_domain)
        validated["cross_domain_confidence"] = self._coerce_confidence(
            result.get("cross_domain_confidence"),
            default=result.get("confidence", 0.0) if cross_domain else 1.0,
        )
        validated["cross_domain_reason"] = result.get("cross_domain_reason", "")
        validated["compatibility_category"] = self._build_compatibility_category(
            validated_final
        )
        return validated

    def _fallback_result(
        self,
        taxonomy_candidates: Optional[Dict[str, Any]],
        reason: str,
        error: bool = False,
    ) -> Dict[str, Any]:
        """Return a safe default result inside the provided source boundary."""
        default_path = (taxonomy_candidates or {}).get("default_path") or [
            None,
            None,
            None,
        ]
        taxonomy_decision = {
            "domain": default_path[0],
            "category": default_path[1],
            "subcategory": default_path[2],
            "resolution": "fallback_default_path",
        }

        return {
            "confidence": 0.0 if error else 0.1,
            "reasoning": reason,
            "source_path_decision": dict(taxonomy_decision),
            "final_taxonomy_decision": dict(taxonomy_decision),
            "taxonomy_decision": dict(taxonomy_decision),
            "compatibility_category": self._build_compatibility_category(
                taxonomy_decision
            ),
            "cross_domain": False,
            "cross_domain_confidence": 0.0 if error else 0.1,
            "cross_domain_reason": "",
            "error": error,
        }

    def _format_taxonomy_context(
        self, taxonomy_candidates: Optional[Dict[str, Any]]
    ) -> str:
        """Format the source-bounded candidate slice for prompt inclusion."""
        if not taxonomy_candidates:
            return (
                "Allowed domains:\n- Unknown\n"
                "Allowed categories:\n- Unknown\n"
                "Allowed subcategories:\n- Unknown\n"
                "Default path:\n- Unknown / Unknown / Unknown"
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

    def _format_candidates(self, values: List[str]) -> str:
        """Render a candidate list for prompt inclusion."""
        if not values:
            return "- None"
        return "\n".join(f"- {value}" for value in values)

    def _format_conservative_guidance(
        self, taxonomy_candidates: Optional[Dict[str, Any]]
    ) -> str:
        """Add conservative mode instructions when enabled."""
        candidates = taxonomy_candidates or {}
        if not candidates.get("conservative_mode"):
            return "Conservative mode is OFF."

        threshold = candidates.get("cross_domain_min_confidence", 0.9)
        return (
            "Conservative mode is ON.\n"
            f"8. Only recommend cross-domain when the evidence is very strong and set "
            f"`cross_domain_confidence` accordingly (current acceptance threshold: {threshold}).\n"
            "9. The source classification is a strong prior. Cross-domain is exceptional.\n"
            "10. Keywords alone are not enough. Tools alone are not enough. Platforms alone are not enough.\n"
            "11. Technical terminology alone does not imply a technical-domain job.\n"
            "12. Cross-domain requires stronger role-function evidence based on responsibilities, day-to-day work, deliverables, and team function.\n"
            "13. If the best fit remains inside the source domain and clearly matches an existing category/subcategory, prefer that specific path and do not fall back to General/General."
        )

    def _validate_source_path(
        self,
        decision: Dict[str, Any],
        taxonomy_candidates: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Validate the safe source-bounded path or fall back to default."""
        allowed_domains = taxonomy_candidates.get("allowed_domains") or []
        allowed_categories = taxonomy_candidates.get("allowed_categories") or []
        allowed_subcategories = taxonomy_candidates.get("allowed_subcategories") or []

        fallback = self._default_decision(taxonomy_candidates)
        if not decision:
            return fallback

        domain = decision.get("domain")
        category = decision.get("category")
        subcategory = decision.get("subcategory")

        if allowed_domains and domain not in allowed_domains:
            return fallback
        if allowed_categories and category not in allowed_categories:
            return fallback
        if allowed_subcategories and subcategory not in allowed_subcategories:
            return fallback

        return {
            "domain": domain,
            "category": category,
            "subcategory": subcategory,
            "resolution": decision.get("resolution", "match_existing"),
        }

    def _normalize_final_path(
        self,
        decision: Dict[str, Any],
        fallback_decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Preserve the model's preferred final path when it has complete shape."""
        if not decision:
            return dict(fallback_decision)

        domain = decision.get("domain")
        category = decision.get("category")
        subcategory = decision.get("subcategory")
        if not (domain and category and subcategory):
            return dict(fallback_decision)

        return {
            "domain": domain,
            "category": category,
            "subcategory": subcategory,
            "resolution": decision.get("resolution", "match_existing"),
        }

    def _default_decision(
        self, taxonomy_candidates: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build the safe default path inside the current source slice."""
        default_path = (taxonomy_candidates or {}).get("default_path") or [
            None,
            None,
            None,
        ]
        return {
            "domain": default_path[0],
            "category": default_path[1],
            "subcategory": default_path[2],
            "resolution": "fallback_default_path",
        }

    def _coerce_confidence(self, value: Any, default: float) -> float:
        """Clamp confidence values into the expected 0-1 range."""
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return default

    def _build_compatibility_category(self, decision: Dict[str, Any]) -> Optional[str]:
        """Build the legacy-compatible path string from a taxonomy decision."""
        parts = [
            decision.get("domain"),
            decision.get("category"),
            decision.get("subcategory"),
        ]
        if not all(parts):
            return None
        return " / ".join(parts)

    async def classify_batch(
        self,
        jobs: List[Dict[str, str]],
        on_progress: Optional[callable] = None
    ) -> List[Dict[str, Any]]:
        """Classify multiple jobs."""
        results = []
        total = len(jobs)

        for i, job in enumerate(jobs):
            result = await self.classify(
                title=job.get("title", ""),
                description=job.get("description", "")
            )
            result["job_index"] = i
            results.append(result)

            if on_progress:
                on_progress(i + 1, total)

        return results


_classifier: Optional[JobClassifier] = None


def get_job_classifier() -> JobClassifier:
    """Get singleton JobClassifier instance."""
    global _classifier
    if _classifier is None:
        _classifier = JobClassifier()
    return _classifier
