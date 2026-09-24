from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.services.jev_evaluation_corpus import (
    RealCorpusExportError,
    build_real_corpus_artifact,
    verify_real_corpus_artifact,
)


def test_real_corpus_export_rejects_non_postgresql_database(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    try:
        with pytest.raises(RealCorpusExportError, match="PostgreSQL"):
            build_real_corpus_artifact(engine, output_dir=tmp_path, limit=10)
    finally:
        engine.dispose()


def test_real_corpus_artifact_is_bounded_minimal_and_hash_verified(
    tmp_path: Path,
) -> None:
    rows = [
        {
            "job_uuid": "00000000-0000-0000-0000-000000000001",
            "source_site": "jobsdb",
            "source_job_id": "source-1",
            "compatibility_job_id": "jobsdb:source-1",
            "company_id": "00000000-0000-0000-0000-000000000010",
            "title": "Backend 工程師",
            "description_raw": "<p>Contact a@example.com.</p><p>必須熟悉 Python。</p>",
            "job_updated_at": "2026-09-01T00:00:00+00:00",
            "mention_id": "00000000-0000-0000-0000-000000000020",
            "raw_name": "Python",
            "resolution": "match_existing",
            "skill_code": "backend.python",
            "candidate_id": None,
            "mention_evidence_hash": "a" * 64,
            "mention_provenance": {"method": "constrained-ai-extraction"},
        },
        {
            "job_uuid": "00000000-0000-0000-0000-000000000002",
            "source_site": "ctgoodjobs",
            "source_job_id": "source-2",
            "compatibility_job_id": "ctgoodjobs:source-2",
            "company_id": None,
            "title": "Engineer",
            "description_raw": "Experience with New Tool is preferred.",
            "job_updated_at": "2026-09-02T00:00:00+00:00",
            "mention_id": "00000000-0000-0000-0000-000000000021",
            "raw_name": "New Tool",
            "resolution": "candidate",
            "skill_code": None,
            "candidate_id": "00000000-0000-0000-0000-000000000030",
            "mention_evidence_hash": "b" * 64,
            "mention_provenance": {"method": "constrained-ai-extraction"},
        },
    ]
    taxonomy = [
        {"code": "backend.python", "labels": {"en": "Python"}, "aliases": ["Py"]}
    ]

    artifact = build_real_corpus_artifact(
        None,
        output_dir=tmp_path,
        limit=10,
        extracted_rows=rows,
        taxonomy_snapshot=taxonomy,
        captured_at="2026-09-23T00:00:00+00:00",
    )
    verified = verify_real_corpus_artifact(artifact)

    assert verified["manifest"]["row_count"] == 2
    row = verified["rows"][0]
    assert row["language"] == "mixed"
    assert row["reference_status"] == "weak_reference"
    assert row["reference_provenance"] == "existing_ai_projection"
    assert row["description_text"] == "Contact [redacted-email]. 必須熟悉 Python。"
    assert row["evaluation_split"] in {"development", "held_out"}
    assert row["group_id"].startswith("connected:")
    assert len(row["content_fingerprint_sha256"]) == 64
    assert "description_raw" not in row
    assert "raw_data" not in row
    assert len(row["description_sha256"]) == 64
    assert len(row["taxonomy_snapshot_sha256"]) == 64
    assert verified["rows"][1]["decision_kind"] == "candidate_recommendation"

    rows_path = artifact / "cases.jsonl"
    rows_path.write_text(rows_path.read_text().replace("Python", "Java", 1))
    with pytest.raises(RealCorpusExportError, match="hash"):
        verify_real_corpus_artifact(artifact)


def test_real_corpus_groups_connected_company_and_duplicate_descriptions(
    tmp_path: Path,
) -> None:
    base = {
        "compatibility_job_id": None,
        "title": "Engineer",
        "resolution": "match_existing",
        "skill_code": "backend.python",
        "candidate_id": None,
        "mention_evidence_hash": "a" * 64,
        "mention_provenance": {},
    }
    rows = [
        {
            **base,
            "job_uuid": f"00000000-0000-0000-0000-00000000000{index}",
            "source_site": "jobsdb",
            "source_job_id": f"source-{index}",
            "company_id": company_id,
            "description_raw": description,
            "job_updated_at": f"2026-09-0{index}T00:00:00+00:00",
            "mention_id": f"00000000-0000-0000-0000-00000000002{index}",
            "raw_name": "Python",
        }
        for index, company_id, description in (
            (1, "company-a", "Same description"),
            (2, "company-a", "Different description"),
            (3, "company-b", "Same description"),
            (4, "company-c", "Independent description"),
        )
    ]

    artifact = build_real_corpus_artifact(
        None,
        output_dir=tmp_path,
        limit=10,
        extracted_rows=rows,
        taxonomy_snapshot=[],
        captured_at="2026-09-23T00:00:00+00:00",
    )
    exported = verify_real_corpus_artifact(artifact)["rows"]

    assert len({row["group_id"] for row in exported[:3]}) == 1
    splits_by_group = {}
    for row in exported:
        splits_by_group.setdefault(row["group_id"], set()).add(row["evaluation_split"])
    assert all(len(splits) == 1 for splits in splits_by_group.values())
    assert {row["evaluation_split"] for row in exported} == {
        "development",
        "held_out",
    }
