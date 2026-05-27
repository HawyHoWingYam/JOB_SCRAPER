from __future__ import annotations

from app.models.crawl_job import CrawlJob, CrawlJobEvent
from app.models.crawl_job_listing import CrawlJobListing
from app.models.schedule import ScheduleExecution
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


def test_crawl_job_listing_declares_composite_indexes_for_backlog_queries():
    index_names = {index.name for index in CrawlJobListing.__table__.indexes}

    assert "ix_crawl_job_listings_source_status_rank_created" in index_names
    assert "ix_crawl_job_listings_job_status" in index_names


def test_bootstrap_database_creates_crawl_job_listing_indexes_for_existing_databases():
    connection = _FakeConnection()
    engine = _FakeEngine(connection)
    metadata = _FakeMetadata()

    bootstrap_database(db_engine=engine, metadata=metadata)

    index_statements = [
        statement
        for statement in connection.executed
        if "CREATE INDEX IF NOT EXISTS" in statement
    ]

    assert any("ix_crawl_job_listings_source_status_rank_created" in statement for statement in index_statements)
    assert any("ix_crawl_job_listings_job_status" in statement for statement in index_statements)


def test_crawl_job_event_declares_manual_action_lookup_index():
    index_names = {index.name for index in CrawlJobEvent.__table__.indexes}

    assert "ix_crawl_job_events_job_event_sequence" in index_names


def test_bootstrap_database_creates_crawl_job_event_indexes_for_existing_databases():
    connection = _FakeConnection()
    engine = _FakeEngine(connection)
    metadata = _FakeMetadata()

    bootstrap_database(db_engine=engine, metadata=metadata)

    index_statements = [
        statement
        for statement in connection.executed
        if "CREATE INDEX IF NOT EXISTS" in statement
    ]

    assert any("ix_crawl_job_events_job_event_sequence" in statement for statement in index_statements)


def test_schedule_execution_declares_composite_indexes_for_history_queries():
    index_names = {index.name for index in ScheduleExecution.__table__.indexes}

    assert "ix_schedule_executions_schedule_started" in index_names
    assert "ix_schedule_executions_crawl_job_started_created" in index_names


def test_bootstrap_database_creates_schedule_execution_indexes_for_existing_databases():
    connection = _FakeConnection()
    engine = _FakeEngine(connection)
    metadata = _FakeMetadata()

    bootstrap_database(db_engine=engine, metadata=metadata)

    index_statements = [
        statement
        for statement in connection.executed
        if "CREATE INDEX IF NOT EXISTS" in statement
    ]

    assert any("ix_schedule_executions_schedule_started" in statement for statement in index_statements)
    assert any("ix_schedule_executions_crawl_job_started_created" in statement for statement in index_statements)


def test_crawl_job_declares_status_queue_sort_index():
    index_names = {index.name for index in CrawlJob.__table__.indexes}

    assert "ix_crawl_jobs_status_queued_created" in index_names


def test_bootstrap_database_creates_crawl_job_status_queue_index_for_existing_databases():
    connection = _FakeConnection()
    engine = _FakeEngine(connection)
    metadata = _FakeMetadata()

    bootstrap_database(db_engine=engine, metadata=metadata)

    index_statements = [
        statement
        for statement in connection.executed
        if "CREATE INDEX IF NOT EXISTS" in statement
    ]

    assert any("ix_crawl_jobs_status_queued_created" in statement for statement in index_statements)


def test_crawl_job_declares_recency_index():
    index_names = {index.name for index in CrawlJob.__table__.indexes}

    assert "ix_crawl_jobs_queued_created" in index_names


def test_bootstrap_database_creates_crawl_job_recency_index_for_existing_databases():
    connection = _FakeConnection()
    engine = _FakeEngine(connection)
    metadata = _FakeMetadata()

    bootstrap_database(db_engine=engine, metadata=metadata)

    index_statements = [
        statement
        for statement in connection.executed
        if "CREATE INDEX IF NOT EXISTS" in statement
    ]

    assert any("ix_crawl_jobs_queued_created" in statement for statement in index_statements)
