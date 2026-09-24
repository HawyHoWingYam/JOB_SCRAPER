from __future__ import annotations

from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.current_taxonomy import (
    CurrentTaxonomyAliasRecord,
    CurrentTaxonomyNodeRecord,
)
from app.services.jev_online_skill_case_builder import build_online_skill_case


def _session():
    engine = create_engine("sqlite:///:memory:")
    CurrentTaxonomyNodeRecord.__table__.create(engine)
    CurrentTaxonomyAliasRecord.__table__.create(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    db.add_all(
        (
            CurrentTaxonomyNodeRecord(
                taxonomy="skill",
                code="backend.python",
                parent_code=None,
                level="skill",
                labels={"en": "Python"},
                sort_order=1,
                is_assignable=True,
                is_active=True,
            ),
            CurrentTaxonomyNodeRecord(
                taxonomy="skill",
                code="backend.java",
                parent_code=None,
                level="skill",
                labels={"en": "Java"},
                sort_order=2,
                is_assignable=True,
                is_active=True,
            ),
            CurrentTaxonomyAliasRecord(
                taxonomy="skill",
                node_code="backend.python",
                alias="Py",
                normalized_alias="py",
            ),
        )
    )
    db.flush()
    return engine, db


def test_builder_freezes_taxonomy_and_small_ranked_option_sets() -> None:
    engine, db = _session()
    try:
        case = build_online_skill_case(
            db,
            job_id=uuid4(),
            source_site="jobsdb",
            title="Backend Engineer",
            evidence_text="Python is required.",
            extracted_skills=(
                {
                    "name": "Python",
                    "existing_skill": "Py",
                    "evidence": "Python is required.",
                },
            ),
            option_limit=2,
        )

        assert case is not None
        assert case.rubric_version == "jev-online-skill-v1"
        assert len(case.taxonomy_snapshot_sha256) == 64
        assert case.candidates[0].raw_name == "Python"
        assert case.candidates[0].evidence == "Python is required."
        assert case.candidates[0].options[0].code == "backend.python"
        assert len(case.candidates[0].options) <= 2
    finally:
        db.close()
        engine.dispose()


def test_builder_changes_snapshot_when_alias_changes_and_skips_empty_work() -> None:
    engine, db = _session()
    try:
        job_id = uuid4()
        first = build_online_skill_case(
            db,
            job_id=job_id,
            source_site="jobsdb",
            title="Backend Engineer",
            evidence_text="Use Python.",
            extracted_skills=({"name": "Python"},),
        )
        assert first is not None

        alias = db.get(
            CurrentTaxonomyAliasRecord,
            ("skill", "backend.python", "Py"),
        )
        alias.normalized_alias = "python alias"
        db.flush()
        changed = build_online_skill_case(
            db,
            job_id=job_id,
            source_site="jobsdb",
            title="Backend Engineer",
            evidence_text="Use Python.",
            extracted_skills=({"name": "Python"},),
        )
        assert changed is not None
        assert changed.taxonomy_snapshot_sha256 != first.taxonomy_snapshot_sha256

        assert (
            build_online_skill_case(
                db,
                job_id=job_id,
                source_site="jobsdb",
                title="Backend Engineer",
                evidence_text="No technical Skill is stated.",
                extracted_skills=(),
            )
            is None
        )
    finally:
        db.close()
        engine.dispose()
