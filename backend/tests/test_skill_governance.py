from __future__ import annotations

import asyncio
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.job_intelligence.skill_governance import (
    SkillCandidateDecisionAdapter,
    SkillCandidateQuery,
    SkillCreateTarget,
    SkillExtractionContext,
    SkillGovernance,
    SkillGovernanceReader,
    SkillGovernanceRebuildInspector,
    SkillTaxonomyPublisher,
    SkillTaxonomyValidationError,
    encode_skill_create_target,
)
from app.job_intelligence.skill_governance.seed import (
    load_skill_seed_bundle,
    skill_seed_content_hash,
)
from app.services.skill_normalizer import normalize_exact_skill_key
from app.services.database_integrity_service import _load_taxonomy_summary
from app.services.enrichment_run_service import EnrichmentRunService
from app.job_intelligence.foundation import DecisionCommand
from app.models.company import Company
from app.models.event_outbox import EventOutbox
from app.models.governance import (
    GOVERNANCE_FOUNDATION_TABLES,
    GovernanceAuditEvent,
    GovernanceIdempotencyRecord,
)
from app.models.job import Job
from app.models.job_category import JobCategory
from app.models.job_domain import JobDomain
from app.models.job_subcategory import JobSubcategory
from app.models.skill_governance import (
    SKILL_GOVERNANCE_TABLES,
    GovernedJobSkill,
    GovernedJobSkillMention,
    GovernedSkill,
    GovernedSkillAlias,
    GovernedSkillCategory,
    GovernedSkillTechnology,
    SkillCandidate,
    SkillTaxonomyActiveRevision,
    SkillTaxonomyRelease,
)
from app.models.source_catalog import (
    SourceCatalogActiveRevision,
    SourceCatalogCandidate,
    SourceCatalogRevision,
)
from app.models.source_job_attributes import SOURCE_JOB_ATTRIBUTE_TABLES
from app.schemas.skill_governance import (
    SkillCandidateDecisionRequestSchema,
    SkillGovernanceFixtureSchema,
)


