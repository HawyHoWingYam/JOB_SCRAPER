from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import make_url


_BACKUP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}")


@dataclass(frozen=True)
class PostgresBackupArtifact:
    artifact_name: str
    artifact_hash: str
    pg_dump_version: str
    pg_restore_version: str


def _run_command(
    args: tuple[str, ...],
    *,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


class PostgresBackupAdapter:
    """Create and restore one PostgreSQL custom-format backup without URL argv."""

    def __init__(
        self,
        *,
        command_runner: Callable[..., Any] = _run_command,
        base_environment: Mapping[str, str] | None = None,
    ) -> None:
        self.command_runner = command_runner
        self.base_environment = dict(base_environment or os.environ)

    def create_and_restore(
        self,
        *,
        source_database_url: str,
        restore_database_url: str,
        backup_id: str,
        checkpoint_dir: Path,
    ) -> PostgresBackupArtifact:
        if not _BACKUP_ID.fullmatch(backup_id):
            raise ValueError("Backup ID must be a bounded filesystem-safe identifier")
        source = make_url(source_database_url)
        restore = make_url(restore_database_url)
        self._require_postgres(source.drivername)
        self._require_postgres(restore.drivername)
        source_database = source.database or ""
        restore_database = restore.database or ""
        if (
            not source_database
            or not restore_database.endswith("_cutover_restore")
            or restore_database == source_database
        ):
            raise ValueError(
                "Restore database must be a distinct *_cutover_restore database"
            )

        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = checkpoint_dir / f"{backup_id}.dump"
        if artifact_path.exists():
            raise FileExistsError(
                f"Immutable backup artifact already exists: {artifact_path.name}"
            )
        temporary_path = checkpoint_dir / f".{backup_id}.{uuid4().hex}.tmp"
        source_env = self._postgres_environment(source)
        restore_env = self._postgres_environment(restore)
        pg_dump_version = self._version("pg_dump", source_env)
        pg_restore_version = self._version("pg_restore", restore_env)

        try:
            self.command_runner(
                (
                    "pg_dump",
                    "--format=custom",
                    "--no-owner",
                    "--no-privileges",
                    "--no-password",
                    "--file",
                    str(temporary_path),
                ),
                env=source_env,
            )
            if not temporary_path.is_file() or temporary_path.stat().st_size <= 0:
                raise RuntimeError("pg_dump did not produce a non-empty artifact")
            artifact_hash = self._file_hash(temporary_path)
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, artifact_path)
            self.command_runner(
                (
                    "pg_restore",
                    "--clean",
                    "--if-exists",
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    "--single-transaction",
                    f"--dbname={restore_database}",
                    str(artifact_path),
                ),
                env=restore_env,
            )
        finally:
            temporary_path.unlink(missing_ok=True)

        return PostgresBackupArtifact(
            artifact_name=artifact_path.name,
            artifact_hash=artifact_hash,
            pg_dump_version=pg_dump_version,
            pg_restore_version=pg_restore_version,
        )

    def _postgres_environment(self, url) -> dict[str, str]:
        env = dict(self.base_environment)
        values = {
            "PGHOST": url.host,
            "PGPORT": str(url.port or 5432),
            "PGDATABASE": url.database,
            "PGUSER": url.username,
            "PGPASSWORD": url.password,
            "PGCONNECT_TIMEOUT": "10",
        }
        for key, value in values.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = str(value)
        query_environment = {
            "sslmode": "PGSSLMODE",
            "sslrootcert": "PGSSLROOTCERT",
            "sslcert": "PGSSLCERT",
            "sslkey": "PGSSLKEY",
        }
        for query_key, environment_key in query_environment.items():
            value = url.query.get(query_key)
            if value is None:
                env.pop(environment_key, None)
            else:
                env[environment_key] = str(value)
        return env

    def _version(self, executable: str, env: dict[str, str]) -> str:
        result = self.command_runner((executable, "--version"), env=env)
        output = str(getattr(result, "stdout", "") or "").strip()
        if not output:
            output = str(getattr(result, "stderr", "") or "").strip()
        if not output:
            raise RuntimeError(f"{executable} did not report its version")
        return output.splitlines()[0]

    @staticmethod
    def _file_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _require_postgres(drivername: str) -> None:
        if not drivername.startswith("postgresql"):
            raise ValueError("Cutover backup requires PostgreSQL database URLs")


__all__ = ["PostgresBackupAdapter", "PostgresBackupArtifact"]
