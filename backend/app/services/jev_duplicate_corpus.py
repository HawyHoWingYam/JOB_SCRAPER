from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from html import unescape
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
from app.services.jev_duplicate_evaluation import (
    DuplicateCandidateJob,
    DuplicateCandidatePolicy,
    DuplicateJobSnapshot,
    build_duplicate_candidates,
)


class DuplicateCorpusArtifactError(ValueError):
    pass


_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{6,}\d)(?!\w)")
_EXPECTED_FILES = {
    "manifest.json",
    "jobs.jsonl",
    "candidate-pairs.jsonl",
    "policy.json",
}
_EMBEDDING_MODEL_PROVENANCE = "code-default:sentence-transformers/all-MiniLM-L6-v2"


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


def _minimal_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(value)
    parser.close()
    visible = "".join(parser.parts) if parser.parts else unescape(value)
    normalized = unicodedata.normalize("NFKC", visible)
    normalized = _EMAIL.sub("[redacted-email]", normalized)
    normalized = _PHONE.sub("[redacted-phone]", normalized)
    return re.sub(r"\s+", " ", normalized).strip()[:4_000]


def _language(value: str) -> str:
    has_cjk = bool(re.search(r"[\u3400-\u9fff]", value))
    has_latin = bool(re.search(r"[A-Za-z]", value))
    if has_cjk and has_latin:
        return "mixed"
    return "zh-Hant" if has_cjk else "en"


def _extract_rows(engine: Engine, *, limit: int) -> list[dict[str, object]]:
    if engine.dialect.name != "postgresql":
        raise DuplicateCorpusArtifactError(
            "duplicate corpus export requires PostgreSQL"
        )
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT CAST(j.id AS text) AS job_uuid,
                               j.source_site,
                               j.source_job_id,
                               CAST(j.company_id AS text) AS company_id,
                               c.name AS company_name,
                               j.title,
                               j.location,
                               j.posted_date,
                               j.updated_at AS job_updated_at,
                               j.description AS description_raw,
                               e.document_hash AS embedding_document_hash,
                               e.embedding_dimensions,
                               e.updated_at AS embedding_updated_at,
                               CAST(e.embedding AS text) AS embedding
                        FROM jobs j
                        JOIN companies c ON c.id = j.company_id
                        JOIN job_embeddings e ON e.job_id = j.id
                        WHERE j.is_deleted IS FALSE
                          AND j.source_site IN ('jobsdb', 'ctgoodjobs', 'offertoday')
                          AND NULLIF(BTRIM(j.title), '') IS NOT NULL
                          AND NULLIF(BTRIM(j.description), '') IS NOT NULL
                        ORDER BY j.source_site, j.source_job_id, j.id
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


