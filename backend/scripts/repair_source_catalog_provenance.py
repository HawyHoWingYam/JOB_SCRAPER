#!/usr/bin/env python3
"""Report or explicitly repair missing Source Catalog provenance bindings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.job_intelligence.source_attributes import (  # noqa: E402
    SourceCatalogProvenanceRepair,
)


def _uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"invalid UUID: {value}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect Source Catalog coverage before an operator-approved "
            "provenance repair."
        )
    )
    parser.add_argument(
        "--source-site",
        default="offertoday",
        choices=("jobsdb", "ctgoodjobs", "offertoday"),
    )
    parser.add_argument("--revision-id", required=True, type=_uuid)
    parser.add_argument(
        "--expected-fingerprint",
        help="Required with --apply; copy exactly from the reviewed report.",
    )
    parser.add_argument("--job-id", action="append", type=_uuid, default=[])
    parser.add_argument(
        "--pending-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Scope to non-deleted, unenriched Jobs with a Source projection (default).",
    )
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply only after the report passes all fences.",
    )
    parser.add_argument(
        "--confirm-repair",
        action="store_true",
        help="Required acknowledgement for --apply; this command never prompts.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.apply and not args.confirm_repair:
        raise SystemExit("--apply requires --confirm-repair")
    if args.apply and not args.expected_fingerprint:
        raise SystemExit("--apply requires --expected-fingerprint")

    db = SessionLocal()
    try:
        service = SourceCatalogProvenanceRepair(db)
        report = service.inspect(
            source_site=args.source_site,
            revision_id=args.revision_id,
            job_ids=tuple(args.job_id) or None,
            pending_only=args.pending_only,
        )
        payload: dict[str, object] = {"report": report.to_payload()}
        if args.apply:
            result = service.apply(
                report,
                expected_revision_id=args.revision_id,
                expected_fingerprint=args.expected_fingerprint,
                batch_size=args.batch_size,
            )
            payload["apply"] = result.to_payload()
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
