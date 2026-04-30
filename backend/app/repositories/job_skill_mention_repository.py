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