def build_duplicate_corpus_artifact(
    engine: Engine | None,
    *,
    output_dir: Path,
    limit: int,
    max_pairs: int,
    extracted_rows: list[dict[str, object]] | None = None,
    captured_at: str | None = None,
    artifact_name: str | None = None,
) -> Path:
    if not 2 <= limit <= 10_000:
        raise DuplicateCorpusArtifactError("limit must be between 2 and 10000")
    if not 1 <= max_pairs <= 100_000:
        raise DuplicateCorpusArtifactError("max_pairs must be between 1 and 100000")
    if extracted_rows is None:
        if engine is None:
            raise DuplicateCorpusArtifactError("database engine is required")
        extracted_rows = _extract_rows(engine, limit=limit)
    sources = extracted_rows[:limit]
    job_rows: list[dict[str, object]] = []
    candidate_jobs: list[DuplicateCandidateJob] = []
    uuid_by_identity: dict[str, str] = {}
    language_by_identity: dict[str, str] = {}
    for source in sources:
        description_raw = str(source.get("description_raw") or "")
        description_text = _minimal_text(description_raw)
        source_site = str(source["source_site"])
        source_job_id = str(source["source_job_id"])
        identity = f"{source_site}:{source_job_id}"
        language = _language(
            " ".join((str(source.get("title") or ""), description_text))
        )
        snapshot = DuplicateJobSnapshot(
            source_site=source_site,
            source_job_id=source_job_id,
            title=str(source.get("title") or ""),
            company_name=_optional_text(source.get("company_name")),
            location=_optional_text(source.get("location")),
            posted_date=_date_text(source.get("posted_date")),
            description_text=description_text or None,
        )
        embedding = _embedding_values(source.get("embedding"))
        candidate_jobs.append(
            DuplicateCandidateJob(snapshot=snapshot, embedding=embedding)
        )
        job_uuid = str(source["job_uuid"])
        uuid_by_identity[identity] = job_uuid
        language_by_identity[identity] = language
        job_rows.append(
            {
                "job_uuid": job_uuid,
                "source_identity": identity,
                "source_site": source_site,
                "source_job_id": source_job_id,
                "company_id": _optional_text(source.get("company_id")),
                "company_name": snapshot.company_name,
                "title": snapshot.title,
                "location": snapshot.location,
                "posted_date": snapshot.posted_date,
                "job_updated_at": _json_time(source.get("job_updated_at")),
                "description_text": description_text,
                "description_sha256": normalized_content_hash(
                    {
                        "schema": "jev.duplicate.raw-description.v1",
                        "source_identity": identity,
                        "description_raw": description_raw,
                    }
                ),
                "normalized_text_sha256": normalized_content_hash(
                    {
                        "schema": "jev.duplicate.visible-evidence.v1",
                        "title": snapshot.title,
                        "company_name": snapshot.company_name,
                        "location": snapshot.location,
                        "description_text": description_text,
                    }
                ),
                "language": language,
                "embedding": {
                    "document_hash": str(source["embedding_document_hash"]),
                    "dimensions": int(source["embedding_dimensions"]),
                    "updated_at": _json_time(source.get("embedding_updated_at")),
                    "model_provenance": _EMBEDDING_MODEL_PROVENANCE,
                },
            }
        )
    job_rows.sort(key=lambda row: str(row["source_identity"]))
    policy = DuplicateCandidatePolicy(
        lexical_top_k=10,
        embedding_top_k=10,
        max_pairs=max_pairs,
    )
    candidates = build_duplicate_candidates(tuple(candidate_jobs), policy=policy)
    candidate_rows = [
        {
            "pair_id": candidate.pair_id,
            "left_job_uuid": uuid_by_identity[candidate.left_identity],
            "right_job_uuid": uuid_by_identity[candidate.right_identity],
            "left_source_identity": candidate.left_identity,
            "right_source_identity": candidate.right_identity,
            "methods": list(candidate.methods),
            "candidate_rank": candidate.rank,
            "lexical_score": candidate.lexical_score,
            "embedding_score": candidate.embedding_score,
            "source_stratum": "|".join(
                sorted(
                    (
                        candidate.left_identity.split(":", 1)[0],
                        candidate.right_identity.split(":", 1)[0],
                    )
                )
            ),
            "language_stratum": "|".join(
                sorted(
                    (
                        language_by_identity[candidate.left_identity],
                        language_by_identity[candidate.right_identity],
                    )
                )
            ),
            "reference_status": "unreviewed",
            "reference_provenance": "none",
        }
        for candidate in candidates
    ]
    policy_payload = {
        "schema_version": "jev-duplicate-policy.v1",
        "normalization": "NFKC-casefold-word-v1",
        "lexical_top_k": policy.lexical_top_k,
        "embedding_top_k": policy.embedding_top_k,
        "max_pairs": policy.max_pairs,
        "embedding_model_provenance": _EMBEDDING_MODEL_PROVENANCE,
        "limitations": [
            "Embedding model provenance is code-declared, not stored per database row.",
            "Candidate references are unreviewed and are not identity truth.",
            "Raw payloads and embedding vectors are excluded from the artifact.",
        ],
    }
    artifact = output_dir / (artifact_name or f"jev-duplicate-corpus-{uuid4()}")
    artifact.mkdir(parents=True, exist_ok=False)
    jobs_bytes = _jsonl_bytes(job_rows)
    candidates_bytes = _jsonl_bytes(candidate_rows)
    policy_bytes = (
        json.dumps(policy_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    (artifact / "jobs.jsonl").write_bytes(jobs_bytes)
    (artifact / "candidate-pairs.jsonl").write_bytes(candidates_bytes)
    (artifact / "policy.json").write_bytes(policy_bytes)
    manifest = {
        "schema_version": "jev-duplicate-corpus.v1",
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
        "job_count": len(job_rows),
        "candidate_pair_count": len(candidate_rows),
        "job_limit": limit,
        "pair_limit": max_pairs,
        "files": {
            "jobs.jsonl": hashlib.sha256(jobs_bytes).hexdigest(),
            "candidate-pairs.jsonl": hashlib.sha256(candidates_bytes).hexdigest(),
            "policy.json": hashlib.sha256(policy_bytes).hexdigest(),
        },
    }
    (artifact / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return artifact


def verify_duplicate_corpus_artifact(artifact: Path) -> dict[str, object]:
    if (
        not artifact.is_dir()
        or {path.name for path in artifact.iterdir()} != _EXPECTED_FILES
    ):
        raise DuplicateCorpusArtifactError(
            "duplicate corpus artifact file set is invalid"
        )
    if any(path.is_symlink() for path in artifact.iterdir()):
        raise DuplicateCorpusArtifactError(
            "duplicate corpus artifact must not contain symlinks"
        )
    try:
        manifest = json.loads((artifact / "manifest.json").read_text())
        policy = json.loads((artifact / "policy.json").read_text())
        jobs_bytes = (artifact / "jobs.jsonl").read_bytes()
        candidates_bytes = (artifact / "candidate-pairs.jsonl").read_bytes()
        jobs = _parse_jsonl(jobs_bytes)
        candidates = _parse_jsonl(candidates_bytes)
    except (OSError, ValueError) as exc:
        raise DuplicateCorpusArtifactError(
            f"duplicate corpus artifact is unreadable: {exc}"
        ) from exc
    if manifest.get("schema_version") != "jev-duplicate-corpus.v1":
        raise DuplicateCorpusArtifactError("duplicate corpus schema is invalid")
    if policy.get("schema_version") != "jev-duplicate-policy.v1":
        raise DuplicateCorpusArtifactError("duplicate corpus policy is invalid")
    file_bytes = {
        "jobs.jsonl": jobs_bytes,
        "candidate-pairs.jsonl": candidates_bytes,
        "policy.json": (artifact / "policy.json").read_bytes(),
    }
    for name, content in file_bytes.items():
        if hashlib.sha256(content).hexdigest() != manifest.get("files", {}).get(name):
            raise DuplicateCorpusArtifactError(f"duplicate corpus {name} hash mismatch")
    if len(jobs) != manifest.get("job_count") or len(candidates) != manifest.get(
        "candidate_pair_count"
    ):
        raise DuplicateCorpusArtifactError("duplicate corpus row count mismatch")
    forbidden = {"raw_data", "description_raw", "embedding_vector"}
    if any(forbidden & set(row) for row in jobs + candidates):
        raise DuplicateCorpusArtifactError(
            "duplicate corpus artifact contains forbidden raw data"
        )
    identities = {row.get("source_identity") for row in jobs}
    if len(identities) != len(jobs) or None in identities:
        raise DuplicateCorpusArtifactError(
            "duplicate corpus source identities are invalid"
        )
    for row in candidates:
        if (
            row.get("left_source_identity") not in identities
            or row.get("right_source_identity") not in identities
        ):
            raise DuplicateCorpusArtifactError(
                "duplicate candidate references an unknown Job"
            )
    return {
        "manifest": manifest,
        "policy": policy,
        "jobs": jobs,
        "candidates": candidates,
    }


def _embedding_values(value: object) -> tuple[float, ...] | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, (list, tuple)):
        raise DuplicateCorpusArtifactError("embedding must be a numeric vector")
    try:
        return tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise DuplicateCorpusArtifactError(
            "embedding must be a numeric vector"
        ) from exc


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _date_text(value: object) -> str | None:
    rendered = _json_time(value)
    return rendered[:10] if rendered else None


def _json_time(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _jsonl_bytes(rows: list[dict[str, object]]) -> bytes:
    return "".join(canonical_json(row) + "\n" for row in rows).encode("utf-8")


def _parse_jsonl(content: bytes) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in content.splitlines():
        if not line:
            raise ValueError("blank JSONL lines are forbidden")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("JSONL rows must be objects")
        rows.append(value)
    return rows


__all__ = [
    "DuplicateCorpusArtifactError",
    "build_duplicate_corpus_artifact",
    "verify_duplicate_corpus_artifact",
]
