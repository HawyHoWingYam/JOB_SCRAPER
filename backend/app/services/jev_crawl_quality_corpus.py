from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unicodedata
from uuid import uuid4

from sqlalchemy import Engine, text

from app.job_intelligence.foundation.hashing import (
    canonical_json,
    normalized_content_hash,
)


class CrawlQualityCorpusError(ValueError):
    pass


_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{6,}\d)(?!\w)")


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, _attrs) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"p", "div", "br", "li", "tr"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        elif tag in {"p", "div", "li", "tr"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _excerpt(value: str) -> str:
    parser = _Text()
    parser.feed(value)
    parser.close()
    normalized = unicodedata.normalize("NFKC", "".join(parser.parts))
    normalized = _EMAIL.sub("[redacted-email]", normalized)
    normalized = _PHONE.sub("[redacted-phone]", normalized)
    return re.sub(r"\s+", " ", normalized).strip()[:2_000]


def _extract(engine: Engine, limit: int) -> list[dict[str, object]]:
    if engine.dialect.name != "postgresql":
        raise CrawlQualityCorpusError("crawl quality corpus requires PostgreSQL")
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            rows = (
                connection.execute(
                    text(
                        """
                    SELECT CAST(l.id AS text) AS listing_id,
                           CAST(l.crawl_job_id AS text) AS crawl_job_id,
                           CAST(l.published_job_id AS text) AS job_uuid,
                           l.source_site, l.source_job_id,
                           l.detail_status, l.detail_attempts,
                           l.detail_error_message, l.detail_payload,
                           j.title, j.description AS description_raw,
                           l.updated_at
                    FROM crawl_job_listings l
                    LEFT JOIN jobs j ON j.id = l.published_job_id
                    WHERE l.source_site IN ('jobsdb', 'ctgoodjobs', 'offertoday')
                    ORDER BY l.updated_at DESC, l.source_site, l.source_job_id
                    LIMIT :limit
                    """
                    ),
                    {"limit": limit},
                )
                .mappings()
                .all()
            )
            transaction.rollback()
        except Exception:
            transaction.rollback()
            raise
    return [dict(row) for row in rows]


def build_crawl_quality_corpus(
    engine: Engine | None,
    *,
    output_dir: Path,
    limit: int,
    extracted_rows: list[dict[str, object]] | None = None,
    artifact_name: str | None = None,
    captured_at: str | None = None,
) -> Path:
    if not 1 <= limit <= 10_000:
        raise CrawlQualityCorpusError("limit must be between 1 and 10000")
    if extracted_rows is None:
        if engine is None:
            raise CrawlQualityCorpusError("database engine is required")
        extracted_rows = _extract(engine, limit)
    rows = []
    for source in extracted_rows[:limit]:
        raw = str(source.get("description_raw") or "")
        excerpt = _excerpt(raw)
        payload = source.get("detail_payload")
        rows.append(
            {
                "case_id": f"real:{source['listing_id']}",
                "crawl_job_id": str(source["crawl_job_id"]),
                "job_uuid": str(source["job_uuid"]) if source.get("job_uuid") else None,
                "source_site": str(source["source_site"]),
                "source_job_id": str(source["source_job_id"]),
                "detail_status": str(source["detail_status"]),
                "detail_attempts": int(source.get("detail_attempts") or 0),
                "has_detail_error": bool(source.get("detail_error_message")),
                "title": source.get("title"),
                "evidence_excerpt": excerpt,
                "language": _language(f"{source.get('title') or ''} {excerpt}"),
                "description_sha256": normalized_content_hash({"raw": raw}),
                "payload_sha256": normalized_content_hash(payload),
                "updated_at": _time(source.get("updated_at")),
                "reference_status": "unreviewed",
                "reference_provenance": "none",
            }
        )
    rows.sort(
        key=lambda row: (
            str(row["source_site"]),
            str(row["source_job_id"]),
            str(row["case_id"]),
        )
    )
    artifact = output_dir / (artifact_name or f"jev-crawl-quality-{uuid4()}")
    artifact.mkdir(parents=True, exist_ok=False)
    content = "".join(canonical_json(row) + "\n" for row in rows).encode()
    (artifact / "cases.jsonl").write_bytes(content)
    manifest = {
        "schema_version": "jev-crawl-quality-corpus.v1",
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
        "row_count": len(rows),
        "limit": limit,
        "cases_sha256": hashlib.sha256(content).hexdigest(),
    }
    (artifact / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    )
    return artifact


def verify_crawl_quality_corpus(artifact: Path) -> dict[str, object]:
    if not artifact.is_dir() or {path.name for path in artifact.iterdir()} != {
        "manifest.json",
        "cases.jsonl",
    }:
        raise CrawlQualityCorpusError("crawl quality artifact file set is invalid")
    if any(path.is_symlink() for path in artifact.iterdir()):
        raise CrawlQualityCorpusError("crawl quality artifact cannot contain symlinks")
    manifest = json.loads((artifact / "manifest.json").read_text())
    content = (artifact / "cases.jsonl").read_bytes()
    rows = [json.loads(line) for line in content.splitlines() if line]
    if manifest.get("schema_version") != "jev-crawl-quality-corpus.v1":
        raise CrawlQualityCorpusError("crawl quality corpus schema is invalid")
    if hashlib.sha256(content).hexdigest() != manifest.get("cases_sha256"):
        raise CrawlQualityCorpusError("crawl quality cases hash mismatch")
    if len(rows) != manifest.get("row_count"):
        raise CrawlQualityCorpusError("crawl quality row count mismatch")
    forbidden = {"detail_payload", "description_raw", "raw_data", "source_url"}
    if any(forbidden & set(row) for row in rows):
        raise CrawlQualityCorpusError(
            "crawl quality artifact contains forbidden raw data"
        )
    return {"manifest": manifest, "rows": rows}


def _language(value: str) -> str:
    cjk = bool(re.search(r"[\u3400-\u9fff]", value))
    latin = bool(re.search(r"[A-Za-z]", value))
    return "mixed" if cjk and latin else "zh-Hant" if cjk else "en"


def _time(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


__all__ = [
    "CrawlQualityCorpusError",
    "build_crawl_quality_corpus",
    "verify_crawl_quality_corpus",
]
