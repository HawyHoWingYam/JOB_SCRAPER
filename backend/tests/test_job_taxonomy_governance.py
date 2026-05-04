import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models import Company, Job, JobCategory, JobDomain, JobSubcategory
from app.services.job_category_normalizer import JobCategoryNormalizer
from scripts import govern_job_taxonomy
from scripts import migrate_job_categories

if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"


def _build_sqlite_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__,
            JobDomain.__table__,
            JobCategory.__table__,
            JobSubcategory.__table__,
            Job.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def _seed_taxonomy(db):
    domain = JobDomain(id=uuid.uuid4(), name="Information & Communication Technology")
    general_category = JobCategory(
        id=uuid.uuid4(),
        domain_id=domain.id,
        name="General",
    )
    software_category = JobCategory(
        id=uuid.uuid4(),
        domain_id=domain.id,
        name="Software Development",
    )
    general = JobSubcategory(
        id=uuid.uuid4(),
        category_id=general_category.id,
        name="General",
    )
    backend = JobSubcategory(
        id=uuid.uuid4(),
        category_id=software_category.id,
        name="Backend Development",
    )
    db.add_all([domain, general_category, software_category, general, backend])
    db.commit()
    return general, backend


def test_normalize_category_legacy_wrapper_auto_creates_inferred_path_in_empty_db():
    db = _build_sqlite_session()
    try:
        normalizer = JobCategoryNormalizer(db)

        resolved = normalizer.normalize_category("Backend Engineer")

        created = db.query(JobSubcategory).filter_by(id=resolved).one()

        assert created.name == "Backend Development"
        assert created.category.name == "Software Development"
        assert created.category.domain.name == "Information & Communication Technology"
    finally:
        db.close()


def test_unknown_final_create_new_leaf_falls_back_to_source_path():
    db = _build_sqlite_session()
    try:
        _, backend = _seed_taxonomy(db)
        normalizer = JobCategoryNormalizer(db)

        resolved = normalizer.resolve_taxonomy_decision(
            {
                "source_path_decision": {
                    "domain": "Information & Communication Technology",
                    "category": "Software Development",
                    "subcategory": "Backend Development",
                    "resolution": "match_existing",
                },
                "final_taxonomy_decision": {
                    "domain": "Information & Communication Technology",
                    "category": "Software Development",
                    "subcategory": "Platform Reliability",
                    "resolution": "create_new",
                },
            },
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Unknown Source Bucket",
        )

        assert resolved == backend.id
        assert db.query(JobSubcategory).filter_by(name="Platform Reliability").count() == 0
    finally:
        db.close()


def test_missing_default_fallback_path_is_created_for_invalid_non_override_ai_paths():
    db = _build_sqlite_session()
    try:
        domain = JobDomain(
            id=uuid.uuid4(),
            name="Information & Communication Technology",
        )
        db.add(domain)
        db.commit()

        normalizer = JobCategoryNormalizer(db)

        resolved = normalizer.resolve_taxonomy_decision(
            {
                "source_path_decision": {
                    "domain": "Information & Communication Technology",
                    "category": "Software Development",
                    "subcategory": "Platform Reliability",
                    "resolution": "create_new",
                },
                "final_taxonomy_decision": {
                    "domain": "Information & Communication Technology",
                    "category": "Observability",
                    "subcategory": "SRE Platform",
                    "resolution": "create_new",
                },
            },
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Unknown Source Bucket",
        )

        created = db.query(JobSubcategory).filter_by(id=resolved).one()

        assert created.name == "General"
        assert created.category.name == "General"
        assert created.category.domain.name == "Information & Communication Technology"
        assert db.query(JobSubcategory).filter_by(name="Platform Reliability").count() == 0
        assert db.query(JobCategory).filter_by(name="Observability").count() == 0
    finally:
        db.close()


