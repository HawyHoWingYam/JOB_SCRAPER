from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts import report_database_integrity


def _sample_summary(status: str = "degraded") -> dict:
    return {
        "status": status,
        "generated_at": "2026-05-22T08:00:00+00:00",
        "issues": ["event_outbox has 2 retrying rows"],
        "schema": {
            "expected_tables": ["jobs", "event_outbox"],
            "observed_tables": ["jobs", "event_outbox"],
            "missing_expected_tables": [],
        },
        "advisory_findings": [
            {
                "id": "job_embeddings_embedding_ann_index",
                "severity": "advisory",
                "message": "job_embeddings.embedding has no ANN vector index",
            }
        ],
        "timestamp_mix": {"timezone_aware_count": 3, "timezone_naive_count": 2, "mixed": True},
        "staging": {
            "total_staged_rows": 5,
            "staged_published_rows": 2,
            "staged_unpublished_rows": 3,
            "published_jobs": 2,
            "staged_to_published_ratio": 2.5,
        },
        "detail_status_counts": {"pending": 3},
        "outbox": {
            "status_counts": {"pending": 2},
            "retrying_rows": 2,
            "max_attempts": 3,
            "oldest_pending_age_seconds": 120,
        },
        "taxonomy": {"all_seed_tables_empty": True, "empty_seed_tables": ["job_domains"]},
        "embeddings": {
            "total_jobs": 2,
            "current_embeddings": 1,
            "missing_current_embeddings": 1,
            "coverage_ratio": 0.5,
            "vector_index_present": False,
        },
        "enrichment_counter_drift": {"visible_nodes_without_distinct_job_count": 0},
        "scheduler": {"executions_missing_request_payload_snapshot": 1},
    }


def test_render_markdown_report_includes_database_sections():
    markdown = report_database_integrity.render_markdown_report(_sample_summary())

    assert "# Database Integrity Report" in markdown
    assert "Status: degraded" in markdown
    assert "Staged unpublished rows: 3" in markdown
    assert "Outbox retrying rows: 2" in markdown
    assert "Missing current embeddings: 1" in markdown
    assert "Advisory schema findings: 1" in markdown


def test_render_json_report_is_stable_pretty_json():
    rendered = report_database_integrity.render_json_report(_sample_summary(status="healthy"))

    parsed = json.loads(rendered)
    assert parsed["status"] == "healthy"
    assert rendered.endswith("\n")


def test_main_writes_output_and_fails_on_critical(monkeypatch):
    monkeypatch.setattr(
        report_database_integrity,
        "build_database_integrity_summary",
        lambda: _sample_summary(status="critical"),
    )

    with tempfile.TemporaryDirectory(dir=BACKEND_ROOT) as tmp_dir:
        output = Path(tmp_dir) / "integrity.md"
        exit_code = report_database_integrity.main(
            ["--format", "markdown", "--output", str(output), "--fail-on-critical"]
        )

        assert exit_code == 2
        assert "Status: critical" in output.read_text(encoding="utf-8")