@pytest.fixture
def skill_governance_db():
    database_url = os.getenv("JOB_INTELLIGENCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("JOB_INTELLIGENCE_TEST_DATABASE_URL is not configured")
    if not database_url.rsplit("/", 1)[-1].endswith("_test"):
        pytest.fail("Skill governance tests require a dedicated *_test database")

    engine = create_engine(database_url)
    tables = (
        JobDomain.__table__,
        JobCategory.__table__,
        JobSubcategory.__table__,
        Company.__table__,
        Job.__table__,
        EventOutbox.__table__,
        SourceCatalogCandidate.__table__,
        SourceCatalogRevision.__table__,
        SourceCatalogActiveRevision.__table__,
        *GOVERNANCE_FOUNDATION_TABLES,
        *SKILL_GOVERNANCE_TABLES,
        *SOURCE_JOB_ATTRIBUTE_TABLES,
    )
    Base.metadata.drop_all(engine, tables=list(reversed(tables)), checkfirst=True)
    Base.metadata.create_all(engine, tables=list(tables))
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(
            engine,
            tables=list(reversed(tables)),
            checkfirst=True,
        )
        engine.dispose()


def _job(db, suffix: str) -> Job:
    company = Company(
        company_id=f"skill-company-{suffix}",
        source_site="jobsdb",
        source_company_id=f"skill-company-{suffix}",
        name=f"Skill Company {suffix}",
    )
    job = Job(
        job_id=f"skill-job-{suffix}",
        source_site="jobsdb",
        source_job_id=f"skill-job-{suffix}",
        company=company,
        title=f"Skill Job {suffix}",
    )
    db.add(job)
    db.commit()
    return job


def _taxonomy_paths(bundle: dict[str, object]) -> set[tuple[str, str, str]]:
    taxonomy = bundle["taxonomy"]
    assert taxonomy["schema_version"] == 1
    assert taxonomy["release_key"] == "skills-2026-07-19-v1"
    assert bundle["rules"]["taxonomy_release_key"] == taxonomy["release_key"]
    assert bundle["backfill"]["taxonomy_release_key"] == taxonomy["release_key"]
    assert isinstance(taxonomy, dict)
    categories = taxonomy["categories"]
    assert isinstance(categories, list)
    return {
        (category["name"], technology["name"], skill["name"])
        for category in categories
        for technology in category["technologies"]
        for skill in technology["skills"]
    }


def test_committed_skill_seed_bundle_is_valid_and_resolves_known_inconsistencies():
    bundle = load_skill_seed_bundle()

    report = SkillTaxonomyPublisher.validate(bundle)

    assert report.to_payload() == {"valid": True, "issues": []}
    taxonomy = bundle["taxonomy"]
    assert taxonomy["expected_counts"] == {
        "categories": 8,
        "technologies": 33,
        "skills": 91,
    }

    categories = taxonomy["categories"]
    technologies = [
        technology for category in categories for technology in category["technologies"]
    ]
    skills = [skill for technology in technologies for skill in technology["skills"]]
    assert (len(categories), len(technologies), len(skills)) == (8, 33, 91)
    assert all(category["code"] for category in categories)
    assert all(technology["code"] for technology in technologies)
    assert all(skill["code"] for skill in skills)
    assert len({category["code"] for category in categories}) == len(categories)
    assert len({technology["code"] for technology in technologies}) == len(technologies)
    assert len({skill["code"] for skill in skills}) == len(skills)

    paths = _taxonomy_paths(bundle)
    assert ("DevOps", "Networking", "Wi-Fi") in paths
    assert ("DevOps", "Security", "PCI DSS") in paths
    assert ("Database", "SQL", "Oracle") in paths

    rules = bundle["rules"]
    aliases = {
        normalize_exact_skill_key(key): value
        for key, value in rules["canonical_aliases"].items()
    }
    assert aliases["vue3"] == "Vue.js"
    assert aliases["vue 3"] == "Vue.js"
    assert "jira" not in {
        normalize_exact_skill_key(value) for value in rules["review_only_terms"]
    }

    entries = bundle["backfill"]["entries"]
    for key in ("jira", "confluence"):
        assert entries[key]["target"] == {
            "category": "Product & Delivery",
            "technology": "Collaboration Tools",
            "skill": key.title(),
        }


def test_skill_seed_validation_accumulates_orphans_collisions_and_rule_overlap():
    invalid = deepcopy(load_skill_seed_bundle())
    first_skill = invalid["taxonomy"]["categories"][0]["technologies"][0]["skills"][0]
    first_skill["aliases"].append("python")
    invalid["rules"]["canonical_aliases"]["missing alias"] = "Missing Skill"
    invalid["rules"]["review_only_terms"].append("Project Management")
    invalid["backfill"]["entries"]["orphan target"] = {
        "action": "merge",
        "target": {
            "category": "Missing",
            "technology": "Missing",
            "skill": "Missing",
        },
    }

    payload = SkillTaxonomyPublisher.validate(invalid).to_payload()

    assert payload["valid"] is False
    assert [issue["code"] for issue in payload["issues"]] == [
        "skill_backfill_target_missing",
        "skill_alias_target_missing",
        "skill_rule_overlap",
        "skill_alias_collision",
    ]
    assert [issue["json_path"] for issue in payload["issues"]] == sorted(
        issue["json_path"] for issue in payload["issues"]
    )


def test_invalid_backfill_target_cannot_materialize_or_create_taxonomy_nodes(
    skill_governance_db,
):
    invalid = deepcopy(load_skill_seed_bundle())
    invalid["backfill"]["entries"]["orphan target"] = {
        "action": "merge",
        "target": {
            "category": "Missing",
            "technology": "Missing",
            "skill": "Missing",
        },
    }

    with pytest.raises(SkillTaxonomyValidationError):
        SkillTaxonomyPublisher(skill_governance_db).materialize(invalid)

    assert (
        skill_governance_db.scalar(
            select(func.count()).select_from(SkillTaxonomyRelease)
        )
        == 0
    )
    assert (
        skill_governance_db.scalar(select(func.count()).select_from(GovernedSkill)) == 0
    )


def test_skill_seed_content_hash_is_deterministic_and_covers_all_three_documents():
    bundle = load_skill_seed_bundle()
    reordered = {
        "backfill": deepcopy(bundle["backfill"]),
        "rules": deepcopy(bundle["rules"]),
        "taxonomy": deepcopy(bundle["taxonomy"]),
    }

    assert skill_seed_content_hash(reordered) == skill_seed_content_hash(bundle)
    assert len(skill_seed_content_hash(bundle)) == 64

    reordered["rules"]["technical_hint_keywords"].append("rust")
    assert skill_seed_content_hash(reordered) != skill_seed_content_hash(bundle)


def test_skill_seed_documents_must_pin_the_same_release_identity():
    invalid = deepcopy(load_skill_seed_bundle())
    invalid["rules"]["taxonomy_release_key"] = "another-release"

    payload = SkillTaxonomyPublisher.validate(invalid).to_payload()

    assert payload["valid"] is False
    assert payload["issues"] == [
        {
            "json_path": "$.rules.taxonomy_release_key",
            "code": "skill_seed_release_mismatch",
            "message": "Skill rules must pin taxonomy release skills-2026-07-19-v1",
            "related_id": "another-release",
            "severity": "error",
        }
    ]


def test_skill_governance_models_register_the_additive_schema():
    assert [table.name for table in SKILL_GOVERNANCE_TABLES] == [
        "skill_taxonomy_releases",
        "skill_taxonomy_active_revisions",
        "governed_skill_categories",
        "governed_skill_technologies",
        "governed_skills",
        "governed_skill_aliases",
        "skill_candidates",
        "governed_job_skill_mentions",
        "governed_job_skills",
    ]


def test_skill_seed_materialization_is_idempotent_complete_and_inactive(
    skill_governance_db,
):
    bundle = load_skill_seed_bundle()
    publisher = SkillTaxonomyPublisher(skill_governance_db)

    first = publisher.materialize(bundle)
    replay = publisher.materialize(bundle)

    assert replay == first
    release = skill_governance_db.get(SkillTaxonomyRelease, first.revision_id)
    assert release is not None
    assert release.status == "ready"
    assert (
        release.materialized_category_count,
        release.materialized_technology_count,
        release.materialized_skill_count,
    ) == (8, 33, 91)
    assert (
        skill_governance_db.scalar(select(func.count()).select_from(GovernedSkill))
        == 91
    )
    assert (
        skill_governance_db.get(SkillTaxonomyActiveRevision, "skill-taxonomy") is None
    )


def test_database_integrity_summary_inventories_governed_skill_state(
    skill_governance_db,
):
    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())
    observed_tables = set(inspect(skill_governance_db.get_bind()).get_table_names())

    taxonomy = _load_taxonomy_summary(skill_governance_db, observed_tables)
    governed = taxonomy["governed_skill"]

    assert taxonomy["legacy_seed"]["seed_table_counts"]["skills"] == 0
    assert governed["available"] is True
    assert governed["table_counts"]["governed_skill_categories"] == 8
    assert governed["table_counts"]["governed_skill_technologies"] == 33
    assert governed["table_counts"]["governed_skills"] == 91
    assert governed["release_status_counts"] == {"ready": 1}
    assert governed["active_revision"] is None
    assert governed["release_count_mismatches"] == []
    assert governed["integrity_issues"] == []

    publisher.activate(revision, expected_lock_version=0)
    governed = _load_taxonomy_summary(
        skill_governance_db,
        observed_tables,
    )["governed_skill"]
    assert governed["active_revision"] == {
        "revision_id": str(revision.revision_id),
        "content_hash": revision.content_hash,
        "lock_version": 1,
        "state": "ready",
    }


def test_skill_revision_activation_uses_compare_and_swap(skill_governance_db):
    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())

    active = publisher.activate(revision, expected_lock_version=0)
    replay = publisher.activate(revision, expected_lock_version=active.lock_version)

    assert active.lock_version == 1
    assert replay.lock_version == 1
    assert replay.revision_id == revision.revision_id

    second_bundle = deepcopy(load_skill_seed_bundle())
    second_bundle["taxonomy"]["release_key"] = "skills-2026-07-19-v2"
    second_bundle["taxonomy"]["source"]["title"] += " v2"
    second_bundle["rules"]["taxonomy_release_key"] = "skills-2026-07-19-v2"
    second_bundle["backfill"]["taxonomy_release_key"] = "skills-2026-07-19-v2"
    second_revision = publisher.materialize(second_bundle)
    switched = publisher.activate(second_revision, expected_lock_version=1)

    assert switched.lock_version == 2
    assert switched.revision_id == second_revision.revision_id


