from __future__ import annotations

import os
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.job_intelligence.skill_governance import SkillTaxonomyPublisher
from app.job_intelligence.skill_governance.seed import load_skill_seed_bundle
from app.models.company import Company
from app.models.event_outbox import EventOutbox
from app.models.governance import GOVERNANCE_FOUNDATION_TABLES
from app.models.job import Job
from app.models.job_category import JobCategory
from app.models.job_domain import JobDomain
from app.models.job_subcategory import JobSubcategory
from app.models.skill_governance import SKILL_GOVERNANCE_TABLES


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260719_160000_add_skill_governance.py"
)


def _run_step(connection, migration, step: str) -> None:
    operation = Operations(MigrationContext.configure(connection))
    migration[step].__globals__["op"] = operation
    migration[step]()


def test_skill_migration_is_additive_and_never_publishes_data(monkeypatch):
    created_tables: list[str] = []
    dropped_tables: list[str] = []
    executed_sql: list[str] = []
    alembic_stub = ModuleType("alembic")
    alembic_stub.op = SimpleNamespace(
        create_table=lambda name, *_elements, **_kwargs: created_tables.append(name),
        create_index=lambda *_args, **_kwargs: None,
        drop_index=lambda *_args, **_kwargs: None,
        drop_table=lambda name: dropped_tables.append(name),
        execute=lambda statement: executed_sql.append(str(statement)),
    )
    monkeypatch.setitem(sys.modules, "alembic", alembic_stub)

    migration = runpy.run_path(MIGRATION_PATH)
    migration["upgrade"]()
    migration["downgrade"]()

    assert migration["revision"] == "20260719_160000"
    assert migration["down_revision"] == "20260719_120000"
    assert created_tables == [table.name for table in SKILL_GOVERNANCE_TABLES]
    assert dropped_tables == list(reversed(created_tables))
    assert not any("INSERT INTO" in statement.upper() for statement in executed_sql)
    assert any(
        "TRG_SKILL_TAXONOMY_RELEASE_READY_GUARD" in statement.upper()
        for statement in executed_sql
    )
    assert any(
        "TRG_GOVERNED_SKILL_CATEGORIES_IMMUTABLE" in statement.upper()
        for statement in executed_sql
    )
    assert any(
        "TRG_SKILL_TAXONOMY_ACTIVE_READY" in statement.upper()
        for statement in executed_sql
    )


