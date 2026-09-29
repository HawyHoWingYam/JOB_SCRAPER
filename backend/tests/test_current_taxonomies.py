from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.api.current_taxonomies import (
    read_job_skills,
    read_skill_tree,
    router as current_taxonomy_router,
)
from app.job_intelligence.current_taxonomies import (
    CurrentJobSkillInput,
    CurrentSkillEnrichment,
    CurrentTaxonomyReader,
    CurrentTaxonomyStore,
    ReplaceCurrentJobSkillsCommand,
    transform_skill_taxonomy,
)
from app.job_intelligence.product_read_model import JobIntelligenceProductReadModel
from app.models.current_taxonomy import (
    CurrentJobSkillAssignment,
    CurrentJobSkillMention,
    CurrentSkillCandidate,
    CurrentTaxonomyAliasRecord,
    CurrentTaxonomyNodeRecord,
)
from app.services.current_embedding_document_builder import (
    CurrentEmbeddingDocumentBuilder,
)
from app.services.classification_domain_adapters import SkillClassificationAdapter


DATA_DIRECTORY = Path(__file__).parents[1] / "app" / "data"


def _load(name: str):
    return json.loads((DATA_DIRECTORY / name).read_text(encoding="utf-8"))


def test_committed_taxonomies_flatten_to_stable_current_codes():
    skill = transform_skill_taxonomy(_load("skill_taxonomy.json"))

    assert len(skill.nodes) == 8 + 43 + 174
    assert len(skill.aliases) == 271
    assert (
        sum(node.level == "skill" and node.is_assignable for node in skill.nodes) == 174
    )

    payload = skill.to_payload()
    assert "version" not in payload
    assert "revision" not in payload
    assert "release" not in payload
    assert len({node.code for node in skill.nodes}) == len(skill.nodes)


