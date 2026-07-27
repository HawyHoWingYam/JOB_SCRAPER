from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.api.current_taxonomies import (
    read_company_industry_state,
    read_company_industry_tree,
    read_job_skills,
    read_job_taxonomy_state,
    read_job_taxonomy_tree,
    read_skill_tree,
    router as current_taxonomy_router,
)
from app.job_intelligence.current_taxonomies import (
    AssignCurrentJobTaxonomyCommand,
    build_preservation_manifest,
    CurrentCompanyIndustryInput,
    CurrentJobSkillInput,
    CurrentTaxonomyEnrichment,
    CurrentTaxonomyPreservationLoader,
    CurrentTaxonomyReader,
    CurrentTaxonomyStore,
    ReplaceCurrentCompanyIndustriesCommand,
    ReplaceCurrentJobSkillsCommand,
    project_current_company_industry,
    transform_company_industry_taxonomy,
    transform_job_taxonomy,
    transform_skill_taxonomy,
)
from app.job_intelligence.current_taxonomies.preservation import (
    PersistedTaxonomyPreservationSnapshot,
    PreservedCompanyIndustryAssignment,
    PreservedJobSkillAssignment,
    PreservedJobSkillMentionEvidence,
    PreservedJobTaxonomyAssignment,
    PreservedSkillCandidateEvidence,
    PreservedSourceTaxonomyMapping,
)
from app.job_intelligence.product_read_model import JobIntelligenceProductReadModel
from app.models.current_taxonomy import (
    CurrentCompanyIndustryAssignment,
    CurrentJobSkillMention,
    CurrentJobSkillAssignment,
    CurrentJobTaxonomyAssignment,
    CurrentSkillCandidate,
    CurrentSourceTaxonomyMapping,
    CurrentTaxonomyAliasRecord,
    CurrentTaxonomyNodeRecord,
)
from app.models.event_outbox import EventOutbox
from app.services.current_embedding_document_builder import (
    CurrentEmbeddingDocumentBuilder,
)


DATA_DIRECTORY = Path(__file__).parents[1] / "app" / "data"


def _load(name: str):
    return json.loads((DATA_DIRECTORY / name).read_text(encoding="utf-8"))


def test_committed_taxonomies_flatten_to_stable_current_codes():
    job = transform_job_taxonomy(_load("job_category_taxonomy.json"))
    industry = transform_company_industry_taxonomy(_load("hsic_v2.json"))
    skill = transform_skill_taxonomy(_load("skill_taxonomy.json"))

    assert len(job.nodes) == 25 + 63 + 198
    assert sum(node.level == "subcategory" and node.is_assignable for node in job.nodes) == 198
    assert len(industry.nodes) == 21 + 88 + 221 + 483 + 1001
    assert sum(node.level == "subclass" and node.is_assignable for node in industry.nodes) == 1001
    assert len(skill.nodes) == 8 + 33 + 91
    assert len(skill.aliases) == 142
    assert sum(node.level == "skill" and node.is_assignable for node in skill.nodes) == 91

    for snapshot in (job, industry, skill):
        payload = snapshot.to_payload()
        assert "version" not in payload
        assert "revision" not in payload
        assert "release" not in payload
        assert len({node.code for node in snapshot.nodes}) == len(snapshot.nodes)


def test_preservation_manifest_maps_legacy_ids_only_to_current_codes():
    snapshot = transform_job_taxonomy(_load("job_category_taxonomy.json"))
    manifest = build_preservation_manifest(
        snapshot,
        {
            "legacy-domain-uuid": "information_communication_technology",
            "legacy-subcategory-uuid": (
                "information_communication_technology.software_development.backend_development"
            ),
        },
    )

    assert manifest.to_payload() == {
        "taxonomy": "job",
        "node_count": 286,
        "legacy_identity_to_code": {
            "legacy-domain-uuid": "information_communication_technology",
            "legacy-subcategory-uuid": (
                "information_communication_technology.software_development.backend_development"
            ),
        },
    }
    with pytest.raises(ValueError, match="Unknown current job taxonomy code"):
        build_preservation_manifest(snapshot, {"legacy": "missing.code"})


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

        assert len(store.list_nodes("skill")) == 132
        assert db.scalar(select(func.count()).select_from(CurrentTaxonomyAliasRecord)) == 142
        react = db.get(CurrentTaxonomyNodeRecord, ("skill", "frontend.javascript.react"))
        assert react.parent_code == "frontend.javascript"
        assert react.is_assignable is True
        assert not hasattr(react, "revision_id")
    finally:
        db.close()
        engine.dispose()


