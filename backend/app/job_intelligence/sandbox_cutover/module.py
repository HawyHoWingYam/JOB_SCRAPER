from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from uuid import UUID

from sqlalchemy import Engine, MetaData, Table, func, inspect, select

from app.job_intelligence.sandbox_cutover.artifacts import (
    RetentionArtifactStore,
    content_hash,
)


RETAINED_TABLE_NAMES = (
    "companies",
    "employment_types",
    "source_classifications",
    "offertoday_taxonomy_snapshots",
    "offertoday_keyword_entries",
    "offertoday_keyword_mutation_logs",
    "current_taxonomy_nodes",
    "current_taxonomy_aliases",
    "jobs",
    "manual_job_evidence",
    "manual_job_mutation_receipts",
    "job_source_attribute_projections",
    "job_source_classification_paths",
    "job_source_classification_path_nodes",
    "job_source_employment_labels",
    "job_employment_types",
    "current_source_taxonomy_mappings",
    "current_company_industry_assignments",
    "current_job_skill_assignments",
    "current_skill_candidates",
    "current_job_skill_mentions",
    "governance_audit_events",
    "governance_idempotency_records",
)

ADDITIVE_RETAINED_TABLE_NAMES = {
    "manual_job_evidence",
    "manual_job_mutation_receipts",
    "offertoday_taxonomy_snapshots",
    "offertoday_keyword_entries",
    "offertoday_keyword_mutation_logs",
}

POST_START_MUTABLE_RETAINED_TABLE_NAMES = frozenset(
    {
        "source_classifications",
        "offertoday_taxonomy_snapshots",
        "offertoday_keyword_entries",
    }
)

DISCARDED_COLUMNS = {
    "companies": ("extra_data",),
    "jobs": ("search_vector",),
}

_AUDIT_TABLE_NAMES = {
    "governance_audit_events",
    "governance_idempotency_records",
}
_FORBIDDEN_IDENTITY_KEYS = {
    "automation_version",
    "category_catalog_version",
    "mapping_version",
    "revision",
    "revision_id",
    "release",
    "release_id",
    "source_catalog_version",
    "taxonomy_version",
    "version",
    "schema_version",
    "lock_version",
    "expected_version",
}
_TYPE_TAG = "__sandbox_cutover_type__"


@dataclass(frozen=True)
class ExportReport:
    artifact_hash: str
    table_counts: dict[str, int]
    table_hashes: dict[str, str]
    discarded_non_null_counts: dict[str, int]


@dataclass(frozen=True)
class ImportReport:
    table_counts: dict[str, int]


@dataclass(frozen=True)
class VerificationReport:
    matched: bool
    mismatches: tuple[str, ...]