def test_unknown_source_create_new_leaf_falls_back_to_registry_default_path():
    db = _build_sqlite_session()
    try:
        general, _ = _seed_taxonomy(db)
        normalizer = JobCategoryNormalizer(db)

        resolved = normalizer.resolve_taxonomy_decision(
            {
                "source_path_decision": {
                    "domain": "Information & Communication Technology",
                    "category": "Software Development",
                    "subcategory": "Platform Reliability",
                    "resolution": "create_new",
                },
            },
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Unknown Source Bucket",
        )

        assert resolved == general.id
        assert db.query(JobSubcategory).filter_by(name="Platform Reliability").count() == 0
    finally:
        db.close()


@pytest.mark.parametrize("resolution", ["match_existing", None])
def test_unknown_non_override_ai_leaf_falls_back_to_source_path_for_non_create_resolutions(
    resolution,
):
    db = _build_sqlite_session()
    try:
        _, backend = _seed_taxonomy(db)
        normalizer = JobCategoryNormalizer(db)

        final_decision = {
            "domain": "Information & Communication Technology",
            "category": "Software Development",
            "subcategory": "Platform Reliability",
        }
        if resolution is not None:
            final_decision["resolution"] = resolution

        resolved = normalizer.resolve_taxonomy_decision(
            {
                "source_path_decision": {
                    "domain": "Information & Communication Technology",
                    "category": "Software Development",
                    "subcategory": "Backend Development",
                    "resolution": "match_existing",
                },
                "final_taxonomy_decision": final_decision,
            },
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Developers/Programmers",
        )

        assert resolved == backend.id
        assert db.query(JobSubcategory).filter_by(name="Platform Reliability").count() == 0
    finally:
        db.close()


def test_governance_override_allows_creating_new_leaf():
    db = _build_sqlite_session()
    try:
        _, backend = _seed_taxonomy(db)
        normalizer = JobCategoryNormalizer(db)

        resolved = normalizer.resolve_taxonomy_decision(
            {
                "governance_override": True,
                "source_path_decision": {
                    "domain": "Information & Communication Technology",
                    "category": "Software Development",
                    "subcategory": "Backend Development",
                    "resolution": "match_existing",
                },
                "final_taxonomy_decision": {
                    "domain": "Information & Communication Technology",
                    "category": "Software Development",
                    "subcategory": "Platform Reliability",
                    "resolution": "create_new",
                },
            },
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Developers/Programmers",
        )

        created = db.query(JobSubcategory).filter_by(name="Platform Reliability").one()

        assert resolved == created.id
        assert created.category_id == backend.category_id
    finally:
        db.close()


def test_get_category_hierarchy_can_render_compatibility_string():
    db = _build_sqlite_session()
    try:
        _, backend = _seed_taxonomy(db)
        normalizer = JobCategoryNormalizer(db)

        hierarchy = normalizer.get_category_hierarchy(backend.id)

        assert hierarchy == {
            "subcategory": "Backend Development",
            "category": "Software Development",
            "domain": "Information & Communication Technology",
        }
    finally:
        db.close()


def test_backfill_unmapped_jobs_assigns_default_slice_path():
    db = _build_sqlite_session()
    try:
        general, _ = _seed_taxonomy(db)
        company = Company(
            id=uuid.uuid4(),
            company_id="company-1",
            name="Company 1",
        )
        job = Job(
            id=uuid.uuid4(),
            job_id="job-1",
            source_site="jobsdb",
            company_id=company.id,
            title="Unmapped role",
            description="Needs fallback",
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Unknown Source Bucket",
        )
        db.add_all([company, job])
        db.commit()

        updated = govern_job_taxonomy.backfill_unmapped_jobs(db, execute=True)

        db.refresh(job)
        assert updated == 1
        assert job.subcategory_id == general.id
    finally:
        db.close()


