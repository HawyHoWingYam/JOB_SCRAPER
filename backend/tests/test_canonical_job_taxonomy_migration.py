from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.database import Base
import app.models  # noqa: F401
from app.models.canonical_job_taxonomy import (
    CANONICAL_JOB_TAXONOMY_TABLES,
    CanonicalJobCategory,
    CanonicalJobDomain,
    CanonicalJobSubcategory,
    CanonicalJobTaxonomyRelease,
    JobTaxonomyAssignment,
    JobTaxonomyReviewItem,
)
from app.models.company import Company
from app.models.governance import GovernanceRevision
from app.models.job import Job


def _constraint_columns(constraint) -> tuple[str, ...]:
    return tuple(
        value if isinstance(value, str) else value.name
        for value in constraint._pending_colargs
    )


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260719_010000_add_canonical_job_taxonomy.py"
)


def _run_migration_step(connection, migration, step: str) -> None:
    operation = Operations(MigrationContext.configure(connection))
    function = migration[step]
    function.__globals__["op"] = operation
    function()


def _canonical_tables(inspector) -> set[str]:
    expected = {table.name for table in CANONICAL_JOB_TAXONOMY_TABLES}
    return expected & set(inspector.get_table_names())


def _canonical_trigger_count(connection) -> int:
    return int(
        connection.execute(
            text(
                "SELECT count(*) FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE NOT t.tgisinternal "
                "AND (c.relname LIKE 'canonical_job_%' "
                "OR c.relname IN "
                "('source_job_taxonomy_mappings', "
                "'source_job_taxonomy_mapping_targets'))"
            )
        ).scalar_one()
    )


