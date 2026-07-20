from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any, Protocol

from sqlalchemy import Connection, Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.job_intelligence.cutover.artifacts import content_hash
from app.job_intelligence.cutover.backup import (
    PostgresBackupAdapter,
    PostgresBackupArtifact,
)
from app.job_intelligence.cutover.constants import KNOWN_WRITERS
from app.job_intelligence.cutover.contracts import WriterStateEvidence
from app.job_intelligence.cutover.writer_probe import SystemWriterStateProvider
from app.utils.time import utc_now


CUTOVER_SCHEMA_REVISION = "20260720_210000"
SUPPORTED_SOURCES = ("ctgoodjobs", "jobsdb", "offertoday")
RESET_CONFIRMATION = "RESET_CRAWL_CONTROL_DATA"

RESET_TABLES = (
    "crawl_dispatch_plan_target_rows",
    "crawl_dispatch_plan_targets",
    "schedule_executions",
    "crawl_job_listings",
    "crawl_job_events",
    "crawl_job_executions",
    "crawl_runs",
    "crawl_dispatch_plans",
    "crawl_jobs",
    "automation_delete_reviews",
    "automation_revisions",
    "scheduler_runtime_heartbeats",
    "scrape_schedules",
)

_ACTIVE_CRAWL_JOB_STATUSES = (
    "queued",
    "dispatching",
    "running",
    "cancelling",
    "manual_action_required",
)
_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*")
_CRAWL_OUTBOX_PREDICATE = """
status = 'pending'
AND (
  aggregate_type = 'crawl_job'
  OR event_type LIKE 'crawl.%'
  OR topic LIKE 'crawl.%'
)
"""


@dataclass(frozen=True)
class RequiredForeignKey:
    source_table: str
    source_columns: tuple[str, ...]
    target_table: str
    target_columns: tuple[str, ...]
    on_delete: str


REQUIRED_FOREIGN_KEYS = (
    RequiredForeignKey(
        "crawl_job_listings", ("crawl_job_id",), "crawl_jobs", ("id",), "CASCADE"
    ),
    RequiredForeignKey(
        "crawl_dispatch_plan_target_rows",
        ("crawl_job_listing_id",),
        "crawl_job_listings",
        ("id",),
        "RESTRICT",
    ),
    RequiredForeignKey(
        "crawl_dispatch_plan_target_rows",
        ("plan_target_id",),
        "crawl_dispatch_plan_targets",
        ("id",),
        "CASCADE",
    ),
    RequiredForeignKey(
        "crawl_dispatch_plan_targets",
        ("plan_id",),
        "crawl_dispatch_plans",
        ("id",),
        "CASCADE",
    ),
    RequiredForeignKey(
        "crawl_jobs",
        ("dispatch_plan_id",),
        "crawl_dispatch_plans",
        ("id",),
        "RESTRICT",
    ),
    RequiredForeignKey(
        "crawl_dispatch_plans",
        ("crawl_job_id",),
        "crawl_jobs",
        ("id",),
        "RESTRICT",
    ),
    RequiredForeignKey(
        "schedule_executions",
        ("dispatch_plan_id",),
        "crawl_dispatch_plans",
        ("id",),
        "RESTRICT",
    ),
    RequiredForeignKey(
        "schedule_executions",
        ("schedule_id",),
        "scrape_schedules",
        ("id",),
        "SET NULL",
    ),
    RequiredForeignKey(
        "automation_revisions",
        ("automation_id",),
        "scrape_schedules",
        ("id",),
        "CASCADE",
    ),
    RequiredForeignKey(
        "automation_delete_reviews",
        ("automation_id",),
        "scrape_schedules",
        ("id",),
        "SET NULL",
    ),
    RequiredForeignKey(
        "enrichment_runs",
        ("trigger_crawl_job_id",),
        "crawl_jobs",
        ("id",),
        "SET NULL",
    ),
)


@dataclass(frozen=True)
class ForeignKeySnapshot:
    name: str
    source_table: str
    source_columns: tuple[str, ...]
    target_table: str
    target_columns: tuple[str, ...]
    on_delete: str

    def payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "source_table": self.source_table,
            "source_columns": list(self.source_columns),
            "target_table": self.target_table,
            "target_columns": list(self.target_columns),
            "on_delete": self.on_delete,
        }