def test_backfill_unmapped_jobs_uses_subclassification_specific_default_path():
    db = _build_sqlite_session()
    try:
        company = Company(
            id=uuid.uuid4(),
            company_id="company-1",
            name="Company 1",
        )
        job = Job(
            id=uuid.uuid4(),
            job_id="job-1",
            source_site="jobsdb",
            company_id=company.id,
            title="Business Systems Analyst",
            description="Needs subclassification-specific path",
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Business/Systems Analysts",
        )
        db.add_all([company, job])
        db.commit()

        updated = govern_job_taxonomy.backfill_unmapped_jobs(db, execute=True)

        db.refresh(job)
        hierarchy = JobCategoryNormalizer(db).get_category_hierarchy(job.subcategory_id)
        assert updated == 1
        assert hierarchy == {
            "subcategory": "Data Analysis",
            "category": "Data & Analytics",
            "domain": "Information & Communication Technology",
        }
    finally:
        db.close()


def test_resolve_taxonomy_decision_prefers_specific_default_over_generic_leaf():
    db = _build_sqlite_session()
    try:
        _, backend = _seed_taxonomy(db)
        normalizer = JobCategoryNormalizer(db)

        resolved = normalizer.resolve_taxonomy_decision(
            {
                "source_path_decision": {
                    "domain": "Information & Communication Technology",
                    "category": "Software Development",
                    "subcategory": "General",
                    "resolution": "match_existing",
                },
                "final_taxonomy_decision": {
                    "domain": "Information & Communication Technology",
                    "category": "Software Development",
                    "subcategory": "General",
                    "resolution": "match_existing",
                },
            },
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Developers/Programmers",
        )

        assert resolved == backend.id
    finally:
        db.close()


def test_backfill_unmapped_jobs_skips_unknown_source_classification_and_continues_batch():
    db = _build_sqlite_session()
    try:
        general, _ = _seed_taxonomy(db)
        company = Company(
            id=uuid.uuid4(),
            company_id="company-1",
            name="Company 1",
        )
        known_job = Job(
            id=uuid.uuid4(),
            job_id="job-known",
            source_site="jobsdb",
            company_id=company.id,
            title="Known role",
            description="Known source classification",
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Unknown Source Bucket",
        )
        unknown_job = Job(
            id=uuid.uuid4(),
            job_id="job-unknown",
            source_site="jobsdb",
            company_id=company.id,
            title="Unknown role",
            description="Unknown source classification",
            source_classification_id="not-in-registry",
            source_classification_name="Mystery",
            source_subclassification_name="Mystery",
        )
        db.add_all([company, known_job, unknown_job])
        db.commit()

        updated = govern_job_taxonomy.backfill_unmapped_jobs(db, execute=True)

        db.refresh(known_job)
        db.refresh(unknown_job)
        assert updated == 1
        assert known_job.subcategory_id == general.id
        assert unknown_job.subcategory_id is None
    finally:
        db.close()


