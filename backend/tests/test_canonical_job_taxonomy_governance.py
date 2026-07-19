import asyncio
import ast
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.job_intelligence.foundation import DecisionCommand, Provenance
from app.job_intelligence.canonical_taxonomy import (
    CanonicalClassifierOutput,
    CanonicalJobTaxonomy,
    CanonicalTaxonomyRebuildInspector,
    CanonicalTaxonomyDecisionAdapter,
    CanonicalTaxonomyPreflight,
    CanonicalMappingActivationConflict,
    CanonicalMappingCoverageError,
    CanonicalTaxonomyActivationConflict,
    CanonicalTaxonomyPublisher,
)
from app.job_intelligence.canonical_taxonomy.breadcrumbs import canonical_breadcrumb
from app.job_intelligence.source_attributes import (
    SourceCatalogRevisionRef,
    SourceClassificationNodeEvidence,
    SourceClassificationPathEvidence,
    SourceJobAttributeEvidence,
    SourceJobAttributes,
)
from app.models.company import Company
from app.models.crawl_job_listing import CrawlJobListing
from app.models.canonical_job_taxonomy import (
    CANONICAL_JOB_TAXONOMY_TABLES,
    CanonicalJobCategory,
    CanonicalJobDomain,
    CanonicalJobSubcategory,
    CanonicalJobTaxonomyActiveMappingRevision,
    CanonicalJobTaxonomyActiveRevision,
    CanonicalJobTaxonomyMappingCoverage,
    CanonicalJobTaxonomyMappingRevision,
    CanonicalJobTaxonomyRelease,
    JobTaxonomyAssignment,
    JobTaxonomyReviewItem,
    SourceJobTaxonomyMapping,
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
from app.models.source_catalog import (
    SourceCatalogActiveRevision,
    SourceCatalogCandidate,
    SourceCatalogRevision,
)
from app.models.source_job_attributes import SOURCE_JOB_ATTRIBUTE_TABLES
from app.source_catalog.domain import (
    CatalogNodeSnapshot,
    CatalogScopeCapabilities,
    DiscoveredCatalog,
)


SEED_PATH = Path(__file__).parents[1] / "app" / "data" / "job_category_taxonomy.json"
MAPPING_PATH = (
    Path(__file__).parents[1] / "app" / "data" / "job_source_taxonomy_mapping.json"
)
ACCOUNTING_TARGET = "accounting.financial_accounting.accounts_payable"
ADMINISTRATION_TARGET = (
    "administration_office_support.administrative_support.administrative_assistant"
)
BANKING_TARGET = "banking_financial_services.banking.retail_banking"


@pytest.fixture
def canonical_taxonomy_db():
    database_url = os.getenv("JOB_INTELLIGENCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("JOB_INTELLIGENCE_TEST_DATABASE_URL is not configured")

    engine = create_engine(database_url)
    tables = (
        Company.__table__,
        JobDomain.__table__,
        JobCategory.__table__,
        JobSubcategory.__table__,
        Job.__table__,
        CrawlJobListing.__table__,
        EventOutbox.__table__,
        SourceCatalogCandidate.__table__,
        SourceCatalogRevision.__table__,
        SourceCatalogActiveRevision.__table__,
        *GOVERNANCE_FOUNDATION_TABLES,
        *CANONICAL_JOB_TAXONOMY_TABLES,
        *SOURCE_JOB_ATTRIBUTE_TABLES,
    )
    Base.metadata.drop_all(engine, tables=list(reversed(tables)), checkfirst=True)
    Base.metadata.create_all(engine, tables=list(tables))
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine, tables=list(reversed(tables)), checkfirst=True)
        engine.dispose()


def test_committed_seed_is_a_valid_explicit_code_release():
    seed = json.loads(SEED_PATH.read_text())

    report = CanonicalTaxonomyPublisher.validate(seed)

    assert report.to_payload() == {"valid": True, "issues": []}
    assert seed["expected_counts"] == {
        "domains": 25,
        "categories": 63,
        "subcategories": 198,
    }

    domains = seed["domains"]
    categories = [category for domain in domains for category in domain["categories"]]
    subcategories = [
        subcategory
        for category in categories
        for subcategory in category["subcategories"]
    ]

    assert (len(domains), len(categories), len(subcategories)) == (25, 63, 198)
    assert all(
        {"code", "label", "order", "categories"} <= domain.keys() for domain in domains
    )
    assert all(
        {"code", "label", "order", "subcategories"} <= category.keys()
        for category in categories
    )
    assert all(
        {"code", "label", "order", "is_assignable"} <= subcategory.keys()
        for subcategory in subcategories
    )
    assert all(subcategory["is_assignable"] is True for subcategory in subcategories)
    assert not {node["label"] for node in [*domains, *categories, *subcategories]} & {
        "General",
        "Unknown",
    }

    project_management_codes = {
        subcategory["code"]
        for subcategory in subcategories
        if subcategory["label"] == "Project Management"
    }
    assert len(project_management_codes) == 2


def test_committed_mapping_seed_uses_explicit_reviewed_dispositions():
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())

    report = CanonicalTaxonomyPublisher.validate(seed, mapping_seed)

    assert report.to_payload() == {
        "valid": True,
        "issues": [
            {
                "json_path": ("$.legacy_discrepancies.ctgoodjobs_proposal_only_ids"),
                "code": "canonical_mapping_legacy_discrepancy",
                "message": (
                    "15 CTgoodjobs IDs exist only in legacy proposed-domain metadata"
                ),
                "related_id": None,
                "severity": "warning",
            }
        ],
    }
    assert mapping_seed["taxonomy_release_key"] == seed["release_key"]
    assert mapping_seed["expected_counts"] == {
        "entries": 68,
        "deterministic": 0,
        "allowed_slice": 62,
        "excluded": 6,
        "unmapped": 0,
    }

    entries = mapping_seed["entries"]
    assert len(entries) == 68
    assert len({entry["source_classification_id"] for entry in entries}) == 68
    assert all(
        entry["source_classification_id"].startswith(f"{entry['source_site']}:")
        for entry in entries
    )

    leaf_codes = [
        subcategory["code"]
        for domain in seed["domains"]
        for category in domain["categories"]
        for subcategory in category["subcategories"]
    ]
    leaf_order = {code: index for index, code in enumerate(leaf_codes)}
    for entry in entries:
        target_codes = entry["target_codes"]
        if entry["disposition"] == "allowed_slice":
            assert target_codes
            assert target_codes == sorted(target_codes, key=leaf_order.__getitem__)
        else:
            assert entry["disposition"] == "excluded"
            assert target_codes == []
        assert set(target_codes) <= set(leaf_codes)

    assert mapping_seed["legacy_discrepancies"]["ctgoodjobs_proposal_only_ids"] == [
        "ctgoodjobs:002",
        "ctgoodjobs:003",
        "ctgoodjobs:004",
        "ctgoodjobs:010",
        "ctgoodjobs:013",
        "ctgoodjobs:017",
        "ctgoodjobs:025",
        "ctgoodjobs:028",
        "ctgoodjobs:029",
        "ctgoodjobs:038",
        "ctgoodjobs:041",
        "ctgoodjobs:043",
        "ctgoodjobs:049",
        "ctgoodjobs:051",
        "ctgoodjobs:052",
    ]


def test_canonical_taxonomy_models_register_the_additive_schema():
    assert [table.name for table in CANONICAL_JOB_TAXONOMY_TABLES] == [
        "canonical_job_taxonomy_releases",
        "canonical_job_taxonomy_active_revisions",
        "canonical_job_domains",
        "canonical_job_categories",
        "canonical_job_subcategories",
        "canonical_job_taxonomy_mapping_revisions",
        "canonical_job_taxonomy_mapping_coverages",
        "source_job_taxonomy_mappings",
        "source_job_taxonomy_mapping_targets",
        "canonical_job_taxonomy_active_mapping_revisions",
        "job_taxonomy_assignments",
        "job_taxonomy_review_items",
    ]


def test_materialize_is_idempotent_and_leaves_a_complete_release_inactive(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)

    first = publisher.materialize(seed)
    replay = publisher.materialize(seed)

    assert replay == first
    release = canonical_taxonomy_db.get(
        CanonicalJobTaxonomyRelease,
        first.revision_id,
    )
    assert release is not None
    assert {
        "status": release.status,
        "content_hash": release.content_hash,
        "expected_counts": (
            release.expected_domain_count,
            release.expected_category_count,
            release.expected_subcategory_count,
        ),
        "materialized_counts": (
            release.materialized_domain_count,
            release.materialized_category_count,
            release.materialized_subcategory_count,
        ),
    } == {
        "status": "ready",
        "content_hash": first.content_hash,
        "expected_counts": (25, 63, 198),
        "materialized_counts": (25, 63, 198),
    }
    assert (
        canonical_taxonomy_db.scalar(
            select(func.count()).select_from(CanonicalJobDomain)
        )
        == 25
    )
    assert (
        canonical_taxonomy_db.scalar(
            select(func.count()).select_from(CanonicalJobCategory)
        )
        == 63
    )
    assert (
        canonical_taxonomy_db.scalar(
            select(func.count()).select_from(CanonicalJobSubcategory)
        )
        == 198
    )
    assert (
        canonical_taxonomy_db.get(
            CanonicalJobTaxonomyActiveRevision,
            "canonical-job-taxonomy",
        )
        is None
    )


