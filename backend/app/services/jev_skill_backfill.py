from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import exists, select

from app.database import SessionLocal
from app.job_intelligence.current_taxonomies.enrichment import CurrentSkillEnrichment
from app.models.current_taxonomy import CurrentJobSkillMention
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.job import Job
from app.services.jev_evaluator_factory import build_jev_evaluator
from app.services.jev_online_skill_case_builder import build_online_skill_case
from app.services.jev_online_skill_runner import JevOnlineSkillRunner
from app.services.jev_online_skill_store import JevOnlineSkillStore


@dataclass(frozen=True)
class JevSkillBackfillPlan:
    matching_historical_count: int
    eligible_count: int
    already_current_count: int
    reserved_count: int
    no_skill_mentions_count: int
    selected_job_ids: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "matching_historical_count": self.matching_historical_count,
            "eligible_count": self.eligible_count,
            "already_current_count": self.already_current_count,
            "reserved_count": self.reserved_count,
            "no_skill_mentions_count": self.no_skill_mentions_count,
            "selected_item_count": len(self.selected_job_ids),
            "selected_job_ids": list(self.selected_job_ids),
        }


class JevSkillBackfillPlanner:
    """Read-only oldest-first planner for historical Jev Skill work."""

    def __init__(self, db) -> None:
        self.db = db

    def inspect(self, *, limit: int) -> JevSkillBackfillPlan:
        if limit < 1:
            raise ValueError("backfill limit must be positive")
        mention_exists = exists().where(
            CurrentJobSkillMention.job_id == Job.id,
            CurrentJobSkillMention.status == "active",
            CurrentJobSkillMention.resolution.in_(("match_existing", "candidate")),
        )
        jobs = tuple(
            self.db.scalars(
                select(Job)
                .where(Job.is_deleted.is_(False), mention_exists)
                .order_by(Job.created_at, Job.id)
            )
        )
        matching_count = len(jobs)
        selected: list[str] = []
        current_count = 0
        reserved_count = 0
        no_mentions_count = 0
        store = JevOnlineSkillStore(self.db)
        runner = JevOnlineSkillRunner(self.db)
        for job in jobs:
            if self._reserved(job.id):
                reserved_count += 1
                continue
            latest = store.latest_for_job(job.id)
            skills = self._frozen_or_reconstructed_skills(latest, job.id)
            case = build_online_skill_case(
                self.db,
                job_id=job.id,
                source_site=job.source_site,
                title=job.title,
                evidence_text=job.description or "",
                extracted_skills=skills,
            )
            if case is None:
                no_mentions_count += 1
                continue
            current_fingerprint = runner.dispatch(case).input_fingerprint
            if (
                latest is not None
                and latest.input_fingerprint == current_fingerprint
                and latest.status
                in {"pending", "running", "answered", "unavailable", "invalid"}
            ):
                current_count += 1
                continue
            if len(selected) < limit:
                selected.append(str(job.id))
        return JevSkillBackfillPlan(
            matching_historical_count=matching_count,
            eligible_count=matching_count
            - current_count
            - reserved_count
            - no_mentions_count,
            already_current_count=current_count,
            reserved_count=reserved_count,
            no_skill_mentions_count=no_mentions_count,
            selected_job_ids=tuple(selected),
        )

    def _frozen_or_reconstructed_skills(
        self,
        latest,
        job_id: UUID,
    ) -> tuple[dict[str, object], ...]:
        if latest is not None:
            snapshot = latest.evidence_snapshot or {}
            candidates = snapshot.get("candidates")
            if isinstance(candidates, list) and candidates:
                frozen = tuple(
                    {
                        "name": candidate.get("raw_name"),
                        "evidence": candidate.get("evidence"),
                    }
                    for candidate in candidates
                    if isinstance(candidate, dict)
                    and str(candidate.get("raw_name") or "").strip()
                )
                if frozen:
                    return frozen
        return JevSkillBackfillService._reconstruct_skills(self.db, job_id)

    def _reserved(self, job_id: UUID) -> bool:
        return bool(
            self.db.scalar(
                select(EnrichmentRunItem.id)
                .join(EnrichmentRun, EnrichmentRun.id == EnrichmentRunItem.run_id)
                .where(
                    EnrichmentRunItem.job_id == job_id,
                    EnrichmentRun.status.in_(
                        ("waiting", "pending", "running", "stopping")
                    ),
                    EnrichmentRunItem.status.in_(("pending", "running")),
                )
                .limit(1)
            )
        )