def test_rebuild_job_taxonomy_metrics_recomputes_distinct_job_count(monkeypatch):
    db = _build_sqlite_session()
    try:
        _, backend = _seed_taxonomy(db)
        company = Company(
            id=uuid.uuid4(),
            company_id="company-1",
            name="Company 1",
        )
        jobs = [
            Job(
                id=uuid.uuid4(),
                job_id="job-1",
                source_site="jobsdb",
                company_id=company.id,
                title="A",
                description="A",
                subcategory_id=backend.id,
                created_at=datetime(2026, 4, 30, 9, 0, 0),
                ai_enriched_at=datetime(2026, 4, 30, 11, 0, 0),
            ),
            Job(
                id=uuid.uuid4(),
                job_id="job-2",
                source_site="jobsdb",
                company_id=company.id,
                title="B",
                description="B",
                subcategory_id=backend.id,
                created_at=datetime(2026, 4, 30, 10, 0, 0),
                ai_enriched_at=datetime(2026, 4, 30, 12, 0, 0),
            ),
        ]
        db.add(company)
        db.add_all(jobs)
        backend.usage_count = 99
        backend.distinct_job_count = 99
        backend.is_filter_visible = False
        backend.category.usage_count = 99
        backend.category.distinct_job_count = 99
        backend.category.is_filter_visible = False
        backend.category.domain.usage_count = 99
        backend.category.domain.distinct_job_count = 99
        backend.category.domain.is_filter_visible = False
        db.commit()

        monkeypatch.setattr(govern_job_taxonomy.settings, "filter_job_l3_min_jobs", 2)
        monkeypatch.setattr(govern_job_taxonomy.settings, "filter_job_l2_min_jobs", 2)
        monkeypatch.setattr(govern_job_taxonomy.settings, "filter_job_l1_min_jobs", 2)

        govern_job_taxonomy.rebuild_job_taxonomy_metrics(db)

        db.refresh(backend)
        db.refresh(backend.category)
        db.refresh(backend.category.domain)

        assert backend.usage_count == 2
        assert backend.distinct_job_count == 2
        assert backend.is_filter_visible is True
        assert backend.category.usage_count == 2
        assert backend.category.distinct_job_count == 2
        assert backend.category.is_filter_visible is True
        assert backend.category.domain.usage_count == 2
        assert backend.category.domain.distinct_job_count == 2
        assert backend.category.domain.is_filter_visible is True
        assert backend.last_used_at == datetime(2026, 4, 30, 12, 0, 0)
        assert backend.category.last_used_at == datetime(2026, 4, 30, 12, 0, 0)
        assert backend.category.domain.last_used_at == datetime(2026, 4, 30, 12, 0, 0)
    finally:
        db.close()


def test_backfill_unmapped_jobs_dry_run_rolls_back_job_assignments_and_metrics():
    db = _build_sqlite_session()
    try:
        general, _ = _seed_taxonomy(db)
        company = Company(
            id=uuid.uuid4(),
            company_id="company-1",
            name="Company 1",
        )
        job = Job(
            id=uuid.uuid4(),
            job_id="job-1",
            source_site="jobsdb",
            company_id=company.id,
            title="Dry run role",
            description="Should roll back",
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Unknown Source Bucket",
        )
        original_last_used_at = datetime(2026, 4, 29, 8, 0, 0)
        general.usage_count = 99
        general.distinct_job_count = 88
        general.is_filter_visible = True
        general.last_used_at = original_last_used_at
        general.category.usage_count = 77
        general.category.distinct_job_count = 66
        general.category.is_filter_visible = True
        general.category.last_used_at = original_last_used_at
        general.category.domain.usage_count = 55
        general.category.domain.distinct_job_count = 44
        general.category.domain.is_filter_visible = True
        general.category.domain.last_used_at = original_last_used_at
        db.add_all([company, job])
        db.commit()

        updated = govern_job_taxonomy.backfill_unmapped_jobs(db, execute=False)

        db.refresh(job)
        db.refresh(general)
        db.refresh(general.category)
        db.refresh(general.category.domain)

        assert updated == 1
        assert job.subcategory_id is None
        assert general.usage_count == 99
        assert general.distinct_job_count == 88
        assert general.is_filter_visible is True
        assert general.last_used_at == original_last_used_at
        assert general.category.usage_count == 77
        assert general.category.distinct_job_count == 66
        assert general.category.is_filter_visible is True
        assert general.category.last_used_at == original_last_used_at
        assert general.category.domain.usage_count == 55
        assert general.category.domain.distinct_job_count == 44
        assert general.category.domain.is_filter_visible is True
        assert general.category.domain.last_used_at == original_last_used_at
    finally:
        db.close()


def test_refine_base_default_jobs_reassigns_general_general_when_specific_default_exists():
    db = _build_sqlite_session()
    try:
        general, _ = _seed_taxonomy(db)
        company = Company(
            id=uuid.uuid4(),
            company_id="company-1",
            name="Company 1",
        )
        job = Job(
            id=uuid.uuid4(),
            job_id="job-1",
            source_site="jobsdb",
            company_id=company.id,
            title="Senior Business Analyst",
            description="Currently on the base default path",
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Business/Systems Analysts",
            subcategory_id=general.id,
        )
        db.add_all([company, job])
        db.commit()

        updated = govern_job_taxonomy.refine_base_default_jobs(db, execute=True)

        db.refresh(job)
        hierarchy = JobCategoryNormalizer(db).get_category_hierarchy(job.subcategory_id)
        assert updated == 1
        assert hierarchy == {
            "subcategory": "Data Analysis",
            "category": "Data & Analytics",
            "domain": "Information & Communication Technology",
        }
    finally:
        db.close()