class SandboxCutover:
    """Export the agreed corpus into a transient, revision-free artifact."""

    def __init__(
        self,
        *,
        source_engine: Engine,
        metadata: MetaData,
        retained_table_names: Sequence[str] = RETAINED_TABLE_NAMES,
        artifact_store: RetentionArtifactStore | None = None,
    ) -> None:
        self._source_engine = source_engine
        self._metadata = metadata
        self._retained_table_names = tuple(retained_table_names)
        self._artifact_store = artifact_store or RetentionArtifactStore()
        missing = [name for name in self._retained_table_names if name not in metadata.tables]
        if missing:
            raise ValueError(
                "Retained tables are not registered in target metadata: "
                + ", ".join(missing)
            )

    def export_retained(self, output: Path) -> ExportReport:
        table_payloads: list[dict[str, Any]] = []
        table_counts: dict[str, int] = {}
        table_hashes: dict[str, str] = {}
        discarded_non_null_counts = {
            f"{table_name}.{column_name}": 0
            for table_name, column_names in DISCARDED_COLUMNS.items()
            for column_name in column_names
        }
        with self._source_engine.connect() as connection:
            source_table_names = set(inspect(connection).get_table_names())
            for name in self._retained_table_names:
                target_table = self._metadata.tables[name]
                if name not in source_table_names:
                    if name not in ADDITIVE_RETAINED_TABLE_NAMES:
                        raise ValueError(f"Retained source table is missing: {name}")
                    raw_rows: list[Mapping[str, Any]] = []
                else:
                    source_table = Table(name, MetaData(), autoload_with=connection)
                    source_columns = set(source_table.c.keys())
                    missing_required = [
                        column.name
                        for column in target_table.columns
                        if column.name not in source_columns
                        and not column.nullable
                        and column.default is None
                        and column.server_default is None
                    ]
                    if missing_required:
                        raise ValueError(
                            f"Retained source table {name} is missing required target "
                            f"columns: {', '.join(missing_required)}"
                        )
                    raw_rows = []
                    for source_row in connection.execute(select(source_table)).mappings():
                        if not _retain_source_row(name, source_row):
                            continue
                        raw_rows.append(
                            {
                                column.name: _coerce_source_value(
                                    column,
                                    source_row.get(column.name),
                                )
                                for column in target_table.columns
                            }
                        )
                    for discarded_column in DISCARDED_COLUMNS.get(name, ()):
                        if discarded_column in source_columns:
                            discarded_non_null_counts[
                                f"{name}.{discarded_column}"
                            ] = connection.execute(
                                select(func.count()).where(
                                    source_table.c[discarded_column].is_not(None)
                                )
                            ).scalar_one()
                rows = [self._serialize_row(name, row) for row in raw_rows]
                rows.sort(key=_row_sort_key)
                row_hash = content_hash(rows)
                table_payloads.append(
                    {
                        "name": name,
                        "row_count": len(rows),
                        "content_hash": row_hash,
                        "rows": rows,
                    }
                )
                table_counts[name] = len(rows)
                table_hashes[name] = row_hash
        payload = {
            "discarded_non_null_counts": discarded_non_null_counts,
            "tables": table_payloads,
        }
        artifact_hash = self._artifact_store.write(output, payload)
        return ExportReport(
            artifact_hash=artifact_hash,
            table_counts=table_counts,
            table_hashes=table_hashes,
            discarded_non_null_counts=discarded_non_null_counts,
        )

    def import_retained(self, path: Path, *, target_engine: Engine) -> ImportReport:
        tables = self._validated_table_payloads(path)
        table_counts: dict[str, int] = {}
        with target_engine.begin() as connection:
            for item in tables:
                name = item["name"]
                table = self._metadata.tables[name]
                if connection.execute(select(table).limit(1)).first() is not None:
                    raise ValueError(
                        f"Refusing to import retained data into non-empty table: {name}"
                    )
            for item in tables:
                name = item["name"]
                rows = [
                    {key: _decode_value(value) for key, value in row.items()}
                    for row in item["rows"]
                ]
                rows = _order_rows_for_import(name, rows)
                if rows:
                    connection.execute(self._metadata.tables[name].insert(), rows)
                table_counts[name] = len(rows)
        return ImportReport(table_counts=table_counts)

    def verify_retained(
        self,
        path: Path,
        *,
        target_engine: Engine,
        ignored_table_names: Iterable[str] = (),
    ) -> VerificationReport:
        tables = self._validated_table_payloads(path)
        ignored = frozenset(ignored_table_names)
        mismatches: list[str] = []
        with target_engine.connect() as connection:
            for item in tables:
                name = item["name"]
                if name in ignored:
                    continue
                table = self._metadata.tables[name]
                actual_rows = [
                    self._serialize_row(name, row)
                    for row in connection.execute(select(table)).mappings()
                ]
                actual_rows.sort(key=_row_sort_key)
                if len(actual_rows) != item["row_count"]:
                    mismatches.append(
                        f"{name}: expected {item['row_count']} rows, "
                        f"found {len(actual_rows)}"
                    )
                if content_hash(actual_rows) != item["content_hash"]:
                    mismatches.append(f"{name}: content hash mismatch")
        return VerificationReport(
            matched=not mismatches,
            mismatches=tuple(mismatches),
        )

    @staticmethod
    def delete_artifact_after_verification(
        path: Path,
        verification: VerificationReport,
    ) -> None:
        if not verification.matched:
            raise ValueError(
                "Retention artifact cannot be deleted because verification has not passed"
            )
        path.unlink()

    @staticmethod
    def read_artifact(path: Path) -> dict[str, Any]:
        return RetentionArtifactStore().read(path)

    def validate_artifact(self, path: Path) -> None:
        """Reject an incomplete or malformed retention artifact before destroy."""

        self._validated_table_payloads(path)

    def _validated_table_payloads(self, path: Path) -> list[dict[str, Any]]:
        payload = self._artifact_store.read(path)
        discarded_counts = payload.get("discarded_non_null_counts")
        expected_discarded_keys = {
            f"{table_name}.{column_name}"
            for table_name, column_names in DISCARDED_COLUMNS.items()
            for column_name in column_names
        }
        if (
            not isinstance(discarded_counts, dict)
            or set(discarded_counts) != expected_discarded_keys
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in discarded_counts.values()
            )
        ):
            raise ValueError(
                "Sandbox retention artifact discarded-column counts are invalid"
            )
        raw_tables = payload.get("tables")
        if not isinstance(raw_tables, list):
            raise ValueError("Sandbox retention artifact tables are invalid")
        expected_names = list(self._retained_table_names)
        actual_names: list[str] = []
        validated: list[dict[str, Any]] = []
        for item in raw_tables:
            if not isinstance(item, dict) or set(item) != {
                "name",
                "row_count",
                "content_hash",
                "rows",
            }:
                raise ValueError("Sandbox retention artifact table entry is invalid")
            name = item["name"]
            rows = item["rows"]
            if (
                not isinstance(name, str)
                or not isinstance(rows, list)
                or not isinstance(item["row_count"], int)
                or not isinstance(item["content_hash"], str)
            ):
                raise ValueError("Sandbox retention artifact table entry is invalid")
            if len(rows) != item["row_count"] or content_hash(rows) != item["content_hash"]:
                raise ValueError(f"Sandbox retention artifact table hash mismatch: {name}")
            if any(not isinstance(row, dict) for row in rows):
                raise ValueError(f"Sandbox retention artifact rows are invalid: {name}")
            actual_names.append(name)
            validated.append(item)
        if actual_names != expected_names:
            raise ValueError(
                "Sandbox retention artifact table set or order does not match target"
            )
        return validated

    @staticmethod
    def _serialize_row(table_name: str, row: Mapping[str, Any]) -> dict[str, Any]:
        serialized: dict[str, Any] = {}
        for key, value in row.items():
            if table_name in _AUDIT_TABLE_NAMES:
                value = _strip_version_identity(value)
            serialized[key] = _encode_value(value)
        return serialized


