from sqlalchemy import distinct, func

from app.models.job_skill_mention import JobSkillMention


class JobSkillMentionRepository:
    def create_mention(
        self,
        db,
        *,
        job_id,
        raw_name,
        normalized_name,
        resolution,
        skill_id=None,
        review_candidate_id=None,
        generic_tag=None,
        source="ai",
        confidence=None,
    ):
        mention = JobSkillMention(
            job_id=job_id,
            raw_name=raw_name,
            normalized_name=normalized_name,
            resolution=resolution,
            skill_id=skill_id,
            review_candidate_id=review_candidate_id,
            generic_tag=generic_tag,
            source=source,
            confidence=confidence,
        )
        db.add(mention)
        db.flush()
        return mention

    def get_mentions_for_job(self, db, job_id):
        return db.query(JobSkillMention).filter_by(job_id=job_id).all()

    def delete_mentions_for_job(self, db, job_id) -> None:
        db.query(JobSkillMention).filter_by(job_id=job_id).delete(synchronize_session=False)
        db.flush()

    def count_jobs_for_review_candidate(self, db, review_candidate_id) -> int:
        count = (
            db.query(func.count(distinct(JobSkillMention.job_id)))
            .filter(JobSkillMention.review_candidate_id == review_candidate_id)
            .scalar()
        )
        return int(count or 0)