def test_canonical_taxonomy_migration_is_additive_and_never_activates_data(
    monkeypatch,
):
    created_tables: list[str] = []
    table_elements: dict[str, tuple[object, ...]] = {}
    dropped_tables: list[str] = []
    executed_sql: list[str] = []

    alembic_stub = ModuleType("alembic")

    def capture_table(name, *elements, **_kwargs):
        created_tables.append(name)
        table_elements[name] = elements

    alembic_stub.op = SimpleNamespace(
        create_table=capture_table,
        create_index=lambda *_args, **_kwargs: None,
        drop_index=lambda *_args, **_kwargs: None,
        drop_table=lambda name: dropped_tables.append(name),
        execute=lambda statement: executed_sql.append(str(statement)),
    )
    monkeypatch.setitem(sys.modules, "alembic", alembic_stub)

    migration = runpy.run_path(MIGRATION_PATH)
    migration["upgrade"]()
    migration["downgrade"]()

    assert migration["revision"] == "20260719_010000"
    assert migration["down_revision"] == "20260718_220000"
    assert created_tables == [
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
    assert dropped_tables == list(reversed(created_tables))
    for table_name, elements in table_elements.items():
        column_names = {
            element.name for element in elements if isinstance(element, sa.Column)
        }
        for constraint in elements:
            if isinstance(
                constraint,
                (sa.ForeignKeyConstraint, sa.UniqueConstraint),
            ):
                assert set(_constraint_columns(constraint)) <= column_names, (
                    table_name,
                    constraint.name,
                )

    mapping_revision_uniques = {
        constraint.name: _constraint_columns(constraint)
        for constraint in table_elements["canonical_job_taxonomy_mapping_revisions"]
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert mapping_revision_uniques["uq_canonical_job_mapping_revision_taxonomy"] == (
        "revision_id",
        "taxonomy_revision_id",
    )

    coverage_foreign_keys = [
        constraint
        for constraint in table_elements["canonical_job_taxonomy_mapping_coverages"]
        if isinstance(constraint, sa.ForeignKeyConstraint)
    ]
    assert any(
        _constraint_columns(constraint) == ("mapping_revision_id",)
        for constraint in coverage_foreign_keys
    )

    assignment_foreign_keys = {
        constraint.name: _constraint_columns(constraint)
        for constraint in table_elements["job_taxonomy_assignments"]
        if isinstance(constraint, sa.ForeignKeyConstraint)
    }
    assert assignment_foreign_keys["fk_job_taxonomy_assignment_mapping_taxonomy"] == (
        "mapping_revision_id",
        "taxonomy_revision_id",
    )
    assert not any("INSERT INTO" in statement.upper() for statement in executed_sql)
    assert any(
        "TRG_CANONICAL_JOB_TAXONOMY_RELEASE_READY_GUARD" in statement.upper()
        for statement in executed_sql
    )
    assert any(
        "TRG_CANONICAL_JOB_TAXONOMY_NODES_IMMUTABLE" in statement.upper()
        for statement in executed_sql
    )
    assert any(
        "BEFORE INSERT OR UPDATE OR DELETE ON CANONICAL_JOB_DOMAINS"
        in statement.upper()
        for statement in executed_sql
    )
    assert any(
        "ACTUAL_SUBCATEGORY_COUNT <> NEW.MATERIALIZED_SUBCATEGORY_COUNT"
        in statement.upper()
        for statement in executed_sql
    )
    assert any(
        "TRG_CANONICAL_JOB_MAPPING_REVISION_READY_GUARD" in statement.upper()
        for statement in executed_sql
    )


def test_canonical_taxonomy_migration_rehearses_postgresql_constraints_and_rollback():
    database_url = os.getenv("JOB_INTELLIGENCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("JOB_INTELLIGENCE_TEST_DATABASE_URL is not configured")
    database_name = make_url(database_url).database or ""
    if not database_name.endswith("_test"):
        pytest.fail(
            "Canonical migration rehearsal requires a dedicated *_test database"
        )

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    expected_tables = {table.name for table in CANONICAL_JOB_TAXONOMY_TABLES}
    prerequisite_tables = [
        table
        for table in Base.metadata.sorted_tables
        if table.name not in expected_tables
    ]
    Base.metadata.create_all(engine, tables=prerequisite_tables)
    migration = runpy.run_path(MIGRATION_PATH)

    if "canonical_job_taxonomy_releases" in inspect(engine).get_table_names():
        with engine.begin() as connection:
            _run_migration_step(connection, migration, "downgrade")

    inserted_revision_ids = (uuid4(), uuid4(), uuid4())
    ready_revision, other_revision, materializing_revision = inserted_revision_ids
    ready_hash, other_hash, materializing_hash = (
        uuid4().hex * 2,
        uuid4().hex * 2,
        uuid4().hex * 2,
    )
    domain_id = uuid4()
    category_id = uuid4()
    subcategory_id = uuid4()
    assignment_id = uuid4()
    review_id = uuid4()

    try:
        with engine.begin() as connection:
            _run_migration_step(connection, migration, "upgrade")

        schema = inspect(engine)
        assert _canonical_tables(schema) == expected_tables
        with engine.connect() as connection:
            assert _canonical_trigger_count(connection) == 10
        mapping_uniques = {
            constraint["name"]: tuple(constraint["column_names"])
            for constraint in schema.get_unique_constraints(
                "canonical_job_taxonomy_mapping_revisions"
            )
        }
        assert mapping_uniques["uq_canonical_job_mapping_revision_taxonomy"] == (
            "revision_id",
            "taxonomy_revision_id",
        )

        now = datetime.now(timezone.utc)
        with Session(engine) as db:
            for revision_id, content_hash in zip(
                inserted_revision_ids,
                (ready_hash, other_hash, materializing_hash),
                strict=True,
            ):
                db.add(
                    GovernanceRevision(
                        id=revision_id,
                        domain="canonical-job-taxonomy",
                        release_key=f"migration-rehearsal-{revision_id}",
                        content_hash=content_hash,
                        source_metadata={},
                        status="published",
                        created_at=now,
                        published_at=now,
                    )
                )
            db.flush()
            ready_release = CanonicalJobTaxonomyRelease(
                revision_id=ready_revision,
                content_hash=ready_hash,
                expected_domain_count=1,
                expected_category_count=1,
                expected_subcategory_count=1,
                materialized_domain_count=0,
                materialized_category_count=0,
                materialized_subcategory_count=0,
                status="materializing",
                ready_at=None,
            )
            other_release = CanonicalJobTaxonomyRelease(
                revision_id=other_revision,
                content_hash=other_hash,
                expected_domain_count=0,
                expected_category_count=0,
                expected_subcategory_count=0,
                materialized_domain_count=0,
                materialized_category_count=0,
                materialized_subcategory_count=0,
                status="materializing",
                ready_at=None,
            )
            materializing_release = CanonicalJobTaxonomyRelease(
                revision_id=materializing_revision,
                content_hash=materializing_hash,
                expected_domain_count=1,
                expected_category_count=0,
                expected_subcategory_count=0,
                materialized_domain_count=0,
                materialized_category_count=0,
                materialized_subcategory_count=0,
                status="materializing",
                ready_at=None,
            )
            db.add_all((ready_release, other_release, materializing_release))
            db.flush()
            domain = CanonicalJobDomain(
                id=domain_id,
                revision_id=ready_revision,
                code="migration.rehearsal",
                label="Migration Rehearsal",
                source_order=1,
            )
            db.add(domain)
            db.flush()
            category = CanonicalJobCategory(
                id=category_id,
                revision_id=ready_revision,
                domain_id=domain_id,
                code="migration.rehearsal.category",
                label="Migration Rehearsal Category",
                source_order=1,
            )
            db.add(category)
            db.flush()
            db.add(
                CanonicalJobSubcategory(
                    id=subcategory_id,
                    revision_id=ready_revision,
                    category_id=category_id,
                    code="migration.rehearsal.category.subcategory",
                    label="Migration Rehearsal Subcategory",
                    source_order=1,
                    is_assignable=True,
                )
            )
            db.flush()
            ready_release.materialized_domain_count = 1
            ready_release.materialized_category_count = 1
            ready_release.materialized_subcategory_count = 1
            ready_release.status = "ready"
            ready_release.ready_at = now
            other_release.status = "ready"
            other_release.ready_at = now
            db.commit()

            company = Company(
                company_id=f"migration-rehearsal-{uuid4()}",
                source_site="ctgoodjobs",
                source_company_id=f"migration-rehearsal-{uuid4()}",
                name="Migration Rehearsal Company",
            )
            assignment_job = Job(
                job_id=f"migration-assignment-{uuid4()}",
                source_site="ctgoodjobs",
                source_job_id=f"migration-assignment-{uuid4()}",
                company=company,
                title="Migration Assignment Job",
            )
            review_job = Job(
                job_id=f"migration-review-{uuid4()}",
                source_site="ctgoodjobs",
                source_job_id=f"migration-review-{uuid4()}",
                company=company,
                title="Migration Review Job",
            )
            db.add_all((assignment_job, review_job))
            db.flush()
            db.add_all(
                (
                    JobTaxonomyAssignment(
                        id=assignment_id,
                        job_id=assignment_job.id,
                        taxonomy_revision_id=ready_revision,
                        subcategory_id=subcategory_id,
                        mapping_revision_id=None,
                        method="operator",
                        evidence_hash="a" * 64,
                        source_evidence_refs=[],
                        mapping_ids=[],
                        breadcrumb={},
                        lock_version=1,
                        is_current=True,
                        captured_at=now,
                    ),
                    JobTaxonomyReviewItem(
                        id=review_id,
                        job_id=review_job.id,
                        taxonomy_revision_id=ready_revision,
                        mapping_revision_id=None,
                        status="active",
                        reasons=["classifier_output_missing"],
                        evidence_hash="b" * 64,
                        evidence_refs=[],
                        recommendations=[],
                        lock_version=1,
                        created_at=now,
                        updated_at=now,
                    ),
                )
            )
            db.commit()
            assignment_job_id = assignment_job.id
            review_job_id = review_job.id

        def rejected(statement: str, parameters: dict[str, object]) -> bool:
            try:
                with engine.begin() as connection:
                    connection.execute(text(statement), parameters)
            except DBAPIError:
                return True
            return False

        assert rejected(
            "UPDATE canonical_job_domains SET label=:label WHERE id=:id",
            {"label": "Mutated", "id": domain_id},
        )
        assert rejected(
            "DELETE FROM canonical_job_domains WHERE id=:id",
            {"id": domain_id},
        )
        assert rejected(
            """
            UPDATE canonical_job_taxonomy_releases
            SET materialized_domain_count = 1,
                status = 'ready',
                ready_at = now()
            WHERE revision_id = :revision_id
            """,
            {"revision_id": materializing_revision},
        )
        assert rejected(
            """
            INSERT INTO canonical_job_categories
                (id, revision_id, domain_id, code, label, source_order)
            VALUES
                (:id, :revision_id, :domain_id, :code, :label, :source_order)
            """,
            {
                "id": uuid4(),
                "revision_id": other_revision,
                "domain_id": domain_id,
                "code": "migration.invalid_parent",
                "label": "Invalid Parent",
                "source_order": 1,
            },
        )
        assert rejected(
            """
            INSERT INTO canonical_job_taxonomy_active_revisions
                (singleton_key, revision_id, content_hash, lock_version)
            VALUES
                ('canonical-job-taxonomy', :revision_id, :content_hash, 1)
            """,
            {
                "revision_id": materializing_revision,
                "content_hash": materializing_hash,
            },
        )
        assert rejected(
            """
            INSERT INTO canonical_job_taxonomy_active_revisions
                (singleton_key, revision_id, content_hash, lock_version)
            VALUES
                ('canonical-job-taxonomy', :revision_id, :content_hash, 1)
            """,
            {
                "revision_id": uuid4(),
                "content_hash": uuid4().hex * 2,
            },
        )
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO canonical_job_taxonomy_active_revisions
                        (singleton_key, revision_id, content_hash, lock_version)
                    VALUES
                        ('canonical-job-taxonomy', :revision_id, :content_hash, 1)
                    """
                ),
                {
                    "revision_id": ready_revision,
                    "content_hash": ready_hash,
                },
            )
        assert rejected(
            """
            DELETE FROM canonical_job_taxonomy_active_revisions
            WHERE singleton_key = 'canonical-job-taxonomy'
            """,
            {},
        )
        assert rejected(
            """
            INSERT INTO canonical_job_taxonomy_active_revisions
                (singleton_key, revision_id, content_hash, lock_version)
            VALUES
                ('canonical-job-taxonomy', :revision_id, :content_hash, 2)
            """,
            {
                "revision_id": other_revision,
                "content_hash": other_hash,
            },
        )
        assert rejected(
            """
            INSERT INTO canonical_job_domains
                (id, revision_id, code, label, source_order)
            VALUES
                (:id, :revision_id, :code, :label, :source_order)
            """,
            {
                "id": uuid4(),
                "revision_id": ready_revision,
                "code": "migration.late_insert",
                "label": "Late Insert",
                "source_order": 2,
            },
        )
        assert rejected(
            """
            INSERT INTO job_taxonomy_assignments
                (id, job_id, taxonomy_revision_id, subcategory_id,
                 mapping_revision_id, method, evidence_hash,
                 source_evidence_refs, mapping_ids, breadcrumb,
                 lock_version, is_current)
            VALUES
                (:id, :job_id, :taxonomy_revision_id, :subcategory_id,
                 NULL, 'operator', :evidence_hash,
                 '[]'::json, '[]'::json, '{}'::json, 1, true)
            """,
            {
                "id": uuid4(),
                "job_id": review_job_id,
                "taxonomy_revision_id": other_revision,
                "subcategory_id": subcategory_id,
                "evidence_hash": "c" * 64,
            },
        )
        assert rejected(
            """
            INSERT INTO job_taxonomy_assignments
                (id, job_id, taxonomy_revision_id, subcategory_id,
                 mapping_revision_id, method, evidence_hash,
                 source_evidence_refs, mapping_ids, breadcrumb,
                 lock_version, is_current)
            VALUES
                (:id, :job_id, :taxonomy_revision_id, :subcategory_id,
                 NULL, 'operator', :evidence_hash,
                 '[]'::json, '[]'::json, '{}'::json, 2, true)
            """,
            {
                "id": uuid4(),
                "job_id": assignment_job_id,
                "taxonomy_revision_id": ready_revision,
                "subcategory_id": subcategory_id,
                "evidence_hash": "d" * 64,
            },
        )
        assert rejected(
            """
            INSERT INTO job_taxonomy_review_items
                (id, job_id, taxonomy_revision_id, mapping_revision_id,
                 status, reasons, evidence_hash, evidence_refs,
                 recommendations, lock_version)
            VALUES
                (:id, :job_id, :taxonomy_revision_id, NULL,
                 'active', '["classifier_output_missing"]'::json,
                 :evidence_hash, '[]'::json, '[]'::json, 2)
            """,
            {
                "id": uuid4(),
                "job_id": review_job_id,
                "taxonomy_revision_id": ready_revision,
                "evidence_hash": "e" * 64,
            },
        )
        assert {
            item["name"] for item in schema.get_indexes("job_taxonomy_assignments")
        } >= {"ux_job_taxonomy_assignment_current"}
        assert {
            item["name"] for item in schema.get_indexes("job_taxonomy_review_items")
        } >= {"ux_job_taxonomy_review_active"}

        with engine.begin() as connection:
            _run_migration_step(connection, migration, "downgrade")
        assert _canonical_tables(inspect(engine)) == set()
        with engine.connect() as connection:
            assert _canonical_trigger_count(connection) == 0

        with engine.begin() as connection:
            _run_migration_step(connection, migration, "upgrade")
        assert _canonical_tables(inspect(engine)) == expected_tables
        with engine.connect() as connection:
            assert _canonical_trigger_count(connection) == 10
    finally:
        if "canonical_job_taxonomy_releases" in inspect(engine).get_table_names():
            with engine.begin() as connection:
                _run_migration_step(connection, migration, "downgrade")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM governance_revisions "
                    "WHERE id IN (:ready, :other, :materializing)"
                ),
                {
                    "ready": ready_revision,
                    "other": other_revision,
                    "materializing": materializing_revision,
                },
            )
        engine.dispose()
