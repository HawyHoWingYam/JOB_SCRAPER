from __future__ import annotations

from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import JobCategory, JobDomain, JobSubcategory
from app.services.job_category_normalizer import JobCategoryNormalizer


def _build_normalizer():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            JobDomain.__table__,
            JobCategory.__table__,
            JobSubcategory.__table__,
        ],
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session_factory()

    domain = JobDomain(id=uuid4(), name="Information & Communication Technology")
    software = JobCategory(id=uuid4(), domain_id=domain.id, name="Software Development")
    infra = JobCategory(id=uuid4(), domain_id=domain.id, name="Infrastructure & Support")
    general = JobCategory(id=uuid4(), domain_id=domain.id, name="General")
    backend = JobSubcategory(id=uuid4(), category_id=software.id, name="Backend Development")
    sysadmin = JobSubcategory(id=uuid4(), category_id=infra.id, name="Systems Administration")
    general_leaf = JobSubcategory(id=uuid4(), category_id=general.id, name="General")

    db.add_all([domain, software, infra, general, backend, sysadmin, general_leaf])
    db.commit()

    return db, JobCategoryNormalizer(db)


def test_resolve_taxonomy_decision_prefers_infrastructure_support_for_devops_like_software_roles():
    db, normalizer = _build_normalizer()

    subcategory_id = normalizer.resolve_taxonomy_decision(
        classification={
            "taxonomy_decision": {
                "domain": "Information & Communication Technology",
                "category": "Software Development",
                "subcategory": "Backend Development",
                "resolution": "match_existing",
            },
            "final_taxonomy_decision": {
                "domain": "Information & Communication Technology",
                "category": "Software Development",
                "subcategory": "Backend Development",
                "resolution": "match_existing",
            },
        },
        source_classification_id="6281",
        source_classification_name="Information & Communication Technology",
        source_subclassification_name="Engineering - Software",
        job_title="DevOps Engineer",
        job_description="Manage CI/CD, cloud infrastructure, containers, and production systems.",
        extracted_skills=["Terraform", "Kubernetes", "Docker", "AWS", "Jenkins"],
    )

    resolved = db.query(JobSubcategory).filter(JobSubcategory.id == subcategory_id).one()

    assert resolved.name == "Systems Administration"
    assert resolved.category.name == "Infrastructure & Support"
    db.close()


def test_resolve_taxonomy_decision_keeps_backend_for_regular_software_roles_without_infra_signals():
    db, normalizer = _build_normalizer()

    subcategory_id = normalizer.resolve_taxonomy_decision(
        classification={
            "taxonomy_decision": {
                "domain": "Information & Communication Technology",
                "category": "Software Development",
                "subcategory": "Backend Development",
                "resolution": "match_existing",
            },
            "final_taxonomy_decision": {
                "domain": "Information & Communication Technology",
                "category": "Software Development",
                "subcategory": "Backend Development",
                "resolution": "match_existing",
            },
        },
        source_classification_id="6281",
        source_classification_name="Information & Communication Technology",
        source_subclassification_name="Engineering - Software",
        job_title="Backend Engineer",
        job_description="Build APIs and backend services using Python and PostgreSQL.",
        extracted_skills=["Python", "FastAPI", "PostgreSQL"],
    )

    resolved = db.query(JobSubcategory).filter(JobSubcategory.id == subcategory_id).one()

    assert resolved.name == "Backend Development"
    assert resolved.category.name == "Software Development"
    db.close()


def test_resolve_taxonomy_decision_prefers_infrastructure_support_for_mlops_roles():
    db, normalizer = _build_normalizer()

    subcategory_id = normalizer.resolve_taxonomy_decision(
        classification={
            "taxonomy_decision": {
                "domain": "Information & Communication Technology",
                "category": "Software Development",
                "subcategory": "Backend Development",
                "resolution": "match_existing",
            },
            "final_taxonomy_decision": {
                "domain": "Information & Communication Technology",
                "category": "Software Development",
                "subcategory": "Backend Development",
                "resolution": "match_existing",
            },
        },
        source_classification_id="6281",
        source_classification_name="Information & Communication Technology",
        source_subclassification_name="Engineering - Software",
        job_title="Senior AI MLOps Engineer",
        job_description="Operate AI/ML platforms with Kubernetes, CI/CD, and cloud infrastructure.",
        extracted_skills=["Kubernetes", "Docker", "Terraform"],
    )

    resolved = db.query(JobSubcategory).filter(JobSubcategory.id == subcategory_id).one()

    assert resolved.name == "Systems Administration"
    assert resolved.category.name == "Infrastructure & Support"
    db.close()


