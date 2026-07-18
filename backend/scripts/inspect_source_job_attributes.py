#!/usr/bin/env python3
"""Read-only inspection of historical Source Job Attribute recoverability."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.job_intelligence.source_attributes import (  # noqa: E402
    SourceJobAttributeRebuildInspector,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("json", "human"),
        default="json",
        help="Deterministic output format (default: json)",
    )
    return parser


def _render_distribution(value: object) -> str:
    distribution = value if isinstance(value, Mapping) else {}
    return json.dumps(
        distribution,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def render_human_report(payload: Mapping[str, object]) -> str:
    lines = [
        "Source Job Attribute rebuild inspection (read-only)",
        f"jobs_inspected: {payload['jobs_inspected']}",
    ]
    raw_sources = payload.get("sources")
    sources = raw_sources if isinstance(raw_sources, list) else []
    for source in sorted(
        (item for item in sources if isinstance(item, Mapping)),
        key=lambda item: str(item.get("source_site") or ""),
    ):
        lines.append(
            f"{source['source_site']}: "
            f"inspected={source['jobs_inspected']} "
            f"recoverable={source['recoverable_jobs']} "
            f"unrecoverable={source['unrecoverable_jobs']} "
            f"multi_path={source['multi_path_jobs']} "
            "recoverable_paths="
            f"{source['recoverable_classification_paths']} "
            "recoverable_employment_labels="
            f"{source['recoverable_employment_labels']} "
            f"mapped_employment_labels={source['mapped_employment_labels']} "
            f"explicit_primary_paths={source['explicit_primary_paths']} "
            f"unknown_employment_labels={source['unknown_employment_labels']} "
            f"ambiguous={source['ambiguous_jobs']} "
            f"legacy_conflicts={source['conflicting_legacy_jobs']} "
            f"malformed={source['malformed_jobs']} "
            "missing_catalog_revision_paths="
            f"{source['missing_catalog_revision_paths']} "
            f"provenance_limited={source['provenance_limited_jobs']} "
            "evidence_sources="
            f"{_render_distribution(source.get('evidence_source_distribution'))} "
            "path_counts="
            f"{_render_distribution(source.get('path_count_distribution'))} "
            "unrecoverable_causes="
            f"{_render_distribution(source.get('unrecoverable_cause_distribution'))}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db = SessionLocal()
    try:
        report = SourceJobAttributeRebuildInspector(db).inspect()
        payload = report.to_payload()
        if args.format == "human":
            print(render_human_report(payload))
        else:
            print(
                json.dumps(
                    payload,
                    default=str,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
