from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.skill_governance import GovernedJobSkill, GovernedJobSkillMention


def rebuild_job_skill_projection(
    db: Session,
    *,
    job_id: UUID,
    revision_id: UUID,
) -> bool:
    """Recompute one Job's governed Skill projection from active matched mentions."""

    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"skill-projection:{job_id}"},
        )

    mentions = (
        db.query(GovernedJobSkillMention)
        .filter(
            GovernedJobSkillMention.job_id == job_id,
            GovernedJobSkillMention.taxonomy_revision_id == revision_id,
            GovernedJobSkillMention.status == "active",
            GovernedJobSkillMention.resolution == "match_existing",
            GovernedJobSkillMention.skill_id.is_not(None),
        )
        .order_by(GovernedJobSkillMention.id.asc())
        .all()
    )
    grouped: dict[UUID, list[GovernedJobSkillMention]] = defaultdict(list)
    for mention in mentions:
        grouped[mention.skill_id].append(mention)
    existing = {
        projection.skill_id: projection
        for projection in (
            db.query(GovernedJobSkill)
            .filter(
                GovernedJobSkill.job_id == job_id,
                GovernedJobSkill.taxonomy_revision_id == revision_id,
            )
            .with_for_update()
            .all()
        )
    }
    changed = False
    for skill_id, skill_mentions in grouped.items():
        confidence_values = [
            mention.confidence
            for mention in skill_mentions
            if mention.confidence is not None
        ]
        values = {
            "source": sorted({mention.source for mention in skill_mentions})[0],
            "confidence": max(confidence_values) if confidence_values else None,
            "provenance": {
                "mention_ids": [str(mention.id) for mention in skill_mentions],
                "sources": sorted({mention.source for mention in skill_mentions}),
            },
            "mention_count": len(skill_mentions),
        }
        projection = existing.pop(skill_id, None)
        if projection is None:
            db.add(
                GovernedJobSkill(
                    job_id=job_id,
                    taxonomy_revision_id=revision_id,
                    skill_id=skill_id,
                    **values,
                )
            )
            changed = True
            continue
        if any(getattr(projection, field) != value for field, value in values.items()):
            for field, value in values.items():
                setattr(projection, field, value)
            changed = True
    for projection in existing.values():
        db.delete(projection)
        changed = True
    db.flush()
    return changed