def test_skill_migration_rehearses_postgresql_guards_and_rollback():
    database_url = os.getenv("JOB_INTELLIGENCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("JOB_INTELLIGENCE_TEST_DATABASE_URL is not configured")
    if not (make_url(database_url).database or "").endswith("_test"):
        pytest.fail("Skill migration requires a dedicated *_test database")

    engine = create_engine(database_url)
    expected_tables = {table.name for table in SKILL_GOVERNANCE_TABLES}
    prerequisite_tables = (
        JobDomain.__table__,
        JobCategory.__table__,
        JobSubcategory.__table__,
        Company.__table__,
        Job.__table__,
        EventOutbox.__table__,
        *GOVERNANCE_FOUNDATION_TABLES,
    )
    Base.metadata.drop_all(engine, checkfirst=True)
    Base.metadata.create_all(engine, tables=list(prerequisite_tables))
    migration = runpy.run_path(MIGRATION_PATH)
    if expected_tables & set(inspect(engine).get_table_names()):
        with engine.begin() as connection:
            _run_step(connection, migration, "downgrade")

    try:
        with engine.begin() as connection:
            _run_step(connection, migration, "upgrade")
        assert expected_tables <= set(inspect(engine).get_table_names())

        session = sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )()
        try:
            publisher = SkillTaxonomyPublisher(session)
            revision = publisher.materialize(load_skill_seed_bundle())
            publisher.activate(revision, expected_lock_version=0)
        finally:
            session.close()

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE governed_skill_categories SET name = 'Changed' "
                        "WHERE revision_id = :revision_id"
                    ),
                    {"revision_id": revision.revision_id},
                )

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                technology_id = connection.scalar(
                    text(
                        "SELECT id FROM governed_skill_technologies "
                        "WHERE revision_id = :revision_id ORDER BY source_order LIMIT 1"
                    ),
                    {"revision_id": revision.revision_id},
                )
                connection.execute(
                    text(
                        "INSERT INTO governed_skills "
                        "(id, revision_id, technology_id, code, name, source_order, "
                        "origin, is_active) VALUES (:id, :revision_id, :technology_id, "
                        "'late.seed', 'Late Seed', 999, 'seed', true)"
                    ),
                    {
                        "id": uuid4(),
                        "revision_id": revision.revision_id,
                        "technology_id": technology_id,
                    },
                )

        with engine.begin() as connection:
            technology_id = connection.scalar(
                text(
                    "SELECT id FROM governed_skill_technologies "
                    "WHERE revision_id = :revision_id ORDER BY source_order LIMIT 1"
                ),
                {"revision_id": revision.revision_id},
            )
            operator_skill_id = uuid4()
            operator_audit_id = uuid4()
            operator_candidate_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO governance_audit_events "
                    "(id, domain, subject_type, subject_id, action, actor, command_hash, "
                    "idempotency_key, before_summary, after_summary, evidence_refs, "
                    "correlation_id, created_at) VALUES (:id, 'skill-governance', "
                    "'skill-candidate', :subject_id, 'create_skill', 'local-operator', "
                    ":command_hash, 'migration-operator-skill', CAST('{}' AS json), "
                    "CAST('{}' AS json), CAST('[]' AS json), "
                    "'migration-operator-skill', now())"
                ),
                {
                    "id": operator_audit_id,
                    "subject_id": str(operator_candidate_id),
                    "command_hash": "c" * 64,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO governed_skills "
                    "(id, revision_id, technology_id, code, name, source_order, "
                    "origin, is_active, created_by_audit_id) VALUES "
                    "(:id, :revision_id, :technology_id, 'operator.rust', 'Rust', "
                    "999, 'operator', true, :audit_id)"
                ),
                {
                    "id": operator_skill_id,
                    "revision_id": revision.revision_id,
                    "technology_id": technology_id,
                    "audit_id": operator_audit_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO skill_candidates "
                    "(id, taxonomy_revision_id, normalized_key, canonical_raw_name, "
                    "status, decision_audit_id, resolved_skill_id, resolved_at) VALUES "
                    "(:id, :revision_id, 'rust', 'Rust', 'resolved_created', "
                    ":audit_id, :skill_id, now())"
                ),
                {
                    "id": operator_candidate_id,
                    "revision_id": revision.revision_id,
                    "audit_id": operator_audit_id,
                    "skill_id": operator_skill_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO governed_skill_aliases "
                    "(id, taxonomy_revision_id, skill_id, raw_alias, normalized_key, "
                    "source, source_order, created_by_audit_id) VALUES "
                    "(:id, :revision_id, :skill_id, 'rustlang', 'rustlang', "
                    "'operator', 1, :audit_id)"
                ),
                {
                    "id": uuid4(),
                    "revision_id": revision.revision_id,
                    "skill_id": operator_skill_id,
                    "audit_id": operator_audit_id,
                },
            )

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                technology_id = connection.scalar(
                    text(
                        "SELECT id FROM governed_skill_technologies "
                        "WHERE revision_id = :revision_id ORDER BY source_order LIMIT 1"
                    ),
                    {"revision_id": revision.revision_id},
                )
                unrelated_audit_id = uuid4()
                connection.execute(
                    text(
                        "INSERT INTO governance_audit_events "
                        "(id, domain, subject_type, subject_id, action, actor, "
                        "command_hash, idempotency_key, before_summary, after_summary, "
                        "evidence_refs, correlation_id, created_at) VALUES "
                        "(:id, 'skill-governance', 'skill-candidate', :subject_id, "
                        "'create_skill', 'local-operator', :command_hash, "
                        "'migration-unrelated-audit', CAST('{}' AS json), "
                        "CAST('{}' AS json), CAST('[]' AS json), "
                        "'migration-unrelated-audit', now())"
                    ),
                    {
                        "id": unrelated_audit_id,
                        "subject_id": str(uuid4()),
                        "command_hash": "d" * 64,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO governed_skills "
                        "(id, revision_id, technology_id, code, name, source_order, "
                        "origin, is_active, created_by_audit_id) VALUES "
                        "(:id, :revision_id, :technology_id, 'operator.unbound', "
                        "'Unbound', 1000, 'operator', true, :audit_id)"
                    ),
                    {
                        "id": uuid4(),
                        "revision_id": revision.revision_id,
                        "technology_id": technology_id,
                        "audit_id": unrelated_audit_id,
                    },
                )
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE governed_skills SET name = 'Changed Rust' "
                        "WHERE id = :id"
                    ),
                    {"id": operator_skill_id},
                )

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE skill_taxonomy_active_revisions "
                        "SET activated_at = now() WHERE singleton_key = 'skill-taxonomy'"
                    )
                )

        with engine.begin() as connection:
            _run_step(connection, migration, "downgrade")
        assert not expected_tables & set(inspect(engine).get_table_names())
    finally:
        if expected_tables & set(inspect(engine).get_table_names()):
            with engine.begin() as connection:
                _run_step(connection, migration, "downgrade")
        Base.metadata.drop_all(
            engine,
            tables=list(reversed(prerequisite_tables)),
            checkfirst=True,
        )
        engine.dispose()
