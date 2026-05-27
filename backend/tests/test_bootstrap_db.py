from __future__ import annotations

from scripts.bootstrap_db import bootstrap_database


class _FakeConnection:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, statement) -> None:
        self.executed.append(str(statement))


class _FakeBeginContext:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> _FakeConnection:
        return self.connection

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeEngine:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def begin(self) -> _FakeBeginContext:
        return _FakeBeginContext(self.connection)


class _FakeMetadata:
    def __init__(self) -> None:
        self.bind = None

    def create_all(self, *, bind) -> None:
        self.bind = bind


def test_bootstrap_database_backfills_ctgoodjobs_schedule_defaults_to_headless():
    connection = _FakeConnection()
    engine = _FakeEngine(connection)
    metadata = _FakeMetadata()

    bootstrap_database(db_engine=engine, metadata=metadata)

    crawl_mode_updates = [
        statement
        for statement in connection.executed
        if "UPDATE scrape_schedules" in statement and "SET crawl_mode = CASE" in statement
    ]
    assert len(crawl_mode_updates) == 1
    assert " = 'jobsdb' THEN 'headed' " in crawl_mode_updates[0]
    assert " = 'ctgoodjobs' THEN 'headless' " in crawl_mode_updates[0]
    assert metadata.bind is engine
