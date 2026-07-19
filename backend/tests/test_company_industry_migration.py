from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
import json
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
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401
from app.job_intelligence.company_industry import CompanyIndustryPublisher
from app.job_intelligence.company_industry.seed import seed_content_hash
from app.models.company import Company
from app.models.company_industry import COMPANY_INDUSTRY_TABLES
from app.models.governance import GOVERNANCE_FOUNDATION_TABLES


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260719_120000_add_company_industry_governance.py"
)
SEED_PATH = Path(__file__).parents[1] / "app" / "data" / "hsic_v2.json"


def _run_step(connection, migration, step: str) -> None:
    operation = Operations(MigrationContext.configure(connection))
    migration[step].__globals__["op"] = operation
    migration[step]()


def test_company_industry_migration_is_additive_and_never_publishes_data(
    monkeypatch,
):
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

    assert migration["revision"] == "20260719_120000"
    assert migration["down_revision"] == "20260719_010000"
    assert created_tables == [table.name for table in COMPANY_INDUSTRY_TABLES]
    assert dropped_tables == list(reversed(created_tables))
    assert not any("INSERT INTO" in statement.upper() for statement in executed_sql)
    assert any(
        "TRG_COMPANY_INDUSTRY_RELEASE_READY_GUARD" in statement.upper()
        for statement in executed_sql
    )
    assert any(
        "TRG_COMPANY_INDUSTRY_NODES_IMMUTABLE" in statement.upper()
        for statement in executed_sql
    )
    assert any(
        "TRG_COMPANY_INDUSTRY_ACTIVE_READY" in statement.upper()
        for statement in executed_sql
    )


