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
from app.job_intelligence.current_taxonomies.enrichment import (
    CurrentTaxonomyEnrichment,
)
from app.job_intelligence.foundation import normalized_content_hash
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
            current_taxonomies = CurrentTaxonomyEnrichment(db)
            classifier_context = current_taxonomies.build_job_context(source_attributes)
            category_candidates = classifier_context.prompt_payload
            skill_candidates = current_taxonomies.build_skill_prompt(
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

            model_provenance = self._model_provenance(llm_status)
            results["canonical_taxonomy"] = (
                current_taxonomies.assign_job_from_classification(
                    job_id=job.id,
                    evidence=source_attributes,
                    classification=classification,
                    context=classifier_context,
                    model_provenance=model_provenance,
                )
            )
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

            raw_confidence = insight.get("confidence")
            confidence = (
                float(raw_confidence)
                if isinstance(raw_confidence, (int, float))
                else None
            )
            results["skill_projection"] = current_taxonomies.replace_job_skills(
                job_id=job.id,
                extracted_skills=extracted_skills,
                confidence=confidence,
                provenance={
                    "method": "constrained-ai-extraction",
                    **model_provenance,
                    "content_hash": normalized_content_hash(extracted_skills),
                },
            )
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
    def _model_provenance(llm_status: Dict[str, Any]) -> dict[str, object]:
        values = {
            "provider": llm_status.get("active_provider"),
            "name": llm_status.get("active_model"),
            "version": llm_status.get("model_version"),
        }
        return {
            key: value.strip()
            for key, value in values.items()
            if isinstance(value, str) and value.strip()
        }

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
