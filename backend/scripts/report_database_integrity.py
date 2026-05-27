#!/usr/bin/env python3
"""Generate a read-only database integrity report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.database_integrity_service import build_database_integrity_summary


def render_json_report(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True) + "\n"


def _format_ratio(value: Any) -> str:
    return "n/a" if value is None else str(value)


def render_markdown_report(summary: dict[str, Any]) -> str:
    schema = summary.get("schema") or {}
    staging = summary.get("staging") or {}
    duplicates = summary.get("duplicates") or {}
    outbox = summary.get("outbox") or {}
    taxonomy = summary.get("taxonomy") or {}
    embeddings = summary.get("embeddings") or {}
    timestamp_mix = summary.get("timestamp_mix") or {}
    scheduler = summary.get("scheduler") or {}
    drift = summary.get("enrichment_counter_drift") or {}
    advisory_findings = list(summary.get("advisory_findings") or [])
    issues = list(summary.get("issues") or [])

    lines = [
        "# Database Integrity Report",
        "",
        f"- Generated at: {summary.get('generated_at')}",
        f"- Status: {summary.get('status', 'unknown')}",
        f"- Expected tables: {len(schema.get('expected_tables') or [])}",
        f"- Observed tables: {len(schema.get('observed_tables') or [])}",
        f"- Missing expected tables: {len(schema.get('missing_expected_tables') or [])}",
        f"- Advisory schema findings: {len(advisory_findings)}",
        "",
        "## Issues",
        "",
    ]
    if issues:
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Schema Drift",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Expected tables | {len(schema.get('expected_tables') or [])} |",
            f"| Observed tables | {len(schema.get('observed_tables') or [])} |",
            f"| Missing expected tables | {len(schema.get('missing_expected_tables') or [])} |",
            f"| Timezone-aware timestamp columns | {timestamp_mix.get('timezone_aware_count', 0)} |",
            f"| Timezone-naive timestamp columns | {timestamp_mix.get('timezone_naive_count', 0)} |",
        "",
        "## Operational Metrics",
        "",
        f"- Staged unpublished rows: {staging.get('staged_unpublished_rows', 0)}",
        f"- Duplicate job source keys: {duplicates.get('jobs_source_key_duplicate_groups', 0)}",
        f"- Duplicate staged listing keys: {duplicates.get('crawl_job_listings_source_key_duplicate_groups', 0)}",
        f"- Outbox retrying rows: {outbox.get('retrying_rows', 0)}",
        f"- Missing current embeddings: {embeddings.get('missing_current_embeddings', 0)}",
        "",
        "| Metric | Value |",
            "| --- | ---: |",
            f"| Total staged rows | {staging.get('total_staged_rows', 0)} |",
            f"| Staged published rows | {staging.get('staged_published_rows', 0)} |",
            f"| Staged unpublished rows | {staging.get('staged_unpublished_rows', 0)} |",
            f"| Duplicate job source key groups | {duplicates.get('jobs_source_key_duplicate_groups', 0)} |",
            f"| Duplicate staged listing key groups | {duplicates.get('crawl_job_listings_source_key_duplicate_groups', 0)} |",
            f"| Published jobs | {staging.get('published_jobs', 0)} |",
            f"| Staged-to-published ratio | {_format_ratio(staging.get('staged_to_published_ratio'))} |",
            f"| Outbox retrying rows | {outbox.get('retrying_rows', 0)} |",
            f"| Oldest outbox pending age seconds | {outbox.get('oldest_pending_age_seconds', 0)} |",
            f"| Taxonomy seed tables empty | {taxonomy.get('all_seed_tables_empty', False)} |",
            f"| Missing current embeddings | {embeddings.get('missing_current_embeddings', 0)} |",
            f"| Vector index present | {embeddings.get('vector_index_present', False)} |",
            (
                "| Visible taxonomy nodes without distinct-job count | "
                f"{drift.get('visible_nodes_without_distinct_job_count', 0)} |"
            ),
            (
                "| Schedule executions missing request snapshots | "
                f"{scheduler.get('executions_missing_request_payload_snapshot', 0)} |"
            ),
            "",
            "## Detail Status Counts",
            "",
        ]
    )
    detail_counts = summary.get("detail_status_counts") or {}
    if detail_counts:
        lines.extend(f"- `{status}`: {count}" for status, count in sorted(detail_counts.items()))
    else:
        lines.append("- None")

    lines.extend(["", "## Outbox Status Counts", ""])
    outbox_counts = outbox.get("status_counts") or {}
    if outbox_counts:
        lines.extend(f"- `{status}`: {count}" for status, count in sorted(outbox_counts.items()))
    else:
        lines.append("- None")

    lines.extend(["", "## Advisory Findings", ""])
    if advisory_findings:
        for finding in advisory_findings:
            lines.append(f"- `{finding.get('id')}`: {finding.get('message')}")
    else:
        lines.append("- None")

    lines.append("")
    return "\n".join(lines)


def build_session_factory_from_database_url(database_url: str):
    engine = create_engine(database_url)
    return sessionmaker(bind=engine)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--database-url", type=str, default=None)
    parser.add_argument("--fail-on-critical", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary_kwargs: dict[str, Any] = {}
    if args.database_url:
        summary_kwargs["session_factory"] = build_session_factory_from_database_url(args.database_url)
    summary = build_database_integrity_summary(**summary_kwargs)
    rendered = render_json_report(summary) if args.format == "json" else render_markdown_report(summary)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

    if args.fail_on_critical and summary.get("status") == "critical":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
