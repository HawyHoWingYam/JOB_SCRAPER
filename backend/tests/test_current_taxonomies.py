from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.api.current_taxonomies import (
    read_company_industry_state,
    read_company_industry_tree,
    read_job_skills,
    read_skill_tree,
    router as current_taxonomy_router,
)
from app.job_intelligence.current_taxonomies import (
    CurrentCompanyIndustryInput,
    CurrentJobSkillInput,
    CurrentSkillEnrichment,
    CurrentTaxonomyReader,
    CurrentTaxonomyStore,
    ReplaceCurrentCompanyIndustriesCommand,
    ReplaceCurrentJobSkillsCommand,
    project_current_company_industry,
    transform_company_industry_taxonomy,
    transform_skill_taxonomy,
)
from app.job_intelligence.product_read_model import JobIntelligenceProductReadModel
from app.models.current_taxonomy import (
    CurrentCompanyIndustryAssignment,
    CurrentJobSkillMention,
    CurrentJobSkillAssignment,
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
    industry = transform_company_industry_taxonomy(_load("hsic_v2.json"))
    skill = transform_skill_taxonomy(_load("skill_taxonomy.json"))

    assert len(industry.nodes) == 21 + 88 + 221 + 483 + 1001
    assert sum(node.level == "subclass" and node.is_assignable for node in industry.nodes) == 1001
    assert len(skill.nodes) == 8 + 33 + 91
    assert len(skill.aliases) == 142
    assert sum(node.level == "skill" and node.is_assignable for node in skill.nodes) == 91

    for snapshot in (industry, skill):
        payload = snapshot.to_payload()
        assert "version" not in payload
        assert "revision" not in payload
        assert "release" not in payload
        assert len({node.code for node in snapshot.nodes}) == len(snapshot.nodes)


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
        {"name": raw_name, "kind": "technical"}
        for raw_name in ("項目管理", "銷售", "客戶服務")
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
        assert db.scalar(select(func.count()).select_from(CurrentJobSkillAssignment)) == 0
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


def test_current_store_runtime_writes_have_no_versions():
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
    now = datetime(2026, 7, 26, tzinfo=UTC)
    job_id = uuid4()
    company_id = uuid4()
    try:
        store = CurrentTaxonomyStore(db)
        company_snapshot = transform_company_industry_taxonomy(_load("hsic_v2.json"))
        store.synchronize(company_snapshot)
        store.synchronize(transform_skill_taxonomy(_load("skill_taxonomy.json")))
        company_code = next(
            node.code for node in company_snapshot.nodes if node.is_assignable
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

        assert db.scalar(select(func.count()).select_from(CurrentCompanyIndustryAssignment)) == 1
        assert db.get(
            CurrentJobSkillAssignment,
            (job_id, "frontend.javascript.react"),
        ).mention_count == 2

        assert db.in_transaction() is True
    finally:
        db.rollback()
        db.close()
        engine.dispose()


def test_current_taxonomy_api_contract_has_no_revision_or_review_routes():
    paths = {route.path for route in current_taxonomy_router.routes}

    assert paths == {
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
    try:
        store = CurrentTaxonomyStore(db)
        store.synchronize(transform_company_industry_taxonomy(_load("hsic_v2.json")))
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
        assert embedding.document_text.splitlines() == [
            "Title: Backend Engineer",
            "Company: Example Company",
            "Source Taxonomy: Information Technology",
            "AI Summary: Build reliable services",
            "Skills: React",
            "Description: Python and React",
        ]
        assert "Revision" not in embedding.document_text
        assert "version" not in embedding.document_text.lower()
    finally:
        db.rollback()
        db.close()
        engine.dispose()
