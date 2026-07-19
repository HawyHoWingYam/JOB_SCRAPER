from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import ast
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.api.company_industries import (
    decide_company_industry_review_item,
    list_company_industry_audit_events,
    list_company_industry_mappings,
    list_company_industry_review_items,
    read_company_industry_revision,
    read_company_industry_review_item,
    read_company_industry_state,
    read_company_industry_tree,
)
from app.api.companies import create_company
from app.job_intelligence.company_industry import (
    CompanyIndustry,
    CompanyIndustryDecisionAdapter,
    CompanyIndustryEvidence,
    CompanyIndustryEvidenceAdapter,
    CompanyIndustryCompatibilityAdapter,
    CompanyIndustryPublisher,
    CompanyIndustryRebuildInspector,
    CompanyIndustryReviewQuery,
    project_company_industry,
)
from app.job_intelligence.company_industry.seed import build_hsic_seed
from app.job_intelligence.foundation import DecisionCommand, Provenance
from app.models.company import Company
from app.models.company_industry import (
    COMPANY_INDUSTRY_TABLES,
    CompanyIndustryActiveRevision,
    CompanyIndustryAssignment,
    CompanyIndustryCrosswalkEdge,
    CompanyIndustryReviewItem,
    CompanyIndustryTaxonomyNode,
    CompanyIndustryTaxonomyRelease,
    SourceIndustryMapping,
)
from app.models.event_outbox import EventOutbox
from app.models.governance import (
    GOVERNANCE_FOUNDATION_TABLES,
    GovernanceAuditEvent,
    GovernanceRevision,
)
from app.models.job import Job
from app.models.job_category import JobCategory
from app.models.job_domain import JobDomain
from app.models.job_subcategory import JobSubcategory
from app.sources.contracts import CanonicalScrapedJob, build_offertoday_company_data
from app.schemas.company_industry import (
    CompanyIndustryDecisionRequestSchema,
    CompanyIndustryFixtureSchema,
)
from app.schemas.company import CompanyCreateSchema
from app.job_intelligence.company_industry.seed import seed_content_hash
from app.utils.data_mapper import (
    map_scraped_company_to_db,
    map_source_scraped_company_to_db,
)


SEED_PATH = Path(__file__).parents[1] / "app" / "data" / "hsic_v2.json"


