from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import csv
import hashlib
import io
import secrets
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.offertoday_coverage import (
    OfferTodayKeywordCsvReview,
    OfferTodayKeywordEntry,
    OfferTodayKeywordMutationLog,
)
from app.models.source_classification import SourceClassification
from app.source_classifications.domain import payload_fingerprint
from app.sources.offertoday.search_space import (
    DEFAULT_OFFERTODAY_IT_HYBRID_KEYWORDS,
    DEFAULT_OFFERTODAY_IT_KEYWORDS,
)
from app.utils.time import utc_now


OFFERTODAY_KEYWORD_CSV_COLUMNS = (
    "classification_id",
    "classification_label",
    "keyword",
    "enabled",
    "notes",
    "last_new_job_ids",
    "last_duplicate_rate",
    "last_run_at",
)
OFFERTODAY_KEYWORD_ENABLED_LIMIT = 150
OFFERTODAY_IT_CLASSIFICATION_ID = "offertoday:118000"


def normalize_offertoday_keyword(value: str) -> str:
    """Return the case-insensitive identity while preserving no display state."""

    return " ".join(str(value or "").split()).casefold()


def _display_keyword(value: str) -> str:
    return " ".join(str(value or "").split())


def initial_offertoday_it_keywords() -> tuple[str, ...]:
    """Return the reviewed 127-term pack in stable authored order."""

    keywords: list[str] = []
    seen: set[str] = set()
    for keyword in (
        *DEFAULT_OFFERTODAY_IT_KEYWORDS,
        *DEFAULT_OFFERTODAY_IT_HYBRID_KEYWORDS,
    ):
        identity = normalize_offertoday_keyword(keyword)
        if identity in seen:
            continue
        seen.add(identity)
        keywords.append(_display_keyword(keyword))
    if len(keywords) != 127:
        raise RuntimeError("Reviewed OfferToday IT keyword pack must contain 127 terms")
    return tuple(keywords)


@dataclass(frozen=True)
class KeywordCsvRowIssue:
    row: int
    field: str
    code: str
    message: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "field": self.field,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True)
class KeywordCsvPreview:
    valid: bool
    csv_hash: str
    errors: tuple[KeywordCsvRowIssue, ...]
    warnings: tuple[dict[str, Any], ...]
    diff: tuple[dict[str, Any], ...]
    resulting_enabled_counts: dict[str, int]
    workload_impact: dict[str, Any]
    confirmation_token: str | None = None
    expires_at: datetime | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "csv_hash": self.csv_hash,
            "errors": [item.to_payload() for item in self.errors],
            "warnings": list(self.warnings),
            "diff": list(self.diff),
            "resulting_enabled_counts": dict(self.resulting_enabled_counts),
            "workload_impact": dict(self.workload_impact),
            "confirmation_token": self.confirmation_token,
            "expires_at": self.expires_at,
        }


