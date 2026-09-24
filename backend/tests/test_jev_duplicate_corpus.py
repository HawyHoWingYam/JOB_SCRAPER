from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.services.jev_duplicate_corpus import (
    DuplicateCorpusArtifactError,
    build_duplicate_corpus_artifact,
    verify_duplicate_corpus_artifact,
)


def _rows() -> list[dict[str, object]]:
    return [
        {
            "job_uuid": "00000000-0000-0000-0000-000000000001",
            "source_site": "jobsdb",
            "source_job_id": "source-a",
            "company_id": "10000000-0000-0000-0000-000000000001",
            "company_name": "Acme",
            "title": "Backend Engineer",
            "location": "Central",
            "posted_date": "2026-09-01T00:00:00+00:00",
            "job_updated_at": "2026-09-02T00:00:00+00:00",
            "description_raw": (
                "<style>secret</style><p>Build Python APIs. Email a@example.com "
                "or call +852 2345 6789.</p>"
            ),
            "embedding_document_hash": "a" * 64,
            "embedding_dimensions": 3,
            "embedding_updated_at": "2026-09-02T01:00:00+00:00",
            "embedding": [1.0, 0.0, 0.0],
        },
        {
            "job_uuid": "00000000-0000-0000-0000-000000000002",
            "source_site": "ctgoodjobs",
            "source_job_id": "source-b",
            "company_id": "10000000-0000-0000-0000-000000000001",
            "company_name": "Acme",
            "title": "Backend Developer",
            "location": "Central",
            "posted_date": "2026-09-01T00:00:00+00:00",
            "job_updated_at": "2026-09-02T00:00:00+00:00",
            "description_raw": "建立 Python API。",
            "embedding_document_hash": "b" * 64,
            "embedding_dimensions": 3,
            "embedding_updated_at": "2026-09-02T01:00:00+00:00",
            "embedding": [0.99, 0.01, 0.0],
        },
    ]


def test_duplicate_corpus_export_is_minimized_hash_bound_and_deterministic(
    tmp_path: Path,
) -> None:
    artifact = build_duplicate_corpus_artifact(
        None,
        output_dir=tmp_path,
        limit=2,
        max_pairs=10,
        extracted_rows=_rows(),
        captured_at="2026-09-23T00:00:00+00:00",
        artifact_name="snapshot-a",
    )

    verified = verify_duplicate_corpus_artifact(artifact)

    assert verified["manifest"]["job_count"] == 2
    assert verified["manifest"]["candidate_pair_count"] == 1
    first = next(
        row for row in verified["jobs"] if row["source_identity"] == "jobsdb:source-a"
    )
    assert first["source_identity"] == "jobsdb:source-a"
    assert first["description_text"] == (
        "Build Python APIs. Email [redacted-email] or call [redacted-phone]."
    )
    assert "description_raw" not in first
    assert "vector" not in first["embedding"]
    assert first["description_sha256"]
    assert first["embedding"]["document_hash"] == "a" * 64
    assert verified["candidates"][0]["reference_status"] == "unreviewed"

    with pytest.raises(FileExistsError):
        build_duplicate_corpus_artifact(
            None,
            output_dir=tmp_path,
            limit=2,
            max_pairs=10,
            extracted_rows=_rows(),
            captured_at="2026-09-23T00:00:00+00:00",
            artifact_name="snapshot-a",
        )


def test_duplicate_corpus_verifier_rejects_tampering_and_extra_files(
    tmp_path: Path,
) -> None:
    artifact = build_duplicate_corpus_artifact(
        None,
        output_dir=tmp_path,
        limit=2,
        max_pairs=10,
        extracted_rows=_rows(),
        artifact_name="snapshot",
    )
    jobs_path = artifact / "jobs.jsonl"
    jobs_path.write_text(jobs_path.read_text() + "{}\n")
    with pytest.raises(DuplicateCorpusArtifactError, match="hash mismatch"):
        verify_duplicate_corpus_artifact(artifact)

    artifact = build_duplicate_corpus_artifact(
        None,
        output_dir=tmp_path,
        limit=2,
        max_pairs=10,
        extracted_rows=_rows(),
        artifact_name="snapshot-extra",
    )
    (artifact / "raw.json").write_text(json.dumps({"secret": True}))
    with pytest.raises(DuplicateCorpusArtifactError, match="file set"):
        verify_duplicate_corpus_artifact(artifact)


def test_duplicate_corpus_export_requires_postgresql_for_database_reads(
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    try:
        with pytest.raises(DuplicateCorpusArtifactError, match="PostgreSQL"):
            build_duplicate_corpus_artifact(
                engine,
                output_dir=tmp_path,
                limit=2,
                max_pairs=10,
            )
    finally:
        engine.dispose()
