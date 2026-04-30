import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models import Company, Job, JobCategory, JobDomain, JobSubcategory
from app.services.job_category_normalizer import JobCategoryNormalizer

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


def test_unknown_ai_leaf_falls_back_to_registry_default_path():
    db = _build_sqlite_session()
    try:
        general, backend = _seed_taxonomy(db)
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