def _strip_version_identity(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _strip_version_identity(item)
            for key, item in value.items()
            if not _is_forbidden_identity_key(str(key))
        }
    if isinstance(value, list):
        return [_strip_version_identity(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_strip_version_identity(item) for item in value)
    return value


def _is_forbidden_identity_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in _FORBIDDEN_IDENTITY_KEYS or normalized.endswith(
        ("_revision", "_revision_id", "_release", "_release_id")
    )


def _encode_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Sandbox retention artifact cannot contain non-finite floats")
        return value
    if isinstance(value, UUID):
        return {_TYPE_TAG: "uuid", "value": str(value)}
    if isinstance(value, datetime):
        return {_TYPE_TAG: "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {_TYPE_TAG: "date", "value": value.isoformat()}
    if isinstance(value, Decimal):
        return {_TYPE_TAG: "decimal", "value": format(value, "f")}
    if isinstance(value, bytes):
        return {
            _TYPE_TAG: "bytes",
            "value": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, Mapping):
        return {str(key): _encode_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode_value(item) for item in value]
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return _encode_value(tolist())
    if isinstance(value, Iterable):
        return [_encode_value(item) for item in value]
    raise TypeError(f"Unsupported retained value: {type(value).__name__}")


def _decode_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {_TYPE_TAG, "value"}:
        kind = value[_TYPE_TAG]
        encoded = value["value"]
        if kind == "uuid":
            return UUID(encoded)
        if kind == "datetime":
            return datetime.fromisoformat(encoded)
        if kind == "date":
            return date.fromisoformat(encoded)
        if kind == "decimal":
            return Decimal(encoded)
        if kind == "bytes":
            return base64.b64decode(encoded)
        raise ValueError(f"Unknown sandbox retention value type: {kind}")
    return {key: _decode_value(item) for key, item in value.items()}


def _coerce_source_value(column, value: Any) -> Any:
    """Restore target Python types lost through compatibility reflection."""

    if value is None:
        return None
    try:
        python_type = column.type.python_type
    except (AttributeError, NotImplementedError):
        return value
    if python_type is UUID and isinstance(value, str):
        return UUID(value)
    return value


def _retain_source_row(table_name: str, row: Mapping[str, Any]) -> bool:
    if table_name in {
        "current_taxonomy_nodes",
        "current_taxonomy_aliases",
        "current_source_taxonomy_mappings",
    }:
        return row.get("taxonomy") != "job"
    if table_name in _AUDIT_TABLE_NAMES:
        domain = str(row.get("domain") or "").strip().lower().replace("-", "_")
        return domain not in {"job_taxonomy", "canonical_job_taxonomy"}
    return True


def _row_sort_key(row: Mapping[str, Any]) -> bytes:
    from app.job_intelligence.sandbox_cutover.artifacts import canonical_json_bytes

    return canonical_json_bytes(row)


def _order_rows_for_import(
    table_name: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if table_name == "source_classifications":
        return _parent_first(
            rows,
            identity=lambda row: row["id"],
            parent=lambda row: row.get("parent_id"),
        )
    if table_name == "current_taxonomy_nodes":
        return _parent_first(
            rows,
            identity=lambda row: (row["taxonomy"], row["code"]),
            parent=lambda row: (
                (row["taxonomy"], row["parent_code"])
                if row.get("parent_code") is not None
                else None
            ),
        )
    return rows


def _parent_first(rows, *, identity, parent):
    pending = list(rows)
    known = {identity(row) for row in pending}
    inserted: set[Any] = set()
    ordered: list[dict[str, Any]] = []
    while pending:
        ready = [
            row
            for row in pending
            if parent(row) is None
            or parent(row) in inserted
            or parent(row) not in known
        ]
        if not ready:
            raise ValueError("Retained hierarchy contains a cycle or missing parent order")
        for row in ready:
            pending.remove(row)
            ordered.append(row)
            inserted.add(identity(row))
    return ordered