def test_concurrent_first_activation_replays_one_active_pointer(
    skill_governance_db,
):
    revision = SkillTaxonomyPublisher(skill_governance_db).materialize(
        load_skill_seed_bundle()
    )
    session_factory = sessionmaker(
        bind=skill_governance_db.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    barrier = Barrier(2)

    def activate() -> tuple[int, object]:
        db = session_factory()
        try:
            barrier.wait(timeout=5)
            active = SkillTaxonomyPublisher(db).activate(
                revision,
                expected_lock_version=0,
            )
            return active.lock_version, active.revision_id
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: activate(), range(2)))

    assert results == [
        (1, revision.revision_id),
        (1, revision.revision_id),
    ]
    assert (
        skill_governance_db.scalar(
            select(func.count()).select_from(SkillTaxonomyActiveRevision)
        )
        == 1
    )


def test_skill_status_resolution_and_alias_constraints_are_database_enforced(
    skill_governance_db,
):
    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(revision, expected_lock_version=0)
    python = skill_governance_db.scalar(
        select(GovernedSkill).where(GovernedSkill.code == "backend.python.python")
    )
    assert python is not None
    job = _job(skill_governance_db, "constraints")

    candidate = SkillCandidate(
        taxonomy_revision_id=revision.revision_id,
        normalized_key="rust",
        canonical_raw_name="Rust",
        status="pending",
        occurrence_count=1,
        distinct_job_count=1,
        evidence_summary={},
        recommendations=[],
    )
    skill_governance_db.add(candidate)
    skill_governance_db.flush()
    skill_governance_db.add(
        GovernedJobSkillMention(
            job_id=job.id,
            taxonomy_revision_id=revision.revision_id,
            raw_name="Rust",
            normalized_key="rust",
            resolution="match_existing",
            candidate_id=candidate.id,
            evidence_hash="a" * 64,
            provenance={},
        )
    )
    with pytest.raises(IntegrityError):
        skill_governance_db.commit()
    skill_governance_db.rollback()

    skill_governance_db.add(
        SkillCandidate(
            taxonomy_revision_id=revision.revision_id,
            normalized_key="invalid",
            canonical_raw_name="Invalid",
            status="free-string-status",
            occurrence_count=0,
            distinct_job_count=0,
            evidence_summary={},
            recommendations=[],
        )
    )
    with pytest.raises(IntegrityError):
        skill_governance_db.commit()
    skill_governance_db.rollback()

    skill_governance_db.add(
        GovernedSkillAlias(
            taxonomy_revision_id=revision.revision_id,
            skill_id=python.id,
            raw_alias="PYTHON",
            normalized_key="python",
            source="operator",
            source_order=999,
        )
    )
    with pytest.raises(IntegrityError):
        skill_governance_db.commit()
    skill_governance_db.rollback()


def test_governed_skill_references_restrict_silent_deletion(skill_governance_db):
    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(revision, expected_lock_version=0)
    python = skill_governance_db.scalar(
        select(GovernedSkill).where(GovernedSkill.code == "backend.python.python")
    )
    job = _job(skill_governance_db, "delete-restrict")
    skill_governance_db.add_all(
        [
            GovernedJobSkillMention(
                job_id=job.id,
                taxonomy_revision_id=revision.revision_id,
                raw_name="Python",
                normalized_key="python",
                resolution="match_existing",
                skill_id=python.id,
                evidence_hash="b" * 64,
                provenance={},
            ),
            GovernedJobSkill(
                job_id=job.id,
                taxonomy_revision_id=revision.revision_id,
                skill_id=python.id,
                source="deterministic",
                confidence=1.0,
                provenance={},
                mention_count=1,
            ),
        ]
    )
    skill_governance_db.commit()

    skill_governance_db.delete(python)
    with pytest.raises((IntegrityError, ValueError)):
        skill_governance_db.commit()


def test_retired_skill_in_successor_revision_cannot_remain_an_ordinary_match(
    skill_governance_db,
):
    publisher = SkillTaxonomyPublisher(skill_governance_db)
    first = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(first, expected_lock_version=0)
    first_job = _job(skill_governance_db, "retirement-before")
    first_result = SkillGovernance(skill_governance_db).extract(
        first_job.id,
        [{"name": "Python", "kind": "technical"}],
        SkillExtractionContext(
            source="ai-extraction", provenance={"fixture": "before"}
        ),
    )
    skill_governance_db.commit()
    assert first_result.mentions[0].resolution == "match_existing"

    successor = deepcopy(load_skill_seed_bundle())
    successor["taxonomy"]["release_key"] = "skills-2026-07-19-retire-python"
    successor["rules"]["taxonomy_release_key"] = successor["taxonomy"]["release_key"]
    successor["backfill"]["taxonomy_release_key"] = successor["taxonomy"]["release_key"]
    python_seed = next(
        skill
        for category in successor["taxonomy"]["categories"]
        for technology in category["technologies"]
        for skill in technology["skills"]
        if skill["code"] == "backend.python.python"
    )
    python_seed["is_active"] = False
    python_seed["retired_at"] = "2026-07-19T10:00:00Z"
    second = publisher.materialize(successor)
    publisher.activate(second, expected_lock_version=1)
    second_job = _job(skill_governance_db, "retirement-after")

    second_result = SkillGovernance(skill_governance_db).extract(
        second_job.id,
        [{"name": "Python", "kind": "technical"}],
        SkillExtractionContext(source="ai-extraction", provenance={"fixture": "after"}),
    )
    skill_governance_db.commit()

    assert second_result.mentions[0].resolution == "review_candidate"
    assert second_result.mentions[0].skill_id is None
    assert (
        SkillGovernanceReader(skill_governance_db).get_job_state(first_job.id).skills
        == ()
    )


