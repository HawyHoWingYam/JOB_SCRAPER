from __future__ import annotations

from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.job_intelligence.current_taxonomies.enrichment import CurrentSkillEnrichment
from app.models.current_taxonomy import (
    CurrentJobSkillAssignment,
    CurrentJobSkillMention,
    CurrentSkillCandidate,
    CurrentTaxonomyAliasRecord,
    CurrentTaxonomyNodeRecord,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    for table in (
        CurrentTaxonomyNodeRecord.__table__,
        CurrentTaxonomyAliasRecord.__table__,
        CurrentJobSkillAssignment.__table__,
        CurrentSkillCandidate.__table__,
        CurrentJobSkillMention.__table__,
    ):
        table.create(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    db.add(
        CurrentTaxonomyNodeRecord(
            taxonomy="skill",
            code="backend.python",
            parent_code=None,
            level="skill",
            labels={"en": "Python"},
            sort_order=1,
            is_assignable=True,
            is_active=True,
        )
    )
    db.flush()
    return engine, db


def test_jev_candidate_route_overrides_exact_name_auto_match() -> None:
    engine, db = _session()
    job_id = uuid4()
    try:
        result = CurrentSkillEnrichment(db).replace_job_skills(
            job_id=job_id,
            extracted_skills=(
                {
                    "name": "Python",
                    "existing_skill": "backend.python",
                    "jev_route": "candidate",
                },
            ),
            confidence=0.78,
            provenance={"method": "jev-online"},
            source="jev-classification",
        )

        assert result["skills"] == []
        assert result["mentions"][0]["resolution"] == "candidate"
        mention = db.scalar(
            select(CurrentJobSkillMention).where(
                CurrentJobSkillMention.job_id == job_id,
                CurrentJobSkillMention.status == "active",
            )
        )
        assert mention.source == "jev-classification"
        assert mention.skill_code is None
        assert mention.candidate_id is not None
        assert db.get(CurrentJobSkillAssignment, (job_id, "backend.python")) is None
    finally:
        db.close()
        engine.dispose()


def test_jev_existing_route_projects_only_active_assignable_code() -> None:
    engine, db = _session()
    job_id = uuid4()
    try:
        result = CurrentSkillEnrichment(db).replace_job_skills(
            job_id=job_id,
            extracted_skills=(
                {
                    "name": "Python language",
                    "existing_skill": "backend.python",
                    "jev_route": "match_existing",
                },
            ),
            confidence=0.97,
            provenance={"method": "jev-online"},
            source="jev-classification",
        )

        assert result["skills"] == [
            {"skill_code": "backend.python", "mention_count": 1}
        ]
        assignment = db.get(
            CurrentJobSkillAssignment,
            (job_id, "backend.python"),
        )
        assert assignment.source == "jev-classification"
        assert assignment.provenance == {"method": "jev-online"}
    finally:
        db.close()
        engine.dispose()


def test_jev_unknown_existing_route_fails_before_false_assignment() -> None:
    engine, db = _session()
    job_id = uuid4()
    try:
        try:
            CurrentSkillEnrichment(db).replace_job_skills(
                job_id=job_id,
                extracted_skills=(
                    {
                        "name": "Invented",
                        "existing_skill": "invented.skill",
                        "jev_route": "match_existing",
                    },
                ),
                confidence=0.99,
                provenance={"method": "jev-online"},
                source="jev-classification",
            )
        except ValueError as error:
            assert "inactive or unknown Skill" in str(error)
        else:
            raise AssertionError("unknown Jev Skill must fail closed")

        assert db.scalar(select(CurrentJobSkillAssignment)) is None
        assert db.scalar(select(CurrentJobSkillMention)) is None
    finally:
        db.close()
        engine.dispose()
