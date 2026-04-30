import sys
import uuid
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
            source_subclassification_name="Developers/Programmers",
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
            source_subclassification_name="Developers/Programmers",
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
            source_subclassification_name="Developers/Programmers",
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
            ),
            Job(
                id=uuid.uuid4(),
                job_id="job-2",
                source_site="jobsdb",
                company_id=company.id,
                title="B",
                description="B",
                subcategory_id=backend.id,
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
        assert backend.last_used_at is not None
    finally:
        db.close()