def test_resolve_taxonomy_decision_prefers_infrastructure_support_for_devtestops_environment_roles():
    db, normalizer = _build_normalizer()

    subcategory_id = normalizer.resolve_taxonomy_decision(
        classification={
            "taxonomy_decision": {
                "domain": "Information & Communication Technology",
                "category": "Software Development",
                "subcategory": "Backend Development",
                "resolution": "match_existing",
            },
            "final_taxonomy_decision": {
                "domain": "Information & Communication Technology",
                "category": "Software Development",
                "subcategory": "Backend Development",
                "resolution": "match_existing",
            },
        },
        source_classification_id="6281",
        source_classification_name="Information & Communication Technology",
        source_subclassification_name="Engineering - Software",
        job_title="Software Developer/Engineer",
        job_description=(
            "Design and maintain test environments, support CI/CD pipelines, "
            "improve environment provisioning, and run reliability testing with Terraform, "
            "Docker, Kubernetes, and Ansible."
        ),
        extracted_skills=["Terraform", "Docker", "Kubernetes", "Ansible", "Linux"],
    )

    resolved = db.query(JobSubcategory).filter(JobSubcategory.id == subcategory_id).one()

    assert resolved.name == "Systems Administration"
    assert resolved.category.name == "Infrastructure & Support"
    db.close()


def test_resolve_taxonomy_decision_keeps_explicit_backend_titles_in_backend_even_with_cloud_native_tools():
    db, normalizer = _build_normalizer()

    subcategory_id = normalizer.resolve_taxonomy_decision(
        classification={
            "taxonomy_decision": {
                "domain": "Information & Communication Technology",
                "category": "Infrastructure & Support",
                "subcategory": "Systems Administration",
                "resolution": "match_existing",
            },
            "final_taxonomy_decision": {
                "domain": "Information & Communication Technology",
                "category": "Infrastructure & Support",
                "subcategory": "Systems Administration",
                "resolution": "match_existing",
            },
        },
        source_classification_id="6281",
        source_classification_name="Information & Communication Technology",
        source_subclassification_name="Engineering - Software",
        job_title="Senior Backend Engineer - Node.js (Azure & Kubernetes)",
        job_description="Build scalable backend APIs and integrations in a cloud-native environment with Kubernetes and Docker.",
        extracted_skills=["Node.js", "Azure", "Kubernetes", "Docker"],
    )

    resolved = db.query(JobSubcategory).filter(JobSubcategory.id == subcategory_id).one()

    assert resolved.name == "Backend Development"
    assert resolved.category.name == "Software Development"
    db.close()


def test_resolve_taxonomy_decision_keeps_cloud_microservices_leads_in_backend_without_strong_infra_signals():
    db, normalizer = _build_normalizer()

    subcategory_id = normalizer.resolve_taxonomy_decision(
        classification={
            "taxonomy_decision": {
                "domain": "Information & Communication Technology",
                "category": "Infrastructure & Support",
                "subcategory": "Systems Administration",
                "resolution": "match_existing",
            },
            "final_taxonomy_decision": {
                "domain": "Information & Communication Technology",
                "category": "Infrastructure & Support",
                "subcategory": "Systems Administration",
                "resolution": "match_existing",
            },
        },
        source_classification_id="6281",
        source_classification_name="Information & Communication Technology",
        source_subclassification_name="Engineering - Software",
        job_title="Technical Lead - Cloud & Microservices (Data)",
        job_description=(
            "Lead architecture and engineering delivery for cloud-native data platforms, "
            "microservices, APIs, and secure enterprise-grade software."
        ),
        extracted_skills=["Java", "Python", "RESTful APIs"],
    )

    resolved = db.query(JobSubcategory).filter(JobSubcategory.id == subcategory_id).one()

    assert resolved.name == "Backend Development"
    assert resolved.category.name == "Software Development"
    db.close()