@pytest.fixture
def company_industry_revision_db():
    database_url = os.getenv("JOB_INTELLIGENCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("JOB_INTELLIGENCE_TEST_DATABASE_URL is not configured")
    if not database_url.rsplit("/", 1)[-1].endswith("_test"):
        pytest.fail("Company Industry tests require a dedicated *_test database")
    engine = create_engine(database_url)
    tables = (
        JobDomain.__table__,
        JobCategory.__table__,
        JobSubcategory.__table__,
        Company.__table__,
        Job.__table__,
        EventOutbox.__table__,
        *GOVERNANCE_FOUNDATION_TABLES,
        *COMPANY_INDUSTRY_TABLES,
    )
    Base.metadata.drop_all(engine, checkfirst=True)
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


def _five_level_official_payload() -> dict[str, object]:
    return {
        "queryArray1": [
            {
                "HSIC20": "J",
                "ENG_TITLE": "Information and communications",
                "CHI_TITLE": "資訊及通訊",
                "SC_TITLE": "资讯及通讯",
            }
        ],
        "queryArray2": [
            {
                "HSIC20": "62",
                "ENG_TITLE": "Information technology service activities",
                "CHI_TITLE": "資訊科技服務活動",
                "SC_TITLE": "资讯科技服务活动",
                "Array1": "J",
            }
        ],
        "queryArray3": [
            {
                "HSIC20": "620",
                "ENG_TITLE": "Information technology service activities",
                "CHI_TITLE": "資訊科技服務活動",
                "SC_TITLE": "资讯科技服务活动",
            }
        ],
        "queryArray4": [
            {
                "HSIC20": "6201",
                "ENG_TITLE": "Computer programming activities",
                "CHI_TITLE": "電腦程式編寫活動",
                "SC_TITLE": "电脑程式编写活动",
            }
        ],
        "queryArray5": [
            {
                "HSIC20": "620100",
                "ENG_TITLE": "Computer programming activities",
                "CHI_TITLE": "電腦程式編寫活動",
                "SC_TITLE": "电脑程式编写活动",
            }
        ],
    }


def _activate_tiny_taxonomy(db):
    seed = build_hsic_seed(
        _five_level_official_payload(),
        retrieved_at="2026-07-19",
        raw_sha256="f" * 64,
        expected_counts={
            level: 1 for level in ("section", "division", "group", "class", "subclass")
        },
    )
    publisher = CompanyIndustryPublisher(db)
    revision = publisher.materialize(seed)
    publisher.activate(revision, expected_lock_version=0)
    return revision


def _company(db, suffix: str) -> Company:
    company = Company(
        company_id=f"company-{suffix}",
        source_site="offertoday",
        source_company_id=f"company-{suffix}",
        name=f"Company {suffix}",
    )
    db.add(company)
    db.commit()
    return company


def _source_evidence(
    *,
    raw_code: str | None = None,
    raw_label: str | None = None,
    hsic_codes: tuple[str, ...] = (),
    declares_primary: bool = False,
) -> CompanyIndustryEvidence:
    return CompanyIndustryEvidence(
        evidence_kind="source_industry",
        source_site="offertoday",
        raw_code=raw_code,
        raw_label=raw_label,
        hsic_codes=hsic_codes,
        declares_primary=declares_primary,
        provenance=Provenance(
            method="authoritative_source",
            source_site="offertoday",
            evidence_refs=({"kind": "company-detail", "id": "fixture"},),
            captured_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        ),
    )


def test_build_hsic_seed_preserves_five_levels_and_bilingual_labels():
    seed = build_hsic_seed(
        _five_level_official_payload(),
        retrieved_at="2026-07-19",
        raw_sha256="a" * 64,
        expected_counts={
            "section": 1,
            "division": 1,
            "group": 1,
            "class": 1,
            "subclass": 1,
        },
    )

    assert [node["code"] for node in seed["nodes"]] == [
        "J",
        "62",
        "620",
        "6201",
        "620100",
    ]
    assert [node["parent_code"] for node in seed["nodes"]] == [
        None,
        "J",
        "62",
        "620",
        "6201",
    ]
    assert [node["level"] for node in seed["nodes"]] == [
        "section",
        "division",
        "group",
        "class",
        "subclass",
    ]
    assert seed["nodes"][-1]["labels"] == {
        "en": "Computer programming activities",
        "zh_hant": "電腦程式編寫活動",
        "zh_hans": "电脑程式编写活动",
    }
    assert seed["source"]["publisher"] == ("Hong Kong Census and Statistics Department")
    assert seed["source"]["rights_owner"] == (
        "Government of the Hong Kong Special Administrative Region"
    )
    assert len(seed["content_hash"]) == 64
    assert CompanyIndustryPublisher.validate(seed).to_payload() == {
        "valid": True,
        "issues": [],
    }


def test_hsic_validation_aggregates_hierarchy_code_label_and_hash_errors():
    seed = build_hsic_seed(
        _five_level_official_payload(),
        retrieved_at="2026-07-19",
        raw_sha256="b" * 64,
        expected_counts={
            "section": 1,
            "division": 1,
            "group": 1,
            "class": 1,
            "subclass": 1,
        },
    )
    invalid = deepcopy(seed)
    invalid["nodes"][1]["code"] = "bad-division"
    invalid["nodes"][2]["parent_code"] = "missing"
    invalid["nodes"][3]["labels"]["zh_hant"] = ""
    invalid["nodes"][4]["parent_code"] = "620100"
    invalid["content_hash"] = "0" * 64

    payload = CompanyIndustryPublisher.validate(invalid).to_payload()

    assert payload["valid"] is False
    assert [issue["code"] for issue in payload["issues"]] == [
        "company_industry_content_hash_mismatch",
        "company_industry_code_invalid",
        "company_industry_parent_missing",
        "company_industry_label_missing",
        "company_industry_cycle",
        "company_industry_parent_level_invalid",
    ]


def test_committed_hsic_seed_matches_official_counts_attribution_and_hash():
    seed = json.loads(SEED_PATH.read_text())

    assert CompanyIndustryPublisher.validate(seed).to_payload() == {
        "valid": True,
        "issues": [],
    }
    assert seed["expected_counts"] == {
        "section": 21,
        "division": 88,
        "group": 221,
        "class": 483,
        "subclass": 1001,
    }
    counts = {
        level: sum(node["level"] == level for node in seed["nodes"])
        for level in seed["expected_counts"]
    }
    assert counts == seed["expected_counts"]
    assert len(seed["nodes"]) == 1814
    assert seed["source"]["overview_url"] == (
        "https://www.censtatd.gov.hk/en/page_698.html"
    )
    assert seed["source"]["terms_url"] == (
        "https://www.censtatd.gov.hk/en/page_31.html"
    )
    assert seed["source"]["raw_sha256"] == (
        "1c774d8cbb9693a6add2f662683a3c5249bccb6999ccb52dabf6d07a18ef91b7"
    )
    assert seed["source"]["modifications"] == [
        "Descriptions omitted",
        "Parent codes and global source order derived",
        "Fields normalized into the project seed schema",
    ]


def test_company_industry_models_register_the_additive_schema():
    assert [table.name for table in COMPANY_INDUSTRY_TABLES] == [
        "company_industry_taxonomy_releases",
        "company_industry_active_revisions",
        "company_industry_taxonomy_nodes",
        "company_industry_crosswalk_edges",
        "source_industry_mappings",
        "company_industry_assignments",
        "company_industry_review_items",
    ]
    assignment_constraints = {
        constraint.name
        for constraint in CompanyIndustryAssignment.__table__.constraints
    }
    mapping_constraints = {
        constraint.name for constraint in SourceIndustryMapping.__table__.constraints
    }
    review_constraints = {
        constraint.name
        for constraint in CompanyIndustryReviewItem.__table__.constraints
    }
    assert "ck_company_industry_assignment_hash" in assignment_constraints
    assert "ck_company_industry_assignment_superseded" in assignment_constraints
    assert "ck_source_industry_mapping_superseded" in mapping_constraints
    assert "ck_company_industry_review_hash" in review_constraints


def test_materialize_replays_exact_release_and_leaves_it_inactive(
    company_industry_revision_db,
):
    seed = build_hsic_seed(
        _five_level_official_payload(),
        retrieved_at="2026-07-19",
        raw_sha256="c" * 64,
        expected_counts={
            level: 1 for level in ("section", "division", "group", "class", "subclass")
        },
    )
    publisher = CompanyIndustryPublisher(company_industry_revision_db)

    first = publisher.materialize(seed)
    replay = publisher.materialize(seed)

    assert replay == first
    release = company_industry_revision_db.get(
        CompanyIndustryTaxonomyRelease,
        first.revision_id,
    )
    assert release is not None
    assert release.status == "ready"
    assert release.expected_counts == {
        "section": 1,
        "division": 1,
        "group": 1,
        "class": 1,
        "subclass": 1,
    }
    assert release.materialized_counts == release.expected_counts
    assert company_industry_revision_db.query(CompanyIndustryTaxonomyNode).count() == 5
    assert (
        company_industry_revision_db.get(
            CompanyIndustryActiveRevision,
            "company-industry",
        )
        is None
    )


def test_failed_materialization_keeps_a_retryable_foundation_identity(
    company_industry_revision_db,
):
    seed = build_hsic_seed(
        _five_level_official_payload(),
        retrieved_at="2026-07-19",
        raw_sha256="1" * 64,
        expected_counts={
            level: 1 for level in ("section", "division", "group", "class", "subclass")
        },
    )

    def fail_domain_release(session, _flush_context, _instances):
        if any(isinstance(row, CompanyIndustryTaxonomyRelease) for row in session.new):
            raise RuntimeError("forced domain materialization failure")

    event.listen(company_industry_revision_db, "before_flush", fail_domain_release)
    try:
        with pytest.raises(
            RuntimeError,
            match="forced domain materialization failure",
        ):
            CompanyIndustryPublisher(company_industry_revision_db).materialize(seed)
    finally:
        event.remove(
            company_industry_revision_db,
            "before_flush",
            fail_domain_release,
        )

    governance = (
        company_industry_revision_db.query(GovernanceRevision)
        .filter(
            GovernanceRevision.domain == "company-industry",
            GovernanceRevision.release_key == seed["release_key"],
        )
        .one()
    )
    assert (
        company_industry_revision_db.get(
            CompanyIndustryTaxonomyRelease,
            governance.id,
        )
        is None
    )

    retry = CompanyIndustryPublisher(company_industry_revision_db).materialize(seed)
    release = company_industry_revision_db.get(
        CompanyIndustryTaxonomyRelease,
        retry.revision_id,
    )

    assert retry.revision_id == governance.id
    assert release is not None
    assert release.status == "ready"
    assert (
        company_industry_revision_db.query(CompanyIndustryTaxonomyNode)
        .filter(CompanyIndustryTaxonomyNode.revision_id == retry.revision_id)
        .count()
        == 5
    )


def test_activation_uses_cas_and_tree_returns_bilingual_breadcrumb(
    company_industry_revision_db,
):
    seed = build_hsic_seed(
        _five_level_official_payload(),
        retrieved_at="2026-07-19",
        raw_sha256="d" * 64,
        expected_counts={
            level: 1 for level in ("section", "division", "group", "class", "subclass")
        },
    )
    publisher = CompanyIndustryPublisher(company_industry_revision_db)
    revision = publisher.materialize(seed)

    active = publisher.activate(revision, expected_lock_version=0)
    replay = publisher.activate(revision, expected_lock_version=active.lock_version)
    view = CompanyIndustry(company_industry_revision_db)
    roots = view.get_tree()
    leaf = (
        company_industry_revision_db.query(CompanyIndustryTaxonomyNode)
        .filter(CompanyIndustryTaxonomyNode.code == "620100")
        .one()
    )

    assert active.lock_version == 1
    assert replay.lock_version == 2
    assert roots.revision.id == revision.revision_id
    assert [node.code for node in roots.nodes] == ["J"]
    assert roots.nodes[0].labels == {
        "en": "Information and communications",
        "zh_hant": "資訊及通訊",
        "zh_hans": "资讯及通讯",
    }
    assert [node.code for node in view.get_breadcrumb(leaf.id)] == [
        "J",
        "62",
        "620",
        "6201",
        "620100",
    ]


def test_activation_rejects_a_stale_lock_version(company_industry_revision_db):
    seed = build_hsic_seed(
        _five_level_official_payload(),
        retrieved_at="2026-07-19",
        raw_sha256="e" * 64,
        expected_counts={
            level: 1 for level in ("section", "division", "group", "class", "subclass")
        },
    )
    publisher = CompanyIndustryPublisher(company_industry_revision_db)
    revision = publisher.materialize(seed)
    publisher.activate(revision, expected_lock_version=0)

    with pytest.raises(ValueError, match="stale"):
        publisher.activate(revision, expected_lock_version=0)


def test_authoritative_hsic_path_assigns_only_the_most_specific_node(
    company_industry_revision_db,
):
    _activate_tiny_taxonomy(company_industry_revision_db)
    company = _company(company_industry_revision_db, "direct")

    outcome = CompanyIndustry(company_industry_revision_db).ingest_evidence(
        company.id,
        _source_evidence(
            raw_code="620100",
            raw_label="Computer programming activities",
            hsic_codes=("6201", "620100"),
            declares_primary=True,
        ),
    )
    company_industry_revision_db.commit()

    assignments = (
        company_industry_revision_db.query(CompanyIndustryAssignment)
        .filter(CompanyIndustryAssignment.company_id == company.id)
        .all()
    )
    assert outcome.state == "assigned"
    assert len(assignments) == 1
    assert assignments[0].method == "authoritative_code"
    assert assignments[0].is_primary is True
    assert assignments[0].primary_basis == "authoritative_source"
    assert assignments[0].breadcrumb[-1]["code"] == "620100"
    assert (
        company_industry_revision_db.query(CompanyIndustryReviewItem)
        .filter(CompanyIndustryReviewItem.company_id == company.id)
        .count()
        == 0
    )


def test_changed_evidence_supersedes_assignment_and_exact_replay_is_a_noop(
    company_industry_revision_db,
):
    _activate_tiny_taxonomy(company_industry_revision_db)
    company = _company(company_industry_revision_db, "assignment-history")
    module = CompanyIndustry(company_industry_revision_db)
    original_evidence = _source_evidence(
        raw_code="620100",
        raw_label="Original company evidence",
        hsic_codes=("620100",),
        declares_primary=True,
    )
    changed_evidence = _source_evidence(
        raw_code="620100",
        raw_label="Updated company evidence",
        hsic_codes=("620100",),
    )

    original = module.ingest_evidence(company.id, original_evidence)
    company_industry_revision_db.commit()
    replay = module.ingest_evidence(company.id, original_evidence)
    changed = module.ingest_evidence(company.id, changed_evidence)
    company_industry_revision_db.commit()

    assignments = (
        company_industry_revision_db.query(CompanyIndustryAssignment)
        .filter(CompanyIndustryAssignment.company_id == company.id)
        .order_by(CompanyIndustryAssignment.lock_version)
        .all()
    )
    assert original.changed is True
    assert replay.changed is False
    assert replay.assignment_id == original.assignment_id
    assert changed.changed is True
    assert changed.assignment_id != original.assignment_id
    assert len(assignments) == 2
    assert assignments[0].status == "superseded"
    assert assignments[0].superseded_at is not None
    assert assignments[1].status == "active"
    assert assignments[1].superseded_at is None
    assert assignments[1].lock_version == 2
    assert assignments[1].evidence_hash != assignments[0].evidence_hash
    assert assignments[1].is_primary is True
    assert assignments[1].primary_basis == "authoritative_source"
    assert (
        company_industry_revision_db.query(EventOutbox)
        .filter(EventOutbox.event_type == "company.industry_changed")
        .count()
        == 2
    )


def test_unmapped_source_and_ai_evidence_create_review_without_assignment(
    company_industry_revision_db,
):
    _activate_tiny_taxonomy(company_industry_revision_db)
    source_company = _company(company_industry_revision_db, "source-review")
    ai_company = _company(company_industry_revision_db, "ai-review")
    module = CompanyIndustry(company_industry_revision_db)

    source_outcome = module.ingest_evidence(
        source_company.id,
        _source_evidence(raw_label="Software consultancy"),
    )
    ai_outcome = module.ingest_evidence(
        ai_company.id,
        CompanyIndustryEvidence(
            evidence_kind="ai_recommendation",
            source_site=None,
            raw_label="Computer programming activities",
            recommendations=({"node_code": "620100", "confidence": 0.99},),
            provenance=Provenance(
                method="ai_recommendation",
                evidence_refs=({"kind": "company-profile", "id": "ai-fixture"},),
                captured_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
                model_provider="fixture",
                model_name="fixture-model",
                model_version="1",
            ),
        ),
    )
    company_industry_revision_db.commit()

    assert source_outcome.state == "review"
    assert ai_outcome.state == "review"
    assert company_industry_revision_db.query(CompanyIndustryAssignment).count() == 0
    assert {
        row.reason
        for row in company_industry_revision_db.query(CompanyIndustryReviewItem).all()
    } == {"unmapped_source_evidence", "ai_recommendation"}


def test_operator_approved_mapping_is_atomic_replayable_and_reusable(
    company_industry_revision_db,
):
    _activate_tiny_taxonomy(company_industry_revision_db)
    first_company = _company(company_industry_revision_db, "mapping-first")
    module = CompanyIndustry(company_industry_revision_db)
    review_outcome = module.ingest_evidence(
        first_company.id,
        _source_evidence(raw_label="Software consultancy"),
    )
    company_industry_revision_db.commit()
    target = (
        company_industry_revision_db.query(CompanyIndustryTaxonomyNode)
        .filter(CompanyIndustryTaxonomyNode.code == "620100")
        .one()
    )
    command = DecisionCommand(
        subject_id=str(review_outcome.review_item_id),
        action="approve_mapping_and_assign",
        target_id=str(target.id),
        expected_version=1,
        idempotency_key="company-industry-mapping-fixture",
        confirmed=True,
    )

    result = CompanyIndustryDecisionAdapter(company_industry_revision_db).decide(
        command
    )
    replay = CompanyIndustryDecisionAdapter(company_industry_revision_db).decide(
        command
    )

    assert result.replayed is False
    assert replay.replayed is True
    assert replay.audit_event_id == result.audit_event_id
    review = company_industry_revision_db.get(
        CompanyIndustryReviewItem,
        review_outcome.review_item_id,
    )
    assert review is not None
    assert review.status == "assigned"
    assert review.decision_audit_id == result.audit_event_id
    mapping = company_industry_revision_db.query(SourceIndustryMapping).one()
    assert mapping.status == "active"
    assert mapping.approved_by == "local-operator"
    assert mapping.decision_audit_id == result.audit_event_id
    assignment = (
        company_industry_revision_db.query(CompanyIndustryAssignment)
        .filter(CompanyIndustryAssignment.company_id == first_company.id)
        .one()
    )
    assert assignment.mapping_id == mapping.id
    assert assignment.method == "operator"
    assert company_industry_revision_db.query(GovernanceAuditEvent).count() == 1
    decision_event = (
        company_industry_revision_db.query(EventOutbox)
        .filter(EventOutbox.event_type == "company.industry_decided")
        .one()
    )
    assert decision_event.payload["governance_audit_event_id"] == str(
        result.audit_event_id
    )

    second_company = _company(company_industry_revision_db, "mapping-second")
    second_outcome = module.ingest_evidence(
        second_company.id,
        _source_evidence(raw_label="  SOFTWARE CONSULTANCY  "),
    )
    company_industry_revision_db.commit()
    second_assignment = (
        company_industry_revision_db.query(CompanyIndustryAssignment)
        .filter(CompanyIndustryAssignment.company_id == second_company.id)
        .one()
    )
    assert second_outcome.state == "assigned"
    assert second_assignment.method == "reviewed_mapping"
    assert second_assignment.mapping_id == mapping.id


def test_reusing_an_approved_mapping_preserves_its_originating_audit(
    company_industry_revision_db,
):
    _activate_tiny_taxonomy(company_industry_revision_db)
    first_company = _company(company_industry_revision_db, "mapping-audit-first")
    second_company = _company(company_industry_revision_db, "mapping-audit-second")
    module = CompanyIndustry(company_industry_revision_db)
    first_review = module.ingest_evidence(
        first_company.id,
        _source_evidence(raw_label="Shared unmapped industry"),
    )
    second_review = module.ingest_evidence(
        second_company.id,
        _source_evidence(raw_label="Shared unmapped industry"),
    )
    company_industry_revision_db.commit()
    target = (
        company_industry_revision_db.query(CompanyIndustryTaxonomyNode)
        .filter(CompanyIndustryTaxonomyNode.code == "620100")
        .one()
    )

    first_result = CompanyIndustryDecisionAdapter(company_industry_revision_db).decide(
        DecisionCommand(
            subject_id=str(first_review.review_item_id),
            action="approve_mapping_and_assign",
            target_id=str(target.id),
            expected_version=1,
            idempotency_key="company-industry-mapping-origin-audit",
            confirmed=True,
        )
    )
    second_result = CompanyIndustryDecisionAdapter(company_industry_revision_db).decide(
        DecisionCommand(
            subject_id=str(second_review.review_item_id),
            action="approve_mapping_and_assign",
            target_id=str(target.id),
            expected_version=1,
            idempotency_key="company-industry-mapping-reuse-audit",
            confirmed=True,
        )
    )

    mapping = company_industry_revision_db.query(SourceIndustryMapping).one()
    resolved_second_review = company_industry_revision_db.get(
        CompanyIndustryReviewItem,
        second_review.review_item_id,
    )
    assert first_result.audit_event_id != second_result.audit_event_id
    assert mapping.decision_audit_id == first_result.audit_event_id
    assert resolved_second_review is not None
    assert resolved_second_review.decision_audit_id == second_result.audit_event_id


def test_company_evidence_adapter_accepts_only_company_owned_offertoday_label():
    adapter = CompanyIndustryEvidenceAdapter()
    offertoday = CanonicalScrapedJob(
        source_site="offertoday",
        source_job_id="offer-1",
        source_url="https://www.offertoday.com/job/offer-1",
        title="Developer",
        description="Build software",
        company_name="Example Limited",
        location="Hong Kong",
        salary_range=None,
        employment_type=None,
        source_classification_id="118000",
        source_classification_name="Information Technology",
        source_subclassification_id=None,
        source_subclassification_name=None,
        posted_date=None,
        raw_data={
            "company_industry": "Software and information technology",
            "jobFunctions": [{"code": "118000", "name": "IT"}],
        },
        source_attribute_evidence={
            "classification_paths": [
                {
                    "provenance": {
                        "captured_at": "2026-07-19T08:30:00+00:00",
                    }
                }
            ]
        },
    )
    jobsdb = deepcopy(offertoday.to_dict())
    jobsdb["source_site"] = "jobsdb"
    jobsdb["raw_data"] = {
        "classification_name": "Information Technology",
        "industry": {"name": "Job taxonomy masquerading as industry"},
    }
    ctgoodjobs = deepcopy(jobsdb)
    ctgoodjobs["source_site"] = "ctgoodjobs"
    ctgoodjobs["raw_data"] = {
        "company_industry": "Software and information technology",
        "classification_name": "Information Technology",
    }

    evidence = adapter.extract(offertoday)
    offertoday_fallback = deepcopy(offertoday.to_dict())
    offertoday_fallback["raw_data"] = {
        "industry": {"name": "Company-owned OfferToday industry"},
        "jobFunctions": [{"code": "118000", "name": "IT"}],
    }
    fallback_evidence = adapter.extract(offertoday_fallback)

    assert evidence is not None
    assert fallback_evidence is not None
    assert evidence.evidence_kind == "source_industry"
    assert evidence.raw_label == "Software and information technology"
    assert fallback_evidence.raw_label == "Company-owned OfferToday industry"
    assert evidence.hsic_codes == ()
    assert evidence.provenance.captured_at == datetime(
        2026,
        7,
        19,
        8,
        30,
        tzinfo=timezone.utc,
    )
    assert adapter.extract(jobsdb) is None
    assert adapter.extract(ctgoodjobs) is None


def test_company_industry_projection_replays_and_rolls_back_with_outer_writer(
    company_industry_revision_db,
):
    revision = _activate_tiny_taxonomy(company_industry_revision_db)
    company = _company(company_industry_revision_db, "projection-transaction")
    target = (
        company_industry_revision_db.query(CompanyIndustryTaxonomyNode)
        .filter(CompanyIndustryTaxonomyNode.code == "620100")
        .one()
    )
    company_industry_revision_db.add(
        SourceIndustryMapping(
            source_site="offertoday",
            key_kind="label",
            raw_value="Software and information technology",
            normalized_key="software and information technology",
            taxonomy_revision_id=revision.revision_id,
            target_node_id=target.id,
            status="active",
            lock_version=1,
            approved_by="local-operator",
            approved_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        )
    )
    company_industry_revision_db.commit()
    canonical_job = {
        "source_site": "offertoday",
        "source_job_id": "projection-transaction-job",
        "raw_data": {
            "company_industry": "Software and information technology",
        },
        "source_attribute_evidence": {
            "classification_paths": [
                {
                    "provenance": {
                        "captured_at": "2026-07-19T08:30:00+00:00",
                    }
                }
            ]
        },
    }

    first = project_company_industry(
        company_industry_revision_db,
        company.id,
        canonical_job,
    )
    replay = project_company_industry(
        company_industry_revision_db,
        company.id,
        canonical_job,
    )

    assert first is not None
    assert replay is not None
    assert first.changed is True
    assert replay.changed is False
    assert replay.assignment_id == first.assignment_id
    assert company_industry_revision_db.query(CompanyIndustryAssignment).count() == 1
    assert (
        company_industry_revision_db.query(EventOutbox)
        .filter(EventOutbox.event_type == "company.industry_changed")
        .count()
        == 1
    )

    company_industry_revision_db.rollback()
    company_industry_revision_db.refresh(company)
    assert company_industry_revision_db.query(CompanyIndustryAssignment).count() == 0
    assert company_industry_revision_db.query(EventOutbox).count() == 0
    assert company.industry is None


def test_legacy_company_builders_do_not_copy_source_classification_to_industry():
    payload = {
        "source_site": "ctgoodjobs",
        "company_id": "company-1",
        "company_name": "Example Limited",
        "classification_name": "Information Technology",
        "source_classification_name": "Information Technology",
    }
    jobsdb_company = map_scraped_company_to_db(payload)
    ctgoodjobs_company = map_source_scraped_company_to_db(payload)
    canonical = CanonicalScrapedJob(
        source_site="offertoday",
        source_job_id="offer-2",
        source_url="https://www.offertoday.com/job/offer-2",
        title="Developer",
        description="Build software",
        company_name="Example Limited",
        location="Hong Kong",
        salary_range=None,
        employment_type=None,
        source_classification_id="118000",
        source_classification_name="Information Technology",
        source_subclassification_id=None,
        source_subclassification_name=None,
        posted_date=None,
        raw_data={"company_industry": "Software"},
    )

    assert "industry" not in jobsdb_company
    assert "industry" not in ctgoodjobs_company
    assert "industry" not in build_offertoday_company_data(canonical)


def test_authoritative_company_writers_project_inside_their_unit_of_work():
    root = Path(__file__).parents[1]
    writers = {
        ("app/workers/run_ingest_worker.py", "_persist_event"),
        ("app/services/offertoday_detail_pipeline.py", "_persist_success"),
        ("app/services/offertoday_job_repair_service.py", "_persist_canonical_job"),
        ("scripts/jobsdb_standalone_crawl.py", "run_detail_phase"),
        ("scripts/ctgoodjobs_standalone_crawl.py", "_persist_ctgoodjobs_job"),
    }
    for relative_path, function_name in writers:
        tree = ast.parse((root / relative_path).read_text())
        function = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        )
        upsert_lines = sorted(
            node.lineno
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "upsert_company"
        )
        projection_lines = sorted(
            node.lineno
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and (
                (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "project_company_industry"
                )
                or (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "project_company_industry"
                )
            )
        )
        commit_lines = sorted(
            node.lineno
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "commit"
        )
        assert len(upsert_lines) == 1, relative_path
        assert len(projection_lines) == 1, relative_path
        assert upsert_lines[0] < projection_lines[0], relative_path
        if commit_lines:
            assert projection_lines[0] < commit_lines[-1], relative_path