@dataclass(frozen=True)
class CrawlControlCutoverReport:
    observed_at: datetime
    schema_revision: str
    backup_id: str
    backup_acknowledged: bool
    writer_evidence: tuple[WriterStateEvidence, ...]
    active_catalog_sources: tuple[str, ...]
    active_crawl_job_count: int
    reset_counts: Mapping[str, int]
    preserve_counts: Mapping[str, int]
    pending_crawl_outbox_count: int
    preserved_outbox_count: int
    foreign_keys: tuple[ForeignKeySnapshot, ...]
    issues: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.issues

    def _stable_payload(self) -> dict[str, object]:
        return {
            "schema_revision": self.schema_revision,
            "backup_id": self.backup_id,
            "backup_acknowledged": self.backup_acknowledged,
            "writer_evidence": [
                {
                    "writer": item.writer,
                    "state": item.state,
                    "evidence_kind": item.evidence_kind,
                    "evidence_ref": item.evidence_ref,
                }
                for item in self.writer_evidence
            ],
            "active_catalog_sources": list(self.active_catalog_sources),
            "active_crawl_job_count": self.active_crawl_job_count,
            "reset_counts": dict(sorted(self.reset_counts.items())),
            "preserve_counts": dict(sorted(self.preserve_counts.items())),
            "pending_crawl_outbox_count": self.pending_crawl_outbox_count,
            "preserved_outbox_count": self.preserved_outbox_count,
            "foreign_keys": [item.payload() for item in self.foreign_keys],
            "issues": list(self.issues),
        }

    @property
    def report_hash(self) -> str:
        return content_hash(self._stable_payload())

    def artifact_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": "dry-run",
            "observed_at": self.observed_at.isoformat(),
            **self._stable_payload(),
            "ready": self.ready,
            "report_hash": self.report_hash,
        }


@dataclass(frozen=True)
class CrawlControlCutoverResult:
    report_hash: str
    backup_id: str
    deleted_counts: Mapping[str, int]
    preserved_counts: Mapping[str, int]
    preserved_outbox_count: int
    completed_at: datetime

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": "execute",
            "report_hash": self.report_hash,
            "backup_id": self.backup_id,
            "deleted_counts": dict(sorted(self.deleted_counts.items())),
            "preserved_counts": dict(sorted(self.preserved_counts.items())),
            "preserved_outbox_count": self.preserved_outbox_count,
            "completed_at": self.completed_at.isoformat(),
        }


@dataclass(frozen=True)
class BackupRehearsalResult:
    artifact: PostgresBackupArtifact
    table_counts: Mapping[str, int]
    restored_database: str

    def payload(self) -> dict[str, object]:
        return {
            "artifact_name": self.artifact.artifact_name,
            "artifact_hash": self.artifact.artifact_hash,
            "pg_dump_version": self.artifact.pg_dump_version,
            "pg_restore_version": self.artifact.pg_restore_version,
            "table_counts": dict(sorted(self.table_counts.items())),
            "restored_database": self.restored_database,
        }


class WriterStateProvider(Protocol):
    def collect(
        self,
        *,
        writers: tuple[str, ...],
        observed_at: datetime,
    ) -> tuple[WriterStateEvidence, ...]: ...


class CrawlControlCutoverError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


FailureInjector = Callable[[str, Connection], None]