def test_exact_governed_alias_projects_skill_without_candidate_and_replays_noop(
    skill_governance_db,
):
    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(revision, expected_lock_version=0)
    job = _job(skill_governance_db, "exact-alias")
    governance = SkillGovernance(skill_governance_db)
    context = SkillExtractionContext(
        source="ai-extraction",
        confidence=0.91,
        provenance={"model": "fixture", "evidence_id": "exact-alias"},
    )

    first = governance.extract(
        job.id,
        [{"name": "vue3", "kind": "technical"}],
        context,
    )
    skill_governance_db.commit()
    replay = governance.extract(
        job.id,
        [{"name": "vue3", "kind": "technical"}],
        context,
    )
    skill_governance_db.commit()

    assert first.changed is True
    assert replay.changed is False
    assert len(first.mentions) == 1
    assert first.mentions[0].resolution == "match_existing"
    assert first.mentions[0].skill_code == "frontend.javascript.vue-js"
    assert first.mentions[0].candidate_id is None
    assert (
        skill_governance_db.scalar(select(func.count()).select_from(SkillCandidate))
        == 0
    )
    assert (
        skill_governance_db.scalar(select(func.count()).select_from(GovernedJobSkill))
        == 1
    )
    assert (
        skill_governance_db.scalar(select(func.count()).select_from(EventOutbox)) == 1
    )


def test_unknown_technical_evidence_is_never_fuzzy_merged_and_rules_stay_secondary(
    skill_governance_db,
):
    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(revision, expected_lock_version=0)
    job = _job(skill_governance_db, "mixed-evidence")

    result = SkillGovernance(skill_governance_db).extract(
        job.id,
        [
            {"name": "Pythn", "kind": "technical"},
            {"name": "Project Planning", "kind": "generic"},
            {"name": "cloud computing", "kind": "technical"},
        ],
        SkillExtractionContext(source="ai-extraction", provenance={"run": "mixed"}),
    )
    skill_governance_db.commit()

    assert [mention.resolution for mention in result.mentions] == [
        "review_candidate",
        "generic_tag",
        "rejected",
    ]
    candidate = skill_governance_db.scalar(select(SkillCandidate))
    assert candidate is not None
    assert candidate.normalized_key == "pythn"
    assert candidate.status == "pending"
    assert (candidate.occurrence_count, candidate.distinct_job_count) == (1, 1)
    assert result.mentions[0].candidate_id == candidate.id
    assert result.mentions[1].generic_tag == "Project Planning"
    assert result.mentions[2].rejection_reason == "suppressed_review_term"
    assert (
        skill_governance_db.scalar(select(func.count()).select_from(GovernedJobSkill))
        == 0
    )


def test_ai_manual_query_selectors_use_governed_pending_candidates(
    skill_governance_db,
):
    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(revision, expected_lock_version=0)
    job = _job(skill_governance_db, "manual-query-candidate")
    job.source_classification_id = "jobsdb:information-technology"
    job.source_classification_name = "Information Technology"
    job.source_subclassification_name = "Software Development"
    SkillGovernance(skill_governance_db).extract(
        job.id,
        [{"name": "Quantum Mesh", "kind": "technical"}],
        SkillExtractionContext(
            source="ai-extraction",
            provenance={"fixture": "manual-query"},
        ),
    )
    skill_governance_db.commit()

    service = EnrichmentRunService(skill_governance_db)
    selected = service._select_manual_query_job_ids(
        review_candidate_names=["Quantum Mesh"],
        polluted_skill_names=None,
        source_subclassification_names=None,
        scope="all",
    )
    compatibility_selected = service._select_manual_query_job_ids(
        review_candidate_names=None,
        polluted_skill_names=["Quantum Mesh"],
        source_subclassification_names=None,
        scope="all",
    )

    assert selected == [str(job.id)]
    assert compatibility_selected == selected