def test_refine_base_default_jobs_uses_title_heuristics_for_other_bucket():
    db = _build_sqlite_session()
    try:
        general, _ = _seed_taxonomy(db)
        company = Company(
            id=uuid.uuid4(),
            company_id="company-1",
            name="Company 1",
        )
        job = Job(
            id=uuid.uuid4(),
            job_id="job-1",
            source_site="jobsdb",
            company_id=company.id,
            title="Senior UX Designer",
            description="Own the product design system and interaction flows.",
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Other",
            subcategory_id=general.id,
        )
        db.add_all([company, job])
        db.commit()

        updated = govern_job_taxonomy.refine_base_default_jobs(db, execute=True)

        db.refresh(job)
        hierarchy = JobCategoryNormalizer(db).get_category_hierarchy(job.subcategory_id)
        assert updated == 1
        assert hierarchy == {
            "subcategory": "UI/UX Design",
            "category": "Product & Quality",
            "domain": "Information & Communication Technology",
        }
    finally:
        db.close()


def test_refine_base_default_jobs_keeps_ambiguous_other_bucket_when_no_safe_heuristic():
    db = _build_sqlite_session()
    try:
        general, _ = _seed_taxonomy(db)
        company = Company(
            id=uuid.uuid4(),
            company_id="company-1",
            name="Company 1",
        )
        job = Job(
            id=uuid.uuid4(),
            job_id="job-1",
            source_site="jobsdb",
            company_id=company.id,
            title="Technology Trainee",
            description="Support the team across multiple tasks.",
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Other",
            subcategory_id=general.id,
        )
        db.add_all([company, job])
        db.commit()

        updated = govern_job_taxonomy.refine_base_default_jobs(db, execute=True)

        db.refresh(job)
        assert updated == 0
        assert job.subcategory_id == general.id
    finally:
        db.close()


def test_apply_job_taxonomy_governance_reassigns_off_taxonomy_ict_paths():
    db = _build_sqlite_session()
    try:
        _, backend = _seed_taxonomy(db)
        governed_web = JobSubcategory(
            id=uuid.uuid4(),
            category_id=backend.category_id,
            name="Web Development",
        )
        drift_category = JobCategory(
            id=uuid.uuid4(),
            domain_id=backend.category.domain_id,
            name="Web Development",
            created_by="ai",
            is_auto_created=True,
        )
        drift_subcategory = JobSubcategory(
            id=uuid.uuid4(),
            category_id=drift_category.id,
            name="Web Development",
            created_by="ai",
            is_auto_created=True,
        )
        company = Company(
            id=uuid.uuid4(),
            company_id="company-1",
            name="Company 1",
        )
        drifted_job = Job(
            id=uuid.uuid4(),
            job_id="job-1",
            source_site="jobsdb",
            company_id=company.id,
            title="Web Developer",
            description="Build public websites and web applications.",
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Web Development & Production",
            subcategory_id=drift_subcategory.id,
        )
        db.add_all([governed_web, drift_category, drift_subcategory, company, drifted_job])
        db.commit()

        report = govern_job_taxonomy.apply_job_taxonomy_governance(db, execute=True)

        db.refresh(drifted_job)
        hierarchy = JobCategoryNormalizer(db).get_category_hierarchy(drifted_job.subcategory_id)

        assert report["jobs_reconciled_off_taxonomy"] == 1
        assert hierarchy == {
            "subcategory": "Web Development",
            "category": "Software Development",
            "domain": "Information & Communication Technology",
        }
    finally:
        db.close()