def test_failed_materialization_keeps_only_revision_identity_and_exact_retry_succeeds(
    canonical_taxonomy_db,
    monkeypatch,
):
    seed = json.loads(SEED_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    original_add_node = publisher._add_node_if_missing
    add_calls = 0

    def fail_after_first_node(model, node_id, **values):
        nonlocal add_calls
        original_add_node(model, node_id, **values)
        add_calls += 1
        if add_calls == 1:
            raise RuntimeError("forced taxonomy materialization failure")

    monkeypatch.setattr(publisher, "_add_node_if_missing", fail_after_first_node)

    with pytest.raises(
        RuntimeError,
        match="forced taxonomy materialization failure",
    ):
        publisher.materialize(seed)

    revision = canonical_taxonomy_db.scalar(
        select(GovernanceRevision).where(
            GovernanceRevision.domain == "canonical-job-taxonomy",
            GovernanceRevision.release_key == seed["release_key"],
        )
    )
    assert revision is not None
    assert revision.status == "published"
    assert len(revision.content_hash) == 64
    assert canonical_taxonomy_db.get(CanonicalJobTaxonomyRelease, revision.id) is None
    assert {
        "domains": canonical_taxonomy_db.scalar(
            select(func.count())
            .select_from(CanonicalJobDomain)
            .where(CanonicalJobDomain.revision_id == revision.id)
        ),
        "categories": canonical_taxonomy_db.scalar(
            select(func.count())
            .select_from(CanonicalJobCategory)
            .where(CanonicalJobCategory.revision_id == revision.id)
        ),
        "subcategories": canonical_taxonomy_db.scalar(
            select(func.count())
            .select_from(CanonicalJobSubcategory)
            .where(CanonicalJobSubcategory.revision_id == revision.id)
        ),
    } == {"domains": 0, "categories": 0, "subcategories": 0}
    assert (
        canonical_taxonomy_db.get(
            CanonicalJobTaxonomyActiveRevision,
            "canonical-job-taxonomy",
        )
        is None
    )

    monkeypatch.setattr(publisher, "_add_node_if_missing", original_add_node)
    retry = publisher.materialize(seed)

    release = canonical_taxonomy_db.get(CanonicalJobTaxonomyRelease, revision.id)
    assert retry.revision_id == revision.id
    assert retry.content_hash == revision.content_hash
    assert release is not None
    assert (
        release.status,
        release.materialized_domain_count,
        release.materialized_category_count,
        release.materialized_subcategory_count,
    ) == ("ready", 25, 63, 198)
    assert (
        canonical_taxonomy_db.query(GovernanceRevision)
        .filter_by(
            domain="canonical-job-taxonomy",
            release_key=seed["release_key"],
        )
        .count()
        == 1
    )


def test_activation_uses_compare_and_swap_without_recomputing_codes(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    first = publisher.materialize(seed)
    publisher.activate(first, expected_lock_version=0)

    renamed_seed = deepcopy(seed)
    renamed_seed["release_key"] = "canonical-job-taxonomy-v2"
    renamed_seed["domains"][0]["label"] = "Accounting & Audit"
    second = publisher.materialize(renamed_seed)
    publisher.activate(second, expected_lock_version=1)

    with pytest.raises(CanonicalTaxonomyActivationConflict):
        publisher.activate(first, expected_lock_version=1)

    canonical_taxonomy_db.expire_all()
    active = canonical_taxonomy_db.get(
        CanonicalJobTaxonomyActiveRevision,
        "canonical-job-taxonomy",
    )
    assert active is not None
    assert (active.revision_id, active.content_hash, active.lock_version) == (
        second.revision_id,
        second.content_hash,
        2,
    )
    accounting_snapshots = canonical_taxonomy_db.scalars(
        select(CanonicalJobDomain)
        .where(CanonicalJobDomain.code == "accounting")
        .order_by(CanonicalJobDomain.label)
    ).all()
    assert [snapshot.label for snapshot in accounting_snapshots] == [
        "Accounting",
        "Accounting & Audit",
    ]


def test_explicit_subcategory_code_does_not_drift_when_reparented(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    first = publisher.materialize(seed)

    reparented_seed = deepcopy(seed)
    reparented_seed["release_key"] = "canonical-job-taxonomy-v2-reparent"
    accounting = next(
        domain
        for domain in reparented_seed["domains"]
        if domain["code"] == "accounting"
    )
    audit_tax = next(
        category
        for category in accounting["categories"]
        if category["code"] == "accounting.audit_tax"
    )
    financial_accounting = next(
        category
        for category in accounting["categories"]
        if category["code"] == "accounting.financial_accounting"
    )
    moved = next(
        subcategory
        for subcategory in audit_tax["subcategories"]
        if subcategory["code"] == "accounting.audit_tax.audit"
    )
    audit_tax["subcategories"].remove(moved)
    for order, subcategory in enumerate(audit_tax["subcategories"], start=1):
        subcategory["order"] = order
    moved["order"] = len(financial_accounting["subcategories"]) + 1
    financial_accounting["subcategories"].append(moved)

    assert CanonicalTaxonomyPublisher.validate(reparented_seed).to_payload() == {
        "valid": True,
        "issues": [],
    }
    second = publisher.materialize(reparented_seed)

    stable_code = "accounting.audit_tax.audit"
    first_node = canonical_taxonomy_db.scalar(
        select(CanonicalJobSubcategory).where(
            CanonicalJobSubcategory.revision_id == first.revision_id,
            CanonicalJobSubcategory.code == stable_code,
        )
    )
    second_node = canonical_taxonomy_db.scalar(
        select(CanonicalJobSubcategory).where(
            CanonicalJobSubcategory.revision_id == second.revision_id,
            CanonicalJobSubcategory.code == stable_code,
        )
    )
    assert first_node is not None
    assert second_node is not None
    first_parent = canonical_taxonomy_db.get(
        CanonicalJobCategory,
        first_node.category_id,
    )
    second_parent = canonical_taxonomy_db.get(
        CanonicalJobCategory,
        second_node.category_id,
    )
    assert first_parent is not None
    assert second_parent is not None
    assert (first_node.code, second_node.code, second_node.label) == (
        stable_code,
        stable_code,
        "Audit",
    )
    assert (first_parent.code, second_parent.code) == (
        "accounting.audit_tax",
        "accounting.financial_accounting",
    )


def test_mapping_materialization_pins_exact_catalog_coverage_and_stays_inactive(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)

    first = publisher.materialize_mapping(seed, mapping_seed)
    replay = publisher.materialize_mapping(seed, mapping_seed)

    assert replay == first
    mapping_revision = canonical_taxonomy_db.get(
        CanonicalJobTaxonomyMappingRevision,
        first.revision_id,
    )
    assert mapping_revision is not None
    target_count = sum(len(entry["target_codes"]) for entry in mapping_seed["entries"])
    assert {
        "status": mapping_revision.status,
        "taxonomy_revision_id": mapping_revision.taxonomy_revision_id,
        "expected_counts": (
            mapping_revision.expected_coverage_count,
            mapping_revision.expected_entry_count,
            mapping_revision.expected_target_count,
        ),
        "materialized_counts": (
            mapping_revision.materialized_coverage_count,
            mapping_revision.materialized_entry_count,
            mapping_revision.materialized_target_count,
        ),
    } == {
        "status": "ready",
        "taxonomy_revision_id": taxonomy_revision.revision_id,
        "expected_counts": (3, 68, target_count),
        "materialized_counts": (3, 68, target_count),
    }
    coverages = canonical_taxonomy_db.scalars(
        select(CanonicalJobTaxonomyMappingCoverage).order_by(
            CanonicalJobTaxonomyMappingCoverage.source_site
        )
    ).all()
    assert {
        coverage.source_site: coverage.identity_count for coverage in coverages
    } == {"ctgoodjobs": 12, "jobsdb": 25, "offertoday": 31}
    assert all(
        len(coverage.source_catalog_fingerprint) == 64
        and len(coverage.identity_set_hash) == 64
        for coverage in coverages
    )
    assert (
        canonical_taxonomy_db.get(
            CanonicalJobTaxonomyActiveMappingRevision,
            "canonical-job-taxonomy-mapping",
        )
        is None
    )


def test_mapping_materialization_rejects_persisted_catalog_fingerprint_mismatch(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(
        canonical_taxonomy_db,
        mapping_seed,
        revision_fingerprint_overrides={"jobsdb": "0" * 64},
    )

    with pytest.raises(CanonicalMappingCoverageError) as exc_info:
        publisher.materialize_mapping(seed, mapping_seed)

    assert (exc_info.value.code, exc_info.value.source_site) == (
        "CATALOG_FINGERPRINT_MISMATCH",
        "jobsdb",
    )
    assert canonical_taxonomy_db.query(CanonicalJobTaxonomyMappingRevision).count() == 0


def test_mapping_activation_fails_closed_when_a_pinned_catalog_is_unpublished(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)

    active = publisher.activate_mapping(
        mapping_revision,
        expected_lock_version=0,
    )
    assert active.lock_version == 1

    jobsdb_pointer = canonical_taxonomy_db.get(
        SourceCatalogActiveRevision,
        "jobsdb",
    )
    assert jobsdb_pointer is not None
    canonical_taxonomy_db.delete(jobsdb_pointer)
    canonical_taxonomy_db.commit()

    with pytest.raises(CanonicalMappingCoverageError) as exc_info:
        publisher.activate_mapping(
            mapping_revision,
            expected_lock_version=1,
        )
    assert (exc_info.value.code, exc_info.value.source_site) == (
        "CATALOG_NOT_PUBLISHED",
        "jobsdb",
    )


def test_mapping_materialization_rejects_missing_and_extra_catalog_identities(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)

    missing_seed = _without_mapping_entry(mapping_seed, "ctgoodjobs:001")
    with pytest.raises(CanonicalMappingCoverageError) as missing_error:
        publisher.materialize_mapping(seed, missing_seed)
    assert {
        "code": missing_error.value.code,
        "source_site": missing_error.value.source_site,
        "missing": missing_error.value.missing,
        "extra": missing_error.value.extra,
    } == {
        "code": "CANONICAL_MAPPING_COVERAGE_MISMATCH",
        "source_site": "ctgoodjobs",
        "missing": ("ctgoodjobs:001",),
        "extra": (),
    }

    extra_seed = _with_extra_excluded_mapping(
        mapping_seed,
        source_site="ctgoodjobs",
        source_classification_id="ctgoodjobs:999",
        source_label="Fixture Extra",
    )
    with pytest.raises(CanonicalMappingCoverageError) as extra_error:
        publisher.materialize_mapping(seed, extra_seed)
    assert {
        "code": extra_error.value.code,
        "source_site": extra_error.value.source_site,
        "missing": extra_error.value.missing,
        "extra": extra_error.value.extra,
    } == {
        "code": "CANONICAL_MAPPING_COVERAGE_MISMATCH",
        "source_site": "ctgoodjobs",
        "missing": (),
        "extra": ("ctgoodjobs:999",),
    }


def test_mapping_activation_compare_and_swap_rejects_a_stale_pointer_version(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    first = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(first, expected_lock_version=0)
    second_seed = deepcopy(mapping_seed)
    second_seed["release_key"] = "canonical-source-mapping-v2"
    second = publisher.materialize_mapping(seed, second_seed)
    publisher.activate_mapping(second, expected_lock_version=1)

    with pytest.raises(CanonicalMappingActivationConflict) as exc_info:
        publisher.activate_mapping(first, expected_lock_version=1)
    assert (exc_info.value.expected, exc_info.value.actual) == (1, 2)


def test_evaluate_assigns_one_convergent_reviewed_mapping_without_legacy_write(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = _with_deterministic_mapping(
        json.loads(MAPPING_PATH.read_text()),
        "ctgoodjobs:001",
        "accounting.financial_accounting.financial_accounting",
    )
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    company = Company(
        company_id="canonical-company-1",
        source_site="ctgoodjobs",
        source_company_id="canonical-company-1",
        name="Canonical Company",
    )
    job = Job(
        job_id="canonical-job-1",
        source_site="ctgoodjobs",
        source_job_id="canonical-job-1",
        company=company,
        title="Financial Accountant",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    source_view = _project_source_path(
        canonical_taxonomy_db,
        job,
        source_classification_id="ctgoodjobs:001",
        label="Accounting",
    )

    result = CanonicalJobTaxonomy(canonical_taxonomy_db).evaluate(
        job.id,
        source_view,
    )

    assignment = canonical_taxonomy_db.get(
        JobTaxonomyAssignment,
        result.assignment_id,
    )
    assert assignment is not None
    assert {
        "result": (result.state, result.changed, result.replayed, result.version),
        "method": assignment.method,
        "taxonomy_revision_id": assignment.taxonomy_revision_id,
        "mapping_revision_id": assignment.mapping_revision_id,
        "breadcrumb": {
            level: {
                "code": node["code"],
                "label": node["label"],
            }
            for level, node in assignment.breadcrumb.items()
        },
        "model": (
            assignment.model_provider,
            assignment.model_name,
            assignment.model_version,
        ),
        "legacy_subcategory_id": job.subcategory_id,
    } == {
        "result": ("assigned", True, False, 1),
        "method": "reviewed_mapping",
        "taxonomy_revision_id": taxonomy_revision.revision_id,
        "mapping_revision_id": mapping_revision.revision_id,
        "breadcrumb": {
            "domain": {
                "code": "accounting",
                "label": "Accounting",
            },
            "category": {
                "code": "accounting.financial_accounting",
                "label": "Financial Accounting",
            },
            "subcategory": {
                "code": "accounting.financial_accounting.financial_accounting",
                "label": "Financial Accounting",
            },
        },
        "model": (None, None, None),
        "legacy_subcategory_id": None,
    }
    assert len(assignment.mapping_ids) == 1
    assert assignment.breadcrumb["subcategory"]["id"] == str(assignment.subcategory_id)
    assert assignment.source_evidence_refs == [
        {
            "kind": "source-classification-path",
            "id": str(source_view.source_classification_paths[0].id),
            "source_site": "ctgoodjobs",
            "source_order": 1,
            "source_catalog_revision_id": str(
                source_view.source_classification_paths[
                    0
                ].source_catalog_revision.revision_id
            ),
            "source_classification_ids": ["ctgoodjobs:001"],
        }
    ]
    canonical_events = (
        canonical_taxonomy_db.query(EventOutbox)
        .filter(EventOutbox.event_type == "job.canonical_taxonomy_changed")
        .all()
    )
    assert len(canonical_events) == 1
    assert canonical_events[0].payload == {
        "job_id": str(job.id),
        "state": "assigned",
        "assignment_id": str(assignment.id),
        "taxonomy_revision_id": str(taxonomy_revision.revision_id),
        "mapping_revision_id": str(mapping_revision.revision_id),
        "evidence_hash": assignment.evidence_hash,
        "version": 1,
        "invalidate": ["canonical-taxonomy-read-model", "job-embedding"],
    }


def test_evaluate_conflicting_deterministic_paths_creates_review_not_assignment(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = _with_deterministic_mapping(
        json.loads(MAPPING_PATH.read_text()),
        "ctgoodjobs:001",
        "accounting.financial_accounting.financial_accounting",
    )
    mapping_seed = _with_deterministic_mapping(
        mapping_seed,
        "ctgoodjobs:007",
        "banking_financial_services.banking.retail_banking",
    )
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    company = Company(
        company_id="canonical-company-conflict",
        source_site="ctgoodjobs",
        source_company_id="canonical-company-conflict",
        name="Conflicting Mapping Company",
    )
    job = Job(
        job_id="canonical-job-conflict",
        source_site="ctgoodjobs",
        source_job_id="canonical-job-conflict",
        company=company,
        title="Finance Operations Lead",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    source_view = _project_source_paths(
        canonical_taxonomy_db,
        job,
        paths=(
            ("ctgoodjobs:001", "Accounting"),
            ("ctgoodjobs:007", "Banking & Financial Services"),
        ),
    )

    result = CanonicalJobTaxonomy(canonical_taxonomy_db).evaluate(
        job.id,
        source_view,
    )

    review = canonical_taxonomy_db.get(JobTaxonomyReviewItem, result.review_item_id)
    assert review is not None
    assert {
        "result": (
            result.state,
            result.changed,
            result.replayed,
            result.version,
            result.reasons,
        ),
        "status": review.status,
        "reasons": review.reasons,
        "taxonomy_revision_id": review.taxonomy_revision_id,
        "mapping_revision_id": review.mapping_revision_id,
        "recommendation_codes": [item["code"] for item in review.recommendations],
        "assignment_count": canonical_taxonomy_db.query(JobTaxonomyAssignment).count(),
        "legacy_subcategory_id": job.subcategory_id,
    } == {
        "result": (
            "unassigned",
            True,
            False,
            1,
            ("conflicting_mapping",),
        ),
        "status": "active",
        "reasons": ["conflicting_mapping"],
        "taxonomy_revision_id": taxonomy_revision.revision_id,
        "mapping_revision_id": mapping_revision.revision_id,
        "recommendation_codes": [
            "accounting.financial_accounting.financial_accounting",
            "banking_financial_services.banking.retail_banking",
        ],
        "assignment_count": 0,
        "legacy_subcategory_id": None,
    }
    assert len(review.evidence_refs) == 2
    canonical_events = (
        canonical_taxonomy_db.query(EventOutbox)
        .filter(EventOutbox.event_type == "job.canonical_taxonomy_changed")
        .all()
    )
    assert len(canonical_events) == 1
    assert canonical_events[0].payload == {
        "job_id": str(job.id),
        "state": "unassigned",
        "review_item_id": str(review.id),
        "taxonomy_revision_id": str(taxonomy_revision.revision_id),
        "mapping_revision_id": str(mapping_revision.revision_id),
        "evidence_hash": review.evidence_hash,
        "version": 1,
        "reasons": ["conflicting_mapping"],
        "invalidate": ["canonical-taxonomy-read-model", "job-embedding"],
    }


@pytest.mark.parametrize(
    (
        "case_id",
        "mapping_changes",
        "classifier_target",
        "expected_outcome",
    ),
    (
        pytest.param(
            "convergent_deterministic",
            (
                ("ctgoodjobs:001", "deterministic", (ACCOUNTING_TARGET,)),
                ("ctgoodjobs:048", "deterministic", (ACCOUNTING_TARGET,)),
            ),
            None,
            ("assigned", "reviewed_mapping", ACCOUNTING_TARGET, (), 2),
            id="convergent-deterministic",
        ),
        pytest.param(
            "deterministic_allowed_compatible",
            (
                ("ctgoodjobs:001", "deterministic", (ACCOUNTING_TARGET,)),
                (
                    "ctgoodjobs:048",
                    "allowed_slice",
                    (ACCOUNTING_TARGET, ADMINISTRATION_TARGET),
                ),
            ),
            None,
            ("assigned", "reviewed_mapping", ACCOUNTING_TARGET, (), 2),
            id="deterministic-plus-compatible-allowed",
        ),
        pytest.param(
            "deterministic_allowed_conflict",
            (
                ("ctgoodjobs:001", "deterministic", (ACCOUNTING_TARGET,)),
                ("ctgoodjobs:048", "allowed_slice", (ADMINISTRATION_TARGET,)),
            ),
            None,
            ("unassigned", None, None, ("conflicting_mapping",), None),
            id="deterministic-plus-incompatible-allowed",
        ),
        pytest.param(
            "allowed_union_ai",
            (),
            ADMINISTRATION_TARGET,
            ("assigned", "constrained_ai", ADMINISTRATION_TARGET, (), 2),
            id="allowed-union-constrained-ai",
        ),
        pytest.param(
            "allowed_union_out_of_slice",
            (),
            BANKING_TARGET,
            (
                "unassigned",
                None,
                None,
                ("classifier_target_out_of_slice",),
                None,
            ),
            id="allowed-union-out-of-slice",
        ),
        pytest.param(
            "excluded_blocks_deterministic",
            (
                ("ctgoodjobs:001", "deterministic", (ACCOUNTING_TARGET,)),
                ("ctgoodjobs:048", "excluded", ()),
            ),
            None,
            ("unassigned", None, None, ("source_mapping_excluded",), None),
            id="excluded-blocks-deterministic",
        ),
        pytest.param(
            "unmapped_blocks_deterministic",
            (
                ("ctgoodjobs:001", "deterministic", (ACCOUNTING_TARGET,)),
                ("ctgoodjobs:048", "unmapped", ()),
            ),
            None,
            ("unassigned", None, None, ("source_mapping_unmapped",), None),
            id="unmapped-blocks-deterministic",
        ),
    ),
)
def test_multi_path_mapping_truth_table_is_complete_and_path_order_independent(
    canonical_taxonomy_db,
    case_id,
    mapping_changes,
    classifier_target,
    expected_outcome,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    for source_id, disposition, target_codes in mapping_changes:
        entry = next(
            item
            for item in mapping_seed["entries"]
            if item["source_classification_id"] == source_id
        )
        previous_disposition = entry["disposition"]
        if previous_disposition != disposition:
            mapping_seed["expected_counts"][previous_disposition] -= 1
            mapping_seed["expected_counts"][disposition] += 1
        entry["disposition"] = disposition
        entry["target_codes"] = list(target_codes)

    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    company = Company(
        company_id=f"canonical-truth-table-company-{case_id}",
        source_site="ctgoodjobs",
        source_company_id=f"canonical-truth-table-company-{case_id}",
        name=f"Canonical Truth Table Company {case_id}",
    )
    forward_job = Job(
        job_id=f"canonical-truth-table-{case_id}-forward",
        source_site="ctgoodjobs",
        source_job_id=f"canonical-truth-table-{case_id}-forward",
        company=company,
        title="Multi-path canonical truth table role",
    )
    reverse_job = Job(
        job_id=f"canonical-truth-table-{case_id}-reverse",
        source_site="ctgoodjobs",
        source_job_id=f"canonical-truth-table-{case_id}-reverse",
        company=company,
        title="Multi-path canonical truth table role",
    )
    canonical_taxonomy_db.add_all((forward_job, reverse_job))
    canonical_taxonomy_db.flush()
    paths = (
        ("ctgoodjobs:001", "Accounting"),
        ("ctgoodjobs:048", "Administration & Office Support"),
    )
    forward_view = _project_source_paths(
        canonical_taxonomy_db,
        forward_job,
        paths=paths,
    )
    reverse_view = _project_source_paths(
        canonical_taxonomy_db,
        reverse_job,
        paths=tuple(reversed(paths)),
    )

    def classifier_output(evidence_id):
        if classifier_target is None:
            return None
        return CanonicalClassifierOutput(
            decision="select_existing",
            target_code=classifier_target,
            provenance=Provenance(
                method="constrained-ai",
                source_site="ctgoodjobs",
                evidence_refs=({"kind": "classifier-response", "id": evidence_id},),
                model_provider="openai",
                model_name="gpt-5-mini",
                model_version="2026-07-01",
                captured_at=datetime(2026, 7, 19, 10, 35, tzinfo=timezone.utc),
            ),
        )

    module = CanonicalJobTaxonomy(canonical_taxonomy_db)
    forward = module.evaluate(
        forward_job.id,
        forward_view,
        classifier_output(f"{case_id}-forward"),
    )
    reverse = module.evaluate(
        reverse_job.id,
        reverse_view,
        classifier_output(f"{case_id}-reverse"),
    )

    def outcome(result):
        if result.state == "assigned":
            assignment = canonical_taxonomy_db.get(
                JobTaxonomyAssignment,
                result.assignment_id,
            )
            assert assignment is not None
            return (
                result.state,
                assignment.method,
                assignment.breadcrumb["subcategory"]["code"],
                result.reasons,
                len(assignment.mapping_ids),
            )
        return (result.state, None, None, result.reasons, None)

    assert outcome(forward) == expected_outcome
    assert outcome(reverse) == expected_outcome


def test_evaluate_accepts_provenanced_ai_choice_inside_allowed_slice(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    company = Company(
        company_id="canonical-company-ai",
        source_site="ctgoodjobs",
        source_company_id="canonical-company-ai",
        name="Constrained AI Company",
    )
    job = Job(
        job_id="canonical-job-ai",
        source_site="ctgoodjobs",
        source_job_id="canonical-job-ai",
        company=company,
        title="Accounts Payable Specialist",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    source_view = _project_source_path(
        canonical_taxonomy_db,
        job,
        source_classification_id="ctgoodjobs:001",
        label="Accounting",
    )
    classifier_output = CanonicalClassifierOutput(
        decision="select_existing",
        target_code="accounting.financial_accounting.accounts_payable",
        provenance=Provenance(
            method="constrained-ai",
            source_site="ctgoodjobs",
            evidence_refs=({"kind": "classifier-response", "id": "response-ai-1"},),
            model_provider="openai",
            model_name="gpt-5-mini",
            model_version="2026-07-01",
            captured_at=datetime(2026, 7, 19, 10, 30, tzinfo=timezone.utc),
        ),
    )

    module = CanonicalJobTaxonomy(canonical_taxonomy_db)
    result = module.evaluate(
        job.id,
        source_view,
        classifier_output,
    )

    assignment = canonical_taxonomy_db.get(
        JobTaxonomyAssignment,
        result.assignment_id,
    )
    assert assignment is not None
    assert {
        "result": (result.state, result.changed, result.version),
        "method": assignment.method,
        "target_code": assignment.breadcrumb["subcategory"]["code"],
        "model": (
            assignment.model_provider,
            assignment.model_name,
            assignment.model_version,
        ),
        "review_count": canonical_taxonomy_db.query(JobTaxonomyReviewItem).count(),
        "legacy_subcategory_id": job.subcategory_id,
    } == {
        "result": ("assigned", True, 1),
        "method": "constrained_ai",
        "target_code": "accounting.financial_accounting.accounts_payable",
        "model": ("openai", "gpt-5-mini", "2026-07-01"),
        "review_count": 0,
        "legacy_subcategory_id": None,
    }
    assert assignment.source_evidence_refs[-1] == {
        "kind": "classifier-response",
        "id": "response-ai-1",
    }
    assert (
        canonical_taxonomy_db.query(EventOutbox)
        .filter(EventOutbox.event_type == "job.canonical_taxonomy_changed")
        .count()
        == 1
    )


def test_evaluate_preserves_out_of_slice_classifier_evidence_in_review(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    company = Company(
        company_id="canonical-company-out-of-slice",
        source_site="ctgoodjobs",
        source_company_id="canonical-company-out-of-slice",
        name="Out Of Slice Company",
    )
    job = Job(
        job_id="canonical-job-out-of-slice",
        source_site="ctgoodjobs",
        source_job_id="canonical-job-out-of-slice",
        company=company,
        title="Accounts Specialist",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    source_view = _project_source_path(
        canonical_taxonomy_db,
        job,
        source_classification_id="ctgoodjobs:001",
        label="Accounting",
    )
    classifier_output = CanonicalClassifierOutput(
        decision="select_existing",
        target_code="banking_financial_services.banking.retail_banking",
        provenance=Provenance(
            method="constrained-ai",
            source_site="ctgoodjobs",
            evidence_refs=(
                {"kind": "classifier-response", "id": "response-out-of-slice"},
            ),
            model_provider="openai",
            model_name="gpt-5-mini",
            model_version="2026-07-01",
            captured_at=datetime(2026, 7, 19, 10, 45, tzinfo=timezone.utc),
        ),
    )

    module = CanonicalJobTaxonomy(canonical_taxonomy_db)
    result = module.evaluate(
        job.id,
        source_view,
        classifier_output,
    )
    replay = module.evaluate(job.id, source_view, classifier_output)

    review = canonical_taxonomy_db.get(JobTaxonomyReviewItem, result.review_item_id)
    assert review is not None
    assert result.reasons == ("classifier_target_out_of_slice",)
    assert (
        replay.review_item_id,
        replay.changed,
        replay.replayed,
        replay.version,
    ) == (review.id, False, True, 1)
    assert review.reasons == ["classifier_target_out_of_slice"]
    assert review.evidence_refs[-1] == {
        "kind": "classifier-response",
        "id": "response-out-of-slice",
    }
    assert [item["code"] for item in review.recommendations] == [
        "accounting.financial_accounting.financial_accounting",
        "accounting.financial_accounting.accounts_payable",
        "accounting.financial_accounting.accounts_receivable",
        "accounting.audit_tax.audit",
        "accounting.audit_tax.tax",
        "accounting.audit_tax.compliance_reporting",
    ]
    assert canonical_taxonomy_db.query(JobTaxonomyAssignment).count() == 0
    assert canonical_taxonomy_db.query(JobTaxonomyReviewItem).count() == 1
    assert (
        canonical_taxonomy_db.query(EventOutbox)
        .filter(EventOutbox.event_type == "job.canonical_taxonomy_changed")
        .count()
        == 1
    )


def test_evaluate_exact_assignment_replay_is_a_no_op(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = _with_deterministic_mapping(
        json.loads(MAPPING_PATH.read_text()),
        "ctgoodjobs:001",
        "accounting.financial_accounting.financial_accounting",
    )
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    company = Company(
        company_id="canonical-company-replay",
        source_site="ctgoodjobs",
        source_company_id="canonical-company-replay",
        name="Replay Company",
    )
    job = Job(
        job_id="canonical-job-replay",
        source_site="ctgoodjobs",
        source_job_id="canonical-job-replay",
        company=company,
        title="Replay Accountant",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    source_view = _project_source_path(
        canonical_taxonomy_db,
        job,
        source_classification_id="ctgoodjobs:001",
        label="Accounting",
    )
    module = CanonicalJobTaxonomy(canonical_taxonomy_db)

    first = module.evaluate(job.id, source_view)
    replay = module.evaluate(job.id, source_view)

    assert {
        "first": (
            first.assignment_id,
            first.changed,
            first.replayed,
            first.version,
        ),
        "replay": (
            replay.assignment_id,
            replay.changed,
            replay.replayed,
            replay.version,
        ),
        "assignments": canonical_taxonomy_db.query(JobTaxonomyAssignment).count(),
        "events": canonical_taxonomy_db.query(EventOutbox)
        .filter(EventOutbox.event_type == "job.canonical_taxonomy_changed")
        .count(),
    } == {
        "first": (first.assignment_id, True, False, 1),
        "replay": (first.assignment_id, False, True, 1),
        "assignments": 1,
        "events": 1,
    }


def test_evaluate_changed_evidence_supersedes_assignment_history(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = _with_deterministic_mapping(
        json.loads(MAPPING_PATH.read_text()),
        "ctgoodjobs:001",
        "accounting.financial_accounting.financial_accounting",
    )
    mapping_seed = _with_deterministic_mapping(
        mapping_seed,
        "ctgoodjobs:007",
        "banking_financial_services.banking.retail_banking",
    )
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    company = Company(
        company_id="canonical-company-replacement",
        source_site="ctgoodjobs",
        source_company_id="canonical-company-replacement",
        name="Replacement Company",
    )
    job = Job(
        job_id="canonical-job-replacement",
        source_site="ctgoodjobs",
        source_job_id="canonical-job-replacement",
        company=company,
        title="Finance Specialist",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    module = CanonicalJobTaxonomy(canonical_taxonomy_db)

    accounting_view = _project_source_path(
        canonical_taxonomy_db,
        job,
        source_classification_id="ctgoodjobs:001",
        label="Accounting",
    )
    first = module.evaluate(job.id, accounting_view)
    banking_view = _project_source_path(
        canonical_taxonomy_db,
        job,
        source_classification_id="ctgoodjobs:007",
        label="Banking & Financial Services",
    )
    replacement = module.evaluate(job.id, banking_view)

    assignments = (
        canonical_taxonomy_db.query(JobTaxonomyAssignment)
        .order_by(JobTaxonomyAssignment.lock_version)
        .all()
    )
    assert {
        "result": (
            replacement.state,
            replacement.changed,
            replacement.replayed,
            replacement.version,
        ),
        "versions": [assignment.lock_version for assignment in assignments],
        "current": [assignment.is_current for assignment in assignments],
        "superseded": [
            assignment.superseded_at is not None for assignment in assignments
        ],
        "targets": [
            assignment.breadcrumb["subcategory"]["code"] for assignment in assignments
        ],
        "current_ids": [
            assignment.id for assignment in assignments if assignment.is_current
        ],
        "events": canonical_taxonomy_db.query(EventOutbox)
        .filter(EventOutbox.event_type == "job.canonical_taxonomy_changed")
        .count(),
        "legacy_subcategory_id": job.subcategory_id,
    } == {
        "result": ("assigned", True, False, 2),
        "versions": [1, 2],
        "current": [False, True],
        "superseded": [True, False],
        "targets": [
            "accounting.financial_accounting.financial_accounting",
            "banking_financial_services.banking.retail_banking",
        ],
        "current_ids": [replacement.assignment_id],
        "events": 2,
        "legacy_subcategory_id": None,
    }
    assert first.assignment_id == assignments[0].id


def test_evaluate_invalidated_assignment_becomes_unassigned_with_review(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = _with_deterministic_mapping(
        json.loads(MAPPING_PATH.read_text()),
        "ctgoodjobs:001",
        "accounting.financial_accounting.financial_accounting",
    )
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    company = Company(
        company_id="canonical-company-unassign",
        source_site="ctgoodjobs",
        source_company_id="canonical-company-unassign",
        name="Unassignment Company",
    )
    job = Job(
        job_id="canonical-job-unassign",
        source_site="ctgoodjobs",
        source_job_id="canonical-job-unassign",
        company=company,
        title="Finance Generalist",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    module = CanonicalJobTaxonomy(canonical_taxonomy_db)

    assigned_view = _project_source_path(
        canonical_taxonomy_db,
        job,
        source_classification_id="ctgoodjobs:001",
        label="Accounting",
    )
    assigned = module.evaluate(job.id, assigned_view)
    unresolved_view = _project_source_path(
        canonical_taxonomy_db,
        job,
        source_classification_id="ctgoodjobs:007",
        label="Banking & Financial Services",
    )
    unassigned = module.evaluate(job.id, unresolved_view)

    assignment = canonical_taxonomy_db.get(
        JobTaxonomyAssignment,
        assigned.assignment_id,
    )
    review = canonical_taxonomy_db.get(
        JobTaxonomyReviewItem,
        unassigned.review_item_id,
    )
    assert assignment is not None
    assert review is not None
    assert {
        "result": (
            unassigned.state,
            unassigned.version,
            unassigned.reasons,
        ),
        "assignment_current": assignment.is_current,
        "assignment_superseded": assignment.superseded_at is not None,
        "review": (review.status, review.lock_version, review.reasons),
        "current_assignment_count": canonical_taxonomy_db.query(JobTaxonomyAssignment)
        .filter(JobTaxonomyAssignment.is_current.is_(True))
        .count(),
        "active_review_count": canonical_taxonomy_db.query(JobTaxonomyReviewItem)
        .filter(JobTaxonomyReviewItem.status == "active")
        .count(),
        "events": canonical_taxonomy_db.query(EventOutbox)
        .filter(EventOutbox.event_type == "job.canonical_taxonomy_changed")
        .count(),
    } == {
        "result": ("unassigned", 2, ("classifier_output_missing",)),
        "assignment_current": False,
        "assignment_superseded": True,
        "review": ("active", 2, ["classifier_output_missing"]),
        "current_assignment_count": 0,
        "active_review_count": 1,
        "events": 2,
    }


def test_evaluate_valid_evidence_resolves_active_review_with_assignment(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    company = Company(
        company_id="canonical-company-review-resolution",
        source_site="ctgoodjobs",
        source_company_id="canonical-company-review-resolution",
        name="Review Resolution Company",
    )
    job = Job(
        job_id="canonical-job-review-resolution",
        source_site="ctgoodjobs",
        source_job_id="canonical-job-review-resolution",
        company=company,
        title="Accounts Payable Analyst",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    source_view = _project_source_path(
        canonical_taxonomy_db,
        job,
        source_classification_id="ctgoodjobs:001",
        label="Accounting",
    )
    module = CanonicalJobTaxonomy(canonical_taxonomy_db)
    unresolved = module.evaluate(job.id, source_view)
    classifier_output = CanonicalClassifierOutput(
        decision="select_existing",
        target_code="accounting.financial_accounting.accounts_payable",
        provenance=Provenance(
            method="constrained-ai",
            source_site="ctgoodjobs",
            evidence_refs=(
                {"kind": "classifier-response", "id": "response-resolution"},
            ),
            model_provider="openai",
            model_name="gpt-5-mini",
            model_version="2026-07-01",
            captured_at=datetime(2026, 7, 19, 11, 0, tzinfo=timezone.utc),
        ),
    )

    assigned = module.evaluate(job.id, source_view, classifier_output)

    review = canonical_taxonomy_db.get(
        JobTaxonomyReviewItem,
        unresolved.review_item_id,
    )
    assignment = canonical_taxonomy_db.get(
        JobTaxonomyAssignment,
        assigned.assignment_id,
    )
    assert review is not None
    assert assignment is not None
    assert {
        "result": (assigned.state, assigned.version, assigned.changed),
        "review": (
            review.status,
            review.lock_version,
            review.resolved_at is not None,
            review.assignment_id,
        ),
        "assignment": (
            assignment.lock_version,
            assignment.is_current,
            assignment.breadcrumb["subcategory"]["code"],
        ),
        "active_review_count": canonical_taxonomy_db.query(JobTaxonomyReviewItem)
        .filter(JobTaxonomyReviewItem.status == "active")
        .count(),
        "events": canonical_taxonomy_db.query(EventOutbox)
        .filter(EventOutbox.event_type == "job.canonical_taxonomy_changed")
        .count(),
    } == {
        "result": ("assigned", 2, True),
        "review": ("assigned", 2, True, assignment.id),
        "assignment": (
            2,
            True,
            "accounting.financial_accounting.accounts_payable",
        ),
        "active_review_count": 0,
        "events": 2,
    }


def test_evaluate_changed_unresolved_evidence_supersedes_active_review(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    company = Company(
        company_id="canonical-company-review-replacement",
        source_site="ctgoodjobs",
        source_company_id="canonical-company-review-replacement",
        name="Review Replacement Company",
    )
    job = Job(
        job_id="canonical-job-review-replacement",
        source_site="ctgoodjobs",
        source_job_id="canonical-job-review-replacement",
        company=company,
        title="Finance Analyst",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    module = CanonicalJobTaxonomy(canonical_taxonomy_db)

    first_view = _project_source_path(
        canonical_taxonomy_db,
        job,
        source_classification_id="ctgoodjobs:001",
        label="Accounting",
    )
    first = module.evaluate(job.id, first_view)
    second_view = _project_source_path(
        canonical_taxonomy_db,
        job,
        source_classification_id="ctgoodjobs:007",
        label="Banking & Financial Services",
    )
    second = module.evaluate(job.id, second_view)

    reviews = (
        canonical_taxonomy_db.query(JobTaxonomyReviewItem)
        .order_by(
            JobTaxonomyReviewItem.created_at,
            JobTaxonomyReviewItem.id,
        )
        .all()
    )
    assert {
        "result": (second.state, second.version, second.reasons),
        "statuses": [review.status for review in reviews],
        "versions": [review.lock_version for review in reviews],
        "resolved": [review.resolved_at is not None for review in reviews],
        "active_ids": [review.id for review in reviews if review.status == "active"],
        "events": canonical_taxonomy_db.query(EventOutbox)
        .filter(EventOutbox.event_type == "job.canonical_taxonomy_changed")
        .count(),
    } == {
        "result": ("unassigned", 2, ("classifier_output_missing",)),
        "statuses": ["superseded", "active"],
        "versions": [2, 2],
        "resolved": [True, False],
        "active_ids": [second.review_item_id],
        "events": 2,
    }
    assert first.review_item_id == reviews[0].id


def test_evaluate_without_source_paths_creates_explicit_unassigned_review(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    company = Company(
        company_id="canonical-company-no-paths",
        source_site="ctgoodjobs",
        source_company_id="canonical-company-no-paths",
        name="No Paths Company",
    )
    job = Job(
        job_id="canonical-job-no-paths",
        source_site="ctgoodjobs",
        source_job_id="canonical-job-no-paths",
        company=company,
        title="Unclassified Role",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    source_view = (
        SourceJobAttributes(canonical_taxonomy_db)
        .project(
            job.id,
            SourceJobAttributeEvidence(
                source_site="ctgoodjobs",
                classification_paths=(),
                employment_labels=(),
            ),
        )
        .view
    )

    result = CanonicalJobTaxonomy(canonical_taxonomy_db).evaluate(
        job.id,
        source_view,
    )

    review = canonical_taxonomy_db.get(JobTaxonomyReviewItem, result.review_item_id)
    assert review is not None
    assert {
        "result": (result.state, result.version, result.reasons),
        "review": (review.reasons, review.evidence_refs, review.recommendations),
        "assignment_count": canonical_taxonomy_db.query(JobTaxonomyAssignment).count(),
        "legacy_subcategory_id": job.subcategory_id,
    } == {
        "result": (
            "unassigned",
            1,
            ("source_classification_paths_missing",),
        ),
        "review": (["source_classification_paths_missing"], [], []),
        "assignment_count": 0,
        "legacy_subcategory_id": None,
    }


def test_evaluate_path_without_catalog_provenance_creates_review(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    company = Company(
        company_id="canonical-company-limited-provenance",
        source_site="ctgoodjobs",
        source_company_id="canonical-company-limited-provenance",
        name="Limited Provenance Company",
    )
    job = Job(
        job_id="canonical-job-limited-provenance",
        source_site="ctgoodjobs",
        source_job_id="canonical-job-limited-provenance",
        company=company,
        title="Historical Accountant",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    provenance = Provenance(
        method="historical-evidence",
        source_site="ctgoodjobs",
        evidence_refs=({"kind": "raw-job", "source_job_id": job.source_job_id},),
        captured_at=datetime(2026, 7, 19, 11, 30, tzinfo=timezone.utc),
    )
    source_view = (
        SourceJobAttributes(canonical_taxonomy_db)
        .project(
            job.id,
            SourceJobAttributeEvidence(
                source_site="ctgoodjobs",
                classification_paths=(
                    SourceClassificationPathEvidence(
                        source_order=1,
                        nodes=(
                            SourceClassificationNodeEvidence(
                                source_position=1,
                                native_depth=0,
                                source_classification_id="ctgoodjobs:001",
                                native_id="001",
                                label="Accounting",
                            ),
                        ),
                        source_declared_primary=False,
                        primary_basis=None,
                        source_catalog_revision=None,
                        provenance=provenance,
                    ),
                ),
                employment_labels=(),
            ),
        )
        .view
    )

    result = CanonicalJobTaxonomy(canonical_taxonomy_db).evaluate(
        job.id,
        source_view,
    )

    review = canonical_taxonomy_db.get(JobTaxonomyReviewItem, result.review_item_id)
    assert review is not None
    assert result.reasons == ("source_catalog_provenance_missing",)
    assert review.evidence_refs == [
        {
            "kind": "source-classification-path",
            "id": str(source_view.source_classification_paths[0].id),
            "source_site": "ctgoodjobs",
            "source_order": 1,
            "source_catalog_revision_id": None,
            "source_classification_ids": ["ctgoodjobs:001"],
        }
    ]
    assert canonical_taxonomy_db.query(JobTaxonomyAssignment).count() == 0


def test_evaluate_blocking_reasons_are_canonical_not_path_ordered(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = _with_non_mapping_disposition(
        json.loads(MAPPING_PATH.read_text()),
        "offertoday:101000",
        "unmapped",
    )
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    company = Company(
        company_id="canonical-company-blockers",
        source_site="offertoday",
        source_company_id="canonical-company-blockers",
        name="Blocking Paths Company",
    )
    job = Job(
        job_id="canonical-job-blockers",
        source_site="offertoday",
        source_job_id="canonical-job-blockers",
        company=company,
        title="Blocked Role",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    source_view = _project_source_paths(
        canonical_taxonomy_db,
        job,
        paths=(
            ("offertoday:101000", "Accounting"),
            ("offertoday:113000", "Farming"),
        ),
    )

    result = CanonicalJobTaxonomy(canonical_taxonomy_db).evaluate(
        job.id,
        source_view,
    )

    review = canonical_taxonomy_db.get(JobTaxonomyReviewItem, result.review_item_id)
    assert review is not None
    assert result.reasons == (
        "source_mapping_excluded",
        "source_mapping_unmapped",
    )
    assert review.reasons == [
        "source_mapping_excluded",
        "source_mapping_unmapped",
    ]
    assert canonical_taxonomy_db.query(JobTaxonomyAssignment).count() == 0


def test_classifier_preflight_blocks_excluded_and_unmapped_paths_before_llm(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = _with_non_mapping_disposition(
        json.loads(MAPPING_PATH.read_text()),
        "offertoday:101000",
        "unmapped",
    )
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    company = Company(
        company_id="canonical-preflight-company",
        source_site="offertoday",
        source_company_id="canonical-preflight-company",
        name="Canonical Preflight Company",
    )
    job = Job(
        job_id="canonical-preflight-job",
        source_site="offertoday",
        source_job_id="canonical-preflight-job",
        company=company,
        title="Blocked Role",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    _project_source_paths(
        canonical_taxonomy_db,
        job,
        paths=(
            ("offertoday:101000", "Accounting"),
            ("offertoday:113000", "Farming"),
        ),
    )

    result = CanonicalTaxonomyPreflight(canonical_taxonomy_db).inspect(job)

    assert result.status == "excluded"
    assert result.reasons == (
        "source_mapping_excluded",
        "source_mapping_unmapped",
    )
    assert result.context is not None
    assert result.context.blocking_reasons == result.reasons
    assert canonical_taxonomy_db.query(JobTaxonomyReviewItem).count() == 0


def test_evaluate_unsupported_source_creates_review_without_registry_guess(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = _without_source_mappings(
        json.loads(MAPPING_PATH.read_text()),
        "ctgoodjobs",
    )
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    company = Company(
        company_id="canonical-company-unsupported",
        source_site="ctgoodjobs",
        source_company_id="canonical-company-unsupported",
        name="Unsupported Source Company",
    )
    job = Job(
        job_id="canonical-job-unsupported",
        source_site="ctgoodjobs",
        source_job_id="canonical-job-unsupported",
        company=company,
        title="Unknown Board Role",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    provenance = Provenance(
        method="historical-evidence",
        source_site="ctgoodjobs",
        evidence_refs=({"kind": "raw-job", "source_job_id": job.source_job_id},),
        captured_at=datetime(2026, 7, 19, 11, 45, tzinfo=timezone.utc),
    )
    source_view = (
        SourceJobAttributes(canonical_taxonomy_db)
        .project(
            job.id,
            SourceJobAttributeEvidence(
                source_site="ctgoodjobs",
                classification_paths=(
                    SourceClassificationPathEvidence(
                        source_order=1,
                        nodes=(
                            SourceClassificationNodeEvidence(
                                source_position=1,
                                native_depth=0,
                                source_classification_id="ctgoodjobs:001",
                                native_id="001",
                                label="Accounting",
                            ),
                        ),
                        source_declared_primary=False,
                        primary_basis=None,
                        source_catalog_revision=None,
                        provenance=provenance,
                    ),
                ),
                employment_labels=(),
            ),
        )
        .view
    )

    result = CanonicalJobTaxonomy(canonical_taxonomy_db).evaluate(
        job.id,
        source_view,
    )

    review = canonical_taxonomy_db.get(JobTaxonomyReviewItem, result.review_item_id)
    assert review is not None
    assert result.reasons == ("unsupported_source",)
    assert review.evidence_refs[0]["source_classification_ids"] == ["ctgoodjobs:001"]
    assert canonical_taxonomy_db.query(JobTaxonomyAssignment).count() == 0
    assert job.subcategory_id is None


def test_assignment_mapping_revision_must_match_taxonomy_revision(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    first_taxonomy = publisher.materialize(seed)
    publisher.activate(first_taxonomy, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    first_mapping = publisher.materialize_mapping(seed, mapping_seed)

    second_seed = deepcopy(seed)
    second_seed["release_key"] = "canonical-job-taxonomy-v2-cross-revision"
    second_seed["domains"][0]["label"] = "Accounting & Audit"
    second_taxonomy = publisher.materialize(second_seed)
    second_subcategory = canonical_taxonomy_db.scalar(
        select(CanonicalJobSubcategory).where(
            CanonicalJobSubcategory.revision_id == second_taxonomy.revision_id,
            CanonicalJobSubcategory.code
            == "accounting.financial_accounting.financial_accounting",
        )
    )
    assert second_subcategory is not None
    company = Company(
        company_id="canonical-company-cross-revision",
        source_site="ctgoodjobs",
        source_company_id="canonical-company-cross-revision",
        name="Cross Revision Company",
    )
    job = Job(
        job_id="canonical-job-cross-revision",
        source_site="ctgoodjobs",
        source_job_id="canonical-job-cross-revision",
        company=company,
        title="Cross Revision Accountant",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    canonical_taxonomy_db.add(
        JobTaxonomyAssignment(
            job_id=job.id,
            taxonomy_revision_id=second_taxonomy.revision_id,
            subcategory_id=second_subcategory.id,
            mapping_revision_id=first_mapping.revision_id,
            method="reviewed_mapping",
            evidence_hash="a" * 64,
            source_evidence_refs=[],
            mapping_ids=[],
            breadcrumb={},
            lock_version=1,
            is_current=True,
        )
    )

    with pytest.raises(IntegrityError):
        canonical_taxonomy_db.flush()


def test_evaluate_invalid_classifier_truth_table_never_assigns(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)
    cases = (
        (
            "fallback_default",
            "accounting.financial_accounting.financial_accounting",
            True,
            "fallback_output",
        ),
        (
            "create_new",
            "accounting.financial_accounting.new_role",
            True,
            "create_new_forbidden",
        ),
        (
            "select_existing",
            "accounting.financial_accounting.accounts_payable",
            False,
            "classifier_provenance_missing",
        ),
        (
            "select_existing",
            "unknown.category.leaf",
            True,
            "canonical_target_unknown",
        ),
        ("invalid", None, True, "classifier_output_invalid"),
    )
    observed = []
    for index, (decision, target_code, complete_model, expected_reason) in enumerate(
        cases,
        start=1,
    ):
        company = Company(
            company_id=f"canonical-company-invalid-{index}",
            source_site="ctgoodjobs",
            source_company_id=f"canonical-company-invalid-{index}",
            name=f"Invalid Classifier Company {index}",
        )
        job = Job(
            job_id=f"canonical-job-invalid-{index}",
            source_site="ctgoodjobs",
            source_job_id=f"canonical-job-invalid-{index}",
            company=company,
            title=f"Invalid Classifier Role {index}",
        )
        canonical_taxonomy_db.add(job)
        canonical_taxonomy_db.flush()
        source_view = _project_source_path(
            canonical_taxonomy_db,
            job,
            source_classification_id="ctgoodjobs:001",
            label="Accounting",
        )
        output = CanonicalClassifierOutput(
            decision=decision,
            target_code=target_code,
            provenance=Provenance(
                method="constrained-ai",
                source_site="ctgoodjobs",
                evidence_refs=(
                    {"kind": "classifier-response", "id": f"invalid-{index}"},
                ),
                model_provider="openai",
                model_name="gpt-5-mini",
                model_version="2026-07-01" if complete_model else None,
                captured_at=datetime(
                    2026,
                    7,
                    19,
                    12,
                    index,
                    tzinfo=timezone.utc,
                ),
            ),
        )
        result = CanonicalJobTaxonomy(canonical_taxonomy_db).evaluate(
            job.id,
            source_view,
            output,
        )
        observed.append((result.state, result.reasons, expected_reason))

    assert observed == [
        ("unassigned", (expected_reason,), expected_reason)
        for *_case, expected_reason in cases
    ]
    assert canonical_taxonomy_db.query(JobTaxonomyAssignment).count() == 0
    assert canonical_taxonomy_db.query(JobTaxonomyReviewItem).filter(
        JobTaxonomyReviewItem.status == "active"
    ).count() == len(cases)


def test_evaluate_assignment_and_outbox_share_the_caller_transaction(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = _with_deterministic_mapping(
        json.loads(MAPPING_PATH.read_text()),
        "ctgoodjobs:001",
        "accounting.financial_accounting.financial_accounting",
    )
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)
    company = Company(
        company_id="canonical-company-transaction",
        source_site="ctgoodjobs",
        source_company_id="canonical-company-transaction",
        name="Transaction Company",
    )
    job = Job(
        job_id="canonical-job-transaction",
        source_site="ctgoodjobs",
        source_job_id="canonical-job-transaction",
        company=company,
        title="Transactional Accountant",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    source_view = _project_source_path(
        canonical_taxonomy_db,
        job,
        source_classification_id="ctgoodjobs:001",
        label="Accounting",
    )
    canonical_taxonomy_db.commit()
    job_id = job.id

    with pytest.raises(RuntimeError, match="forced outbox failure"):
        CanonicalJobTaxonomy(
            canonical_taxonomy_db,
            outbox_repository=_FailingOutboxRepository(),
        ).evaluate(job_id, source_view)
    canonical_taxonomy_db.rollback()
    assert canonical_taxonomy_db.get(Job, job_id) is not None
    assert canonical_taxonomy_db.query(JobTaxonomyAssignment).count() == 0
    assert canonical_taxonomy_db.query(JobTaxonomyReviewItem).count() == 0
    assert (
        canonical_taxonomy_db.query(EventOutbox)
        .filter(EventOutbox.event_type == "job.canonical_taxonomy_changed")
        .count()
        == 0
    )

    CanonicalJobTaxonomy(canonical_taxonomy_db).evaluate(job_id, source_view)
    canonical_taxonomy_db.rollback()
    assert canonical_taxonomy_db.query(JobTaxonomyAssignment).count() == 0
    assert (
        canonical_taxonomy_db.query(EventOutbox)
        .filter(EventOutbox.event_type == "job.canonical_taxonomy_changed")
        .count()
        == 0
    )


def test_concurrent_exact_evaluation_writes_one_assignment_and_event(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = _with_deterministic_mapping(
        json.loads(MAPPING_PATH.read_text()),
        "ctgoodjobs:001",
        "accounting.financial_accounting.financial_accounting",
    )
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)
    company = Company(
        company_id="canonical-company-concurrency",
        source_site="ctgoodjobs",
        source_company_id="canonical-company-concurrency",
        name="Concurrency Company",
    )
    job = Job(
        job_id="canonical-job-concurrency",
        source_site="ctgoodjobs",
        source_job_id="canonical-job-concurrency",
        company=company,
        title="Concurrent Accountant",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    _project_source_path(
        canonical_taxonomy_db,
        job,
        source_classification_id="ctgoodjobs:001",
        label="Accounting",
    )
    canonical_taxonomy_db.commit()
    job_id = job.id
    session_factory = sessionmaker(
        bind=canonical_taxonomy_db.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    barrier = Barrier(2)

    def evaluate_once():
        db = session_factory()
        try:
            source_view = SourceJobAttributes(db).get(job_id)
            barrier.wait(timeout=5)
            result = CanonicalJobTaxonomy(db).evaluate(job_id, source_view)
            db.commit()
            return (
                result.assignment_id,
                result.changed,
                result.replayed,
                result.version,
            )
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: evaluate_once(), range(2)))

    assert sorted(
        (changed, replayed, version)
        for _assignment_id, changed, replayed, version in results
    ) == [(False, True, 1), (True, False, 1)]
    assert len({assignment_id for assignment_id, *_rest in results}) == 1
    canonical_taxonomy_db.expire_all()
    assert canonical_taxonomy_db.query(JobTaxonomyAssignment).count() == 1
    assert (
        canonical_taxonomy_db.query(EventOutbox)
        .filter(EventOutbox.event_type == "job.canonical_taxonomy_changed")
        .count()
        == 1
    )


def test_operator_assign_existing_is_atomic_audited_and_idempotent(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)
    company = Company(
        company_id="canonical-company-operator-assign",
        source_site="ctgoodjobs",
        source_company_id="canonical-company-operator-assign",
        name="Operator Assignment Company",
    )
    job = Job(
        job_id="canonical-job-operator-assign",
        source_site="ctgoodjobs",
        source_job_id="canonical-job-operator-assign",
        company=company,
        title="Operator Reviewed Accountant",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    source_view = _project_source_path(
        canonical_taxonomy_db,
        job,
        source_classification_id="ctgoodjobs:001",
        label="Accounting",
    )
    unresolved = CanonicalJobTaxonomy(canonical_taxonomy_db).evaluate(
        job.id,
        source_view,
    )
    canonical_taxonomy_db.commit()
    target = canonical_taxonomy_db.scalar(
        select(CanonicalJobSubcategory).where(
            CanonicalJobSubcategory.revision_id == taxonomy_revision.revision_id,
            CanonicalJobSubcategory.code
            == "accounting.financial_accounting.accounts_payable",
        )
    )
    assert target is not None
    command = DecisionCommand(
        subject_id=str(unresolved.review_item_id),
        action="assign_existing_subcategory",
        target_id=str(target.id),
        expected_version=1,
        idempotency_key="canonical-operator-assign-1",
        confirmed=True,
        note="Confirmed from the preserved job description",
        correlation_id="canonical-operator-correlation-1",
    )
    adapter = CanonicalTaxonomyDecisionAdapter(canonical_taxonomy_db)

    result = adapter.decide(command)
    replay = adapter.decide(command)

    review = canonical_taxonomy_db.get(
        JobTaxonomyReviewItem,
        unresolved.review_item_id,
    )
    assignment = canonical_taxonomy_db.get(
        JobTaxonomyAssignment,
        review.assignment_id,
    )
    audit = canonical_taxonomy_db.get(
        GovernanceAuditEvent,
        result.audit_event_id,
    )
    assert review is not None
    assert assignment is not None
    assert audit is not None
    assert {
        "result": (result.version, result.replayed),
        "replay": (
            replay.version,
            replay.replayed,
            replay.audit_event_id,
        ),
        "review": (
            review.status,
            review.lock_version,
            review.assignment_id,
            review.decision_audit_id,
        ),
        "assignment": (
            assignment.method,
            assignment.lock_version,
            assignment.taxonomy_revision_id,
            assignment.mapping_revision_id,
            assignment.breadcrumb["subcategory"]["code"],
        ),
        "audit": (
            audit.action,
            audit.actor,
            audit.subject_id,
            audit.correlation_id,
        ),
        "audit_count": canonical_taxonomy_db.query(GovernanceAuditEvent).count(),
        "operator_event_count": canonical_taxonomy_db.query(EventOutbox)
        .filter(EventOutbox.event_type == "job.canonical_taxonomy_decided")
        .count(),
    } == {
        "result": (2, False),
        "replay": (2, True, result.audit_event_id),
        "review": ("assigned", 2, assignment.id, result.audit_event_id),
        "assignment": (
            "operator",
            2,
            taxonomy_revision.revision_id,
            None,
            "accounting.financial_accounting.accounts_payable",
        ),
        "audit": (
            "assign_existing_subcategory",
            "local-operator",
            str(review.id),
            "canonical-operator-correlation-1",
        ),
        "audit_count": 1,
        "operator_event_count": 1,
    }


def test_operator_marks_insufficient_evidence_without_assignment(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)
    company = Company(
        company_id="canonical-company-insufficient",
        source_site="ctgoodjobs",
        source_company_id="canonical-company-insufficient",
        name="Insufficient Evidence Company",
    )
    job = Job(
        job_id="canonical-job-insufficient",
        source_site="ctgoodjobs",
        source_job_id="canonical-job-insufficient",
        company=company,
        title="Ambiguous Role",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    source_view = _project_source_path(
        canonical_taxonomy_db,
        job,
        source_classification_id="ctgoodjobs:001",
        label="Accounting",
    )
    unresolved = CanonicalJobTaxonomy(canonical_taxonomy_db).evaluate(
        job.id,
        source_view,
    )
    canonical_taxonomy_db.commit()
    command = DecisionCommand(
        subject_id=str(unresolved.review_item_id),
        action="mark_insufficient_evidence",
        target_id=None,
        expected_version=1,
        idempotency_key="canonical-operator-insufficient-1",
        confirmed=True,
        note="The preserved description does not identify a job function",
    )

    result = CanonicalTaxonomyDecisionAdapter(canonical_taxonomy_db).decide(command)

    review = canonical_taxonomy_db.get(
        JobTaxonomyReviewItem,
        unresolved.review_item_id,
    )
    assert review is not None
    assert {
        "result": (
            result.version,
            result.subject["status"],
            result.resulting_projection,
        ),
        "review": (
            review.status,
            review.lock_version,
            review.resolved_at is not None,
            review.assignment_id,
            review.decision_audit_id,
        ),
        "assignment_count": canonical_taxonomy_db.query(JobTaxonomyAssignment).count(),
        "audit_count": canonical_taxonomy_db.query(GovernanceAuditEvent).count(),
        "operator_event_count": canonical_taxonomy_db.query(EventOutbox)
        .filter(EventOutbox.event_type == "job.canonical_taxonomy_decided")
        .count(),
        "legacy_subcategory_id": job.subcategory_id,
    } == {
        "result": (
            2,
            "insufficient_evidence",
            {
                "job_id": str(job.id),
                "state": "unassigned",
                "review_item_id": str(review.id),
                "taxonomy_revision_id": str(taxonomy_revision.revision_id),
                "version": 2,
                "reasons": ["insufficient_evidence"],
            },
        ),
        "review": (
            "insufficient_evidence",
            2,
            True,
            None,
            result.audit_event_id,
        ),
        "assignment_count": 0,
        "audit_count": 1,
        "operator_event_count": 1,
        "legacy_subcategory_id": None,
    }


def test_job_insight_extractor_uses_canonical_stable_code_contract():
    from app.ai.job_insight_extractor import JobInsightExtractor

    taxonomy_candidates = {
        "authority": "canonical-job-taxonomy",
        "taxonomy_revision_id": "taxonomy-revision",
        "mapping_revision_id": "mapping-revision",
        "source_classification_paths": [
            {
                "source_order": 1,
                "nodes": [{"id": "ctgoodjobs:001", "label": "Accounting"}],
            }
        ],
        "canonical_targets": [
            {
                "code": "accounting.financial_accounting.accounts_payable",
                "label": "Accounts Payable",
                "breadcrumb": ("Accounting / Financial Accounting / Accounts Payable"),
            }
        ],
        "blocking_reasons": [],
    }
    extractor = JobInsightExtractor()
    prompt = extractor.build_prompt(
        title="Accounts Payable Specialist",
        description="Process supplier invoices.",
        taxonomy_candidates=taxonomy_candidates,
        skill_taxonomy_candidates={},
    )

    assert "ctgoodjobs:001" in prompt
    assert "accounting.financial_accounting.accounts_payable" in prompt
    assert "Default path:" not in prompt
    assert "source_path_decision" not in prompt

    class _FakeLLM:
        async def generate_json(self, _prompt):
            return {
                "classification": {
                    "decision": "select_existing",
                    "target_code": ("accounting.financial_accounting.accounts_payable"),
                    "confidence": 0.92,
                    "reasoning": "Invoice payment ownership is explicit.",
                },
                "summary": "Processes supplier invoices.",
                "skills": [],
                "experience": {},
                "confidence": 0.92,
            }

    extractor.llm = _FakeLLM()
    result = asyncio.run(
        extractor.extract(
            title="Accounts Payable Specialist",
            description="Process supplier invoices.",
            taxonomy_candidates=taxonomy_candidates,
            skill_taxonomy_candidates={},
        )
    )

    assert result["classification"] == {
        "confidence": 0.92,
        "reasoning": "Invoice payment ownership is explicit.",
        "decision": "select_existing",
        "target_code": "accounting.financial_accounting.accounts_payable",
    }


def test_legacy_job_taxonomy_writer_entry_points_fail_closed():
    from app.services.job_category_normalizer import (
        JobCategoryNormalizer,
        LegacyJobTaxonomyWriterRetiredError,
    )

    normalizer = JobCategoryNormalizer(db=None, registry=object())
    retired_calls = (
        lambda: normalizer.normalize_category("Legacy role"),
        lambda: normalizer.resolve_taxonomy_decision(
            {},
            source_classification_id="ctgoodjobs:001",
        ),
        lambda: normalizer.get_taxonomy_candidate_slice(
            source_classification_id="ctgoodjobs:001"
        ),
        lambda: normalizer.build_default_path(object()),
        lambda: normalizer._get_or_create_path(
            "Legacy Domain",
            "Legacy Category",
            "Legacy Subcategory",
            allow_create=True,
        ),
    )

    for call in retired_calls:
        with pytest.raises(
            LegacyJobTaxonomyWriterRetiredError,
            match="CanonicalJobTaxonomy",
        ):
            call()


def test_production_code_has_no_legacy_job_taxonomy_writer_call_sites():
    backend_root = Path(__file__).parents[1]
    normalizer_path = backend_root / "app" / "services" / "job_category_normalizer.py"
    production_paths = sorted(
        [
            *(backend_root / "app").rglob("*.py"),
            *(backend_root / "scripts").rglob("*.py"),
        ]
    )
    forbidden_calls = {
        "normalize_category",
        "resolve_taxonomy_decision",
        "_get_or_create_path",
    }
    violations: list[str] = []

    for path in production_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative_path = path.relative_to(backend_root)
        for node in ast.walk(tree):
            if (
                path != normalizer_path
                and isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in forbidden_calls
            ):
                violations.append(
                    f"{relative_path}:{node.lineno}:call:{node.func.attr}"
                )
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
                targets = (
                    node.targets
                    if isinstance(node, (ast.Assign, ast.Delete))
                    else [node.target]
                )
                if any(
                    isinstance(target, ast.Attribute)
                    and target.attr == "subcategory_id"
                    for target in targets
                ):
                    violations.append(
                        f"{relative_path}:{node.lineno}:legacy-subcategory-write"
                    )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Job"
                and any(keyword.arg == "subcategory_id" for keyword in node.keywords)
            ):
                violations.append(
                    f"{relative_path}:{node.lineno}:legacy-job-constructor-write"
                )

    governance_script = backend_root / "scripts" / "govern_job_taxonomy.py"
    script_tree = ast.parse(
        governance_script.read_text(encoding="utf-8"),
        filename=str(governance_script),
    )
    exposed_commands = {
        node.args[0].value
        for node in ast.walk(script_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_parser"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }

    assert violations == []
    assert exposed_commands == {"audit"}


def test_ai_enrichment_uses_canonical_candidates_and_fails_closed_without_model_version(
    canonical_taxonomy_db,
    monkeypatch,
):
    from app.services import ai_enrichment_service as enrichment_module

    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    company = Company(
        company_id="canonical-ai-company",
        source_site="ctgoodjobs",
        source_company_id="canonical-ai-company",
        name="Canonical AI Company",
    )
    job = Job(
        job_id="canonical-ai-job",
        source_site="ctgoodjobs",
        source_job_id="canonical-ai-job",
        company=company,
        title="Accounts Payable Specialist",
        description="Process supplier invoices and payment reconciliations.",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    _project_source_path(
        canonical_taxonomy_db,
        job,
        source_classification_id="ctgoodjobs:001",
        label="Accounting",
    )

    captured: dict[str, object] = {}

    class _FakeInsightExtractor:
        async def extract(self, **kwargs):
            captured.update(kwargs)
            return {
                "classification": {
                    "decision": "select_existing",
                    "target_code": ("accounting.financial_accounting.accounts_payable"),
                    "confidence": 0.97,
                    "reasoning": "The role owns supplier invoice payments.",
                },
                "summary": "Owns supplier invoice processing and reconciliations.",
                "skills": [],
                "experience": {
                    "experience_level": "not_specified",
                    "experience_min_years": None,
                    "experience_max_years": None,
                    "summary": None,
                    "evidence": [],
                },
                "confidence": 0.97,
            }

    class _FakeSkillGovernanceReader:
        def __init__(self, _db):
            pass

        def get_prompt_candidate_slice(self, *_args, **_kwargs):
            return {
                "existing_categories": [],
                "existing_technologies": [],
                "existing_skills": [],
                "review_only_terms": [],
                "suppressed_review_terms": [],
            }

    class _FakeSkillProjection:
        taxonomy_revision_id = taxonomy_revision.revision_id
        changed = False
        mentions = ()

    class _FakeSkillGovernance:
        def __init__(self, _db):
            pass

        def extract(self, *_args, **_kwargs):
            return _FakeSkillProjection()

    class _ForbiddenLegacyNormalizer:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("legacy JobCategoryNormalizer was constructed")

    monkeypatch.setattr(
        enrichment_module,
        "get_job_insight_extractor",
        lambda: _FakeInsightExtractor(),
    )
    monkeypatch.setattr(
        enrichment_module,
        "SkillGovernanceReader",
        _FakeSkillGovernanceReader,
    )
    monkeypatch.setattr(
        enrichment_module,
        "SkillGovernance",
        _FakeSkillGovernance,
    )
    monkeypatch.setattr(
        enrichment_module,
        "JobCategoryNormalizer",
        _ForbiddenLegacyNormalizer,
        raising=False,
    )
    monkeypatch.setattr(
        enrichment_module,
        "get_llm_status",
        lambda scope: {
            "provider": "openai",
            "active_provider": "openai",
            "model": "gpt-test",
            "active_model": "gpt-test",
            "model_version": None,
            "scope": scope,
        },
        raising=False,
    )

    service = enrichment_module.AIEnrichmentService()
    result = asyncio.run(service.enrich_job(job, canonical_taxonomy_db))

    taxonomy_candidates = captured["taxonomy_candidates"]
    assert isinstance(taxonomy_candidates, dict)
    assert taxonomy_candidates["authority"] == "canonical-job-taxonomy"
    assert "default_path" not in taxonomy_candidates
    target_codes = {
        target["code"] for target in taxonomy_candidates["canonical_targets"]
    }
    assert "accounting.financial_accounting.accounts_payable" in target_codes
    assert all(
        target["code"] and target["breadcrumb"]
        for target in taxonomy_candidates["canonical_targets"]
    )

    verification = sessionmaker(
        bind=canonical_taxonomy_db.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )()
    try:
        persisted_job = verification.get(Job, job.id)
        review = (
            verification.query(JobTaxonomyReviewItem)
            .filter_by(
                job_id=job.id,
                status="active",
            )
            .one()
        )
        assert {
            "result": result["status"],
            "summary": persisted_job.ai_summary,
            "legacy_subcategory_id": persisted_job.subcategory_id,
            "assignment_count": verification.query(JobTaxonomyAssignment)
            .filter_by(job_id=job.id, is_current=True)
            .count(),
            "review_reasons": review.reasons,
            "canonical_event_count": verification.query(EventOutbox)
            .filter(
                EventOutbox.event_type == "job.canonical_taxonomy_changed",
                EventOutbox.aggregate_id == str(job.id),
            )
            .count(),
        } == {
            "result": "success",
            "summary": "Owns supplier invoice processing and reconciliations.",
            "legacy_subcategory_id": None,
            "assignment_count": 0,
            "review_reasons": ["classifier_provenance_missing"],
            "canonical_event_count": 1,
        }
    finally:
        verification.close()


def test_ai_enrichment_blocking_mapping_creates_review_without_calling_llm(
    canonical_taxonomy_db,
    monkeypatch,
):
    from app.services import ai_enrichment_service as enrichment_module

    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    company = Company(
        company_id="canonical-blocked-ai-company",
        source_site="offertoday",
        source_company_id="canonical-blocked-ai-company",
        name="Canonical Blocked AI Company",
    )
    job = Job(
        job_id="canonical-blocked-ai-job",
        source_site="offertoday",
        source_job_id="canonical-blocked-ai-job",
        company=company,
        title="Farming Role",
        description="Work on a farm.",
    )
    canonical_taxonomy_db.add(job)
    canonical_taxonomy_db.flush()
    _project_source_path(
        canonical_taxonomy_db,
        job,
        source_classification_id="offertoday:113000",
        label="Farming",
    )

    calls = 0

    class _ForbiddenInsightExtractor:
        async def extract(self, **_kwargs):
            nonlocal calls
            calls += 1
            raise AssertionError("blocking canonical evidence crossed the LLM boundary")

    monkeypatch.setattr(
        enrichment_module,
        "get_job_insight_extractor",
        lambda: _ForbiddenInsightExtractor(),
    )
    result = asyncio.run(
        enrichment_module.AIEnrichmentService().enrich_job(
            job,
            canonical_taxonomy_db,
        )
    )

    review = (
        canonical_taxonomy_db.query(JobTaxonomyReviewItem)
        .filter_by(job_id=job.id, status="active")
        .one()
    )
    assert calls == 0
    assert result["status"] == "excluded"
    assert result["error"] == "source_mapping_excluded"
    assert result["canonical_taxonomy"]["review_item_id"] == str(review.id)
    assert review.reasons == ["source_mapping_excluded"]
    assert job.ai_enriched_at is None


def test_rebuild_inspector_is_deterministic_honest_and_performs_zero_writes(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = _with_deterministic_mapping(
        json.loads(MAPPING_PATH.read_text()),
        "ctgoodjobs:001",
        "accounting.financial_accounting.accounts_payable",
    )
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)

    legacy_domain = JobDomain(
        name="Legacy Accounting",
        created_by="ai",
        is_auto_created=True,
    )
    canonical_taxonomy_db.add(legacy_domain)
    canonical_taxonomy_db.flush()
    legacy_category = JobCategory(
        domain_id=legacy_domain.id,
        name="General",
        created_by="ai",
        is_auto_created=True,
    )
    canonical_taxonomy_db.add(legacy_category)
    canonical_taxonomy_db.flush()
    legacy_subcategory = JobSubcategory(
        category_id=legacy_category.id,
        name="General",
        created_by="ai",
        is_auto_created=True,
    )
    canonical_taxonomy_db.add(legacy_subcategory)
    canonical_taxonomy_db.flush()

    company = Company(
        company_id="canonical-rebuild-company",
        source_site="ctgoodjobs",
        source_company_id="canonical-rebuild-company",
        name="Canonical Rebuild Company",
    )
    assigned_job = Job(
        job_id="canonical-rebuild-assigned",
        source_site="ctgoodjobs",
        source_job_id="canonical-rebuild-assigned",
        company=company,
        title="Accounts Payable Specialist",
        subcategory_id=legacy_subcategory.id,
    )
    review_job = Job(
        job_id="canonical-rebuild-review",
        source_site="ctgoodjobs",
        source_job_id="canonical-rebuild-review",
        company=company,
        title="Ambiguous Accounting Role",
    )
    canonical_taxonomy_db.add_all([assigned_job, review_job])
    canonical_taxonomy_db.flush()
    assigned_source = _project_source_path(
        canonical_taxonomy_db,
        assigned_job,
        source_classification_id="ctgoodjobs:001",
        label="Accounting",
    )
    review_source = _project_source_path(
        canonical_taxonomy_db,
        review_job,
        source_classification_id="ctgoodjobs:048",
        label="Administration & Office Support",
    )
    CanonicalJobTaxonomy(canonical_taxonomy_db).evaluate(
        assigned_job.id,
        assigned_source,
    )
    CanonicalJobTaxonomy(canonical_taxonomy_db).evaluate(
        review_job.id,
        review_source,
    )
    canonical_taxonomy_db.commit()

    before = {
        "jobs": canonical_taxonomy_db.query(Job).count(),
        "assignments": canonical_taxonomy_db.query(JobTaxonomyAssignment).count(),
        "reviews": canonical_taxonomy_db.query(JobTaxonomyReviewItem).count(),
        "outbox": canonical_taxonomy_db.query(EventOutbox).count(),
        "audit": canonical_taxonomy_db.query(GovernanceAuditEvent).count(),
    }

    inspector = CanonicalTaxonomyRebuildInspector(canonical_taxonomy_db)
    first = inspector.inspect()
    second = inspector.inspect()

    after = {
        "jobs": canonical_taxonomy_db.query(Job).count(),
        "assignments": canonical_taxonomy_db.query(JobTaxonomyAssignment).count(),
        "reviews": canonical_taxonomy_db.query(JobTaxonomyReviewItem).count(),
        "outbox": canonical_taxonomy_db.query(EventOutbox).count(),
        "audit": canonical_taxonomy_db.query(GovernanceAuditEvent).count(),
    }
    payload = first.to_payload()
    assert second.to_payload() == payload
    assert before == after
    assert (
        len(canonical_taxonomy_db.new),
        len(canonical_taxonomy_db.dirty),
        len(canonical_taxonomy_db.deleted),
    ) == (0, 0, 0)
    assert payload["mode"] == "read-only"
    assert payload["jobs_inspected"] == 2
    assert payload["taxonomy_revision"] == {
        "id": str(taxonomy_revision.revision_id),
        "content_hash": taxonomy_revision.content_hash,
    }
    assert payload["mapping_revision"] == {
        "id": str(mapping_revision.revision_id),
        "content_hash": mapping_revision.content_hash,
    }
    assert payload["job_states"] == {
        "assigned": 1,
        "unassigned_review_pending": 1,
    }
    assert payload["accepted_by_method"] == {"reviewed_mapping": 1}
    assert payload["review_by_reason"] == {"classifier_output_missing": 1}
    assert payload["mapping_evidence"]["coverage_by_source"] == {
        "ctgoodjobs": {
            "identity_count": 12,
            "identity_set_hash": payload["mapping_evidence"]["coverage_by_source"][
                "ctgoodjobs"
            ]["identity_set_hash"],
            "source_catalog_fingerprint": payload["mapping_evidence"][
                "coverage_by_source"
            ]["ctgoodjobs"]["source_catalog_fingerprint"],
            "source_catalog_revision_id": payload["mapping_evidence"][
                "coverage_by_source"
            ]["ctgoodjobs"]["source_catalog_revision_id"],
        },
        "jobsdb": {
            "identity_count": 25,
            "identity_set_hash": payload["mapping_evidence"]["coverage_by_source"][
                "jobsdb"
            ]["identity_set_hash"],
            "source_catalog_fingerprint": payload["mapping_evidence"][
                "coverage_by_source"
            ]["jobsdb"]["source_catalog_fingerprint"],
            "source_catalog_revision_id": payload["mapping_evidence"][
                "coverage_by_source"
            ]["jobsdb"]["source_catalog_revision_id"],
        },
        "offertoday": {
            "identity_count": 31,
            "identity_set_hash": payload["mapping_evidence"]["coverage_by_source"][
                "offertoday"
            ]["identity_set_hash"],
            "source_catalog_fingerprint": payload["mapping_evidence"][
                "coverage_by_source"
            ]["offertoday"]["source_catalog_fingerprint"],
            "source_catalog_revision_id": payload["mapping_evidence"][
                "coverage_by_source"
            ]["offertoday"]["source_catalog_revision_id"],
        },
    }
    assert payload["mapping_evidence"]["job_policy"] == {
        "conflicting_mapping_jobs": 0,
        "excluded_mapping_jobs": 0,
        "missing_mapping_jobs": 0,
        "projected_path_jobs": 2,
        "source_catalog_provenance_mismatch_jobs": 0,
        "source_catalog_provenance_missing_jobs": 0,
        "unmapped_mapping_jobs": 0,
    }
    assert payload["legacy_comparison"] == {
        "agreement_jobs": 0,
        "both_assigned_jobs": 1,
        "canonical_only_jobs": 0,
        "disagreement_jobs": 1,
        "legacy_assigned_jobs": 1,
        "legacy_auto_created_jobs": 1,
        "legacy_fallback_jobs": 1,
        "legacy_only_jobs": 0,
        "neither_assigned_jobs": 1,
    }
    assert payload["classifier_provenance"] == {
        "classifier_hash_only_jobs": 0,
        "constrained_ai_missing_model_provenance_jobs": 0,
        "mapping_provenance_missing_jobs": 0,
        "raw_classifier_output_available_jobs": 0,
        "raw_classifier_output_unavailable_jobs": 1,
    }
    assert payload["unrecoverable_parser_evidence"] == {
        "causes": {"no_preserved_evidence": 2},
        "jobs": 2,
    }


def test_rebuild_inspector_reports_missing_model_and_mapping_provenance(
    canonical_taxonomy_db,
):
    seed = json.loads(SEED_PATH.read_text())
    mapping_seed = json.loads(MAPPING_PATH.read_text())
    publisher = CanonicalTaxonomyPublisher(canonical_taxonomy_db)
    taxonomy_revision = publisher.materialize(seed)
    publisher.activate(taxonomy_revision, expected_lock_version=0)
    _publish_fixture_catalogs(canonical_taxonomy_db, mapping_seed)
    mapping_revision = publisher.materialize_mapping(seed, mapping_seed)
    publisher.activate_mapping(mapping_revision, expected_lock_version=0)
    target = canonical_taxonomy_db.scalar(
        select(CanonicalJobSubcategory).where(
            CanonicalJobSubcategory.revision_id == taxonomy_revision.revision_id,
            CanonicalJobSubcategory.code
            == "accounting.financial_accounting.accounts_payable",
        )
    )
    mapping = canonical_taxonomy_db.scalar(
        select(SourceJobTaxonomyMapping).where(
            SourceJobTaxonomyMapping.mapping_revision_id
            == mapping_revision.revision_id,
            SourceJobTaxonomyMapping.source_classification_id == "ctgoodjobs:001",
        )
    )
    assert target is not None
    assert mapping is not None
    company = Company(
        company_id="canonical-provenance-company",
        source_site="ctgoodjobs",
        source_company_id="canonical-provenance-company",
        name="Canonical Provenance Company",
    )
    missing_model_job = Job(
        job_id="canonical-provenance-model",
        source_site="ctgoodjobs",
        source_job_id="canonical-provenance-model",
        company=company,
        title="Missing model provenance",
    )
    missing_mapping_job = Job(
        job_id="canonical-provenance-mapping",
        source_site="ctgoodjobs",
        source_job_id="canonical-provenance-mapping",
        company=company,
        title="Missing mapping provenance",
    )
    canonical_taxonomy_db.add_all([missing_model_job, missing_mapping_job])
    canonical_taxonomy_db.flush()
    breadcrumb = canonical_breadcrumb(
        canonical_taxonomy_db,
        target.id,
        taxonomy_revision_id=taxonomy_revision.revision_id,
    )
    canonical_taxonomy_db.add_all(
        [
            JobTaxonomyAssignment(
                job_id=missing_model_job.id,
                taxonomy_revision_id=taxonomy_revision.revision_id,
                subcategory_id=target.id,
                mapping_revision_id=mapping_revision.revision_id,
                method="constrained_ai",
                evidence_hash="a" * 64,
                source_evidence_refs=[
                    {
                        "kind": "ai-classifier-output",
                        "content_hash": "b" * 64,
                    }
                ],
                mapping_ids=[str(mapping.id)],
                model_provider="openai",
                model_name="gpt-test",
                model_version=None,
                breadcrumb=breadcrumb,
                lock_version=1,
                is_current=True,
            ),
            JobTaxonomyAssignment(
                job_id=missing_mapping_job.id,
                taxonomy_revision_id=taxonomy_revision.revision_id,
                subcategory_id=target.id,
                mapping_revision_id=None,
                method="reviewed_mapping",
                evidence_hash="c" * 64,
                source_evidence_refs=[{"kind": "fixture", "id": "mapping"}],
                mapping_ids=[],
                model_provider=None,
                model_name=None,
                model_version=None,
                breadcrumb=breadcrumb,
                lock_version=1,
                is_current=True,
            ),
        ]
    )
    canonical_taxonomy_db.commit()

    report = CanonicalTaxonomyRebuildInspector(canonical_taxonomy_db).inspect(
        (missing_model_job.id, missing_mapping_job.id)
    )

    assert report.to_payload()["classifier_provenance"] == {
        "classifier_hash_only_jobs": 1,
        "constrained_ai_missing_model_provenance_jobs": 1,
        "mapping_provenance_missing_jobs": 1,
        "raw_classifier_output_available_jobs": 0,
        "raw_classifier_output_unavailable_jobs": 1,
    }


def test_canonical_rebuild_cli_is_read_only_and_has_no_apply_mode(
    monkeypatch,
    capsys,
):
    from scripts import inspect_canonical_job_taxonomy

    class ReadOnlySession:
        closed = False

        def close(self):
            self.closed = True

        def commit(self):
            raise AssertionError("read-only inspection must not commit")

        def flush(self):
            raise AssertionError("read-only inspection must not flush")

        def add(self, _value):
            raise AssertionError("read-only inspection must not add rows")

        def delete(self, _value):
            raise AssertionError("read-only inspection must not delete rows")

    class Report:
        @staticmethod
        def to_payload():
            return {
                "accepted_by_method": {},
                "classifier_provenance": {},
                "job_states": {},
                "jobs_inspected": 0,
                "legacy_comparison": {},
                "mapping_evidence": {},
                "mapping_revision": None,
                "mode": "read-only",
                "review_by_reason": {},
                "review_by_status": {},
                "source_attribute_rebuild": {
                    "jobs_inspected": 0,
                    "sources": [],
                },
                "taxonomy_revision": None,
                "unrecoverable_parser_evidence": {"causes": {}, "jobs": 0},
            }

    db = ReadOnlySession()
    inspected_sessions = []

    class Inspector:
        def __init__(self, session):
            inspected_sessions.append(session)

        @staticmethod
        def inspect(job_ids=None):
            assert job_ids is None
            return Report()

    monkeypatch.setattr(inspect_canonical_job_taxonomy, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        inspect_canonical_job_taxonomy,
        "CanonicalTaxonomyRebuildInspector",
        Inspector,
    )

    assert inspect_canonical_job_taxonomy.main([]) == 0
    expected = json.dumps(
        Report.to_payload(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert capsys.readouterr().out == f"{expected}\n"
    assert inspected_sessions == [db]
    assert db.closed is True

    assert inspect_canonical_job_taxonomy.main(["--format", "human"]) == 0
    human_output = capsys.readouterr().out
    assert "review_by_status: {}" in human_output
    assert "mapping_evidence: {}" in human_output
    assert 'source_attribute_rebuild: {"jobs_inspected":0,"sources":[]}' in human_output
    assert inspected_sessions == [db, db]

    for forbidden_option in ("--apply", "--execute", "--activate"):
        with pytest.raises(SystemExit) as exc_info:
            inspect_canonical_job_taxonomy.main([forbidden_option])
        assert exc_info.value.code == 2


class _FailingOutboxRepository:
    def enqueue(self, *_args, **_kwargs):
        raise RuntimeError("forced outbox failure")


def _with_deterministic_mapping(mapping_seed, source_id, target_code):
    mapping_seed = deepcopy(mapping_seed)
    entry = next(
        item
        for item in mapping_seed["entries"]
        if item["source_classification_id"] == source_id
    )
    assert entry["disposition"] == "allowed_slice"
    entry["disposition"] = "deterministic"
    entry["target_codes"] = [target_code]
    mapping_seed["expected_counts"]["allowed_slice"] -= 1
    mapping_seed["expected_counts"]["deterministic"] += 1
    return mapping_seed


def _with_non_mapping_disposition(mapping_seed, source_id, disposition):
    mapping_seed = deepcopy(mapping_seed)
    entry = next(
        item
        for item in mapping_seed["entries"]
        if item["source_classification_id"] == source_id
    )
    previous = entry["disposition"]
    assert previous in {"allowed_slice", "deterministic"}
    assert disposition in {"excluded", "unmapped"}
    entry["disposition"] = disposition
    entry["target_codes"] = []
    mapping_seed["expected_counts"][previous] -= 1
    mapping_seed["expected_counts"][disposition] += 1
    return mapping_seed


def _without_source_mappings(mapping_seed, source_site):
    mapping_seed = deepcopy(mapping_seed)
    removed = [
        entry
        for entry in mapping_seed["entries"]
        if entry["source_site"] == source_site
    ]
    mapping_seed["entries"] = [
        entry
        for entry in mapping_seed["entries"]
        if entry["source_site"] != source_site
    ]
    mapping_seed["expected_counts"]["entries"] -= len(removed)
    for entry in removed:
        mapping_seed["expected_counts"][entry["disposition"]] -= 1
    return mapping_seed


def _without_mapping_entry(mapping_seed, source_id):
    mapping_seed = deepcopy(mapping_seed)
    removed = next(
        entry
        for entry in mapping_seed["entries"]
        if entry["source_classification_id"] == source_id
    )
    mapping_seed["entries"] = [
        entry
        for entry in mapping_seed["entries"]
        if entry["source_classification_id"] != source_id
    ]
    mapping_seed["expected_counts"]["entries"] -= 1
    mapping_seed["expected_counts"][removed["disposition"]] -= 1
    return mapping_seed


def _with_extra_excluded_mapping(
    mapping_seed,
    *,
    source_site,
    source_classification_id,
    source_label,
):
    mapping_seed = deepcopy(mapping_seed)
    mapping_seed["entries"].append(
        {
            "source_site": source_site,
            "source_classification_id": source_classification_id,
            "source_label": source_label,
            "disposition": "excluded",
            "target_codes": [],
            "review_evidence": {"fixture": True},
        }
    )
    mapping_seed["entries"].sort(key=lambda entry: entry["source_classification_id"])
    mapping_seed["expected_counts"]["entries"] += 1
    mapping_seed["expected_counts"]["excluded"] += 1
    return mapping_seed


def _project_source_path(db, job, *, source_classification_id, label):
    return _project_source_paths(
        db,
        job,
        paths=((source_classification_id, label),),
    )


def _project_source_paths(db, job, *, paths):
    catalog_revision = (
        db.query(SourceCatalogRevision)
        .filter(SourceCatalogRevision.source_site == job.source_site)
        .one()
    )
    provenance = Provenance(
        method="canonical-taxonomy-test",
        source_site=job.source_site,
        evidence_refs=({"kind": "fixture", "source_job_id": job.source_job_id},),
        captured_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
    )
    evidence = SourceJobAttributeEvidence(
        source_site=job.source_site,
        classification_paths=tuple(
            SourceClassificationPathEvidence(
                source_order=source_order,
                nodes=(
                    SourceClassificationNodeEvidence(
                        source_position=1,
                        native_depth=0,
                        source_classification_id=source_classification_id,
                        native_id=source_classification_id.split(":", 1)[1],
                        label=label,
                    ),
                ),
                source_declared_primary=False,
                primary_basis=None,
                source_catalog_revision=SourceCatalogRevisionRef(
                    source_site=job.source_site,
                    revision_id=catalog_revision.id,
                    fingerprint=catalog_revision.fingerprint,
                ),
                provenance=provenance,
            )
            for source_order, (source_classification_id, label) in enumerate(
                paths,
                start=1,
            )
        ),
        employment_labels=(),
    )
    return SourceJobAttributes(db).project(job.id, evidence).view


def _publish_fixture_catalogs(
    db,
    mapping_seed,
    *,
    revision_fingerprint_overrides=None,
):
    entries_by_source: dict[str, list[dict]] = {}
    for entry in mapping_seed["entries"]:
        entries_by_source.setdefault(entry["source_site"], []).append(entry)

    for source_site, entries in sorted(entries_by_source.items()):
        nodes = tuple(
            CatalogNodeSnapshot(
                node_key=entry["source_classification_id"],
                source_site=source_site,
                classification_id=entry["source_classification_id"],
                native_id=entry["source_classification_id"].split(":", 1)[1],
                native_label=entry["source_label"],
                parent_node_key=None,
                native_path=(entry["source_label"],),
                depth=0,
                selectable=True,
                supports_exact=False,
                supports_subtree=False,
                queryable=False,
                alias_of_node_key=None,
                query_semantics_hash=None,
            )
            for entry in entries
        )
        catalog = DiscoveredCatalog(
            source_site=source_site,
            nodes=nodes,
            capabilities=CatalogScopeCapabilities(
                supports_all_scope=False,
                all_scope_root_node_keys=(),
            ),
            source_payload={"fixture_source": source_site},
            provenance={"fixture": True},
        )
        candidate = SourceCatalogCandidate(
            source_site=source_site,
            fingerprint=catalog.fingerprint,
            normalized_payload=catalog.normalized_payload(),
            source_payload=dict(catalog.source_payload),
            provenance=dict(catalog.provenance),
            diff={},
            validation_summary={"valid": True},
            state="published",
        )
        db.add(candidate)
        db.flush()
        revision = SourceCatalogRevision(
            source_site=source_site,
            sequence=1,
            fingerprint=(revision_fingerprint_overrides or {}).get(
                source_site,
                catalog.fingerprint,
            ),
            normalized_payload=catalog.normalized_payload(),
            source_payload=dict(catalog.source_payload),
            provenance=dict(catalog.provenance),
            candidate_id=candidate.id,
            publication_metadata={"fixture": True},
            published_by="fixture",
        )
        db.add(revision)
        db.flush()
        db.add(
            SourceCatalogActiveRevision(
                source_site=source_site,
                revision_id=revision.id,
                updated_by="fixture",
            )
        )
    db.commit()
