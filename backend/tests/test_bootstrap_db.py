import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.bootstrap_db import bootstrap_database


class _FakeConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(str(statement))


class _FakeBegin:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    def begin(self):
        return _FakeBegin(self.connection)


class _FakeMetadata:
    def __init__(self):
        self.bound_engine = None

    def create_all(self, *, bind):
        self.bound_engine = bind


def test_bootstrap_database_enables_vector_extension_before_creating_tables():
    connection = _FakeConnection()
    engine = _FakeEngine(connection)
    metadata = _FakeMetadata()

    bootstrap_database(db_engine=engine, metadata=metadata)

    assert connection.statements == [
        "CREATE EXTENSION IF NOT EXISTS vector",
        "ALTER TABLE scrape_schedules ADD COLUMN IF NOT EXISTS crawl_mode VARCHAR(32)",
        "UPDATE scrape_schedules SET crawl_mode = CASE WHEN COALESCE(NULLIF(source_site, ''), 'jobsdb') IN ('jobsdb', 'ctgoodjobs') THEN 'headed' ELSE 'headless' END WHERE crawl_mode IS NULL",
    ]
    assert metadata.bound_engine is engine
