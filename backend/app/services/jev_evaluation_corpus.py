from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unicodedata
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from app.job_intelligence.foundation.hashing import (
    canonical_json,
    normalized_content_hash,
)


class RealCorpusExportError(ValueError):
    pass


_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{6,}\d)(?!\w)")


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, _attrs) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        elif tag in {"br", "p", "div", "li", "tr"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1
        elif tag in {"p", "div", "li", "tr"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def _language(value: str) -> str:
    has_cjk = bool(re.search(r"[\u3400-\u9fff]", value))
    has_latin = bool(re.search(r"[A-Za-z]", value))
    if has_cjk and has_latin:
        return "mixed"
    if has_cjk:
        return "zh-Hant"
    return "en"


def _minimal_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(value)
    parser.close()
    visible = "".join(parser.parts) if parser.parts else unescape(value)
    normalized = unicodedata.normalize("NFKC", visible)
    normalized = _EMAIL.sub("[redacted-email]", normalized)
    normalized = _PHONE.sub("[redacted-phone]", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _assign_connected_groups_and_splits(rows: list[dict]) -> None:
    parents = list(range(len(rows)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    seen: dict[tuple[str, str], int] = {}
    for index, row in enumerate(rows):
        keys = [("content", row["content_fingerprint_sha256"])]
        if row.get("company_id"):
            keys.append(("company", str(row["company_id"])))
        for key in keys:
            if key in seen:
                union(index, seen[key])
            else:
                seen[key] = index

    members: dict[int, list[int]] = {}
    for index in range(len(rows)):
        members.setdefault(find(index), []).append(index)
    groups = []
    for indexes in members.values():
        identities = sorted(
            f"{rows[index]['source_site']}:{rows[index]['source_job_id']}"
            for index in indexes
        )
        group_id = (
            "connected:"
            + hashlib.sha256(canonical_json(identities).encode("utf-8")).hexdigest()
        )
        newest = max(str(rows[index].get("job_updated_at") or "") for index in indexes)
        groups.append((newest, group_id, indexes))

    groups.sort(key=lambda item: (item[0], item[1]))
    held_out_count = 0 if len(groups) < 2 else max(1, (len(groups) + 4) // 5)
    held_out_ids = (
        {group_id for _, group_id, _ in groups[-held_out_count:]}
        if held_out_count
        else set()
    )
    for _, group_id, indexes in groups:
        for index in indexes:
            rows[index]["group_id"] = group_id
            rows[index]["evaluation_split"] = (
                "held_out" if group_id in held_out_ids else "development"
            )


def _extract_rows(engine: Engine, *, limit: int) -> tuple[list[dict], list[dict]]:
    if engine.dialect.name != "postgresql":
        raise RealCorpusExportError("real-corpus export requires PostgreSQL")
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            job_rows = (
                connection.execute(
                    text(
                        """
                    SELECT CAST(j.id AS text) AS job_uuid,
                           j.source_site, j.source_job_id,
                           j.job_id AS compatibility_job_id,
                           CAST(j.company_id AS text) AS company_id,
                           j.title, j.description AS description_raw,
                           j.updated_at AS job_updated_at,
                           CAST(m.id AS text) AS mention_id,
                           m.raw_name, m.resolution, m.skill_code,
                           CAST(m.candidate_id AS text) AS candidate_id,
                           m.evidence_hash AS mention_evidence_hash,
                           m.provenance AS mention_provenance
                    FROM jobs j
                    JOIN current_job_skill_mentions m ON m.job_id = j.id
                    WHERE j.is_deleted IS FALSE
                      AND j.source_site IN ('jobsdb', 'ctgoodjobs', 'offertoday')
                      AND NULLIF(BTRIM(j.description), '') IS NOT NULL
                      AND m.status = 'active'
                    ORDER BY j.source_site, j.source_job_id, m.id
                    LIMIT :limit
                    """
                    ),
                    {"limit": limit},
                )
                .mappings()
                .all()
            )
            taxonomy_rows = (
                connection.execute(
                    text(
                        """
                    SELECT n.code, n.labels,
                           COALESCE(
                             (
                               SELECT json_agg(a.alias ORDER BY a.alias)
                               FROM current_taxonomy_aliases a
                               WHERE a.taxonomy = n.taxonomy
                                 AND a.node_code = n.code
                             ),
                             '[]'
                           ) AS aliases
                    FROM current_taxonomy_nodes n
                    WHERE n.taxonomy = 'skill'
                      AND n.is_active IS TRUE AND n.is_assignable IS TRUE
                    ORDER BY n.code
                    """
                    )
                )
                .mappings()
                .all()
            )
            transaction.rollback()
        except Exception:
            transaction.rollback()
            raise
    return [dict(row) for row in job_rows], [dict(row) for row in taxonomy_rows]


def _json_safe(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def build_real_corpus_artifact(
    engine: Engine | None,
    *,
    output_dir: Path,
    limit: int,
    extracted_rows: list[dict] | None = None,
    taxonomy_snapshot: list[dict] | None = None,
    captured_at: str | None = None,
) -> Path:
    if not 1 <= limit <= 10_000:
        raise RealCorpusExportError("limit must be between 1 and 10000")
    if extracted_rows is None or taxonomy_snapshot is None:
        if engine is None:
            raise RealCorpusExportError("database engine is required")
        extracted_rows, taxonomy_snapshot = _extract_rows(engine, limit=limit)
    extracted_rows = extracted_rows[:limit]
    taxonomy_snapshot = sorted(taxonomy_snapshot, key=lambda row: str(row["code"]))
    taxonomy_hash = normalized_content_hash(taxonomy_snapshot)
    rows = []
    for source in extracted_rows:
        raw_description = str(source.get("description_raw") or "")
        description_text = _minimal_text(raw_description)
        reference_status = (
            "weak_reference"
            if source.get("resolution")
            in {"match_existing", "candidate", "generic_tag", "rejected"}
            else "unresolved"
        )
        rows.append(
            {
                "case_id": f"real:{source['mention_id']}",
                "split": "real_corpus",
                "decision_kind": (
                    "candidate_recommendation"
                    if source.get("resolution") == "candidate"
                    else "evidence_support"
                ),
                "job_uuid": str(source["job_uuid"]),
                "source_site": source["source_site"],
                "source_job_id": str(source["source_job_id"]),
                "compatibility_job_id": source.get("compatibility_job_id"),
                "company_id": source.get("company_id"),
                "title": source.get("title"),
                "description_text": description_text,
                "content_fingerprint_sha256": normalized_content_hash(
                    {
                        "hash_schema": "jev.normalized-description.v1",
                        "text": description_text,
                    }
                ),
                "description_sha256": normalized_content_hash(
                    {
                        "hash_schema": "jev.job-description.v1",
                        "source_site": source["source_site"],
                        "source_job_id": str(source["source_job_id"]),
                        "description_raw": raw_description,
                    }
                ),
                "job_updated_at": _json_safe(source.get("job_updated_at")),
                "language": _language(description_text),
                "mention_id": str(source["mention_id"]),
                "raw_name": source.get("raw_name"),
                "resolution": source.get("resolution"),
                "skill_code": source.get("skill_code"),
                "candidate_id": source.get("candidate_id"),
                "mention_evidence_hash": source.get("mention_evidence_hash"),
                "mention_provenance": source.get("mention_provenance") or {},
                "reference_status": reference_status,
                "reference_provenance": (
                    "existing_ai_projection"
                    if reference_status == "weak_reference"
                    else "unresolved"
                ),
                "taxonomy_snapshot_sha256": taxonomy_hash,
            }
        )
    _assign_connected_groups_and_splits(rows)
    artifact = output_dir / f"jev-real-corpus-{uuid4()}"
    artifact.mkdir(parents=True, exist_ok=False)
    cases_bytes = "".join(canonical_json(row) + "\n" for row in rows).encode("utf-8")
    (artifact / "cases.jsonl").write_bytes(cases_bytes)
    (artifact / "taxonomy.json").write_text(
        json.dumps(taxonomy_snapshot, ensure_ascii=False, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "jev-real-corpus.v1",
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
        "row_count": len(rows),
        "limit": limit,
        "taxonomy_snapshot_sha256": taxonomy_hash,
        "cases_sha256": hashlib.sha256(cases_bytes).hexdigest(),
        "limitations": [
            "Existing projections are weak references, not validated truth.",
            "Contact details are minimized before model evaluation.",
            "Raw source payloads are excluded.",
        ],
    }
    (artifact / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return artifact


def verify_real_corpus_artifact(artifact: Path) -> dict[str, object]:
    expected_files = {"manifest.json", "cases.jsonl", "taxonomy.json"}
    if (
        not artifact.is_dir()
        or {path.name for path in artifact.iterdir()} != expected_files
    ):
        raise RealCorpusExportError("real-corpus artifact file set is invalid")
    if any(path.is_symlink() for path in artifact.iterdir()):
        raise RealCorpusExportError("real-corpus artifact must not contain symlinks")
    try:
        manifest = json.loads((artifact / "manifest.json").read_text())
        taxonomy = json.loads((artifact / "taxonomy.json").read_text())
        cases_bytes = (artifact / "cases.jsonl").read_bytes()
        rows = [json.loads(line) for line in cases_bytes.splitlines() if line]
    except (OSError, ValueError) as exc:
        raise RealCorpusExportError(
            f"real-corpus artifact is unreadable: {exc}"
        ) from exc
    if manifest.get("schema_version") != "jev-real-corpus.v1":
        raise RealCorpusExportError("real-corpus schema version is invalid")
    if hashlib.sha256(cases_bytes).hexdigest() != manifest.get("cases_sha256"):
        raise RealCorpusExportError("real-corpus cases hash mismatch")
    if normalized_content_hash(taxonomy) != manifest.get("taxonomy_snapshot_sha256"):
        raise RealCorpusExportError("real-corpus taxonomy hash mismatch")
    if len(rows) != manifest.get("row_count"):
        raise RealCorpusExportError("real-corpus row count mismatch")
    if any("raw_data" in row or "description_raw" in row for row in rows):
        raise RealCorpusExportError("real-corpus artifact contains forbidden raw data")
    return {"manifest": manifest, "taxonomy": taxonomy, "rows": rows}


__all__ = [
    "RealCorpusExportError",
    "build_real_corpus_artifact",
    "verify_real_corpus_artifact",
]