def test_current_assignment_and_mapping_tables_have_no_release_identity():
    tables = (
        CurrentJobTaxonomyAssignment.__table__,
        CurrentCompanyIndustryAssignment.__table__,
        CurrentJobSkillAssignment.__table__,
        CurrentSkillCandidate.__table__,
        CurrentJobSkillMention.__table__,
        CurrentSourceTaxonomyMapping.__table__,
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


def test_source_mapping_is_optional_and_only_constrains_when_present():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    for table in (
        CurrentTaxonomyNodeRecord.__table__,
        CurrentTaxonomyAliasRecord.__table__,
        CurrentSourceTaxonomyMapping.__table__,
    ):
        table.create(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        store = CurrentTaxonomyStore(db)
        store.synchronize(transform_job_taxonomy(_load("job_category_taxonomy.json")))

        fallback = store.resolve_allowed_codes(
            "job",
            source_site="jobsdb",
            source_key="jobsdb:new-category",
        )
        assert len(fallback) == 198

        target = (
            "information_communication_technology."
            "software_development.backend_development"
        )
        db.add(
            CurrentSourceTaxonomyMapping(
                taxonomy="job",
                source_site="jobsdb",
                source_key="jobsdb:6281",
                target_code=target,
                source_label="Information Technology",
                role="deterministic",
                evidence={},
            )
        )
        db.flush()
        assert store.resolve_allowed_codes(
            "job",
            source_site="jobsdb",
            source_key="jobsdb:6281",
        ) == (target,)
    finally:
        db.close()
        engine.dispose()


def test_current_reader_expands_big_job_categories_to_assignable_children():
    engine = create_engine("sqlite:///:memory:")
    for table in (
        CurrentTaxonomyNodeRecord.__table__,
        CurrentTaxonomyAliasRecord.__table__,
    ):
        table.create(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        CurrentTaxonomyStore(db).synchronize(
            transform_job_taxonomy(_load("job_category_taxonomy.json"))
        )
        reader = CurrentTaxonomyReader(db)

        tree = reader.get_tree("job")
        codes = reader.resolve_assignable_codes(
            "job",
            ("information_communication_technology",),
        )

        assert len(tree.nodes) == 286
        assert codes
        assert all(code.startswith("information_communication_technology.") for code in codes)
        assert (
            "information_communication_technology."
            "software_development.backend_development"
        ) in codes
    finally:
        db.close()
        engine.dispose()


def test_current_reader_returns_job_state_and_unversioned_embedding_document():
    engine = create_engine("sqlite:///:memory:")
    for table in (
        CurrentTaxonomyNodeRecord.__table__,
        CurrentTaxonomyAliasRecord.__table__,
        CurrentJobTaxonomyAssignment.__table__,
    ):
        table.create(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    job_id = uuid4()
    try:
        CurrentTaxonomyStore(db).synchronize(
            transform_job_taxonomy(_load("job_category_taxonomy.json"))
        )
        target = (
            "information_communication_technology."
            "software_development.backend_development"
        )
        breadcrumb = {
            "domain": {
                "code": "information_communication_technology",
                "label": "Information & Communication Technology",
            },
            "category": {
                "code": "information_communication_technology.software_development",
                "label": "Software Development",
            },
            "subcategory": {"code": target, "label": "Backend Development"},
        }
        db.add(
            CurrentJobTaxonomyAssignment(
                job_id=job_id,
                taxonomy="job",
                taxonomy_code=target,
                method="ai",
                evidence_hash="e" * 64,
                source_evidence_refs=[],
                mapping_ids=[],
                model_provenance={"model": "test"},
                breadcrumb=breadcrumb,
            )
        )
        db.flush()

        reader = CurrentTaxonomyReader(db)
        state = reader.get_job_taxonomy_state(job_id)
        document = reader.build_job_taxonomy_embedding_document(job_id)

        assert state.state == "assigned"
        assert state.assignment is not None
        assert state.assignment.taxonomy_code == target
        assert document is not None
        assert document.taxonomy_code == target
        assert "Assignment Method: ai" in document.document_text
        assert "Revision" not in document.document_text
        assert "version" not in document.document_text.lower()
        assert not hasattr(document, "taxonomy_revision_id")

        unassigned_id = uuid4()
        assert reader.get_job_taxonomy_state(unassigned_id).state == "unassigned"
        assert reader.build_job_taxonomy_embedding_document(unassigned_id) is None
        states = reader.get_job_taxonomy_states((job_id, unassigned_id))
        assert states[job_id].state == "assigned"
        assert states[unassigned_id].state == "unassigned"
        payloads = JobIntelligenceProductReadModel(db).get_canonical_job_states(
            (job_id, unassigned_id)
        )
        serialized = json.dumps(list(payloads.values()), default=str, sort_keys=True)
        assert payloads[job_id]["canonical_taxonomy"]["assignment"][
            "taxonomy_code"
        ] == target
        assert "revision" not in serialized
        assert "review_item" not in serialized
    finally:
        db.close()
        engine.dispose()


def test_current_reader_returns_company_assignments_and_active_job_skills():
    engine = create_engine("sqlite:///:memory:")
    for table in (
        CurrentTaxonomyNodeRecord.__table__,
        CurrentTaxonomyAliasRecord.__table__,
        CurrentCompanyIndustryAssignment.__table__,
        CurrentJobSkillAssignment.__table__,
        CurrentSkillCandidate.__table__,
        CurrentJobSkillMention.__table__,
    ):
        table.create(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    company_id = uuid4()
    job_id = uuid4()
    candidate_id = uuid4()
    try:
        store = CurrentTaxonomyStore(db)
        store.synchronize(transform_company_industry_taxonomy(_load("hsic_v2.json")))
        store.synchronize(transform_skill_taxonomy(_load("skill_taxonomy.json")))
        industry_code = next(
            node.code
            for node in store.list_nodes("company_industry")
            if node.is_assignable
        )
        db.add(
            CurrentCompanyIndustryAssignment(
                company_id=company_id,
                taxonomy="company_industry",
                taxonomy_code=industry_code,
                method="accepted",
                provenance={"source": "existing-assignment"},
                evidence_hash="i" * 64,
                breadcrumb={"subclass": {"code": industry_code, "label": "Industry"}},
                is_primary=True,
                primary_basis="accepted",
            )
        )
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
        company_state = reader.get_company_industry_state(company_id)
        skill_state = reader.get_job_skills(job_id)

        assert len(company_state.assignments) == 1
        assert company_state.assignments[0].is_primary is True
        assert company_state.assignments[0].taxonomy_code == industry_code
        assert [skill.name for skill in skill_state.skills] == ["React"]
        assert skill_state.skills[0].mention_count == 2
        assert [mention.raw_name for mention in skill_state.candidate_mentions] == [
            "Rust"
        ]
        assert skill_state.candidate_mentions[0].candidate_id == candidate_id
        assert reader.get_company_industry_state(uuid4()).assignments == ()
        assert reader.get_job_skills(uuid4()).skills == ()
        assert reader.get_job_skills(uuid4()).candidate_mentions == ()

        missing_company_id = uuid4()
        missing_job_id = uuid4()
        company_states = reader.get_company_industry_states(
            (company_id, missing_company_id)
        )
        skill_states = reader.get_job_skill_states((job_id, missing_job_id))
        assert company_states[company_id].assignments[0].taxonomy_code == industry_code
        assert company_states[missing_company_id].assignments == ()
        assert skill_states[job_id].skills[0].code == "frontend.javascript.react"
        assert skill_states[job_id].candidate_mentions[0].normalized_key == "rust"
        assert skill_states[missing_job_id].skills == ()
        assert skill_states[missing_job_id].candidate_mentions == ()

        product = JobIntelligenceProductReadModel(db)
        company_payload = product.get_company_details(
            (company_id, missing_company_id)
        )
        skill_payload = product.get_governed_skill_name_states(
            (job_id, missing_job_id)
        )
        serialized = json.dumps(
            {
                "companies": list(company_payload.values()),
                "skills": list(skill_payload.values()),
            },
            default=str,
            sort_keys=True,
        )
        assert company_payload[company_id]["company_industries"]["assignments"][0][
            "taxonomy_code"
        ] == industry_code
        assert skill_payload[job_id]["governed_skill_names"] == ["React"]
        assert "revision" not in serialized
        assert "review_item" not in serialized
    finally:
        db.close()
        engine.dispose()


def test_preservation_loader_remaps_active_rows_without_revision_or_review_state():
    db = MagicMock()
    job_revision = uuid4()
    company_revision = uuid4()
    skill_revision = uuid4()
    db.get.side_effect = (
        SimpleNamespace(revision_id=job_revision),
        SimpleNamespace(revision_id=company_revision),
        SimpleNamespace(revision_id=skill_revision),
        SimpleNamespace(mapping_revision_id=uuid4()),
    )
    now = datetime(2026, 7, 26, tzinfo=UTC)
    job_id = uuid4()
    company_id = uuid4()
    candidate_id = uuid4()
    job_code = "information_communication_technology.software_development.backend_development"
    company_code = "6201"
    skill_code = "frontend.javascript.react"

    job_assignment = SimpleNamespace(
        id=uuid4(),
        job_id=job_id,
        method="constrained_ai",
        evidence_hash="a" * 64,
        source_evidence_refs=[{"kind": "source"}],
        mapping_ids=[str(uuid4())],
        model_provider="openai",
        model_name="test-model",
        model_version=None,
        breadcrumb={"subcategory": {"code": job_code}},
        captured_at=now,
    )
    company_assignment = SimpleNamespace(
        id=uuid4(),
        company_id=company_id,
        method="operator",
        provenance={"source": "accepted"},
        evidence_hash="b" * 64,
        breadcrumb={"subclass": {"code": company_code}},
        is_primary=True,
        primary_basis="operator",
        captured_at=now,
    )
    skill_assignment = SimpleNamespace(
        id=uuid4(),
        job_id=job_id,
        source="ai_enrichment",
        confidence=0.9,
        provenance={"source": "mention"},
        mention_count=2,
        updated_at=now,
    )
    candidate = SimpleNamespace(
        id=candidate_id,
        normalized_key="new framework",
        canonical_raw_name="New Framework",
        raw_variants=["New Framework", "new-framework"],
        occurrence_count=5,
        distinct_job_count=4,
        evidence_summary={"jobs": 4},
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )
    mention = SimpleNamespace(
        id=uuid4(),
        job_id=job_id,
        raw_name="New Framework",
        normalized_key="new framework",
        resolution="review_candidate",
        status="active",
        candidate_id=candidate_id,
        origin_candidate_id=None,
        generic_tag=None,
        rejection_reason=None,
        source="ai-extraction",
        confidence=0.8,
        provenance={"source": "description"},
        evidence_hash="c" * 64,
        created_at=now,
        updated_at=now,
        superseded_at=None,
    )
    legacy_skill_id = uuid4()
    audit = SimpleNamespace(
        id=uuid4(),
        domain="skill-governance",
        subject_type="skill-candidate",
        subject_id=str(candidate_id),
        action="merge",
        actor="local-operator",
        command_hash="d" * 64,
        idempotency_key="skill-candidate:test",
        before_summary={
            "taxonomy_revision_id": str(skill_revision),
            "version": 1,
            "model_version": "test-model-v1",
        },
        after_summary={
            "skill_id": str(legacy_skill_id),
            "version": 2,
        },
        evidence_refs=[
            {"kind": "skill-mention", "id": str(mention.id), "revision_id": "old"}
        ],
        correlation_id="test-correlation",
        created_at=now,
    )
    job_mapping = SimpleNamespace(
        source_site="jobsdb",
        source_classification_id="jobsdb:6281",
        source_label="Information Technology",
        review_evidence={"accepted": True},
    )
    company_mapping = SimpleNamespace(
        source_site="jobsdb",
        key_kind="code",
        normalized_key="6201",
        raw_value="6201",
    )
    db.scalars.return_value = [audit]
    db.execute.side_effect = (
        [(job_assignment, SimpleNamespace(code=job_code))],
        [(company_assignment, SimpleNamespace(code=company_code))],
        [(skill_assignment, SimpleNamespace(code=skill_code))],
        [(candidate, None)],
        [(mention, None)],
        [
            (
                job_mapping,
                SimpleNamespace(role="deterministic"),
                SimpleNamespace(code=job_code),
            )
        ],
        [(company_mapping, SimpleNamespace(code=company_code))],
    )

    snapshot = CurrentTaxonomyPreservationLoader(db).load(
        current_job_codes={job_code},
        current_company_codes={company_code},
        current_skill_codes={skill_code},
        legacy_identity_to_code={str(legacy_skill_id): skill_code},
    )

    assert snapshot.job_assignments[0].taxonomy_code == job_code
    assert snapshot.job_assignments[0].model_provenance == {
        "provider": "openai",
        "name": "test-model",
    }
    assert snapshot.company_assignments[0].taxonomy_code == company_code
    assert snapshot.skill_assignments[0].skill_code == skill_code
    assert snapshot.skill_candidates[0].occurrence_count == 5
    assert snapshot.skill_mentions[0].resolution == "candidate"
    assert {
        (row.taxonomy, row.source_site, row.source_key, row.target_code)
        for row in snapshot.source_mappings
    } == {
        ("job", "jobsdb", "jobsdb:6281", job_code),
        ("company_industry", "jobsdb", "code:6201", company_code),
    }
    assert snapshot.audit_events[0].before_summary == {
        "model_version": "test-model-v1"
    }
    assert snapshot.audit_events[0].after_summary == {"skill_code": skill_code}
    assert snapshot.audit_events[0].evidence_refs == [
        {"kind": "skill-mention", "id": str(mention.id)}
    ]
    for row in (
        snapshot.job_assignments[0],
        snapshot.company_assignments[0],
        snapshot.skill_assignments[0],
        snapshot.skill_candidates[0],
        snapshot.skill_mentions[0],
    ):
        assert not hasattr(row, "taxonomy_revision_id")
        assert not hasattr(row, "lock_version")
        assert not hasattr(row, "recommendations")


def test_current_store_materializes_preserved_rows_without_committing():
    engine = create_engine("sqlite:///:memory:")
    for table in (
        CurrentTaxonomyNodeRecord.__table__,
        CurrentTaxonomyAliasRecord.__table__,
        CurrentJobTaxonomyAssignment.__table__,
        CurrentCompanyIndustryAssignment.__table__,
        CurrentJobSkillAssignment.__table__,
        CurrentSkillCandidate.__table__,
        CurrentJobSkillMention.__table__,
        CurrentSourceTaxonomyMapping.__table__,
    ):
        table.create(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    now = datetime(2026, 7, 26, tzinfo=UTC)
    job_id = uuid4()
    company_id = uuid4()
    candidate_id = uuid4()
    mention_id = uuid4()
    job_code = "information_communication_technology.software_development.backend_development"
    company_snapshot = transform_company_industry_taxonomy(_load("hsic_v2.json"))
    company_code = next(node.code for node in company_snapshot.nodes if node.is_assignable)
    skill_code = "frontend.javascript.react"
    try:
        store = CurrentTaxonomyStore(db)
        store.synchronize(transform_job_taxonomy(_load("job_category_taxonomy.json")))
        store.synchronize(company_snapshot)
        store.synchronize(transform_skill_taxonomy(_load("skill_taxonomy.json")))
        snapshot = PersistedTaxonomyPreservationSnapshot(
            job_assignments=(
                PreservedJobTaxonomyAssignment(
                    legacy_assignment_id=uuid4(),
                    job_id=job_id,
                    taxonomy_code=job_code,
                    method="constrained_ai",
                    evidence_hash="a" * 64,
                    source_evidence_refs=[{"kind": "source"}],
                    mapping_ids=[],
                    model_provenance={"name": "test-model"},
                    breadcrumb={"subcategory": {"code": job_code}},
                    captured_at=now,
                ),
            ),
            company_assignments=(
                PreservedCompanyIndustryAssignment(
                    legacy_assignment_id=uuid4(),
                    company_id=company_id,
                    taxonomy_code=company_code,
                    method="operator",
                    provenance={"source": "accepted"},
                    evidence_hash="b" * 64,
                    breadcrumb={"subclass": {"code": company_code}},
                    is_primary=True,
                    primary_basis="operator",
                    captured_at=now,
                ),
            ),
            skill_assignments=(
                PreservedJobSkillAssignment(
                    legacy_projection_id=uuid4(),
                    job_id=job_id,
                    skill_code=skill_code,
                    source="ai_enrichment",
                    confidence=0.9,
                    provenance={"source": "mention"},
                    mention_count=1,
                    updated_at=now,
                ),
            ),
            skill_candidates=(
                PreservedSkillCandidateEvidence(
                    id=candidate_id,
                    normalized_key="new framework",
                    canonical_raw_name="New Framework",
                    raw_variants=["New Framework"],
                    occurrence_count=3,
                    distinct_job_count=2,
                    evidence_summary={"jobs": 2},
                    resolved_skill_code=None,
                    first_seen_at=now,
                    last_seen_at=now,
                    created_at=now,
                    updated_at=now,
                ),
            ),
            skill_mentions=(
                PreservedJobSkillMentionEvidence(
                    id=mention_id,
                    job_id=job_id,
                    raw_name="New Framework",
                    normalized_key="new framework",
                    resolution="candidate",
                    status="active",
                    skill_code=None,
                    candidate_id=candidate_id,
                    origin_candidate_id=None,
                    generic_tag=None,
                    rejection_reason=None,
                    source="ai-extraction",
                    confidence=0.8,
                    provenance={"source": "description"},
                    evidence_hash="c" * 64,
                    created_at=now,
                    updated_at=now,
                    superseded_at=None,
                ),
            ),
            source_mappings=(
                PreservedSourceTaxonomyMapping(
                    taxonomy="job",
                    source_site="jobsdb",
                    source_key="jobsdb:6281",
                    target_code=job_code,
                    source_label="Information Technology",
                    role="deterministic",
                    evidence={"accepted": True},
                ),
            ),
        )

        store.replace_preserved_rows(snapshot)

        assert db.get(CurrentJobTaxonomyAssignment, job_id).taxonomy_code == job_code
        assert db.scalar(select(func.count()).select_from(CurrentCompanyIndustryAssignment)) == 1
        assert db.get(CurrentJobSkillAssignment, (job_id, skill_code)).mention_count == 1
        assert db.get(CurrentSkillCandidate, candidate_id).occurrence_count == 3
        assert db.get(CurrentJobSkillMention, mention_id).resolution == "candidate"
        assert db.get(
            CurrentSourceTaxonomyMapping,
            ("job", "jobsdb", "jobsdb:6281", job_code),
        ).role == "deterministic"
        assert db.in_transaction() is True
    finally:
        db.rollback()
        db.close()
        engine.dispose()


def test_current_enrichment_uses_full_fallback_then_optional_mapping():
    engine = create_engine("sqlite:///:memory:")
    for table in (
        CurrentTaxonomyNodeRecord.__table__,
        CurrentTaxonomyAliasRecord.__table__,
        CurrentSourceTaxonomyMapping.__table__,
        CurrentJobTaxonomyAssignment.__table__,
    ):
        table.create(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    job_id = uuid4()
    evidence = SimpleNamespace(
        source_site="jobsdb",
        evidence_hash="e" * 64,
        source_classification_paths=(
            SimpleNamespace(
                source_order=0,
                nodes=(
                    SimpleNamespace(
                        source_classification_id="jobsdb:6281",
                        label="Information Technology",
                    ),
                ),
            ),
        ),
    )
    target = (
        "information_communication_technology."
        "software_development.backend_development"
    )
    try:
        store = CurrentTaxonomyStore(db)
        store.synchronize(transform_job_taxonomy(_load("job_category_taxonomy.json")))
        enrichment = CurrentTaxonomyEnrichment(db)

        fallback = enrichment.build_job_context(evidence)
        assert len(fallback.allowed_codes) == 198
        assert "revision" not in json.dumps(fallback.prompt_payload).lower()

        db.add(
            CurrentSourceTaxonomyMapping(
                taxonomy="job",
                source_site="jobsdb",
                source_key="jobsdb:6281",
                target_code=target,
                source_label="Information Technology",
                role="allowed",
                evidence={},
            )
        )
        db.flush()
        mapped = enrichment.build_job_context(evidence)
        assert mapped.allowed_codes == frozenset({target})

        result = enrichment.assign_job_from_classification(
            job_id=job_id,
            evidence=evidence,
            classification={"decision": "select_existing", "target_code": target},
            context=mapped,
            model_provenance={"provider": "test", "version": "model-v1"},
        )
        assignment = db.get(CurrentJobTaxonomyAssignment, job_id)
        assert result["state"] == "assigned"
        assert assignment.taxonomy_code == target
        assert assignment.mapping_ids == [
            {
                "source_site": "jobsdb",
                "source_key": "jobsdb:6281",
                "target_code": target,
            }
        ]
        assert not hasattr(assignment, "taxonomy_revision_id")
    finally:
        db.rollback()
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
        enrichment = CurrentTaxonomyEnrichment(db)
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
        assert db.get(
            CurrentJobSkillAssignment,
            (first_job_id, "frontend.javascript.react"),
        ) is not None
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


def test_current_company_projection_assigns_mapped_evidence_without_review_queue():
    engine = create_engine("sqlite:///:memory:")
    for table in (
        CurrentTaxonomyNodeRecord.__table__,
        CurrentTaxonomyAliasRecord.__table__,
        CurrentSourceTaxonomyMapping.__table__,
        CurrentCompanyIndustryAssignment.__table__,
        EventOutbox.__table__,
    ):
        table.create(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    company_id = uuid4()
    try:
        store = CurrentTaxonomyStore(db)
        store.synchronize(transform_company_industry_taxonomy(_load("hsic_v2.json")))
        target = next(
            node.code
            for node in store.list_nodes("company_industry")
            if node.is_assignable
        )
        evidence = SimpleNamespace(
            source_site="offertoday",
            source_job_id="offer-1",
            raw_data={"company_industry": "Software Companies"},
            captured_at="2026-07-26T12:00:00Z",
        )

        missing = project_current_company_industry(db, company_id, evidence)
        assert missing.state == "unassigned"
        assert missing.changed is False
        assert CurrentTaxonomyReader(db).get_company_industry_state(
            company_id
        ).assignments == ()

        db.add(
            CurrentSourceTaxonomyMapping(
                taxonomy="company_industry",
                source_site="offertoday",
                source_key="label:software companies",
                target_code=target,
                source_label="Software Companies",
                role="deterministic",
                evidence={},
            )
        )
        db.flush()
        assigned = project_current_company_industry(db, company_id, evidence)
        state = CurrentTaxonomyReader(db).get_company_industry_state(company_id)

        assert assigned.state == "assigned"
        assert assigned.changed is True
        assert [row.taxonomy_code for row in state.assignments] == [target]
        assert state.assignments[0].is_primary is True
        payload = json.dumps(state.assignments[0].provenance, sort_keys=True)
        assert "revision" not in payload
        assert db.scalar(select(func.count()).select_from(EventOutbox)) == 1
    finally:
        db.rollback()
        db.close()
        engine.dispose()


def test_current_store_runtime_writes_are_last_write_wins_without_versions():
    engine = create_engine("sqlite:///:memory:")
    for table in (
        CurrentTaxonomyNodeRecord.__table__,
        CurrentTaxonomyAliasRecord.__table__,
        CurrentJobTaxonomyAssignment.__table__,
        CurrentCompanyIndustryAssignment.__table__,
        CurrentJobSkillAssignment.__table__,
        CurrentSkillCandidate.__table__,
        CurrentJobSkillMention.__table__,
    ):
        table.create(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    now = datetime(2026, 7, 26, tzinfo=UTC)
    job_id = uuid4()
    company_id = uuid4()
    first_code = "information_communication_technology.software_development.backend_development"
    second_code = "information_communication_technology.software_development.frontend_development"
    try:
        store = CurrentTaxonomyStore(db)
        store.synchronize(transform_job_taxonomy(_load("job_category_taxonomy.json")))
        company_snapshot = transform_company_industry_taxonomy(_load("hsic_v2.json"))
        store.synchronize(company_snapshot)
        store.synchronize(transform_skill_taxonomy(_load("skill_taxonomy.json")))
        company_code = next(
            node.code for node in company_snapshot.nodes if node.is_assignable
        )

        for code, method in ((first_code, "ai"), (second_code, "operator")):
            store.assign_job(
                AssignCurrentJobTaxonomyCommand(
                    job_id=job_id,
                    taxonomy_code=code,
                    method=method,
                    evidence_hash="a" * 64,
                    source_evidence_refs=(),
                    mapping_ids=(),
                    model_provenance=None,
                    breadcrumb={"subcategory": {"code": code}},
                    captured_at=now,
                )
            )
        store.replace_company_industries(
            ReplaceCurrentCompanyIndustriesCommand(
                company_id=company_id,
                assignments=(
                    CurrentCompanyIndustryInput(
                        taxonomy_code=company_code,
                        method="operator",
                        provenance={},
                        evidence_hash="b" * 64,
                        breadcrumb={"subclass": {"code": company_code}},
                        is_primary=True,
                        primary_basis="operator",
                        captured_at=now,
                    ),
                ),
            )
        )
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

        assert db.get(CurrentJobTaxonomyAssignment, job_id).taxonomy_code == second_code
        assert db.scalar(select(func.count()).select_from(CurrentJobTaxonomyAssignment)) == 1
        assert db.scalar(select(func.count()).select_from(CurrentCompanyIndustryAssignment)) == 1
        assert db.get(
            CurrentJobSkillAssignment,
            (job_id, "frontend.javascript.react"),
        ).mention_count == 2

        with pytest.raises(ValueError, match="non-assignable"):
            store.assign_job(
                AssignCurrentJobTaxonomyCommand(
                    job_id=job_id,
                    taxonomy_code="information_communication_technology",
                    method="operator",
                    evidence_hash="c" * 64,
                    source_evidence_refs=(),
                    mapping_ids=(),
                    model_provenance=None,
                    breadcrumb={},
                    captured_at=now,
                )
            )
        assert db.in_transaction() is True
    finally:
        db.rollback()
        db.close()
        engine.dispose()


def test_current_taxonomy_api_contract_has_no_revision_or_review_routes():
    paths = {route.path for route in current_taxonomy_router.routes}

    assert paths == {
        "/job-intelligence/job-taxonomy/tree",
        "/job-intelligence/jobs/{job_id}/job-taxonomy",
        "/job-intelligence/company-industries/tree",
        "/job-intelligence/companies/{company_id}/industries",
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
        CurrentJobTaxonomyAssignment.__table__,
        CurrentCompanyIndustryAssignment.__table__,
        CurrentJobSkillAssignment.__table__,
        CurrentSkillCandidate.__table__,
        CurrentJobSkillMention.__table__,
    ):
        table.create(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    now = datetime(2026, 7, 26, tzinfo=UTC)
    job_id = uuid4()
    company_id = uuid4()
    job_code = "information_communication_technology.software_development.backend_development"
    try:
        store = CurrentTaxonomyStore(db)
        store.synchronize(transform_job_taxonomy(_load("job_category_taxonomy.json")))
        store.synchronize(transform_company_industry_taxonomy(_load("hsic_v2.json")))
        store.synchronize(transform_skill_taxonomy(_load("skill_taxonomy.json")))
        store.assign_job(
            AssignCurrentJobTaxonomyCommand(
                job_id=job_id,
                taxonomy_code=job_code,
                method="ai",
                evidence_hash="a" * 64,
                source_evidence_refs=(),
                mapping_ids=(),
                model_provenance=None,
                breadcrumb={
                    "domain": {
                        "code": "information_communication_technology",
                        "label": "Information & Communication Technology",
                    },
                    "category": {
                        "code": "information_communication_technology.software_development",
                        "label": "Software Development",
                    },
                    "subcategory": {
                        "code": job_code,
                        "label": "Backend Development",
                    },
                },
                captured_at=now,
            )
        )
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
            read_job_taxonomy_tree(db),
            read_job_taxonomy_state(job_id, db),
            read_company_industry_tree(db),
            read_company_industry_state(company_id, db),
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
        assert serialized[1]["assignment"]["taxonomy_code"] == job_code
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
        assert "Job Taxonomy:" in embedding.document_text
        assert "Skills: React" in embedding.document_text
        assert "Revision" not in embedding.document_text
        assert "version" not in embedding.document_text.lower()
    finally:
        db.rollback()
        db.close()
        engine.dispose()