class OfferTodayKeywordCatalogError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class OfferTodayKeywordCatalog:
    """Own CSV governance and reads for ordinary-current keyword packs."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def bootstrap_initial_it_pack(self, *, actor: str = "system-bootstrap") -> int:
        classification = self._classification_by_identity().get(
            OFFERTODAY_IT_CLASSIFICATION_ID
        )
        if classification is None:
            return 0
        existing = {
            entry.normalized_keyword
            for entry in self.db.scalars(
                select(OfferTodayKeywordEntry).where(
                    OfferTodayKeywordEntry.source_classification_id
                    == classification.id
                )
            )
        }
        created = 0
        for keyword in initial_offertoday_it_keywords():
            normalized = normalize_offertoday_keyword(keyword)
            if normalized in existing:
                continue
            self.db.add(
                OfferTodayKeywordEntry(
                    source_classification_id=classification.id,
                    keyword=keyword,
                    normalized_keyword=normalized,
                    enabled=True,
                    notes="Initial reviewed IT keyword pack",
                    created_by=actor,
                    updated_by=actor,
                )
            )
            existing.add(normalized)
            created += 1
        self.db.flush()
        return created

    def list_entries(self) -> tuple[dict[str, Any], ...]:
        rows = self.db.execute(
            select(OfferTodayKeywordEntry, SourceClassification)
            .join(
                SourceClassification,
                SourceClassification.id
                == OfferTodayKeywordEntry.source_classification_id,
            )
            .order_by(
                SourceClassification.classification_id,
                OfferTodayKeywordEntry.normalized_keyword,
            )
        )
        return tuple(self._entry_payload(entry, classification) for entry, classification in rows)

    def enabled_entries_for_classification(
        self,
        classification_id: str,
    ) -> tuple[OfferTodayKeywordEntry, ...]:
        classification = self._classification_by_identity().get(classification_id)
        if classification is None:
            raise OfferTodayKeywordCatalogError(
                "CLASSIFICATION_INVALID",
                "Keyword pack owner must be an active top-level OfferToday classification",
            )
        return tuple(
            self.db.scalars(
                select(OfferTodayKeywordEntry)
                .where(
                    OfferTodayKeywordEntry.source_classification_id
                    == classification.id,
                    OfferTodayKeywordEntry.enabled.is_(True),
                )
                .order_by(OfferTodayKeywordEntry.normalized_keyword)
            )
        )

    def catalog_updated_at(self) -> datetime | None:
        values = [
            self._aware_utc(entry.updated_at)
            for entry in self.db.scalars(select(OfferTodayKeywordEntry))
        ]
        return max(values) if values else None

    def record_completed_execution_evidence(
        self,
        *,
        classification_id: str,
        normalized_keyword: str,
        newly_contributed_job_ids: int,
        duplicate_rate: float,
        run_at: datetime | None = None,
    ) -> bool:
        """Update runtime-owned evidence after one completed keyword target."""

        classification = self._classification_by_identity().get(classification_id)
        if classification is None:
            return False
        entry = self.db.scalar(
            select(OfferTodayKeywordEntry)
            .where(
                OfferTodayKeywordEntry.source_classification_id == classification.id,
                OfferTodayKeywordEntry.normalized_keyword == normalized_keyword,
            )
            .with_for_update()
        )
        if entry is None:
            return False
        entry.last_new_job_ids = max(0, int(newly_contributed_job_ids))
        entry.last_duplicate_rate = min(1.0, max(0.0, float(duplicate_rate)))
        entry.last_run_at = run_at or utc_now()
        self.db.flush()
        return True

    def export_csv(self) -> str:
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=OFFERTODAY_KEYWORD_CSV_COLUMNS)
        writer.writeheader()
        for entry in self.list_entries():
            writer.writerow(
                {
                    "classification_id": entry["classification_id"],
                    "classification_label": entry["classification_label"],
                    "keyword": entry["keyword"],
                    "enabled": "true" if entry["enabled"] else "false",
                    "notes": entry["notes"],
                    "last_new_job_ids": self._csv_value(entry["last_new_job_ids"]),
                    "last_duplicate_rate": self._csv_value(
                        entry["last_duplicate_rate"]
                    ),
                    "last_run_at": self._csv_value(entry["last_run_at"]),
                }
            )
        return output.getvalue()

    def preview_csv(
        self,
        csv_bytes: bytes,
        *,
        actor: str,
        ttl: timedelta = timedelta(minutes=10),
    ) -> KeywordCsvPreview:
        self._validate_actor(actor)
        csv_hash = hashlib.sha256(csv_bytes).hexdigest()
        parsed_rows, issues = self._parse_csv(csv_bytes)
        classifications = self._classification_by_identity()
        existing = self._entry_state()
        warnings: list[dict[str, Any]] = []
        change_set: list[dict[str, Any]] = []
        file_identities: set[tuple[str, str]] = set()

        for row_number, row in parsed_rows:
            classification_id = row["classification_id"]
            classification = classifications.get(classification_id)
            if classification is None:
                issues.append(
                    KeywordCsvRowIssue(
                        row_number,
                        "classification_id",
                        "CLASSIFICATION_INVALID",
                        "Classification must be an active top-level OfferToday identity",
                    )
                )
                continue
            keyword = _display_keyword(row["keyword"])
            normalized = normalize_offertoday_keyword(keyword)
            if not normalized:
                issues.append(
                    KeywordCsvRowIssue(
                        row_number,
                        "keyword",
                        "KEYWORD_EMPTY",
                        "Keyword cannot be empty",
                    )
                )
                continue
            if len(keyword) > 255 or len(row["notes"]) > 4000:
                issues.append(
                    KeywordCsvRowIssue(
                        row_number,
                        "keyword" if len(keyword) > 255 else "notes",
                        "VALUE_TOO_LONG",
                        "Keyword or notes exceeds the supported length",
                    )
                )
                continue
            identity = (classification_id, normalized)
            if identity in file_identities:
                issues.append(
                    KeywordCsvRowIssue(
                        row_number,
                        "keyword",
                        "KEYWORD_DUPLICATE",
                        "Keyword duplicates another row after case/whitespace normalization",
                    )
                )
                continue
            file_identities.add(identity)
            enabled = self._parse_enabled(row["enabled"])
            if enabled is None:
                issues.append(
                    KeywordCsvRowIssue(
                        row_number,
                        "enabled",
                        "ENABLED_INVALID",
                        "Enabled must be true or false",
                    )
                )
                continue
            supplied_label = row["classification_label"].strip()
            if supplied_label and supplied_label != classification.label:
                warnings.append(
                    {
                        "row": row_number,
                        "code": "CLASSIFICATION_LABEL_STALE",
                        "classification_id": classification_id,
                        "supplied_label": supplied_label,
                        "current_label": classification.label,
                    }
                )
            current = existing.get(identity)
            action = "add"
            if current is not None:
                if (
                    current["keyword"] == keyword
                    and current["enabled"] is enabled
                    and current["notes"] == row["notes"]
                ):
                    action = "unchanged"
                elif current["enabled"] and not enabled:
                    action = "disable"
                else:
                    action = "update"
            change_set.append(
                {
                    "row": row_number,
                    "classification_id": classification_id,
                    "source_classification_id": str(classification.id),
                    "keyword": keyword,
                    "normalized_keyword": normalized,
                    "enabled": enabled,
                    "notes": row["notes"],
                    "action": action,
                }
            )

        resulting_counts = self._resulting_enabled_counts(
            existing=existing,
            change_set=change_set,
            classification_ids=tuple(classifications),
        )
        for classification_id, count in sorted(resulting_counts.items()):
            if count > OFFERTODAY_KEYWORD_ENABLED_LIMIT:
                issues.append(
                    KeywordCsvRowIssue(
                        0,
                        "enabled",
                        "ENABLED_LIMIT_EXCEEDED",
                        f"{classification_id} would have {count} enabled keywords; maximum is {OFFERTODAY_KEYWORD_ENABLED_LIMIT}",
                    )
                )

        current_counts = self._current_enabled_counts(existing, tuple(classifications))
        workload_impact = {
            "current_enabled_keyword_count": sum(current_counts.values()),
            "resulting_enabled_keyword_count": sum(resulting_counts.values()),
            "enabled_keyword_delta": sum(resulting_counts.values())
            - sum(current_counts.values()),
            "by_classification": {
                classification_id: {
                    "current_enabled": current_counts[classification_id],
                    "resulting_enabled": resulting_counts[classification_id],
                    "query_target_delta": resulting_counts[classification_id]
                    - current_counts[classification_id],
                }
                for classification_id in sorted(classifications)
            },
        }
        diff = tuple(self._diff_payload(item) for item in change_set)
        if issues:
            return KeywordCsvPreview(
                valid=False,
                csv_hash=csv_hash,
                errors=tuple(issues),
                warnings=tuple(warnings),
                diff=diff,
                resulting_enabled_counts=resulting_counts,
                workload_impact=workload_impact,
            )

        token = secrets.token_urlsafe(32)
        expires_at = utc_now() + ttl
        review = OfferTodayKeywordCsvReview(
            confirmation_token_hash=self._token_hash(token),
            csv_hash=csv_hash,
            catalog_fingerprint=self.catalog_fingerprint(),
            change_set=change_set,
            diff=list(diff),
            resulting_enabled_counts=resulting_counts,
            workload_impact=workload_impact,
            requested_by=actor,
            expires_at=expires_at,
        )
        self.db.add(review)
        self.db.commit()
        return KeywordCsvPreview(
            valid=True,
            csv_hash=csv_hash,
            errors=(),
            warnings=tuple(warnings),
            diff=diff,
            resulting_enabled_counts=resulting_counts,
            workload_impact=workload_impact,
            confirmation_token=token,
            expires_at=expires_at,
        )

    def confirm_csv(
        self,
        *,
        confirmation_token: str,
        csv_hash: str,
        actor: str,
    ) -> dict[str, Any]:
        self._validate_actor(actor)
        review = self.db.scalar(
            select(OfferTodayKeywordCsvReview)
            .where(
                OfferTodayKeywordCsvReview.confirmation_token_hash
                == self._token_hash(confirmation_token)
            )
            .with_for_update()
        )
        now = utc_now()
        if review is None:
            raise OfferTodayKeywordCatalogError(
                "KEYWORD_CSV_REVIEW_STALE",
                "Keyword CSV review token is unknown",
            )
        if (
            review.requested_by != actor
            or review.csv_hash != csv_hash
            or review.consumed_at is not None
            or self._aware_utc(review.expires_at) <= now
            or review.catalog_fingerprint != self.catalog_fingerprint(for_update=True)
        ):
            raise OfferTodayKeywordCatalogError(
                "KEYWORD_CSV_REVIEW_STALE",
                "Keyword CSV review is expired, consumed, or stale",
            )

        classifications = self._classification_by_identity()
        entries = {
            (classification.classification_id, entry.normalized_keyword): entry
            for entry, classification in self.db.execute(
                select(OfferTodayKeywordEntry, SourceClassification)
                .join(SourceClassification)
                .with_for_update()
            )
        }
        counts = {"added": 0, "updated": 0, "disabled": 0}
        for change in review.change_set:
            classification = classifications.get(change["classification_id"])
            if classification is None or str(classification.id) != change[
                "source_classification_id"
            ]:
                raise OfferTodayKeywordCatalogError(
                    "KEYWORD_CSV_REVIEW_STALE",
                    "A reviewed Source Classification is no longer current",
                )
            identity = (
                change["classification_id"],
                change["normalized_keyword"],
            )
            entry = entries.get(identity)
            action = change["action"]
            if entry is None:
                entry = OfferTodayKeywordEntry(
                    source_classification_id=classification.id,
                    keyword=change["keyword"],
                    normalized_keyword=change["normalized_keyword"],
                    enabled=change["enabled"],
                    notes=change["notes"],
                    created_by=actor,
                    updated_by=actor,
                )
                self.db.add(entry)
                entries[identity] = entry
                counts["added"] += 1
                continue
            if action == "unchanged":
                continue
            entry.keyword = change["keyword"]
            entry.enabled = change["enabled"]
            entry.notes = change["notes"]
            entry.updated_by = actor
            entry.updated_at = now
            counts["disabled" if action == "disable" else "updated"] += 1

        review.consumed_at = now
        self.db.add(
            OfferTodayKeywordMutationLog(
                actor=actor,
                csv_hash=review.csv_hash,
                added_count=counts["added"],
                updated_count=counts["updated"],
                disabled_count=counts["disabled"],
            )
        )
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {
            **counts,
            "csv_hash": review.csv_hash,
            "resulting_enabled_counts": dict(review.resulting_enabled_counts),
        }

    def catalog_fingerprint(self, *, for_update: bool = False) -> str:
        statement = select(OfferTodayKeywordEntry, SourceClassification).join(
            SourceClassification
        )
        if for_update:
            statement = statement.with_for_update()
        entries = [
            {
                "classification_id": classification.classification_id,
                "keyword": entry.keyword,
                "normalized_keyword": entry.normalized_keyword,
                "enabled": entry.enabled,
                "notes": entry.notes,
            }
            for entry, classification in self.db.execute(statement)
        ]
        entries.sort(key=lambda item: (item["classification_id"], item["normalized_keyword"]))
        active_classifications = sorted(self._classification_by_identity())
        return payload_fingerprint(
            {
                "active_top_level_classification_ids": active_classifications,
                "entries": entries,
            }
        )

    def _parse_csv(
        self, csv_bytes: bytes
    ) -> tuple[list[tuple[int, dict[str, str]]], list[KeywordCsvRowIssue]]:
        try:
            text = csv_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            return [], [
                KeywordCsvRowIssue(
                    0,
                    "file",
                    "CSV_ENCODING_INVALID",
                    "CSV must use UTF-8 encoding",
                )
            ]
        try:
            reader = csv.DictReader(io.StringIO(text, newline=""))
            header = tuple(reader.fieldnames or ())
            if len(set(header)) != len(header) or set(header) != set(
                OFFERTODAY_KEYWORD_CSV_COLUMNS
            ):
                return [], [
                    KeywordCsvRowIssue(
                        1,
                        "header",
                        "CSV_HEADER_INVALID",
                        "CSV header must contain the documented eight columns exactly once",
                    )
                ]
            rows: list[tuple[int, dict[str, str]]] = []
            for row in reader:
                if None in row:
                    return [], [
                        KeywordCsvRowIssue(
                            reader.line_num,
                            "row",
                            "CSV_ROW_INVALID",
                            "CSV row has more values than the header",
                        )
                    ]
                normalized_row = {
                    column: str(row.get(column) or "")
                    for column in OFFERTODAY_KEYWORD_CSV_COLUMNS
                }
                if not any(value.strip() for value in normalized_row.values()):
                    continue
                rows.append((reader.line_num, normalized_row))
            return rows, []
        except csv.Error:
            return [], [
                KeywordCsvRowIssue(
                    0,
                    "file",
                    "CSV_PARSE_INVALID",
                    "CSV could not be parsed",
                )
            ]

    def _classification_by_identity(self) -> dict[str, SourceClassification]:
        return {
            row.classification_id: row
            for row in self.db.scalars(
                select(SourceClassification).where(
                    SourceClassification.source_site == "offertoday",
                    SourceClassification.is_top_level.is_(True),
                    SourceClassification.is_active.is_(True),
                )
            )
        }

    def _entry_state(self) -> dict[tuple[str, str], dict[str, Any]]:
        return {
            (classification.classification_id, entry.normalized_keyword): {
                "keyword": entry.keyword,
                "enabled": bool(entry.enabled),
                "notes": entry.notes,
            }
            for entry, classification in self.db.execute(
                select(OfferTodayKeywordEntry, SourceClassification).join(
                    SourceClassification
                )
            )
        }

    @staticmethod
    def _current_enabled_counts(
        existing: dict[tuple[str, str], dict[str, Any]],
        classification_ids: tuple[str, ...],
    ) -> dict[str, int]:
        return {
            classification_id: sum(
                1
                for (owner, _), entry in existing.items()
                if owner == classification_id and entry["enabled"]
            )
            for classification_id in classification_ids
        }

    @classmethod
    def _resulting_enabled_counts(
        cls,
        *,
        existing: dict[tuple[str, str], dict[str, Any]],
        change_set: list[dict[str, Any]],
        classification_ids: tuple[str, ...],
    ) -> dict[str, int]:
        state = {
            identity: bool(entry["enabled"]) for identity, entry in existing.items()
        }
        for change in change_set:
            state[(change["classification_id"], change["normalized_keyword"])] = bool(
                change["enabled"]
            )
        return {
            classification_id: sum(
                1
                for (owner, _), enabled in state.items()
                if owner == classification_id and enabled
            )
            for classification_id in classification_ids
        }

    @staticmethod
    def _parse_enabled(value: str) -> bool | None:
        normalized = value.strip().casefold()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
        return None

    @staticmethod
    def _diff_payload(change: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in change.items()
            if key != "source_classification_id"
        }

    @staticmethod
    def _entry_payload(
        entry: OfferTodayKeywordEntry,
        classification: SourceClassification,
    ) -> dict[str, Any]:
        return {
            "id": str(entry.id),
            "classification_id": classification.classification_id,
            "classification_label": classification.label,
            "keyword": entry.keyword,
            "normalized_keyword": entry.normalized_keyword,
            "enabled": bool(entry.enabled),
            "notes": entry.notes,
            "updated_at": OfferTodayKeywordCatalog._aware_utc(entry.updated_at),
            "last_new_job_ids": entry.last_new_job_ids,
            "last_duplicate_rate": entry.last_duplicate_rate,
            "last_run_at": (
                OfferTodayKeywordCatalog._aware_utc(entry.last_run_at)
                if entry.last_run_at is not None
                else None
            ),
        }

    @staticmethod
    def _csv_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return OfferTodayKeywordCatalog._aware_utc(value).isoformat()
        return str(value)

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_actor(actor: str) -> None:
        if not str(actor or "").strip():
            raise OfferTodayKeywordCatalogError(
                "KEYWORD_ACTOR_INVALID", "Keyword catalog actor is required"
            )

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


__all__ = [
    "OFFERTODAY_IT_CLASSIFICATION_ID",
    "OFFERTODAY_KEYWORD_CSV_COLUMNS",
    "OFFERTODAY_KEYWORD_ENABLED_LIMIT",
    "KeywordCsvPreview",
    "OfferTodayKeywordCatalog",
    "OfferTodayKeywordCatalogError",
    "initial_offertoday_it_keywords",
    "normalize_offertoday_keyword",
]