class CrawlControlCutover:
    """Inventory, rehearse, and atomically reset only Crawl Control data."""

    def __init__(
        self,
        engine: Engine,
        *,
        writer_state_provider: WriterStateProvider | None = None,
        backup_adapter: PostgresBackupAdapter | None = None,
        failure_injector: FailureInjector | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.engine = engine
        self.writer_state_provider = (
            writer_state_provider or SystemWriterStateProvider()
        )
        self.backup_adapter = backup_adapter or PostgresBackupAdapter()
        self.failure_injector = failure_injector
        self.clock = clock

    def dry_run(
        self,
        *,
        backup_id: str,
        backup_acknowledged: bool,
    ) -> CrawlControlCutoverReport:
        self._require_postgres()
        observed_at = self.clock()
        writer_evidence = self.writer_state_provider.collect(
            writers=KNOWN_WRITERS,
            observed_at=observed_at,
        )
        with self.engine.connect() as connection:
            return self._inspect(
                connection,
                observed_at=observed_at,
                writer_evidence=writer_evidence,
                backup_id=backup_id,
                backup_acknowledged=backup_acknowledged,
            )

    def execute(
        self,
        *,
        backup_id: str,
        backup_acknowledged: bool,
        expected_report_hash: str,
        confirmation: str,
    ) -> CrawlControlCutoverResult:
        self._require_postgres()
        if confirmation != RESET_CONFIRMATION:
            raise CrawlControlCutoverError(
                "CUTOVER_RESET_UNCONFIRMED",
                f"Reset requires exact confirmation {RESET_CONFIRMATION}",
            )

        observed_at = self.clock()
        writer_evidence = self.writer_state_provider.collect(
            writers=KNOWN_WRITERS,
            observed_at=observed_at,
        )
        connection = self.engine.connect().execution_options(
            isolation_level="SERIALIZABLE"
        )
        transaction = connection.begin()
        try:
            self._lock_reset_tables(connection)
            report = self._inspect(
                connection,
                observed_at=observed_at,
                writer_evidence=writer_evidence,
                backup_id=backup_id,
                backup_acknowledged=backup_acknowledged,
            )
            self._require_ready(report)
            if report.report_hash != expected_report_hash:
                raise CrawlControlCutoverError(
                    "CUTOVER_DRY_RUN_STALE",
                    "Current preflight no longer matches the reviewed dry-run report",
                    details={
                        "expected_report_hash": expected_report_hash,
                        "current_report_hash": report.report_hash,
                    },
                )

            connection.execute(
                text("SET LOCAL app.crawl_control_maintenance = 'on'")
            )
            deleted_counts = self._reset(connection)
            self._verify_preservation(connection, report)
            transaction.commit()
        except Exception:
            transaction.rollback()
            raise
        finally:
            connection.close()

        return CrawlControlCutoverResult(
            report_hash=report.report_hash,
            backup_id=backup_id,
            deleted_counts=deleted_counts,
            preserved_counts=report.preserve_counts,
            preserved_outbox_count=report.preserved_outbox_count,
            completed_at=self.clock(),
        )

    def rehearse_backup(
        self,
        *,
        restore_database_url: str,
        backup_id: str,
        checkpoint_dir: Path,
    ) -> BackupRehearsalResult:
        self._require_postgres()
        source_url = self.engine.url.render_as_string(hide_password=False)
        source_database = make_url(source_url).database or ""
        restore_database = make_url(restore_database_url).database or ""
        if not source_database.endswith("_test"):
            raise CrawlControlCutoverError(
                "CUTOVER_REHEARSAL_SOURCE_UNSAFE",
                "Backup rehearsal source database must end in _test",
            )
        if not restore_database.endswith("_cutover_restore"):
            raise CrawlControlCutoverError(
                "CUTOVER_REHEARSAL_RESTORE_UNSAFE",
                "Backup rehearsal restore database must end in _cutover_restore",
            )

        with self.engine.connect() as connection:
            source_counts = self._all_table_counts(connection)
        artifact = self.backup_adapter.create_and_restore(
            source_database_url=source_url,
            restore_database_url=restore_database_url,
            backup_id=backup_id,
            checkpoint_dir=checkpoint_dir,
        )
        restore_engine = create_engine(restore_database_url, pool_pre_ping=True)
        try:
            with restore_engine.connect() as connection:
                restore_counts = self._all_table_counts(connection)
        finally:
            restore_engine.dispose()
        if restore_counts != source_counts:
            raise CrawlControlCutoverError(
                "CUTOVER_BACKUP_RESTORE_MISMATCH",
                "Restored table counts do not match the disposable source",
                details={
                    "source_counts": source_counts,
                    "restore_counts": restore_counts,
                },
            )
        return BackupRehearsalResult(
            artifact=artifact,
            table_counts=source_counts,
            restored_database=restore_database,
        )

    def _inspect(
        self,
        connection: Connection,
        *,
        observed_at: datetime,
        writer_evidence: tuple[WriterStateEvidence, ...],
        backup_id: str,
        backup_acknowledged: bool,
    ) -> CrawlControlCutoverReport:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        issues: list[str] = []
        required_tables = set(RESET_TABLES) | {
            "alembic_version",
            "companies",
            "jobs",
            "enrichment_runs",
            "event_outbox",
            "source_catalog_candidates",
            "source_catalog_revisions",
            "source_catalog_active_revisions",
        }
        missing_tables = sorted(required_tables - tables)
        if missing_tables:
            issues.append(f"missing required tables: {', '.join(missing_tables)}")

        schema_revision = self._schema_revision(connection, tables)
        if schema_revision != CUTOVER_SCHEMA_REVISION:
            issues.append(
                f"schema revision must be {CUTOVER_SCHEMA_REVISION}, got "
                f"{schema_revision or 'missing'}"
            )
        if not backup_id.strip() or not backup_acknowledged:
            issues.append("pre-cutover backup identity has not been acknowledged")

        evidence_by_writer = {item.writer: item for item in writer_evidence}
        if set(evidence_by_writer) != set(KNOWN_WRITERS):
            issues.append("writer/process evidence is incomplete")
        non_stopped = sorted(
            writer
            for writer in KNOWN_WRITERS
            if evidence_by_writer.get(writer) is None
            or evidence_by_writer[writer].state != "stopped"
        )
        if non_stopped:
            issues.append(f"writers are not confirmed stopped: {', '.join(non_stopped)}")

        active_sources = self._active_catalog_sources(connection, tables)
        if active_sources != SUPPORTED_SOURCES:
            missing_sources = sorted(set(SUPPORTED_SOURCES) - set(active_sources))
            issues.append(
                "published active Source Catalog revisions are missing: "
                + ", ".join(missing_sources)
            )
        active_crawl_jobs = self._active_crawl_job_count(connection, tables)
        if active_crawl_jobs:
            issues.append(
                f"{active_crawl_jobs} Crawl Jobs still require terminal acknowledgement"
            )

        foreign_keys = self._foreign_keys(inspector, tables)
        missing_foreign_keys = [
            required
            for required in REQUIRED_FOREIGN_KEYS
            if not self._has_foreign_key(foreign_keys, required)
        ]
        if missing_foreign_keys:
            issues.extend(
                "missing/mismatched FK: "
                f"{item.source_table}{item.source_columns} -> "
                f"{item.target_table}{item.target_columns} ON DELETE {item.on_delete}"
                for item in missing_foreign_keys
            )

        reset_counts = self._counts(
            connection, (table for table in RESET_TABLES if table in tables)
        )
        preserve_tables = sorted(
            tables
            - set(RESET_TABLES)
            - {"alembic_version", "event_outbox"}
        )
        preserve_counts = self._counts(connection, preserve_tables)
        pending_crawl_outbox_count = self._count_where(
            connection,
            "event_outbox",
            _CRAWL_OUTBOX_PREDICATE,
            table_exists="event_outbox" in tables,
        )
        preserved_outbox_count = self._count_where(
            connection,
            "event_outbox",
            f"NOT ({_CRAWL_OUTBOX_PREDICATE})",
            table_exists="event_outbox" in tables,
        )

        return CrawlControlCutoverReport(
            observed_at=observed_at,
            schema_revision=schema_revision,
            backup_id=backup_id.strip(),
            backup_acknowledged=backup_acknowledged,
            writer_evidence=tuple(
                sorted(writer_evidence, key=lambda item: item.writer)
            ),
            active_catalog_sources=active_sources,
            active_crawl_job_count=active_crawl_jobs,
            reset_counts=reset_counts,
            preserve_counts=preserve_counts,
            pending_crawl_outbox_count=pending_crawl_outbox_count,
            preserved_outbox_count=preserved_outbox_count,
            foreign_keys=foreign_keys,
            issues=tuple(sorted(issues)),
        )

    def _reset(self, connection: Connection) -> dict[str, int]:
        deleted: dict[str, int] = {}

        def execute(name: str, statement: str) -> None:
            result = connection.execute(text(statement))
            deleted[name] = max(int(result.rowcount or 0), 0)
            if self.failure_injector is not None:
                self.failure_injector(name, connection)

        execute(
            "event_outbox",
            f"DELETE FROM event_outbox WHERE {_CRAWL_OUTBOX_PREDICATE}",
        )
        execute("schedule_executions", "DELETE FROM schedule_executions")
        execute(
            "crawl_job_authority_links",
            "UPDATE crawl_jobs SET dispatch_plan_id = NULL, "
            "dispatch_plan_fingerprint = NULL WHERE dispatch_plan_id IS NOT NULL",
        )
        execute(
            "dispatch_plan_authority_links",
            "UPDATE crawl_dispatch_plans SET state = 'expired', consumed_at = NULL, "
            "crawl_job_id = NULL, automation_id = NULL",
        )
        execute(
            "crawl_dispatch_plan_target_rows",
            "DELETE FROM crawl_dispatch_plan_target_rows",
        )
        execute(
            "crawl_dispatch_plan_targets",
            "DELETE FROM crawl_dispatch_plan_targets",
        )
        execute("crawl_dispatch_plans", "DELETE FROM crawl_dispatch_plans")
        execute("crawl_job_listings", "DELETE FROM crawl_job_listings")
        execute("crawl_job_events", "DELETE FROM crawl_job_events")
        execute("crawl_job_executions", "DELETE FROM crawl_job_executions")
        execute("crawl_runs", "DELETE FROM crawl_runs")
        execute("crawl_jobs", "DELETE FROM crawl_jobs")
        execute("automation_delete_reviews", "DELETE FROM automation_delete_reviews")
        execute("automation_revisions", "DELETE FROM automation_revisions")
        execute(
            "scheduler_runtime_heartbeats",
            "DELETE FROM scheduler_runtime_heartbeats",
        )
        execute("scrape_schedules", "DELETE FROM scrape_schedules")
        return deleted

    def _verify_preservation(
        self,
        connection: Connection,
        before: CrawlControlCutoverReport,
    ) -> None:
        reset_after = self._counts(connection, RESET_TABLES)
        nonempty = {name: count for name, count in reset_after.items() if count}
        preserve_after = self._counts(connection, before.preserve_counts)
        preserved_outbox_after = self._count_where(
            connection,
            "event_outbox",
            f"NOT ({_CRAWL_OUTBOX_PREDICATE})",
            table_exists=True,
        )
        if nonempty or preserve_after != dict(before.preserve_counts):
            raise CrawlControlCutoverError(
                "CUTOVER_PRESERVATION_FAILED",
                "Reset-table or preserved-table counts changed unexpectedly",
                details={
                    "nonempty_reset_tables": nonempty,
                    "preserve_before": dict(before.preserve_counts),
                    "preserve_after": preserve_after,
                },
            )
        if preserved_outbox_after != before.preserved_outbox_count:
            raise CrawlControlCutoverError(
                "CUTOVER_PRESERVATION_FAILED",
                "Published or unrelated outbox rows changed during reset",
                details={
                    "before": before.preserved_outbox_count,
                    "after": preserved_outbox_after,
                },
            )

    def _lock_reset_tables(self, connection: Connection) -> None:
        tables = set(inspect(connection).get_table_names())
        lock_tables = sorted(set(RESET_TABLES) | {"event_outbox"})
        missing = set(lock_tables) - tables
        if missing:
            raise CrawlControlCutoverError(
                "CUTOVER_PREFLIGHT_FAILED",
                f"Cannot lock missing reset tables: {', '.join(sorted(missing))}",
            )
        quoted = ", ".join(self._quote_identifier(name) for name in lock_tables)
        connection.execute(
            text(f"LOCK TABLE {quoted} IN ACCESS EXCLUSIVE MODE NOWAIT")
        )

    @staticmethod
    def _require_ready(report: CrawlControlCutoverReport) -> None:
        if not report.ready:
            raise CrawlControlCutoverError(
                "CUTOVER_PREFLIGHT_FAILED",
                "Crawl Control maintenance preflight failed",
                details={"issues": list(report.issues)},
            )

    def _require_postgres(self) -> None:
        if self.engine.dialect.name != "postgresql":
            raise CrawlControlCutoverError(
                "CUTOVER_POSTGRES_REQUIRED",
                "Crawl Control cutover requires PostgreSQL",
            )

    @staticmethod
    def _schema_revision(connection: Connection, tables: set[str]) -> str:
        if "alembic_version" not in tables:
            return ""
        revisions = tuple(
            str(row[0]).strip()
            for row in connection.execute(
                text("SELECT version_num FROM alembic_version ORDER BY version_num")
            )
            if str(row[0]).strip()
        )
        return revisions[0] if len(revisions) == 1 else ""

    @staticmethod
    def _active_catalog_sources(
        connection: Connection,
        tables: set[str],
    ) -> tuple[str, ...]:
        required = {
            "source_catalog_active_revisions",
            "source_catalog_revisions",
            "source_catalog_candidates",
        }
        if not required <= tables:
            return ()
        rows = connection.execute(
            text(
                "SELECT active.source_site "
                "FROM source_catalog_active_revisions AS active "
                "JOIN source_catalog_revisions AS revision "
                "ON revision.id = active.revision_id "
                "AND revision.source_site = active.source_site "
                "JOIN source_catalog_candidates AS candidate "
                "ON candidate.id = revision.candidate_id "
                "WHERE candidate.state = 'published' "
                "ORDER BY active.source_site"
            )
        )
        return tuple(str(row[0]) for row in rows)

    @staticmethod
    def _active_crawl_job_count(
        connection: Connection,
        tables: set[str],
    ) -> int:
        if "crawl_jobs" not in tables:
            return 0
        result = connection.execute(
            text(
                "SELECT count(*) FROM crawl_jobs WHERE status IN "
                "(:queued, :dispatching, :running, :cancelling, :manual_action)"
            ),
            {
                "queued": _ACTIVE_CRAWL_JOB_STATUSES[0],
                "dispatching": _ACTIVE_CRAWL_JOB_STATUSES[1],
                "running": _ACTIVE_CRAWL_JOB_STATUSES[2],
                "cancelling": _ACTIVE_CRAWL_JOB_STATUSES[3],
                "manual_action": _ACTIVE_CRAWL_JOB_STATUSES[4],
            },
        )
        return int(result.scalar_one())

    @classmethod
    def _foreign_keys(
        cls,
        inspector: Any,
        tables: set[str],
    ) -> tuple[ForeignKeySnapshot, ...]:
        snapshots: list[ForeignKeySnapshot] = []
        for table_name in sorted(tables):
            for foreign_key in inspector.get_foreign_keys(table_name):
                target_table = str(foreign_key.get("referred_table") or "")
                if table_name not in RESET_TABLES and target_table not in RESET_TABLES:
                    continue
                options = foreign_key.get("options") or {}
                snapshots.append(
                    ForeignKeySnapshot(
                        name=str(foreign_key.get("name") or ""),
                        source_table=table_name,
                        source_columns=tuple(foreign_key.get("constrained_columns") or ()),
                        target_table=target_table,
                        target_columns=tuple(foreign_key.get("referred_columns") or ()),
                        on_delete=str(options.get("ondelete") or "NO ACTION").upper(),
                    )
                )
        return tuple(
            sorted(
                snapshots,
                key=lambda item: (
                    item.source_table,
                    item.source_columns,
                    item.target_table,
                    item.name,
                ),
            )
        )

    @staticmethod
    def _has_foreign_key(
        snapshots: tuple[ForeignKeySnapshot, ...],
        required: RequiredForeignKey,
    ) -> bool:
        return any(
            item.source_table == required.source_table
            and item.source_columns == required.source_columns
            and item.target_table == required.target_table
            and item.target_columns == required.target_columns
            and item.on_delete == required.on_delete
            for item in snapshots
        )

    @classmethod
    def _counts(
        cls,
        connection: Connection,
        tables: Any,
    ) -> dict[str, int]:
        return {
            table_name: int(
                connection.execute(
                    text(f"SELECT count(*) FROM {cls._quote_identifier(table_name)}")
                ).scalar_one()
            )
            for table_name in sorted(tables)
        }

    @classmethod
    def _count_where(
        cls,
        connection: Connection,
        table_name: str,
        predicate: str,
        *,
        table_exists: bool,
    ) -> int:
        if not table_exists:
            return 0
        return int(
            connection.execute(
                text(
                    f"SELECT count(*) FROM {cls._quote_identifier(table_name)} "
                    f"WHERE {predicate}"
                )
            ).scalar_one()
        )

    @classmethod
    def _all_table_counts(cls, connection: Connection) -> dict[str, int]:
        tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
        return cls._counts(connection, tables)

    @staticmethod
    def _quote_identifier(value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError(f"Unsafe SQL identifier: {value!r}")
        return f'"{value}"'


__all__ = [
    "BackupRehearsalResult",
    "CUTOVER_SCHEMA_REVISION",
    "CrawlControlCutover",
    "CrawlControlCutoverError",
    "CrawlControlCutoverReport",
    "CrawlControlCutoverResult",
    "ForeignKeySnapshot",
    "RESET_CONFIRMATION",
    "RESET_TABLES",
]
