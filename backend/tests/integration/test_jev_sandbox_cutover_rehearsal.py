from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.database import Base
import app.models  # noqa: F401
from app.job_intelligence.sandbox_cutover import (
    RUNTIME_TABLE_NAMES,
    SandboxCutover,
    clear_database,
    verify_target_state,
)
from app.models.jev import (
    JevRun,
    JevRunAttempt,
    JevRunItem,
)
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService
from scripts.bootstrap_db import bootstrap_database


JEV_TABLE_NAMES = tuple(
    sorted(name for name in Base.metadata.tables if name.startswith("jev_"))
)


def _test_engine():
    database_url = os.getenv("SANDBOX_CUTOVER_TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("sandbox cutover disposable PostgreSQL URL is not configured")
    if make_url(database_url).get_backend_name() != "postgresql":
        raise RuntimeError(
            "SANDBOX_CUTOVER_TEST_DATABASE_URL must use PostgreSQL"
        )
    if not (make_url(database_url).database or "").endswith("_test"):
        raise RuntimeError("SANDBOX_CUTOVER_TEST_DATABASE_URL must end in _test")
    return create_engine(database_url)


def _seed_jev_runtime(engine) -> None:
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    with Session(engine) as db:
        settings = JevRuntimeSettingsService(db).get_or_create()
        settings.api_key = "disposable-cutover-secret"
        run = JevRun(
            purpose="cutover_rehearsal",
            rubric_version="test-v1",
            status="completed",
            settings_snapshot={"model": "jev-latest"},
            total_items=1,
            pending_items=0,
            completed_items=1,
            completed_at=now,
        )
        db.add(run)
        db.flush()
        item = JevRunItem(
            run_id=run.id,
            subject_id="cutover-subject",
            position=0,
            payload={"state": "test", "questions": {}},
            status="completed",
            attempt_count=1,
            result={"usage": {"input_tokens": 1, "output_tokens": 1}},
            completed_at=now,
        )
        db.add(item)
        db.flush()
        db.add(
            JevRunAttempt(
                item_id=item.id,
                attempt_number=1,
                status="answered",
                model="jev-latest",
                input_tokens=1,
                output_tokens=1,
                actual_microdollars=100,
                completed_at=now,
            )
        )
        db.commit()


def test_jev_runtime_is_excluded_and_cleared_by_disposable_cutover(
    tmp_path: Path,
) -> None:
    assert set(JEV_TABLE_NAMES) <= set(RUNTIME_TABLE_NAMES)
    engine = _test_engine()
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        bootstrap_database(db_engine=engine, metadata=Base.metadata)
        _seed_jev_runtime(engine)

        artifact = tmp_path / "retained-without-jev.json"
        cutover = SandboxCutover(source_engine=engine, metadata=Base.metadata)
        manifest = cutover.export_retained(artifact)
        assert not set(JEV_TABLE_NAMES).intersection(manifest.table_counts)

        clear_database(db_engine=engine, confirmed=True)
        bootstrap_database(db_engine=engine, metadata=Base.metadata)
        cutover.import_retained(artifact, target_engine=engine)
        report = verify_target_state(db_engine=engine, metadata=Base.metadata)
        assert report.clean, report.issues
        with engine.connect() as connection:
            for table_name in JEV_TABLE_NAMES:
                assert (
                    connection.scalar(text(f"SELECT COUNT(*) FROM {table_name}")) == 0
                )
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        engine.dispose()