class JevSkillBackfillService:
    """Run only Jev Skill classification for a historical Job."""

    async def enrich_job_id(self, job_id: UUID) -> dict[str, Any]:
        db = SessionLocal()
        evaluator = None
        try:
            job = db.get(Job, job_id)
            if job is None:
                return {
                    "job_id": str(job_id),
                    "status": "error",
                    "error": "job not found",
                }
            extracted_skills = self._reconstruct_skills(db, job.id)
            case = build_online_skill_case(
                db,
                job_id=job.id,
                source_site=job.source_site,
                title=job.title,
                evidence_text=job.description or "",
                extracted_skills=extracted_skills,
            )
            if case is None:
                return {
                    "job_id": str(job.id),
                    "status": "excluded",
                    "error": "no_active_skill_mentions",
                    "error_code": "no_active_skill_mentions",
                }
            runner = JevOnlineSkillRunner(db)
            record = runner.start(job_id=job.id, case=case)
            db.commit()
            if record.status not in {"answered", "unavailable", "invalid"}:
                run = runner.runs.get(record.jev_run_id)
                evaluator = build_jev_evaluator(db, run)
                record = await runner.execute(record.id, case=case, evaluator=evaluator)
                db.commit()
            projection_state: dict[str, object] = {
                "state": "preserved",
                "reason": record.error_code or record.status,
            }
            if record.apply_projection:
                projection_state = CurrentSkillEnrichment(db).replace_job_skills(
                    job_id=job.id,
                    extracted_skills=runner.projection_skills(record),
                    confidence=None,
                    provenance={
                        "method": "jev-skill-backfill",
                        "classification_id": record.id,
                        "jev_run_id": record.jev_run_id,
                        "input_fingerprint": record.input_fingerprint,
                        "taxonomy_snapshot_sha256": record.taxonomy_snapshot_sha256,
                        "rubric_version": record.rubric_version,
                        "request_id": (record.receipt or {}).get("request_id"),
                        "provider": (record.receipt or {}).get("provider"),
                        "model": (record.receipt or {}).get("model"),
                    },
                    source="jev-classification",
                )
                db.commit()
            return {
                "job_id": str(job.id),
                "status": "success",
                "jev_skill_classification": {
                    "id": record.id,
                    "status": record.status,
                    "apply_projection": bool(record.apply_projection),
                    "error_code": record.error_code,
                    "jev_run_id": record.jev_run_id,
                },
                "skill_projection": projection_state,
            }
        except Exception as exc:
            db.rollback()
            return {"job_id": str(job_id), "status": "error", "error": str(exc)}
        finally:
            if evaluator is not None:
                await evaluator.aclose()
            db.close()

    @staticmethod
    def _reconstruct_skills(db, job_id: UUID) -> tuple[dict[str, object], ...]:
        mentions = tuple(
            db.scalars(
                select(CurrentJobSkillMention)
                .where(
                    CurrentJobSkillMention.job_id == job_id,
                    CurrentJobSkillMention.status == "active",
                    CurrentJobSkillMention.resolution.in_(
                        ("match_existing", "candidate")
                    ),
                )
                .order_by(CurrentJobSkillMention.created_at, CurrentJobSkillMention.id)
            )
        )
        return tuple(
            {
                "name": mention.raw_name,
                "existing_skill": mention.skill_code,
                "evidence": "Historical active Skill mention; inspect the Job text.",
            }
            for mention in mentions
        )


_service: JevSkillBackfillService | None = None


def get_jev_skill_backfill_service() -> JevSkillBackfillService:
    global _service
    if _service is None:
        _service = JevSkillBackfillService()
    return _service


__all__ = [
    "JevSkillBackfillPlan",
    "JevSkillBackfillPlanner",
    "JevSkillBackfillService",
    "get_jev_skill_backfill_service",
]
