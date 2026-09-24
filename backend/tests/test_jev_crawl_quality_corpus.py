from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.services.jev_crawl_quality_corpus import (
    CrawlQualityCorpusError,
    build_crawl_quality_corpus,
    verify_crawl_quality_corpus,
)


def test_corpus_is_minimized_hash_bound_and_refuses_overwrite(tmp_path: Path) -> None:
    rows = [
        {
            "listing_id": "listing-1",
            "crawl_job_id": "crawl-1",
            "job_uuid": "job-1",
            "source_site": "jobsdb",
            "source_job_id": "source-1",
            "detail_status": "completed",
            "detail_attempts": 1,
            "detail_error_message": None,
            "title": "Engineer",
            "description_raw": "<p>Build systems. Contact a@example.com or +852 2345 6789.</p>",
            "detail_payload": {"description": "secret raw copy"},
            "updated_at": "2026-09-23T00:00:00+00:00",
        }
    ]
    artifact = build_crawl_quality_corpus(
        None,
        output_dir=tmp_path,
        limit=10,
        extracted_rows=rows,
        artifact_name="snapshot",
        captured_at="2026-09-23T00:00:00+00:00",
    )
    verified = verify_crawl_quality_corpus(artifact)
    row = verified["rows"][0]
    assert (
        row["evidence_excerpt"]
        == "Build systems. Contact [redacted-email] or [redacted-phone]."
    )
    assert "detail_payload" not in row
    assert "description_raw" not in row
    assert row["payload_sha256"]
    with pytest.raises(FileExistsError):
        build_crawl_quality_corpus(
            None,
            output_dir=tmp_path,
            limit=10,
            extracted_rows=rows,
            artifact_name="snapshot",
        )


def test_corpus_requires_postgresql_for_database_reads(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    try:
        with pytest.raises(CrawlQualityCorpusError, match="PostgreSQL"):
            build_crawl_quality_corpus(engine, output_dir=tmp_path, limit=10)
    finally:
        engine.dispose()