def test_concurrent_unknown_terms_register_one_candidate_and_two_job_mentions(
    skill_governance_db,
):
    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(revision, expected_lock_version=0)
    jobs = [_job(skill_governance_db, f"concurrent-{index}") for index in range(2)]
    job_ids = [job.id for job in jobs]
    session_factory = sessionmaker(
        bind=skill_governance_db.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    barrier = Barrier(2)

    def extract(job_id):
        db = session_factory()
        try:
            barrier.wait(timeout=5)
            result = SkillGovernance(db).extract(
                job_id,
                [{"name": "Rust", "kind": "technical"}],
                SkillExtractionContext(
                    source="ai-extraction",
                    provenance={"job_id": str(job_id)},
                ),
            )
            db.commit()
            return result.mentions[0].candidate_id
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        candidate_ids = list(executor.map(extract, job_ids))

    skill_governance_db.expire_all()
    candidates = skill_governance_db.scalars(select(SkillCandidate)).all()
    mentions = skill_governance_db.scalars(select(GovernedJobSkillMention)).all()
    assert len(candidates) == 1
    assert len(set(candidate_ids)) == 1
    assert len(mentions) == 2
    assert {mention.job_id for mention in mentions} == set(job_ids)
    assert (candidates[0].occurrence_count, candidates[0].distinct_job_count) == (2, 2)


def test_concurrent_alias_extractions_serialize_one_job_skill_projection(
    skill_governance_db,
):
    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(revision, expected_lock_version=0)
    job = _job(skill_governance_db, "concurrent-projection")
    session_factory = sessionmaker(
        bind=skill_governance_db.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    barrier = Barrier(2)

    def extract(term_and_source: tuple[str, str]) -> None:
        term, source = term_and_source
        db = session_factory()
        try:
            barrier.wait(timeout=5)
            SkillGovernance(db).extract(
                job.id,
                [{"name": term, "kind": "technical"}],
                SkillExtractionContext(
                    source=source,
                    provenance={"fixture": source},
                ),
            )
            db.commit()
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(
            executor.map(
                extract,
                (("Vue.js", "fixture-a"), ("Vue 3", "fixture-b")),
            )
        )

    skill_governance_db.expire_all()
    mentions = skill_governance_db.scalars(
        select(GovernedJobSkillMention).where(
            GovernedJobSkillMention.job_id == job.id,
            GovernedJobSkillMention.status == "active",
        )
    ).all()
    projections = skill_governance_db.scalars(
        select(GovernedJobSkill).where(GovernedJobSkill.job_id == job.id)
    ).all()
    assert len(mentions) == 2
    assert len(projections) == 1
    assert projections[0].mention_count == 2


def _candidate_with_jobs(db, *, term: str, suffix: str, count: int = 2):
    jobs = [_job(db, f"{suffix}-{index}") for index in range(count)]
    governance = SkillGovernance(db)
    for job in jobs:
        governance.extract(
            job.id,
            [{"name": term, "kind": "technical"}],
            SkillExtractionContext(
                source="ai-extraction",
                provenance={"job_id": str(job.id), "fixture": suffix},
            ),
        )
    db.commit()
    candidate = db.scalar(
        select(SkillCandidate).where(
            SkillCandidate.normalized_key == normalize_exact_skill_key(term)
        )
    )
    assert candidate is not None
    return candidate, jobs


def test_merge_existing_decision_atomically_fans_out_and_replays_once(
    skill_governance_db,
):
    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(revision, expected_lock_version=0)
    candidate, jobs = _candidate_with_jobs(
        skill_governance_db,
        term="Rust",
        suffix="merge",
    )
    python = skill_governance_db.scalar(
        select(GovernedSkill).where(GovernedSkill.code == "backend.python.python")
    )
    command = DecisionCommand(
        subject_id=str(candidate.id),
        action="merge_existing",
        target_id=str(python.id),
        expected_version=1,
        idempotency_key="merge-rust-python",
        confirmed=True,
        note="Reviewed exact alias",
    )
    outbox_before = skill_governance_db.scalar(
        select(func.count()).select_from(EventOutbox)
    )

    first = SkillCandidateDecisionAdapter(skill_governance_db).decide(command)
    replay = SkillCandidateDecisionAdapter(skill_governance_db).decide(command)

    assert first.replayed is False
    assert replay.replayed is True
    assert first.audit_event_id == replay.audit_event_id
    skill_governance_db.expire_all()
    resolved = skill_governance_db.get(SkillCandidate, candidate.id)
    assert resolved.status == "resolved_merged"
    assert resolved.lock_version == 2
    assert resolved.resolved_skill_id == python.id
    assert (resolved.occurrence_count, resolved.distinct_job_count) == (0, 0)
    mentions = skill_governance_db.scalars(
        select(GovernedJobSkillMention).where(
            GovernedJobSkillMention.origin_candidate_id == candidate.id,
            GovernedJobSkillMention.status == "active",
        )
    ).all()
    assert len(mentions) == 2
    assert all(mention.resolution == "match_existing" for mention in mentions)
    assert all(mention.skill_id == python.id for mention in mentions)
    assert all(mention.candidate_id is None for mention in mentions)
    assert {
        projection.job_id
        for projection in skill_governance_db.scalars(
            select(GovernedJobSkill).where(GovernedJobSkill.skill_id == python.id)
        )
    } == {job.id for job in jobs}
    reviewed_alias = skill_governance_db.scalar(
        select(GovernedSkillAlias).where(
            GovernedSkillAlias.taxonomy_revision_id == revision.revision_id,
            GovernedSkillAlias.normalized_key == "rust",
        )
    )
    assert reviewed_alias.skill_id == python.id
    assert reviewed_alias.source == "operator"
    assert reviewed_alias.created_by_audit_id == first.audit_event_id
    assert (
        skill_governance_db.scalar(
            select(func.count()).select_from(GovernanceAuditEvent)
        )
        == 1
    )
    assert (
        skill_governance_db.scalar(
            select(func.count()).select_from(GovernanceIdempotencyRecord)
        )
        == 1
    )
    assert (
        skill_governance_db.scalar(select(func.count()).select_from(EventOutbox))
        == outbox_before + len(jobs) + 1
    )


def test_create_skill_decision_creates_only_an_audited_operator_skill(
    skill_governance_db,
):
    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(revision, expected_lock_version=0)
    candidate, jobs = _candidate_with_jobs(
        skill_governance_db,
        term="Rust Lang",
        suffix="create",
    )
    target = SkillCreateTarget(
        category_code="backend",
        technology_code="backend.python",
        stable_code="backend.python.rust",
        name="Rust",
        aliases=("rustlang",),
    )

    result = SkillCandidateDecisionAdapter(skill_governance_db).decide(
        DecisionCommand(
            subject_id=str(candidate.id),
            action="create_skill",
            target_id=encode_skill_create_target(target),
            expected_version=1,
            idempotency_key="create-rust",
            confirmed=True,
        )
    )

    created = skill_governance_db.scalar(
        select(GovernedSkill).where(
            GovernedSkill.revision_id == revision.revision_id,
            GovernedSkill.code == "backend.python.rust",
        )
    )
    assert created is not None
    assert created.origin == "operator"
    assert created.created_by_audit_id == result.audit_event_id
    technology = skill_governance_db.get(GovernedSkillTechnology, created.technology_id)
    category = skill_governance_db.get(GovernedSkillCategory, technology.category_id)
    assert (category.code, technology.code) == ("backend", "backend.python")
    aliases = skill_governance_db.scalars(
        select(GovernedSkillAlias).where(GovernedSkillAlias.skill_id == created.id)
    ).all()
    assert {alias.normalized_key for alias in aliases} == {
        "rust",
        "rustlang",
        "rust lang",
    }
    assert all(alias.created_by_audit_id == result.audit_event_id for alias in aliases)
    resolved = skill_governance_db.get(SkillCandidate, candidate.id)
    assert resolved.status == "resolved_created"
    assert resolved.resolved_skill_id == created.id
    assert {
        projection.job_id
        for projection in skill_governance_db.scalars(
            select(GovernedJobSkill).where(GovernedJobSkill.skill_id == created.id)
        )
    } == {job.id for job in jobs}


@pytest.mark.parametrize(
    ("action", "target_id", "note", "candidate_status", "mention_resolution"),
    [
        (
            "classify_generic",
            "Technical Tooling",
            None,
            "resolved_generic",
            "generic_tag",
        ),
        ("reject", None, "Not a skill", "rejected", "rejected"),
    ],
)
def test_generic_and_reject_decisions_keep_evidence_out_of_governed_projection(
    skill_governance_db,
    action,
    target_id,
    note,
    candidate_status,
    mention_resolution,
):
    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(revision, expected_lock_version=0)
    candidate, _jobs = _candidate_with_jobs(
        skill_governance_db,
        term=f"Mystery {action}",
        suffix=action,
    )

    SkillCandidateDecisionAdapter(skill_governance_db).decide(
        DecisionCommand(
            subject_id=str(candidate.id),
            action=action,
            target_id=target_id,
            expected_version=1,
            idempotency_key=f"decision-{action}",
            confirmed=True,
            note=note,
        )
    )

    resolved = skill_governance_db.get(SkillCandidate, candidate.id)
    assert resolved.status == candidate_status
    assert (resolved.occurrence_count, resolved.distinct_job_count) == (0, 0)
    mentions = skill_governance_db.scalars(
        select(GovernedJobSkillMention).where(
            GovernedJobSkillMention.origin_candidate_id == candidate.id,
            GovernedJobSkillMention.status == "active",
        )
    ).all()
    assert {mention.resolution for mention in mentions} == {mention_resolution}
    assert all(mention.candidate_id is None for mention in mentions)
    if action == "classify_generic":
        assert {mention.generic_tag for mention in mentions} == {target_id}
    else:
        assert {mention.rejection_reason for mention in mentions} == {note}
    assert (
        skill_governance_db.scalar(select(func.count()).select_from(GovernedJobSkill))
        == 0
    )


def test_decision_outbox_failure_rolls_back_candidate_mentions_projection_and_audit(
    skill_governance_db,
):
    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(revision, expected_lock_version=0)
    candidate, _jobs = _candidate_with_jobs(
        skill_governance_db,
        term="Rollback Skill",
        suffix="rollback",
    )
    python = skill_governance_db.scalar(
        select(GovernedSkill).where(GovernedSkill.code == "backend.python.python")
    )

    class FailingOutboxRepository:
        def enqueue(self, *_args, **_kwargs):
            raise RuntimeError("forced decision outbox failure")

    with pytest.raises(RuntimeError, match="forced decision outbox failure"):
        SkillCandidateDecisionAdapter(
            skill_governance_db,
            outbox_repository=FailingOutboxRepository(),
        ).decide(
            DecisionCommand(
                subject_id=str(candidate.id),
                action="merge_existing",
                target_id=str(python.id),
                expected_version=1,
                idempotency_key="rollback-merge",
                confirmed=True,
            )
        )

    skill_governance_db.expire_all()
    pending = skill_governance_db.get(SkillCandidate, candidate.id)
    assert pending.status == "pending"
    assert pending.lock_version == 1
    assert {
        mention.resolution
        for mention in skill_governance_db.scalars(
            select(GovernedJobSkillMention).where(
                GovernedJobSkillMention.candidate_id == candidate.id,
                GovernedJobSkillMention.status == "active",
            )
        )
    } == {"review_candidate"}
    assert (
        skill_governance_db.scalar(
            select(func.count()).select_from(GovernanceAuditEvent)
        )
        == 0
    )
    assert (
        skill_governance_db.scalar(
            select(func.count()).select_from(GovernanceIdempotencyRecord)
        )
        == 0
    )


def test_skill_read_model_separates_governed_and_unreviewed_evidence(
    skill_governance_db,
):
    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(revision, expected_lock_version=0)
    job = _job(skill_governance_db, "read-state")
    SkillGovernance(skill_governance_db).extract(
        job.id,
        [
            {"name": "Vue 3", "kind": "technical"},
            {"name": "Rust", "kind": "technical"},
            {"name": "Project Planning", "kind": "generic"},
            {"name": "cloud computing", "kind": "technical"},
        ],
        SkillExtractionContext(source="ai-extraction", provenance={"fixture": "read"}),
    )
    skill_governance_db.commit()

    reader = SkillGovernanceReader(skill_governance_db)
    active = reader.get_active_revision()
    tree = reader.get_tree()
    state = reader.get_job_state(job.id)
    page = reader.list_candidates(SkillCandidateQuery())
    candidate = page.items[0]
    before = {
        "audit": skill_governance_db.scalar(
            select(func.count()).select_from(GovernanceAuditEvent)
        ),
        "outbox": skill_governance_db.scalar(
            select(func.count()).select_from(EventOutbox)
        ),
    }
    recommendations = reader.recommend(candidate.id, limit=5)

    assert active.id == revision.revision_id
    assert active.counts == {"categories": 8, "technologies": 33, "skills": 91}
    assert len(tree.categories) == 8
    assert {skill.code for skill in state.skills} == {"frontend.javascript.vue-js"}
    assert len(state.unreviewed_skill_mentions) == 1
    assert state.unreviewed_skill_mentions[0].raw_name == "Rust"
    assert state.unreviewed_skill_mentions[0].label == "Unreviewed Skill Mention"
    assert state.unreviewed_skill_mentions[0].candidate_id == candidate.id
    assert page.total == 1
    assert candidate.normalized_key == "rust"
    assert candidate.affected_job_count == 1
    assert candidate.deep_link.endswith(str(candidate.id))
    assert list(recommendations) == sorted(
        recommendations,
        key=lambda item: (
            -item.score,
            item.skill_code,
            item.skill_name,
            str(item.skill_id),
        ),
    )
    assert all(
        recommendation.advisory_only is True for recommendation in recommendations
    )
    assert skill_governance_db.get(SkillCandidate, candidate.id).status == "pending"
    assert before == {
        "audit": skill_governance_db.scalar(
            select(func.count()).select_from(GovernanceAuditEvent)
        ),
        "outbox": skill_governance_db.scalar(
            select(func.count()).select_from(EventOutbox)
        ),
    }


def test_candidate_queue_batches_advisory_recommendations(
    skill_governance_db,
    monkeypatch,
):
    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(revision, expected_lock_version=0)
    _candidate_with_jobs(
        skill_governance_db,
        term="Quantum Mesh",
        suffix="batched-recommendation-a",
        count=1,
    )
    _candidate_with_jobs(
        skill_governance_db,
        term="Neural Fabric",
        suffix="batched-recommendation-b",
        count=1,
    )
    reader = SkillGovernanceReader(skill_governance_db)

    def fail_per_candidate_query(*_args, **_kwargs):
        raise AssertionError("candidate list must not call recommend per item")

    monkeypatch.setattr(reader, "recommend", fail_per_candidate_query)
    page = reader.list_candidates(SkillCandidateQuery())

    assert page.total == 2
    assert len(page.items) == 2
    assert all(item.recommendations for item in page.items)


def test_skill_governance_routes_and_job_detail_use_real_typed_contracts(
    skill_governance_db,
):
    from app.api import router as api_router
    from app.api.jobs import get_job
    from app.api.skill_governance import (
        decide_skill_candidate,
        list_skill_audit_events,
        list_skill_candidates,
        read_job_skills,
        read_skill_candidate,
        read_skill_revision,
        read_skill_tree,
        recommend_skill_candidate,
        search_governed_skills,
    )

    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision_ref = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(revision_ref, expected_lock_version=0)
    job = _job(skill_governance_db, "api-contract")
    SkillGovernance(skill_governance_db).extract(
        job.id,
        [
            {"name": "Vue 3", "kind": "technical"},
            {"name": "Rust", "kind": "technical"},
            {"name": "Project Planning", "kind": "generic"},
            {"name": "cloud computing", "kind": "technical"},
        ],
        SkillExtractionContext(source="ai-extraction", provenance={"fixture": "api"}),
    )
    skill_governance_db.commit()

    revision = read_skill_revision(db=skill_governance_db)
    tree = read_skill_tree(db=skill_governance_db)
    state = read_job_skills(job.id, db=skill_governance_db)
    search = search_governed_skills(
        q="vue3",
        category_code=None,
        technology_code=None,
        limit=100,
        db=skill_governance_db,
    )
    page = list_skill_candidates(
        status=["pending"],
        search=None,
        cursor=None,
        limit=50,
        db=skill_governance_db,
    )
    candidate = read_skill_candidate(page.items[0].id, db=skill_governance_db)
    recommendations = recommend_skill_candidate(
        candidate.id,
        limit=5,
        db=skill_governance_db,
    )
    detail = asyncio.run(get_job(job.id, db=skill_governance_db))

    assert revision.counts.model_dump() == {
        "categories": 8,
        "technologies": 33,
        "skills": 91,
    }
    assert len(tree.categories) == 8
    assert [skill.name for skill in state.skills] == ["Vue.js"]
    assert [mention.raw_name for mention in state.unreviewed_skill_mentions] == ["Rust"]
    assert [skill.code for skill in search.skills] == ["frontend.javascript.vue-js"]
    assert candidate.status == "pending"
    assert all(item.advisory_only is True for item in recommendations)
    assert detail.skills == ["Vue.js"]
    assert detail.provisional_skills == ["Rust"]
    assert [item.raw_name for item in detail.unreviewed_skill_mentions] == ["Rust"]

    fixture = SkillGovernanceFixtureSchema(
        revision=revision,
        tree=tree,
        job_state=state,
        candidate_page=page,
    )
    fixture_payload = fixture.model_dump(mode="json")
    assert (
        SkillGovernanceFixtureSchema.model_validate(fixture_payload).model_dump(
            mode="json"
        )
        == fixture_payload
    )

    decision = decide_skill_candidate(
        candidate.id,
        SkillCandidateDecisionRequestSchema(
            action="classify_generic",
            generic_tag="Programming Language Candidate",
            expected_version=candidate.version,
            idempotency_key="api-generic-rust",
            confirmed=True,
        ),
        db=skill_governance_db,
    )
    audit = list_skill_audit_events(
        subject_id=str(candidate.id),
        cursor=None,
        limit=50,
        db=skill_governance_db,
    )
    assert decision.replayed is False
    assert decision.subject["status"] == "resolved_generic"
    assert len(audit.items) == 1

    route_paths = {route.path for route in api_router.routes}
    assert {
        "/api/v1/job-intelligence/skills/revision",
        "/api/v1/job-intelligence/skills/tree",
        "/api/v1/job-intelligence/skills/search",
        "/api/v1/job-intelligence/jobs/{job_id}/skills",
        "/api/v1/job-intelligence/governance/skills/candidates",
        "/api/v1/job-intelligence/governance/skills/candidates/{candidate_id}",
        "/api/v1/job-intelligence/governance/skills/candidates/{candidate_id}/recommendations",
        "/api/v1/job-intelligence/governance/skills/candidates/{candidate_id}/decision",
        "/api/v1/job-intelligence/governance/skills/audit-events",
    } <= route_paths


def test_skill_routes_return_stable_missing_cursor_confirmation_and_stale_errors(
    skill_governance_db,
):
    from fastapi import HTTPException

    from app.api.skill_governance import (
        decide_skill_candidate,
        list_skill_candidates,
        read_skill_candidate,
        read_skill_revision,
    )

    with pytest.raises(HTTPException) as inactive_info:
        read_skill_revision(db=skill_governance_db)
    assert inactive_info.value.status_code == 404
    assert inactive_info.value.detail["code"] == "SKILL_TAXONOMY_NOT_ACTIVE"

    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(revision, expected_lock_version=0)
    candidate, _jobs = _candidate_with_jobs(
        skill_governance_db,
        term="Stable Error Candidate",
        suffix="stable-errors",
        count=1,
    )

    with pytest.raises(HTTPException) as missing_info:
        read_skill_candidate(uuid4(), db=skill_governance_db)
    assert missing_info.value.status_code == 404
    assert missing_info.value.detail["code"] == "SKILL_CANDIDATE_NOT_FOUND"

    with pytest.raises(HTTPException) as cursor_info:
        list_skill_candidates(
            status=["pending"],
            search=None,
            cursor="not-a-cursor",
            limit=50,
            db=skill_governance_db,
        )
    assert cursor_info.value.status_code == 422
    assert cursor_info.value.detail["code"] == "SKILL_CANDIDATE_CURSOR_INVALID"

    with pytest.raises(HTTPException) as unconfirmed_info:
        decide_skill_candidate(
            candidate.id,
            SkillCandidateDecisionRequestSchema(
                action="reject",
                rejection_reason="Not a Skill",
                expected_version=1,
                idempotency_key="unconfirmed-stable-error",
                confirmed=False,
            ),
            db=skill_governance_db,
        )
    assert unconfirmed_info.value.status_code == 422
    assert unconfirmed_info.value.detail["code"] == "GOVERNANCE_DECISION_UNCONFIRMED"

    with pytest.raises(HTTPException) as stale_info:
        decide_skill_candidate(
            candidate.id,
            SkillCandidateDecisionRequestSchema(
                action="reject",
                rejection_reason="Not a Skill",
                expected_version=999,
                idempotency_key="stale-stable-error",
                confirmed=True,
            ),
            db=skill_governance_db,
        )
    assert stale_info.value.status_code == 409
    assert stale_info.value.detail["code"] == "GOVERNANCE_DECISION_STALE_VERSION"
    assert (
        skill_governance_db.scalar(
            select(func.count()).select_from(GovernanceAuditEvent)
        )
        == 0
    )


def test_skill_governance_backend_contract_fixture_roundtrips_mixed_states():
    fixture_path = (
        Path(__file__).parent / "fixtures" / "skill_governance_responses.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    parsed = SkillGovernanceFixtureSchema.model_validate(fixture)

    assert parsed.model_dump(mode="json") == fixture
    assert [skill.name for skill in parsed.job_state.skills] == ["Python"]
    assert parsed.job_state.unreviewed_skill_mentions[0].label == (
        "Unreviewed Skill Mention"
    )
    assert {item.status for item in parsed.candidate_page.items} == {
        "pending",
        "resolved_generic",
        "rejected",
    }


def test_search_stats_filters_and_embedding_consume_only_active_governed_skills(
    skill_governance_db,
):
    from app.api.filters import (
        get_skill_categories,
        get_skill_technologies,
        get_skills,
    )
    from app.api.job_search_parser import ParsedSearchClause
    from app.api.job_search_query import apply_parsed_clauses
    from app.api.stats import get_skill_stats
    from app.services.embedding_document_builder import EmbeddingDocumentBuilder

    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(revision, expected_lock_version=0)
    governed_job = _job(skill_governance_db, "consumer-governed")
    unresolved_job = _job(skill_governance_db, "consumer-unreviewed")
    governance = SkillGovernance(skill_governance_db)
    governance.extract(
        governed_job.id,
        [{"name": "Vue 3", "kind": "technical"}],
        SkillExtractionContext(
            source="ai-extraction", provenance={"fixture": "consumer"}
        ),
    )
    governance.extract(
        unresolved_job.id,
        [{"name": "Rust", "kind": "technical"}],
        SkillExtractionContext(
            source="ai-extraction", provenance={"fixture": "consumer"}
        ),
    )
    skill_governance_db.commit()

    base_query = skill_governance_db.query(Job).join(Company)
    vue_matches = apply_parsed_clauses(
        base_query,
        [ParsedSearchClause(clause_type="broad", value="Vue.js")],
    ).all()
    rust_matches = apply_parsed_clauses(
        base_query,
        [ParsedSearchClause(clause_type="broad", value="Rust")],
    ).all()
    stats = asyncio.run(
        get_skill_stats(limit=20, category=None, db=skill_governance_db)
    )
    categories = get_skill_categories(db=skill_governance_db)
    frontend_category = next(item for item in categories if item["name"] == "Frontend")
    technologies = get_skill_technologies(
        category_id=frontend_category["id"],
        db=skill_governance_db,
    )
    javascript = next(item for item in technologies if item["name"] == "JavaScript")
    skills = get_skills(
        technology_id=javascript["id"],
        db=skill_governance_db,
    )
    state = SkillGovernanceReader(skill_governance_db).get_job_state(governed_job.id)
    document = EmbeddingDocumentBuilder().build_for_job(
        governed_job,
        governed_skill_names=(skill.name for skill in state.skills),
    )

    assert {job.id for job in vue_matches} == {governed_job.id}
    assert rust_matches == []
    assert stats["skills"] == [
        {
            "name": "Vue.js",
            "category": "Frontend",
            "count": 1,
            "dashboard_bucket": "Frontend",
        }
    ]
    assert any(item["name"] == "Vue.js" for item in skills)
    assert "Skills: Vue.js" in document.document_text
    assert "Rust" not in document.document_text


def test_skill_rebuild_inspector_is_deterministic_read_only_and_reports_differences(
    skill_governance_db,
):
    publisher = SkillTaxonomyPublisher(skill_governance_db)
    revision = publisher.materialize(load_skill_seed_bundle())
    publisher.activate(revision, expected_lock_version=0)
    evidence_job = _job(skill_governance_db, "rebuild-evidence")
    evidence_job.raw_data = {
        "ai_extraction": {
            "skills": [
                {"name": "Vue 3", "kind": "technical"},
                {"name": "Rust", "kind": "technical"},
                {"name": "Project Planning", "kind": "generic"},
                {"name": "cloud computing", "kind": "technical"},
            ]
        }
    }
    no_evidence_job = _job(skill_governance_db, "rebuild-none")
    SkillGovernance(skill_governance_db).extract(
        evidence_job.id,
        [{"name": "Vue 3", "kind": "technical"}],
        SkillExtractionContext(
            source="ai-extraction", provenance={"fixture": "rebuild"}
        ),
    )
    skill_governance_db.commit()
    before = {
        model.__tablename__: skill_governance_db.scalar(
            select(func.count()).select_from(model)
        )
        for model in (
            SkillCandidate,
            GovernedJobSkillMention,
            GovernedJobSkill,
            GovernanceAuditEvent,
            GovernanceIdempotencyRecord,
            EventOutbox,
        )
    }

    inspector = SkillGovernanceRebuildInspector(skill_governance_db)
    first = inspector.inspect([evidence_job.id, no_evidence_job.id]).to_payload()
    second = inspector.inspect([evidence_job.id, no_evidence_job.id]).to_payload()
    after = {
        model.__tablename__: skill_governance_db.scalar(
            select(func.count()).select_from(model)
        )
        for model in (
            SkillCandidate,
            GovernedJobSkillMention,
            GovernedJobSkill,
            GovernanceAuditEvent,
            GovernanceIdempotencyRecord,
            EventOutbox,
        )
    }

    assert first == second
    assert first["mode"] == "read-only"
    assert first["jobs_inspected"] == 2
    assert first["terms_inspected"] == 4
    assert first["outcomes"] == {
        "match_existing": 1,
        "review_candidate": 1,
        "generic_tag": 1,
        "rejected": 1,
    }
    assert first["affected_jobs"] == 1
    assert first["no_preserved_evidence_jobs"] == 1
    evidence_report = next(
        item for item in first["jobs"] if item["job_id"] == str(evidence_job.id)
    )
    assert evidence_report["difference_count"] == 3
    assert before == after


def test_skill_rebuild_cli_rejects_mutating_flags_before_opening_a_session(
    monkeypatch,
):
    import scripts.inspect_skill_governance as script

    monkeypatch.setattr(
        script,
        "SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("session must not open")),
    )
    for forbidden in ("--apply", "--execute", "--activate"):
        with pytest.raises(SystemExit) as exc_info:
            script.main([forbidden])
        assert exc_info.value.code == 2
