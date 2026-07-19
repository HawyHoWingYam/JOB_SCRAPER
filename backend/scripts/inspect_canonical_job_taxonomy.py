#!/usr/bin/env python3
"""Read-only Canonical Job Taxonomy rebuild inspection."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import sys
from uuid import UUID


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.job_intelligence.canonical_taxonomy import (  # noqa: E402
    CanonicalTaxonomyRebuildInspector,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("json", "human"),
        default="json",
        help="Deterministic output format (default: json)",
    )
    parser.add_argument(
        "--job-id",
        action="append",
        type=UUID,
        default=None,
        help="Restrict inspection to a Job UUID; repeatable",
    )
    return parser


def _render(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def render_human_report(payload: Mapping[str, object]) -> str:
    taxonomy_revision = payload.get("taxonomy_revision")
    mapping_revision = payload.get("mapping_revision")
    lines = [
        "Canonical Job Taxonomy rebuild inspection (read-only)",
        f"jobs_inspected: {payload['jobs_inspected']}",
        f"taxonomy_revision: {_render(taxonomy_revision)}",
        f"mapping_revision: {_render(mapping_revision)}",
        f"job_states: {_render(payload.get('job_states'))}",
        f"accepted_by_method: {_render(payload.get('accepted_by_method'))}",
        f"review_by_status: {_render(payload.get('review_by_status'))}",
        f"review_by_reason: {_render(payload.get('review_by_reason'))}",
        f"mapping_evidence: {_render(payload.get('mapping_evidence'))}",
        f"legacy_comparison: {_render(payload.get('legacy_comparison'))}",
        "classifier_provenance: " f"{_render(payload.get('classifier_provenance'))}",
        "source_attribute_rebuild: "
        f"{_render(payload.get('source_attribute_rebuild'))}",
        "unrecoverable_parser_evidence: "
        f"{_render(payload.get('unrecoverable_parser_evidence'))}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db = SessionLocal()
    try:
        report = CanonicalTaxonomyRebuildInspector(db).inspect(args.job_id)
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
