from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.job_skill import JobSkill


class JobSkillRepository:
    def create_job_skill(self, db: Session, job_id, skill_id, source='ai', confidence=None) -> JobSkill:
        """Create job-skill association (idempotent)"""
        existing = db.query(JobSkill).filter(
            and_(JobSkill.job_id == job_id, JobSkill.skill_id == skill_id)
        ).first()

        if existing:
            return existing

        job_skill = JobSkill(
            job_id=job_id,
            skill_id=skill_id,
            source=source,
            confidence=confidence
        )
        db.add(job_skill)
        db.flush()
        return job_skill

    def get_job_skills(self, db: Session, job_id) -> List[JobSkill]:
        """Get all skills for a job"""
        return db.query(JobSkill).filter(JobSkill.job_id == job_id).all()

    def delete_obsolete_job_skills(
        self,
        db: Session,
        job_id,
        *,
        keep_skill_ids,
        source: str = "ai",
    ) -> None:
        query = db.query(JobSkill).filter(
            JobSkill.job_id == job_id,
            JobSkill.source == source,
        )
        if keep_skill_ids:
            query = query.filter(~JobSkill.skill_id.in_(list(keep_skill_ids)))
        query.delete(synchronize_session=False)
        db.flush()
