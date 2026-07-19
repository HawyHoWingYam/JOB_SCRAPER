"""
AI Enrichment Service

Orchestrates unified job insight enrichment with batch processing.
"""

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.job_insight_extractor import get_job_insight_extractor
from app.ai.llm_client import LLMResponseFormatError, LLMUpstreamError, get_llm_status
from app.job_intelligence.canonical_taxonomy import (
    CanonicalClassifierContext,
    CanonicalClassifierOutput,
    CanonicalJobTaxonomy,
    EvaluationResult,
)
from app.job_intelligence.foundation import Provenance, normalized_content_hash
from app.job_intelligence.skill_governance import (
    SkillExtractionContext,
    SkillGovernance,
    SkillGovernanceReader,
)
from app.job_intelligence.source_attributes import SourceJobAttributes
from app.models.job import Job
from app.database import SessionLocal
from app.services.job_role_mode import resolve_job_role_mode
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


class AIEnrichmentService:
    """Orchestrates AI enrichment for jobs."""

    def __init__(self):
        self.insight_extractor = get_job_insight_extractor()
        self.batch_size = 10

    async def enrich_job(self, job: Job, db: Session) -> Dict[str, Any]:
        """Enrich a single job with one AI insight request."""
        results: Dict[str, Any] = {"job_id": str(job.id), "status": "success"}

        try:
            role_mode = resolve_job_role_mode(
                title=job.title,
                source_subclassification_name=job.source_subclassification_name or "",
                source_classification_name=job.source_classification_name or "",
            )
            source_attributes = SourceJobAttributes(db).get(job.id)
            canonical_taxonomy = CanonicalJobTaxonomy(db)
            classifier_context = canonical_taxonomy.build_classifier_context(
                source_attributes
            )
            if classifier_context.blocking_reasons:
                evaluation = canonical_taxonomy.evaluate(
                    job.id,
                    source_attributes,
                    classifier_output=None,
                )
                results["status"] = "excluded"
                results["error"] = ",".join(classifier_context.blocking_reasons)
                results["canonical_taxonomy"] = self._evaluation_payload(evaluation)
                db.commit()
                return results

            category_candidates = classifier_context.to_prompt_payload()
            skill_candidates = SkillGovernanceReader(db).get_prompt_candidate_slice(
                job.title,
                description=job.description or "",
                source_subclassification_name=job.source_subclassification_name,
                role_mode=role_mode,
            )
            insight = await self.insight_extractor.extract(
                title=job.title,
                description=job.description or "",
                taxonomy_candidates=category_candidates,
                skill_taxonomy_candidates=skill_candidates,
            )

            classification = insight.get("classification") or {}
            llm_status = get_llm_status("jobs")
            results["classification"] = classification
            extracted_skills = insight.get("skills") or []
            results["skills"] = {
                "skills": extracted_skills,
                "confidence": insight.get("confidence"),
            }

            classifier_output = self._canonical_classifier_output(
                classification,
                context=classifier_context,
                llm_status=llm_status,
            )
            evaluation = canonical_taxonomy.evaluate(
                job.id,
                source_attributes,
                classifier_output,
            )
            results["canonical_taxonomy"] = self._evaluation_payload(evaluation)
            job.ai_enriched_at = utc_now()

            job.ai_summary = insight.get("summary")

            experience = insight.get("experience") or {}
            if not isinstance(experience, dict):
                experience = {}
            job.experience_level = experience.get("experience_level") or "not_specified"
            job.experience_min_years = experience.get("experience_min_years")
            job.experience_max_years = experience.get("experience_max_years")
            job.experience_summary = experience.get("summary")
            job.experience_evidence = experience.get("evidence")

            skill_projection = SkillGovernance(db).extract(
                job.id,
                extracted_skills,
                SkillExtractionContext(
                    source="ai-extraction",
                    confidence=insight.get("confidence"),
                    provenance={
                        "method": "constrained-ai-extraction",
                        "model_provider": llm_status.get("active_provider"),
                        "model_name": llm_status.get("active_model"),
                        "model_version": llm_status.get("model_version"),
                        "content_hash": normalized_content_hash(extracted_skills),
                    },
                ),
            )
            results["skill_projection"] = {
                "taxonomy_revision_id": str(skill_projection.taxonomy_revision_id),
                "changed": skill_projection.changed,
                "mentions": [
                    {
                        "id": str(mention.id),
                        "resolution": mention.resolution,
                        "skill_id": (
                            str(mention.skill_id)
                            if mention.skill_id is not None
                            else None
                        ),
                        "candidate_id": (
                            str(mention.candidate_id)
                            if mention.candidate_id is not None
                            else None
                        ),
                    }
                    for mention in skill_projection.mentions
                ],
            }
            db.commit()

        except LLMUpstreamError as e:
            logger.error(f"Enrichment upstream failure for job {job.id}: {e}")
            results["status"] = "error"
            error_text = str(e)
            if isinstance(e, LLMResponseFormatError):
                # Provide a stable, sanitized envelope preview for downstream parsing/tests,
                # without depending on provider-specific output structures.
                normalized_preview = None
                try:
                    payload = json.loads(getattr(e, "raw_response", "") or "")
                    if (
                        isinstance(payload, dict)
                        and isinstance(payload.get("response"), dict)
                        and "output" in payload["response"]
                    ):
                        payload["response"]["output"] = []
                        normalized_preview = json.dumps(payload, separators=(",", ":"))
                except Exception:
                    normalized_preview = None
                if normalized_preview:
                    error_text = f"{error_text} Normalized raw response preview: {normalized_preview}"
            results["error"] = error_text
            db.rollback()
        except Exception as e:
            logger.error(f"Enrichment failed for job {job.id}: {e}")
            results["status"] = "error"
            results["error"] = str(e)
            db.rollback()

        return results

    @staticmethod
    def _evaluation_payload(evaluation: EvaluationResult) -> dict[str, object]:
        return {
            "state": evaluation.state,
            "version": evaluation.version,
            "assignment_id": (
                str(evaluation.assignment_id)
                if evaluation.assignment_id is not None
                else None
            ),
            "review_item_id": (
                str(evaluation.review_item_id)
                if evaluation.review_item_id is not None
                else None
            ),
            "reasons": list(evaluation.reasons),
        }

    @staticmethod
    def _canonical_classifier_output(
        classification: object,
        *,
        context: CanonicalClassifierContext,
        llm_status: Dict[str, Any],
    ) -> CanonicalClassifierOutput:
        payload = classification if isinstance(classification, dict) else {}
        raw_decision = payload.get("decision")
        decision = (
            raw_decision
            if raw_decision
            in {"select_existing", "fallback_default", "create_new", "invalid"}
            else "invalid"
        )
        raw_target_code = payload.get("target_code")
        target_code = (
            raw_target_code.strip()
            if isinstance(raw_target_code, str) and raw_target_code.strip()
            else None
        )

        def optional_text(value: object) -> str | None:
            if not isinstance(value, str):
                return None
            normalized = value.strip()
            return normalized or None

        provenance = Provenance(
            method="constrained-ai-classifier",
            evidence_refs=(
                {
                    "kind": "ai-classifier-output",
                    "content_hash": normalized_content_hash(payload),
                    "taxonomy_revision_id": str(context.taxonomy_revision_id),
                    "mapping_revision_id": str(context.mapping_revision_id),
                },
            ),
            captured_at=utc_now(),
            source_site=None,
            model_provider=optional_text(llm_status.get("active_provider")),
            model_name=optional_text(llm_status.get("active_model")),
            model_version=optional_text(llm_status.get("model_version")),
        )
        return CanonicalClassifierOutput(
            decision=decision,
            target_code=target_code,
            provenance=provenance,
        )

    async def enrich_batch(
        self,
        job_ids: List[UUID],
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, Any]:
        """Backward-compatible alias for enriching an explicit set of job IDs."""
        return await self.enrich_job_ids(job_ids, on_progress)

    async def enrich_job_ids(
        self,
        job_ids: List[UUID],
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, Any]:
        """Enrich multiple jobs by ID."""
        db = SessionLocal()
        results: Dict[str, Any] = {
            "total": len(job_ids),
            "success": 0,
            "failed": 0,
            "jobs": [],
        }

        try:
            for i, job_id in enumerate(job_ids):
                job = db.query(Job).filter(Job.id == job_id).first()
                if job:
                    result = await self.enrich_job(job, db)
                    results["jobs"].append(result)
                    if result["status"] == "success":
                        results["success"] += 1
                    else:
                        results["failed"] += 1

                if on_progress:
                    on_progress(i + 1, len(job_ids))

                # Small delay between jobs
                await asyncio.sleep(0.5)

        finally:
            db.close()

        return results

    async def enrich_job_id(self, job_id: UUID) -> Dict[str, Any]:
        """Enrich a single job by ID using an isolated DB session."""
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job is None:
                return {
                    "job_id": str(job_id),
                    "status": "error",
                    "error": "job not found",
                }
            return await self.enrich_job(job, db)
        finally:
            db.close()

    async def enrich_unenriched(
        self,
        limit: int = 100,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, Any]:
        """Enrich jobs that haven't been processed yet."""
        db = SessionLocal()

        try:
            jobs = (
                db.query(Job)
                .filter(
                    Job.ai_enriched_at.is_(None),
                    Job.is_deleted.is_(False),
                    Job.source_attribute_projection.has(),
                )
                .limit(limit)
                .all()
            )

            job_ids = [job.id for job in jobs]
        finally:
            db.close()

        return await self.enrich_batch(job_ids, on_progress)


_service: Optional[AIEnrichmentService] = None


def get_ai_enrichment_service() -> AIEnrichmentService:
    """Get singleton AIEnrichmentService instance."""
    global _service
    if _service is None:
        _service = AIEnrichmentService()
    return _service