def test_prune_unused_taxonomy_nodes_removes_empty_subcategories_categories_and_domains():
    db = _build_sqlite_session()
    try:
        general, backend = _seed_taxonomy(db)

        empty_domain = JobDomain(
            id=uuid.uuid4(),
            name="Unused Domain",
        )
        empty_category = JobCategory(
            id=uuid.uuid4(),
            domain_id=empty_domain.id,
            name="Unused Category",
        )
        empty_subcategory = JobSubcategory(
            id=uuid.uuid4(),
            category_id=empty_category.id,
            name="Unused Subcategory",
        )
        db.add_all([empty_domain, empty_category, empty_subcategory])

        partially_empty_category = JobCategory(
            id=uuid.uuid4(),
            domain_id=backend.category.domain_id,
            name="Partially Empty Category",
        )
        partially_empty_subcategory = JobSubcategory(
            id=uuid.uuid4(),
            category_id=partially_empty_category.id,
            name="Partially Empty Subcategory",
        )
        db.add_all([partially_empty_category, partially_empty_subcategory])

        company = Company(
            id=uuid.uuid4(),
            company_id="company-1",
            name="Company 1",
        )
        used_job = Job(
            id=uuid.uuid4(),
            job_id="job-1",
            source_site="jobsdb",
            company_id=company.id,
            title="Used role",
            description="Used role",
            subcategory_id=backend.id,
        )
        db.add_all([company, used_job])
        db.commit()

        govern_job_taxonomy.rebuild_job_taxonomy_metrics(db)
        deleted = govern_job_taxonomy.prune_unused_taxonomy_nodes(db, execute=True)

        assert deleted == {
            "subcategories_deleted": 3,
            "categories_deleted": 3,
            "domains_deleted": 1,
        }
        assert db.query(JobSubcategory).filter_by(id=empty_subcategory.id).count() == 0
        assert db.query(JobCategory).filter_by(id=empty_category.id).count() == 0
        assert db.query(JobDomain).filter_by(id=empty_domain.id).count() == 0
        assert db.query(JobCategory).filter_by(id=partially_empty_category.id).count() == 0
        assert db.query(JobSubcategory).filter_by(id=general.id).count() == 0
        assert db.query(JobCategory).filter_by(id=general.category_id).count() == 0
        assert db.query(JobSubcategory).filter_by(id=backend.id).count() == 1
    finally:
        db.close()


def test_migrate_job_categories_uses_governed_source_classification_flow():
    db = _build_sqlite_session()
    try:
        general, _ = _seed_taxonomy(db)
        company = Company(
            id=uuid.uuid4(),
            company_id="company-1",
            name="Company 1",
        )
        job = Job(
            id=uuid.uuid4(),
            job_id="job-1",
            source_site="jobsdb",
            company_id=company.id,
            title="Governed migration role",
            description="Should use source taxonomy, not legacy ai_category",
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Unknown Source Bucket",
        )
        db.add_all([company, job])
        db.commit()

        report = migrate_job_categories.migrate_job_categories(db=db, execute=True)

        db.refresh(job)
        assert report["jobs_backfilled"] == 1
        assert report["dry_run"] is False
        assert job.subcategory_id == general.id
    finally:
        db.close()


def test_migrate_job_categories_dry_run_rolls_back_changes():
    db = _build_sqlite_session()
    try:
        _seed_taxonomy(db)
        company = Company(
            id=uuid.uuid4(),
            company_id="company-1",
            name="Company 1",
        )
        job = Job(
            id=uuid.uuid4(),
            job_id="job-1",
            source_site="jobsdb",
            company_id=company.id,
            title="Dry-run migration role",
            description="Should not persist",
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Unknown Source Bucket",
        )
        db.add_all([company, job])
        db.commit()

        report = migrate_job_categories.migrate_job_categories(db=db, execute=False)

        db.refresh(job)
        assert report["jobs_backfilled"] == 1
        assert report["dry_run"] is True
        assert job.subcategory_id is None
    finally:
        db.close()