def test_ingest_company_builder_has_no_source_classification_industry_write():
    path = Path(__file__).parents[1] / "app" / "workers" / "run_ingest_worker.py"
    tree = ast.parse(path.read_text())
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_build_company_data"
    )
    constants = {
        node.value
        for node in ast.walk(function)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "source_classification_name" not in constants


def test_company_state_ancestor_filter_review_queue_and_mapping_registry(
    company_industry_revision_db,
):
    _activate_tiny_taxonomy(company_industry_revision_db)
    assigned_company = _company(company_industry_revision_db, "read-assigned")
    review_company = _company(company_industry_revision_db, "read-review")
    module = CompanyIndustry(company_industry_revision_db)
    assignment_outcome = module.ingest_evidence(
        assigned_company.id,
        _source_evidence(
            raw_code="620100",
            hsic_codes=("620100",),
            declares_primary=True,
        ),
    )
    review_outcome = module.ingest_evidence(
        review_company.id,
        _source_evidence(raw_label="Software consultancy"),
    )
    company_industry_revision_db.commit()
    target = (
        company_industry_revision_db.query(CompanyIndustryTaxonomyNode)
        .filter(CompanyIndustryTaxonomyNode.code == "620100")
        .one()
    )
    CompanyIndustryDecisionAdapter(company_industry_revision_db).decide(
        DecisionCommand(
            subject_id=str(review_outcome.review_item_id),
            action="approve_mapping_and_assign",
            target_id=str(target.id),
            expected_version=1,
            idempotency_key="company-read-mapping",
            confirmed=True,
        )
    )
    another_review_company = _company(
        company_industry_revision_db,
        "read-review-pending",
    )
    pending = module.ingest_evidence(
        another_review_company.id,
        _source_evidence(raw_label="Unmapped activity"),
    )
    company_industry_revision_db.commit()

    state = module.get_company_state(assigned_company.id)
    root = (
        company_industry_revision_db.query(CompanyIndustryTaxonomyNode)
        .filter(CompanyIndustryTaxonomyNode.code == "J")
        .one()
    )
    filtered = (
        company_industry_revision_db.query(Company)
        .filter(module.build_company_filter((root.id,)))
        .order_by(Company.company_id)
        .all()
    )
    page = module.list_review_items(
        CompanyIndustryReviewQuery(
            statuses=("active",),
            source_sites=("offertoday",),
            reasons=("unmapped_source_evidence",),
            company_id=another_review_company.id,
            limit=1,
        )
    )
    mappings = module.list_mappings(source_sites=("offertoday",))

    assert state.to_payload() == {
        "company_id": str(assigned_company.id),
        "assignments": [
            {
                "id": str(assignment_outcome.assignment_id),
                "taxonomy_revision_id": str(target.revision_id),
                "node_id": str(target.id),
                "method": "authoritative_code",
                "breadcrumb": state.assignments[0].breadcrumb,
                "is_primary": True,
                "primary_basis": "authoritative_source",
                "version": 1,
                "provenance": state.assignments[0].provenance,
            }
        ],
        "review_item_refs": [],
    }
    assert [company.company_id for company in filtered] == [
        "company-read-assigned",
        "company-read-review",
    ]
    assert page.total == 1
    assert [item.id for item in page.items] == [pending.review_item_id]
    assert page.next_cursor is None
    assert len(mappings) == 1
    assert mappings[0].source_site == "offertoday"
    assert mappings[0].normalized_key == "software consultancy"
    assert mappings[0].target_node_id == target.id
    assert mappings[0].decision_audit_id is not None


def test_versioned_company_industry_api_roundtrips_real_domain_contracts(
    company_industry_revision_db,
):
    revision = _activate_tiny_taxonomy(company_industry_revision_db)
    company = _company(company_industry_revision_db, "api")
    review_outcome = CompanyIndustry(company_industry_revision_db).ingest_evidence(
        company.id,
        _source_evidence(raw_label="Software consultancy"),
    )
    company_industry_revision_db.commit()
    target = (
        company_industry_revision_db.query(CompanyIndustryTaxonomyNode)
        .filter(CompanyIndustryTaxonomyNode.code == "620100")
        .one()
    )

    revision_response = read_company_industry_revision(db=company_industry_revision_db)
    tree_response = read_company_industry_tree(
        parent_id=None,
        db=company_industry_revision_db,
    )
    state_response = read_company_industry_state(
        company_id=company.id,
        db=company_industry_revision_db,
    )
    queue_response = list_company_industry_review_items(
        status=["active"],
        source_site=["offertoday"],
        reason=["unmapped_source_evidence"],
        company_id=company.id,
        raw_value=None,
        cursor=None,
        limit=50,
        db=company_industry_revision_db,
    )
    decision_response = decide_company_industry_review_item(
        review_item_id=review_outcome.review_item_id,
        request=CompanyIndustryDecisionRequestSchema(
            action="approve_mapping_and_assign",
            target_id=target.id,
            expected_version=1,
            idempotency_key="company-industry-api",
            confirmed=True,
        ),
        db=company_industry_revision_db,
    )
    mapping_response = list_company_industry_mappings(
        source_site=["offertoday"],
        status=["active"],
        db=company_industry_revision_db,
    )
    audit_response = list_company_industry_audit_events(
        subject_id=str(review_outcome.review_item_id),
        cursor=None,
        limit=50,
        db=company_industry_revision_db,
    )

    assert revision_response.id == revision.revision_id
    assert revision_response.counts.model_dump() == {
        "section": 1,
        "division": 1,
        "group": 1,
        "class": 1,
        "subclass": 1,
    }
    assert [node.code for node in tree_response.nodes] == ["J"]
    assert state_response.company_id == company.id
    assert state_response.assignments == []
    assert queue_response.total == 1
    assert queue_response.items[0].deep_link.endswith(
        str(review_outcome.review_item_id)
    )
    assert decision_response.resulting_projection["node_id"] == str(target.id)
    assert decision_response.replayed is False
    assert len(mapping_response) == 1
    assert mapping_response[0].target_node_id == target.id
    assert len(audit_response.items) == 1
    assert audit_response.items[0].actor == "local-operator"


def test_company_industry_api_returns_stable_error_codes(
    company_industry_revision_db,
):
    with pytest.raises(HTTPException) as inactive_error:
        read_company_industry_revision(db=company_industry_revision_db)
    assert inactive_error.value.status_code == 404
    assert inactive_error.value.detail["code"] == (
        "COMPANY_INDUSTRY_TAXONOMY_NOT_ACTIVE"
    )

    _activate_tiny_taxonomy(company_industry_revision_db)
    with pytest.raises(HTTPException) as parent_error:
        read_company_industry_tree(
            parent_id=uuid4(),
            db=company_industry_revision_db,
        )
    assert parent_error.value.status_code == 404
    assert parent_error.value.detail["code"] == "COMPANY_INDUSTRY_PARENT_NOT_FOUND"

    with pytest.raises(HTTPException) as company_error:
        read_company_industry_state(
            company_id=uuid4(),
            db=company_industry_revision_db,
        )
    assert company_error.value.status_code == 404
    assert company_error.value.detail["code"] == "COMPANY_INDUSTRY_COMPANY_NOT_FOUND"

    with pytest.raises(HTTPException) as review_error:
        read_company_industry_review_item(
            review_item_id=uuid4(),
            db=company_industry_revision_db,
        )
    assert review_error.value.status_code == 404
    assert review_error.value.detail["code"] == (
        "COMPANY_INDUSTRY_REVIEW_ITEM_NOT_FOUND"
    )

    with pytest.raises(HTTPException) as cursor_error:
        list_company_industry_review_items(
            status=["active"],
            source_site=None,
            reason=None,
            company_id=None,
            raw_value=None,
            cursor="not-a-valid-cursor",
            limit=50,
            db=company_industry_revision_db,
        )
    assert cursor_error.value.status_code == 422
    assert cursor_error.value.detail["code"] == (
        "COMPANY_INDUSTRY_REVIEW_CURSOR_INVALID"
    )

    with pytest.raises(HTTPException) as audit_cursor_error:
        list_company_industry_audit_events(
            subject_id=None,
            cursor="not-a-valid-cursor",
            limit=50,
            db=company_industry_revision_db,
        )
    assert audit_cursor_error.value.status_code == 422
    assert audit_cursor_error.value.detail["code"] == (
        "COMPANY_INDUSTRY_AUDIT_CURSOR_INVALID"
    )

    with pytest.raises(HTTPException) as missing_subject_error:
        decide_company_industry_review_item(
            review_item_id=uuid4(),
            request=CompanyIndustryDecisionRequestSchema(
                action="mark_insufficient_evidence",
                expected_version=1,
                idempotency_key="company-industry-api-missing-subject",
                confirmed=True,
            ),
            db=company_industry_revision_db,
        )
    assert missing_subject_error.value.status_code == 404
    assert missing_subject_error.value.detail["code"] == (
        "GOVERNANCE_DECISION_SUBJECT_NOT_FOUND"
    )

    company = _company(company_industry_revision_db, "api-errors")
    review = CompanyIndustry(company_industry_revision_db).ingest_evidence(
        company.id,
        _source_evidence(raw_label="API error evidence"),
    )
    company_industry_revision_db.commit()
    with pytest.raises(HTTPException) as stale_error:
        decide_company_industry_review_item(
            review_item_id=review.review_item_id,
            request=CompanyIndustryDecisionRequestSchema(
                action="mark_insufficient_evidence",
                expected_version=0,
                idempotency_key="company-industry-api-stale",
                confirmed=True,
            ),
            db=company_industry_revision_db,
        )
    assert stale_error.value.status_code == 409
    assert stale_error.value.detail["code"] == "GOVERNANCE_DECISION_STALE_VERSION"

    decide_company_industry_review_item(
        review_item_id=review.review_item_id,
        request=CompanyIndustryDecisionRequestSchema(
            action="mark_insufficient_evidence",
            expected_version=1,
            idempotency_key="company-industry-api-idempotency-conflict",
            confirmed=True,
        ),
        db=company_industry_revision_db,
    )
    with pytest.raises(HTTPException) as idempotency_error:
        decide_company_industry_review_item(
            review_item_id=review.review_item_id,
            request=CompanyIndustryDecisionRequestSchema(
                action="mark_not_company_industry",
                expected_version=1,
                idempotency_key="company-industry-api-idempotency-conflict",
                confirmed=True,
            ),
            db=company_industry_revision_db,
        )
    assert idempotency_error.value.status_code == 409
    assert idempotency_error.value.detail["code"] == "GOVERNANCE_IDEMPOTENCY_CONFLICT"


def test_manual_company_industry_is_preserved_as_review_evidence_only(
    company_industry_revision_db,
):
    _activate_tiny_taxonomy(company_industry_revision_db)

    created = asyncio.run(
        create_company(
            CompanyCreateSchema(
                name="Manual Industry Company",
                industry="Software consultancy",
            ),
            db=company_industry_revision_db,
        )
    )

    review = (
        company_industry_revision_db.query(CompanyIndustryReviewItem)
        .filter(CompanyIndustryReviewItem.company_id == created.id)
        .one()
    )
    assert created.industry == "Software consultancy"
    assert review.reason == "manual_evidence"
    assert review.status == "active"
    assert (
        company_industry_revision_db.query(CompanyIndustryAssignment)
        .filter(CompanyIndustryAssignment.company_id == created.id)
        .count()
        == 0
    )


def test_rebuild_inspector_classifies_legacy_evidence_without_writes(
    company_industry_revision_db,
):
    revision = _activate_tiny_taxonomy(company_industry_revision_db)
    target = (
        company_industry_revision_db.query(CompanyIndustryTaxonomyNode)
        .filter(CompanyIndustryTaxonomyNode.code == "620100")
        .one()
    )
    mapping = SourceIndustryMapping(
        source_site="offertoday",
        key_kind="label",
        raw_value="Software consultancy",
        normalized_key="software consultancy",
        taxonomy_revision_id=revision.revision_id,
        target_node_id=target.id,
        status="active",
        lock_version=1,
        approved_by="local-operator",
        approved_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )
    company_industry_revision_db.add(mapping)
    polluted = Company(
        company_id="rebuild-polluted",
        source_site="jobsdb",
        source_company_id="rebuild-polluted",
        name="Polluted",
        industry="Information Technology",
    )
    recoverable = Company(
        company_id="rebuild-recoverable",
        source_site="offertoday",
        source_company_id="rebuild-recoverable",
        name="Recoverable",
        industry="Software consultancy",
        extra_data={"raw_data": {"company_industry": "Software consultancy"}},
    )
    conflicting = Company(
        company_id="rebuild-conflicting",
        source_site="offertoday",
        source_company_id="rebuild-conflicting",
        name="Conflicting",
        industry="Financial services",
        extra_data={"raw_data": {"company_industry": "Software consultancy"}},
    )
    legacy = Company(
        company_id="rebuild-legacy",
        source_site="ctgoodjobs",
        source_company_id="rebuild-legacy",
        name="Legacy",
        industry="Miscellaneous activity",
    )
    empty = Company(
        company_id="rebuild-empty",
        source_site="jobsdb",
        source_company_id="rebuild-empty",
        name="Empty",
    )
    company_industry_revision_db.add_all(
        [polluted, recoverable, conflicting, legacy, empty]
    )
    company_industry_revision_db.flush()
    company_industry_revision_db.add(
        Job(
            job_id="rebuild-polluted-job",
            source_site="jobsdb",
            source_job_id="rebuild-polluted-job",
            company_id=polluted.id,
            title="Developer",
            source_classification_name="Information Technology",
        )
    )
    company_industry_revision_db.commit()
    before = {
        "assignments": company_industry_revision_db.query(
            CompanyIndustryAssignment
        ).count(),
        "reviews": company_industry_revision_db.query(
            CompanyIndustryReviewItem
        ).count(),
    }

    payload = (
        CompanyIndustryRebuildInspector(company_industry_revision_db)
        .inspect()
        .to_payload()
    )

    after = {
        "assignments": company_industry_revision_db.query(
            CompanyIndustryAssignment
        ).count(),
        "reviews": company_industry_revision_db.query(
            CompanyIndustryReviewItem
        ).count(),
    }
    assert payload == {
        "mode": "dry-run",
        "companies_inspected": 5,
        "active_revision_id": str(revision.revision_id),
        "evidence_states": {
            "conflicting": 1,
            "legacy_review": 1,
            "no_evidence": 1,
            "polluted": 1,
            "recoverable": 1,
        },
        "auto_mappable": 1,
        "review_required": 3,
        "primary_evidence": 0,
        "company_ids_by_state": {
            "conflicting": [str(conflicting.id)],
            "legacy_review": [str(legacy.id)],
            "no_evidence": [str(empty.id)],
            "polluted": [str(polluted.id)],
            "recoverable": [str(recoverable.id)],
        },
    }
    assert after == before


def test_company_industry_rebuild_cli_is_read_only_and_deterministic(
    monkeypatch,
    capsys,
):
    from scripts import inspect_company_industries

    payload = {
        "mode": "dry-run",
        "companies_inspected": 0,
        "active_revision_id": None,
        "evidence_states": {},
        "auto_mappable": 0,
        "review_required": 0,
        "primary_evidence": 0,
        "company_ids_by_state": {},
    }
    sessions = []

    class ReadOnlySession:
        closed = False

        def close(self):
            self.closed = True

    class Report:
        @staticmethod
        def to_payload():
            return payload

    class Inspector:
        def __init__(self, session):
            self.session = session

        def inspect(self, company_ids):
            assert company_ids is None
            return Report()

    def session_factory():
        session = ReadOnlySession()
        sessions.append(session)
        return session

    monkeypatch.setattr(inspect_company_industries, "SessionLocal", session_factory)
    monkeypatch.setattr(
        inspect_company_industries,
        "CompanyIndustryRebuildInspector",
        Inspector,
    )

    assert inspect_company_industries.main([]) == 0
    assert capsys.readouterr().out == (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    assert sessions[-1].closed is True

    assert inspect_company_industries.main(["--format", "human"]) == 0
    human_output = capsys.readouterr().out
    assert "Company Industry rebuild inspection (dry-run)" in human_output
    assert "evidence_states: {}" in human_output
    assert sessions[-1].closed is True

    session_count = len(sessions)
    for forbidden_option in ("--apply", "--execute", "--activate"):
        with pytest.raises(SystemExit) as exc_info:
            inspect_company_industries.main([forbidden_option])
        assert exc_info.value.code == 2
    assert len(sessions) == session_count


def test_compatibility_adapter_never_infers_primary_from_assignment_order(
    company_industry_revision_db,
):
    _activate_tiny_taxonomy(company_industry_revision_db)
    primary_company = _company(company_industry_revision_db, "compat-primary")
    ambiguous_company = _company(company_industry_revision_db, "compat-ambiguous")
    legacy_company = Company(
        company_id="compat-legacy",
        source_site="jobsdb",
        source_company_id="compat-legacy",
        name="Compat Legacy",
        industry="Legacy industry text",
    )
    company_industry_revision_db.add(legacy_company)
    module = CompanyIndustry(company_industry_revision_db)
    module.ingest_evidence(
        primary_company.id,
        _source_evidence(
            raw_code="620100",
            hsic_codes=("620100",),
            declares_primary=True,
        ),
    )
    for code in ("6201", "620100"):
        module.ingest_evidence(
            ambiguous_company.id,
            _source_evidence(
                raw_code=code,
                hsic_codes=(code,),
            ),
        )
    company_industry_revision_db.commit()
    adapter = CompanyIndustryCompatibilityAdapter(company_industry_revision_db)

    primary = adapter.project(primary_company.id)
    ambiguous = adapter.project(ambiguous_company.id)
    legacy = adapter.project(legacy_company.id)

    assert primary.authority == "governed_primary"
    assert primary.value == "Computer programming activities"
    assert ambiguous.authority == "ambiguous_governed"
    assert ambiguous.value is None
    assert legacy.authority == "legacy_evidence"
    assert legacy.value == "Legacy industry text"


def test_company_industry_backend_contract_fixture_roundtrips():
    fixture_path = (
        Path(__file__).parent / "fixtures" / "company_industry_responses.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    parsed = CompanyIndustryFixtureSchema.model_validate(fixture)

    assert parsed.model_dump(mode="json") == fixture
    assert parsed.tree.nodes[0].labels.zh_hant == "資訊及通訊"
    assert parsed.company_state.assignments[0].is_primary is True
    assert parsed.review_page.items[0].status == "active"
    assert parsed.mappings[0].approved_by == "local-operator"


def test_crosswalk_requires_explicit_revision_and_provenance_and_is_immutable(
    company_industry_revision_db,
):
    seed = build_hsic_seed(
        _five_level_official_payload(),
        retrieved_at="2026-07-19",
        raw_sha256="9" * 64,
        expected_counts={
            level: 1 for level in ("section", "division", "group", "class", "subclass")
        },
    )
    seed["crosswalks"] = [
        {
            "hsic_code": "620100",
            "target_standard": "ISIC",
            "target_release": "Rev.4",
            "target_code": "6201",
            "cardinality": "one_to_one",
            "method": "official",
            "confidence": 1.0,
            "provenance": {
                "source_url": "https://www.censtatd.gov.hk/en/page_698.html"
            },
        }
    ]
    seed["content_hash"] = seed_content_hash(seed)

    assert CompanyIndustryPublisher.validate(seed).to_payload() == {
        "valid": True,
        "issues": [],
    }
    revision = CompanyIndustryPublisher(company_industry_revision_db).materialize(seed)
    edge = company_industry_revision_db.query(CompanyIndustryCrosswalkEdge).one()
    assert edge.taxonomy_revision_id == revision.revision_id
    assert (edge.target_standard, edge.target_release, edge.target_code) == (
        "ISIC",
        "Rev.4",
        "6201",
    )
    edge.target_release = "Rev.5"
    with pytest.raises(ValueError, match="immutable"):
        company_industry_revision_db.flush()
    company_industry_revision_db.rollback()

    invalid = deepcopy(seed)
    invalid["crosswalks"][0]["hsic_code"] = "999999"
    invalid["crosswalks"][0]["target_release"] = ""
    invalid["crosswalks"][0]["method"] = "inferred"
    invalid["crosswalks"][0]["provenance"] = {}
    invalid["content_hash"] = seed_content_hash(invalid)
    assert [
        issue["code"]
        for issue in CompanyIndustryPublisher.validate(invalid).to_payload()["issues"]
    ] == [
        "company_industry_crosswalk_hsic_unknown",
        "company_industry_crosswalk_method_invalid",
        "company_industry_crosswalk_provenance_missing",
        "company_industry_crosswalk_target_missing",
    ]


def test_committed_hsic_seed_materializes_all_nodes_and_real_breadcrumb(
    company_industry_revision_db,
):
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    publisher = CompanyIndustryPublisher(company_industry_revision_db)

    revision = publisher.materialize(seed)
    publisher.activate(revision, expected_lock_version=0)
    leaf = (
        company_industry_revision_db.query(CompanyIndustryTaxonomyNode)
        .filter(
            CompanyIndustryTaxonomyNode.revision_id == revision.revision_id,
            CompanyIndustryTaxonomyNode.code == "620101",
        )
        .one()
    )
    breadcrumb = CompanyIndustry(company_industry_revision_db).get_breadcrumb(leaf.id)

    assert (
        company_industry_revision_db.query(CompanyIndustryTaxonomyNode)
        .filter(CompanyIndustryTaxonomyNode.revision_id == revision.revision_id)
        .count()
        == 1814
    )
    assert [node.code for node in breadcrumb] == [
        "J",
        "62",
        "620",
        "6201",
        "620101",
    ]
    assert breadcrumb[-1].labels == {
        "en": "Development of computer games",
        "zh_hant": "電腦遊戲開發",
        "zh_hans": "电脑游戏开发",
    }
