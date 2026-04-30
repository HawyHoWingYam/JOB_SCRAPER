"""
AI Enrichment Service

Orchestrates unified job insight enrichment with batch processing.
"""

import logging
import asyncio
import json
from typing import Optional, List, Dict, Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.job_insight_extractor import get_job_insight_extractor
from app.ai.llm_client import LLMUpstreamError, LLMResponseFormatError
from app.config import settings
from app.models.job import Job
from app.models import JobSubcategory, Skill
from app.database import SessionLocal
from app.repositories.job_skill_repository import JobSkillRepository
from app.services.job_category_normalizer import JobCategoryNormalizer
from app.services.skill_normalizer import SkillNormalizer
from app.services.taxonomy_visibility_service import get_taxonomy_visibility_service
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


class AIEnrichmentService:
    """Orchestrates AI enrichment for jobs."""

    def __init__(self):
        self.settings = settings
        self.insight_extractor = get_job_insight_extractor()
        self.visibility_service = get_taxonomy_visibility_service()
        self.batch_size = 10

    async def enrich_job(self, job: Job, db: Session) -> Dict[str, Any]:
        """Enrich a single job with one AI insight request."""
        results = {"job_id": str(job.id), "status": "success"}

        try:
            skill_normalizer = SkillNormalizer(db)
            job_category_normalizer = JobCategoryNormalizer(db)
            category_candidates = job_category_normalizer.get_taxonomy_candidate_slice(
                source_classification_id=job.source_classification_id,
                source_classification_name=job.source_classification_name,
                source_subclassification_name=job.source_subclassification_name,
            )
            category_candidates["conservative_mode"] = (
                self.settings.job_classification_conservative_mode
            )
            category_candidates["cross_domain_min_confidence"] = (
                self.settings.job_classification_cross_domain_min_confidence
            )
            skill_candidates = skill_normalizer.get_taxonomy_candidate_slice(job.title)
            insight = await self.insight_extractor.extract(
                title=job.title,
                description=job.description or "",
                taxonomy_candidates=category_candidates,
                skill_taxonomy_candidates=skill_candidates,
            )

            classification = insight.get("classification") or {}
            results["classification"] = classification
            extracted_skills = insight.get("skills") or []
            results["skills"] = {
                "skills": extracted_skills,
                "confidence": insight.get("confidence"),
            }

            previous_subcategory_id = job.subcategory_id
            subcategory_id = job_category_normalizer.resolve_taxonomy_decision(
                classification,
                source_classification_id=job.source_classification_id,
                source_classification_name=job.source_classification_name,
                source_subclassification_name=job.source_subclassification_name,
                conservative_mode=self.settings.job_classification_conservative_mode,
                cross_domain_min_confidence=(
                    self.settings.job_classification_cross_domain_min_confidence
                ),
            )
            job.subcategory_id = subcategory_id
            job.ai_enriched_at = utc_now()

            accepted_hierarchy = {}
            if hasattr(job_category_normalizer, "get_category_hierarchy"):
                accepted_hierarchy = (
                    job_category_normalizer.get_category_hierarchy(subcategory_id) or {}
                )

            job.ai_category = (
                self._build_compatibility_category(accepted_hierarchy)
                or classification.get("compatibility_category")
                or classification.get("category")
            )
            job.ai_summary = insight.get("summary")

            experience = insight.get("experience") or {}
            if not isinstance(experience, dict):
                experience = {}
            job.experience_level = experience.get("experience_level") or "not_specified"
            job.experience_min_years = experience.get("experience_min_years")
            job.experience_max_years = experience.get("experience_max_years")
            job.experience_summary = experience.get("summary")
            job.experience_evidence = experience.get("evidence")

            subcategory = db.query(JobSubcategory).filter_by(id=subcategory_id).first()
            if subcategory is not None:
                self.visibility_service.record_job_taxonomy_usage(
                    subcategory,
                    is_distinct_job=previous_subcategory_id != subcategory_id,
                )

            # Update relational tables
            job_skill_repo = JobSkillRepository()
            existing_skill_ids = {
                job_skill.skill_id
                for job_skill in job_skill_repo.get_job_skills(db, job.id)
            }

            for skill_name in extracted_skills:
                skill_id, _, _ = skill_normalizer.normalize_skill(skill_name)
                skill = db.query(Skill).filter_by(id=skill_id).first()

                job_skill_repo.create_job_skill(
                    db,
                    job_id=job.id,
                    skill_id=skill_id,
                    source="ai",
                    confidence=insight.get("confidence"),
                )

                if skill is not None:
                    self.visibility_service.record_skill_usage(
                        skill,
                        is_distinct_job=skill_id not in existing_skill_ids,
                    )
                existing_skill_ids.add(skill_id)

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

    async def enrich_batch(
        self,
        job_ids: List[UUID],
        on_progress: Optional[callable] = None
    ) -> Dict[str, Any]:
        """Backward-compatible alias for enriching an explicit set of job IDs."""
        return await self.enrich_job_ids(job_ids, on_progress)

    async def enrich_job_ids(
        self,
        job_ids: List[UUID],
        on_progress: Optional[callable] = None
    ) -> Dict[str, Any]:
        """Enrich multiple jobs by ID."""
        db = SessionLocal()
        results = {"total": len(job_ids), "success": 0, "failed": 0, "jobs": []}

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

    async def enrich_unenriched(
        self,
        limit: int = 100,
        on_progress: Optional[callable] = None
    ) -> Dict[str, Any]:
        """Enrich jobs that haven't been processed yet."""
        db = SessionLocal()

        try:
            jobs = db.query(Job).filter(
                Job.ai_enriched_at.is_(None),
                Job.is_deleted.is_(False),
                Job.source_classification_id.isnot(None),
                Job.source_classification_id != "",
            ).limit(limit).all()

            job_ids = [job.id for job in jobs]
        finally:
            db.close()

        return await self.enrich_batch(job_ids, on_progress)

    def _build_compatibility_category(self, hierarchy: Dict[str, Any]) -> Optional[str]:
        """Render an accepted taxonomy hierarchy into the legacy ai_category string."""
        parts = [
            hierarchy.get("domain"),
            hierarchy.get("category"),
            hierarchy.get("subcategory"),
        ]
        if not all(parts):
            return None
        return " / ".join(parts)


_service: Optional[AIEnrichmentService] = None

def get_ai_enrichment_service() -> AIEnrichmentService:
    """Get singleton AIEnrichmentService instance."""
    global _service
    if _service is None:
        _service = AIEnrichmentService()
    return _service
