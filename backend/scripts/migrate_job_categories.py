#!/usr/bin/env python3
"""Backfill canonical job taxonomy using the governed source-classification flow."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import SessionLocal
from scripts import govern_job_taxonomy


def audit_job_categories(db: Any = None) -> dict[str, int]:
    """Return a read-only snapshot of current job taxonomy coverage."""
    owns_session = db is None
    session = db or SessionLocal()
    try:
        return govern_job_taxonomy.audit_job_taxonomy(session)
    finally:
        if owns_session:
            session.close()


def migrate_job_categories(
    db: Any = None,
    *,
    execute: bool = False,
) -> dict[str, Any]:
    """Run governed job taxonomy backfill with execute/dry-run semantics."""
    owns_session = db is None
    session = db or SessionLocal()
    try:
        return govern_job_taxonomy.apply_job_taxonomy_governance(
            session,
            execute=execute,
        )
    finally:
        if owns_session:
            session.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("audit", help="Read-only canonical taxonomy coverage audit")

    apply_parser = subparsers.add_parser("apply", help="Backfill missing canonical job taxonomy")
    mode = apply_parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="Persist canonical taxonomy backfill")
    mode.add_argument("--dry-run", action="store_true", help="Simulate without committing")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "audit":
        report = audit_job_categories()
    else:
        report = migrate_job_categories(execute=bool(args.execute))
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