def test_current_store_synchronizes_hierarchy_and_aliases_without_revisions():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    for table in (
        CurrentTaxonomyNodeRecord.__table__,
        CurrentTaxonomyAliasRecord.__table__,
    ):
        table.create(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        store = CurrentTaxonomyStore(db)
        snapshot = transform_skill_taxonomy(_load("skill_taxonomy.json"))
        store.synchronize(snapshot)
        store.synchronize(snapshot)

        assert len(store.list_nodes("skill")) == 225
        assert (
            db.scalar(select(func.count()).select_from(CurrentTaxonomyAliasRecord))
            == 271
        )
        react = db.get(
            CurrentTaxonomyNodeRecord, ("skill", "frontend.javascript.react")
        )
        assert react.parent_code == "frontend.javascript"
        assert react.is_assignable is True
        assert not hasattr(react, "revision_id")
    finally:
        db.close()
        engine.dispose()


def test_current_skill_tables_have_no_release_identity():
    tables = (
        CurrentJobSkillAssignment.__table__,
        CurrentSkillCandidate.__table__,
        CurrentJobSkillMention.__table__,
    )
    forbidden = {
        "revision_id",
        "taxonomy_revision_id",
        "mapping_revision_id",
        "lock_version",
        "release_id",
    }

    for table in tables:
        assert forbidden.isdisjoint(table.columns.keys())
        assert any(
            foreign_key.target_fullname.startswith("current_taxonomy_nodes.")
            for foreign_key in table.foreign_keys
        )


def test_current_skill_evidence_keeps_candidates_and_mentions_without_review_versions():
    candidate = CurrentSkillCandidate.__table__
    mention = CurrentJobSkillMention.__table__
    forbidden = {
        "taxonomy_revision_id",
        "revision_id",
        "lock_version",
        "decision_audit_id",
        "recommendations",
    }

    assert forbidden.isdisjoint(candidate.columns.keys())
    assert forbidden.isdisjoint(mention.columns.keys())
    assert {
        "status",
        "suggested_category_code",
        "suggested_technology_code",
    }.isdisjoint(candidate.columns.keys())
    assert {
        "normalized_key",
        "raw_variants",
        "occurrence_count",
        "distinct_job_count",
        "evidence_summary",
    }.issubset(candidate.columns.keys())
    assert {
        "job_id",
        "raw_name",
        "normalized_key",
        "candidate_id",
        "skill_code",
        "provenance",
        "evidence_hash",
    }.issubset(mention.columns.keys())


def test_current_reader_returns_active_job_skills():
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
    job_id = uuid4()
    candidate_id = uuid4()
    try:
        store = CurrentTaxonomyStore(db)
        store.synchronize(transform_skill_taxonomy(_load("skill_taxonomy.json")))
        db.add(
            CurrentJobSkillAssignment(
                job_id=job_id,
                skill_code="frontend.javascript.react",
                taxonomy="skill",
                source="ai_enrichment",
                confidence=0.95,
                provenance={"source": "existing-projection"},
                mention_count=2,
            )
        )
        db.add(
            CurrentSkillCandidate(
                id=candidate_id,
                taxonomy="skill",
                normalized_key="rust",
                canonical_raw_name="Rust",
                raw_variants=["Rust"],
                occurrence_count=1,
                distinct_job_count=1,
                evidence_summary={"source": "ai-extraction"},
            )
        )
        db.add(
            CurrentJobSkillMention(
                job_id=job_id,
                taxonomy="skill",
                raw_name="Rust",
                normalized_key="rust",
                resolution="candidate",
                status="active",
                candidate_id=candidate_id,
                source="ai-extraction",
                confidence=0.82,
                provenance={"run_id": "test-run"},
                evidence_hash="m" * 64,
            )
        )
        db.flush()

        reader = CurrentTaxonomyReader(db)
        skill_state = reader.get_job_skills(job_id)

        assert [skill.name for skill in skill_state.skills] == ["React"]
        assert skill_state.skills[0].mention_count == 2
        assert [mention.raw_name for mention in skill_state.candidate_mentions] == [
            "Rust"
        ]
        assert skill_state.candidate_mentions[0].candidate_id == candidate_id
        assert reader.get_job_skills(uuid4()).skills == ()
        assert reader.get_job_skills(uuid4()).candidate_mentions == ()

        missing_job_id = uuid4()
        skill_states = reader.get_job_skill_states((job_id, missing_job_id))
        assert skill_states[job_id].skills[0].code == "frontend.javascript.react"
        assert skill_states[job_id].candidate_mentions[0].normalized_key == "rust"
        assert skill_states[missing_job_id].skills == ()
        assert skill_states[missing_job_id].candidate_mentions == ()

        product = JobIntelligenceProductReadModel(db)
        skill_payload = product.get_governed_skill_name_states((job_id, missing_job_id))
        serialized = json.dumps(
            list(skill_payload.values()), default=str, sort_keys=True
        )
        assert skill_payload[job_id]["governed_skill_names"] == ["React"]
        assert "revision" not in serialized
        assert "review_item" not in serialized
    finally:
        db.close()
        engine.dispose()


def test_current_skill_enrichment_matches_existing_and_accumulates_candidates():
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
    first_job_id = uuid4()
    second_job_id = uuid4()
    try:
        store = CurrentTaxonomyStore(db)
        store.synchronize(transform_skill_taxonomy(_load("skill_taxonomy.json")))
        enrichment = CurrentSkillEnrichment(db)
        extracted = (
            {"name": "React", "resolution": "match_existing"},
            {"name": "New Framework", "kind": "technical"},
            {"name": "Teamwork", "kind": "generic", "resolution": "drop"},
        )
        for job_id in (first_job_id, second_job_id):
            enrichment.replace_job_skills(
                job_id=job_id,
                extracted_skills=extracted,
                confidence=0.9,
                provenance={"model": "test"},
            )

        candidate = db.scalar(
            select(CurrentSkillCandidate).where(
                CurrentSkillCandidate.normalized_key == "new framework"
            )
        )
        assert candidate.occurrence_count == 2
        assert candidate.distinct_job_count == 2
        assert (
            db.get(
                CurrentJobSkillAssignment,
                (first_job_id, "frontend.javascript.react"),
            )
            is not None
        )
        active_resolutions = set(
            db.scalars(
                select(CurrentJobSkillMention.resolution).where(
                    CurrentJobSkillMention.job_id == first_job_id,
                    CurrentJobSkillMention.status == "active",
                )
            )
        )
        assert active_resolutions == {"match_existing", "candidate", "generic_tag"}

        enrichment.replace_job_skills(
            job_id=first_job_id,
            extracted_skills=({"name": "React"},),
            confidence=0.8,
            provenance={"model": "test"},
        )
        assert candidate.occurrence_count == 1
        assert candidate.distinct_job_count == 1
    finally:
        db.rollback()
        db.close()
        engine.dispose()


def test_operator_skill_decision_survives_later_ai_projection():
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
    job_id = uuid4()
    try:
        store = CurrentTaxonomyStore(db)
        store.synchronize(transform_skill_taxonomy(_load("skill_taxonomy.json")))
        enrichment = CurrentSkillEnrichment(db)
        enrichment.replace_job_skills(
            job_id=job_id,
            extracted_skills=({"name": "New Framework", "kind": "technical"},),
            confidence=0.8,
            provenance={"method": "constrained-ai-extraction"},
        )
        candidate = db.scalar(
            select(CurrentSkillCandidate).where(
                CurrentSkillCandidate.normalized_key == "new framework"
            )
        )

        SkillClassificationAdapter().apply_operator_decision(
            db,
            candidate.id,
            action="reject",
            rejection_reason="too_specific",
        )
        enrichment.replace_job_skills(
            job_id=job_id,
            extracted_skills=(
                {"name": "New Framework", "kind": "technical"},
                {"name": "React", "kind": "technical"},
            ),
            confidence=0.9,
            provenance={"method": "constrained-ai-extraction"},
        )

        active = tuple(
            db.scalars(
                select(CurrentJobSkillMention).where(
                    CurrentJobSkillMention.job_id == job_id,
                    CurrentJobSkillMention.status == "active",
                )
            )
        )
        by_name = {mention.raw_name: mention for mention in active}
        assert set(by_name) == {"New Framework", "React"}
        assert by_name["New Framework"].resolution == "rejected"
        assert by_name["New Framework"].source == "operator-decision"
        assert by_name["New Framework"].rejection_reason == "too_specific"
        assert by_name["React"].resolution == "match_existing"
        assignments = tuple(
            db.scalars(
                select(CurrentJobSkillAssignment).where(
                    CurrentJobSkillAssignment.job_id == job_id
                )
            )
        )
        assert [row.skill_code for row in assignments] == ["frontend.javascript.react"]
    finally:
        db.rollback()
        db.close()
        engine.dispose()


def test_current_jev_correction_survives_only_same_evidence_ai_rerun():
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
    job_id = uuid4()
    try:
        store = CurrentTaxonomyStore(db)
        store.synchronize(transform_skill_taxonomy(_load("skill_taxonomy.json")))
        enrichment = CurrentSkillEnrichment(db)
        enrichment.replace_job_skills(
            job_id=job_id,
            extracted_skills=(
                {
                    "name": "Python",
                    "jev_route": "rejected",
                    "decision_reason": "incidental",
                },
                {
                    "name": "React",
                    "jev_route": "match_existing",
                    "existing_skill": "React",
                },
            ),
            confidence=None,
            provenance={"job_evidence_hash": "a" * 64},
            source="jev-classification",
        )

        enrichment.replace_job_skills(
            job_id=job_id,
            extracted_skills=({"name": "Python", "kind": "technical"},),
            confidence=0.8,
            provenance={"job_evidence_hash": "a" * 64},
            source="ai-extraction",
        )
        same_evidence = tuple(
            db.scalars(
                select(CurrentJobSkillMention).where(
                    CurrentJobSkillMention.job_id == job_id,
                    CurrentJobSkillMention.status == "active",
                )
            )
        )
        assert {row.raw_name: row.resolution for row in same_evidence} == {
            "Python": "rejected",
            "React": "match_existing",
        }

        enrichment.replace_job_skills(
            job_id=job_id,
            extracted_skills=({"name": "Python", "kind": "technical"},),
            confidence=0.9,
            provenance={"job_evidence_hash": "b" * 64},
            source="ai-extraction",
        )
        changed_evidence = tuple(
            db.scalars(
                select(CurrentJobSkillMention).where(
                    CurrentJobSkillMention.job_id == job_id,
                    CurrentJobSkillMention.status == "active",
                )
            )
        )
        assert [
            (row.raw_name, row.resolution, row.source) for row in changed_evidence
        ] == [("Python", "match_existing", "ai-extraction")]
    finally:
        db.rollback()
        db.close()
        engine.dispose()


def test_current_skill_enrichment_resolves_localized_generic_aliases_before_candidates():
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
    job_id = uuid4()
    extracted = tuple(
        {"name": raw_name, "kind": "technical"} for raw_name in ("項目管理", "銷售", "客戶服務")
    )
    try:
        enrichment = CurrentSkillEnrichment(db)

        for _ in range(2):
            enrichment.replace_job_skills(
                job_id=job_id,
                extracted_skills=extracted,
                confidence=0.9,
                provenance={"model": "test"},
            )

        mentions = tuple(
            db.scalars(
                select(CurrentJobSkillMention).where(
                    CurrentJobSkillMention.job_id == job_id,
                    CurrentJobSkillMention.status == "active",
                )
            )
        )
        assert {mention.raw_name: mention.generic_tag for mention in mentions} == {
            "項目管理": "Project Management",
            "銷售": "Sales",
            "客戶服務": "Customer Service",
        }
        assert {mention.resolution for mention in mentions} == {"generic_tag"}
        assert {mention.candidate_id for mention in mentions} == {None}
        assert db.scalar(select(func.count()).select_from(CurrentSkillCandidate)) == 0
        assert (
            db.scalar(select(func.count()).select_from(CurrentJobSkillAssignment)) == 0
        )
    finally:
        db.rollback()
        db.close()
        engine.dispose()


def test_current_store_runtime_writes_have_no_versions():
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
    now = datetime(2026, 7, 26, tzinfo=UTC)
    job_id = uuid4()
    try:
        store = CurrentTaxonomyStore(db)
        store.synchronize(transform_skill_taxonomy(_load("skill_taxonomy.json")))
        store.replace_job_skills(
            ReplaceCurrentJobSkillsCommand(
                job_id=job_id,
                skills=(
                    CurrentJobSkillInput(
                        skill_code="frontend.javascript.react",
                        source="ai_enrichment",
                        confidence=0.95,
                        provenance={},
                        mention_count=2,
                        updated_at=now,
                    ),
                ),
            )
        )

        assert (
            db.get(
                CurrentJobSkillAssignment,
                (job_id, "frontend.javascript.react"),
            ).mention_count
            == 2
        )

        assert db.in_transaction() is True
    finally:
        db.rollback()
        db.close()
        engine.dispose()


def test_current_taxonomy_api_contract_has_no_revision_or_review_routes():
    paths = {route.path for route in current_taxonomy_router.routes}

    assert paths == {
        "/job-intelligence/skills/tree",
        "/job-intelligence/jobs/{job_id}/skills",
    }
    assert all("revision" not in path for path in paths)
    assert all("governance" not in path for path in paths)
    assert all("review" not in path for path in paths)


def test_current_taxonomy_api_serializes_only_current_state():
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
    now = datetime(2026, 7, 26, tzinfo=UTC)
    job_id = uuid4()
    try:
        store = CurrentTaxonomyStore(db)
        store.synchronize(transform_skill_taxonomy(_load("skill_taxonomy.json")))
        store.replace_job_skills(
            ReplaceCurrentJobSkillsCommand(
                job_id=job_id,
                skills=(
                    CurrentJobSkillInput(
                        skill_code="frontend.javascript.react",
                        source="ai_enrichment",
                        confidence=0.9,
                        provenance={},
                        mention_count=1,
                        updated_at=now,
                    ),
                ),
            )
        )

        payloads = (
            read_skill_tree(db),
            read_job_skills(job_id, db),
        )
        serialized = [payload.model_dump(mode="json") for payload in payloads]
        text = json.dumps(serialized, sort_keys=True)

        assert '"taxonomy_revision_id"' not in text
        assert '"revision"' not in text
        assert '"release"' not in text
        assert '"version"' not in text
        assert '"review_item_refs"' not in text
        assert serialized[-1]["skills"][0]["name"] == "React"

        embedding = CurrentEmbeddingDocumentBuilder().build_for_job(
            db,
            SimpleNamespace(
                id=job_id,
                title="Backend Engineer",
                company=SimpleNamespace(name="Example Company"),
                source_classification_name="Information Technology",
                source_subclassification_name=None,
                ai_summary="Build reliable services",
                description="Python and React",
            ),
        )
        assert embedding.document_text == "Python and React"
        assert "Revision" not in embedding.document_text
        assert "version" not in embedding.document_text.lower()

        same_description = CurrentEmbeddingDocumentBuilder().build_for_job(
            db,
            SimpleNamespace(
                id=job_id,
                title="A title that must not affect the embedding",
                company=SimpleNamespace(name="A different company"),
                source_classification_name="A different classification",
                source_subclassification_name=None,
                ai_summary="A different summary",
                description="Python and React",
            ),
        )
        assert same_description == embedding
    finally:
        db.rollback()
        db.close()
        engine.dispose()
