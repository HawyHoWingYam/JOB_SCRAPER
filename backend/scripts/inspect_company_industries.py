#!/usr/bin/env python3
"""Dry-run Company Industry pollution and rebuild inspection."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import sys
from uuid import UUID


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.job_intelligence.company_industry import (  # noqa: E402
    CompanyIndustryRebuildInspector,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("json", "human"),
        default="json",
    )
    parser.add_argument(
        "--company-id",
        action="append",
        type=UUID,
        default=None,
        help="Restrict the dry-run to one Company UUID; repeatable",
    )
    return parser


def render_human_report(payload: Mapping[str, object]) -> str:
    def encoded(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    return "\n".join(
        (
            "Company Industry rebuild inspection (dry-run)",
            f"companies_inspected: {payload['companies_inspected']}",
            f"active_revision_id: {payload['active_revision_id']}",
            f"evidence_states: {encoded(payload['evidence_states'])}",
            f"auto_mappable: {payload['auto_mappable']}",
            f"review_required: {payload['review_required']}",
            f"primary_evidence: {payload['primary_evidence']}",
            f"company_ids_by_state: {encoded(payload['company_ids_by_state'])}",
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db = SessionLocal()
    try:
        payload = (
            CompanyIndustryRebuildInspector(db).inspect(args.company_id).to_payload()
        )
        if args.format == "human":
            print(render_human_report(payload))
        else:
            print(
                json.dumps(
                    payload,
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