def test_company_industry_migration_rehearses_postgresql_guards_and_rollback():
    database_url = os.getenv("JOB_INTELLIGENCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("JOB_INTELLIGENCE_TEST_DATABASE_URL is not configured")
    if not (make_url(database_url).database or "").endswith("_test"):
        pytest.fail("Company Industry migration requires a dedicated *_test database")

    engine = create_engine(database_url)
    expected_tables = {table.name for table in COMPANY_INDUSTRY_TABLES}
    prerequisite_tables = (Company.__table__, *GOVERNANCE_FOUNDATION_TABLES)
    Base.metadata.drop_all(engine, checkfirst=True)
    Base.metadata.create_all(engine, tables=list(prerequisite_tables))
    migration = runpy.run_path(MIGRATION_PATH)
    if expected_tables & set(inspect(engine).get_table_names()):
        with engine.begin() as connection:
            _run_step(connection, migration, "downgrade")

    revision_id = uuid4()
    node_ids = [uuid4() for _ in range(5)]
    crosswalk_id = uuid4()
    company_id = uuid4()
    content_hash = "a" * 64
    counts = {
        "section": 1,
        "division": 1,
        "group": 1,
        "class": 1,
        "subclass": 1,
    }
    now = datetime.now(timezone.utc)

    try:
        with engine.begin() as connection:
            _run_step(connection, migration, "upgrade")
        assert expected_tables <= set(inspect(engine).get_table_names())

        application_seed = deepcopy(json.loads(SEED_PATH.read_text(encoding="utf-8")))
        application_seed["crosswalks"] = [
            {
                "hsic_code": "620101",
                "target_standard": "ISIC",
                "target_release": "Rev.4",
                "target_code": "6201",
                "cardinality": "one_to_one",
                "method": "official",
                "confidence": 1.0,
                "provenance": {
                    "source_url": "https://www.censtatd.gov.hk/en/page_698.html",
                },
            }
        ]
        application_seed["content_hash"] = seed_content_hash(application_seed)
        application_session = sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )()
        try:
            application_revision = CompanyIndustryPublisher(
                application_session
            ).materialize(application_seed)
        finally:
            application_session.close()
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM company_industry_taxonomy_nodes "
                        "WHERE revision_id = :revision_id"
                    ),
                    {"revision_id": application_revision.revision_id},
                )
                == 1814
            )
            application_crosswalk_id = connection.scalar(
                text(
                    "SELECT id FROM company_industry_crosswalk_edges "
                    "WHERE taxonomy_revision_id = :revision_id"
                ),
                {"revision_id": application_revision.revision_id},
            )
        assert application_crosswalk_id is not None
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE company_industry_crosswalk_edges "
                        "SET target_release = 'Rev.5' WHERE id = :id"
                    ),
                    {"id": application_crosswalk_id},
                )

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO governance_revisions "
                    "(id, domain, release_key, content_hash, source_metadata, "
                    "status, created_at, published_at) "
                    "VALUES (:id, 'company-industry', 'hsic-test', :hash, "
                    "CAST('{}' AS json), 'published', :now, :now)"
                ),
                {"id": revision_id, "hash": content_hash, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO companies "
                    "(id, company_id, source_site, source_company_id, name, "
                    "is_deleted, created_at, updated_at) "
                    "VALUES (:id, 'migration-company', 'offertoday', "
                    "'migration-company', 'Migration Company', false, :now, :now)"
                ),
                {"id": company_id, "now": now.replace(tzinfo=None)},
            )
            connection.execute(
                text(
                    "INSERT INTO company_industry_taxonomy_releases "
                    "(revision_id, standard, release, content_hash, source_metadata, "
                    "expected_counts, materialized_counts, expected_total, "
                    "materialized_total, status, created_at) "
                    "VALUES (:id, 'HSIC', 'V2.0', :hash, CAST('{}' AS json), "
                    "CAST(:counts AS json), CAST(:empty_counts AS json), 5, 0, "
                    "'materializing', :now)"
                ),
                {
                    "id": revision_id,
                    "hash": content_hash,
                    "counts": json.dumps(counts),
                    "empty_counts": json.dumps({key: 0 for key in counts}),
                    "now": now,
                },
            )
            parent_id = None
            for order, (node_id, level, code) in enumerate(
                zip(
                    node_ids,
                    ("section", "division", "group", "class", "subclass"),
                    ("J", "62", "620", "6201", "620100"),
                    strict=True,
                ),
                start=1,
            ):
                connection.execute(
                    text(
                        "INSERT INTO company_industry_taxonomy_nodes "
                        "(id, revision_id, code, parent_id, level, label_en, "
                        "label_zh_hant, label_zh_hans, source_order, is_assignable, "
                        "source_metadata) VALUES (:id, :revision_id, :code, "
                        ":parent_id, :level, :label, :label, :label, :source_order, "
                        "true, CAST('{}' AS json))"
                    ),
                    {
                        "id": node_id,
                        "revision_id": revision_id,
                        "code": code,
                        "parent_id": parent_id,
                        "level": level,
                        "label": f"Node {code}",
                        "source_order": order,
                    },
                )
                parent_id = node_id
            connection.execute(
                text(
                    "INSERT INTO company_industry_crosswalk_edges "
                    "(id, taxonomy_revision_id, hsic_node_id, target_standard, "
                    "target_release, target_code, cardinality, method, confidence, "
                    "provenance, source_order) VALUES (:id, :revision_id, :node_id, "
                    "'ISIC', 'Rev.4', '6201', 'one_to_one', 'official', 1.0, "
                    "CAST('{}' AS json), 1)"
                ),
                {
                    "id": crosswalk_id,
                    "revision_id": revision_id,
                    "node_id": node_ids[-1],
                },
            )
            connection.execute(
                text(
                    "UPDATE company_industry_taxonomy_releases SET "
                    "materialized_counts = CAST(:counts AS json), "
                    "materialized_total = 5, status = 'ready', ready_at = :now "
                    "WHERE revision_id = :id"
                ),
                {
                    "id": revision_id,
                    "counts": json.dumps(counts),
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO company_industry_active_revisions "
                    "(singleton_key, revision_id, content_hash, lock_version, activated_at) "
                    "VALUES ('company-industry', :id, :hash, 1, :now)"
                ),
                {"id": revision_id, "hash": content_hash, "now": now},
            )

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO company_industry_taxonomy_nodes "
                        "(id, revision_id, code, parent_id, level, label_en, "
                        "label_zh_hant, label_zh_hans, source_order, is_assignable, "
                        "source_metadata) VALUES (:id, :revision_id, '620101', "
                        ":parent_id, 'subclass', 'late', 'late', 'late', 6, true, "
                        "CAST('{}' AS json))"
                    ),
                    {
                        "id": uuid4(),
                        "revision_id": revision_id,
                        "parent_id": node_ids[-2],
                    },
                )

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE company_industry_crosswalk_edges "
                        "SET target_release = 'Rev.5' WHERE id = :id"
                    ),
                    {"id": crosswalk_id},
                )

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM company_industry_crosswalk_edges WHERE id = :id"),
                    {"id": crosswalk_id},
                )

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE company_industry_active_revisions "
                        "SET activated_at = :now WHERE singleton_key = 'company-industry'"
                    ),
                    {"now": now},
                )

        assignment_values = {
            "revision_id": revision_id,
            "company_id": company_id,
            "node_id": node_ids[-1],
            "now": now,
            "hash": "b" * 64,
        }
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO company_industry_assignments "
                    "(id, company_id, taxonomy_revision_id, node_id, method, "
                    "provenance, evidence_hash, breadcrumb, is_primary, primary_basis, "
                    "status, lock_version, captured_at) VALUES (:id, :company_id, "
                    ":revision_id, :node_id, 'authoritative_code', CAST('{}' AS json), "
                    ":hash, CAST('[]' AS json), true, 'authoritative_source', "
                    "'active', 1, :now)"
                ),
                {**assignment_values, "id": uuid4()},
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO company_industry_assignments "
                        "(id, company_id, taxonomy_revision_id, node_id, method, "
                        "provenance, evidence_hash, breadcrumb, is_primary, primary_basis, "
                        "status, lock_version, captured_at) VALUES (:id, :company_id, "
                        ":revision_id, :node_id, 'operator', CAST('{}' AS json), :hash, "
                        "CAST('[]' AS json), true, 'operator', 'active', 1, :now)"
                    ),
                    {
                        **assignment_values,
                        "id": uuid4(),
                        "node_id": node_ids[-2],
                        "hash": "c" * 64,
                    },
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO company_industry_assignments "
                        "(id, company_id, taxonomy_revision_id, node_id, method, "
                        "provenance, evidence_hash, breadcrumb, is_primary, "
                        "primary_basis, status, lock_version, captured_at, "
                        "superseded_at) VALUES (:id, :company_id, :revision_id, "
                        ":node_id, 'operator', CAST('{}' AS json), 'invalid-hash', "
                        "CAST('[]' AS json), false, NULL, 'superseded', 1, :now, :now)"
                    ),
                    {
                        **assignment_values,
                        "id": uuid4(),
                        "node_id": node_ids[-2],
                    },
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO company_industry_assignments "
                        "(id, company_id, taxonomy_revision_id, node_id, method, "
                        "provenance, evidence_hash, breadcrumb, is_primary, "
                        "primary_basis, status, lock_version, captured_at) "
                        "VALUES (:id, :company_id, :revision_id, :node_id, "
                        "'operator', CAST('{}' AS json), :hash, CAST('[]' AS json), "
                        "false, NULL, 'superseded', 1, :now)"
                    ),
                    {
                        **assignment_values,
                        "id": uuid4(),
                        "node_id": node_ids[-2],
                        "hash": "d" * 64,
                    },
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO source_industry_mappings "
                        "(id, source_site, key_kind, raw_value, normalized_key, "
                        "taxonomy_revision_id, target_node_id, status, lock_version, "
                        "approved_by, approved_at, created_at) VALUES (:id, "
                        "'offertoday', 'label', 'Retired mapping', 'retired mapping', "
                        ":revision_id, :node_id, 'superseded', 1, 'local-operator', "
                        ":now, :now)"
                    ),
                    {
                        "id": uuid4(),
                        "revision_id": revision_id,
                        "node_id": node_ids[-1],
                        "now": now,
                    },
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO company_industry_review_items "
                        "(id, company_id, taxonomy_revision_id, reason, status, "
                        "evidence_hash, provenance, recommendations, lock_version, "
                        "created_at, updated_at) VALUES (:id, :company_id, "
                        ":revision_id, 'manual_evidence', 'active', 'invalid-hash', "
                        "CAST('{}' AS json), CAST('[]' AS json), 1, :now, :now)"
                    ),
                    {
                        "id": uuid4(),
                        "company_id": company_id,
                        "revision_id": revision_id,
                        "now": now,
                    },
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
