#!/usr/bin/env python3
"""Operator CLI for Crawl Control cutover preflight and approved reset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings  # noqa: E402
from app.crawl_control.cutover import (  # noqa: E402
    RESET_CONFIRMATION,
    CrawlControlCutover,
    CrawlControlCutoverError,
)
from app.job_intelligence.cutover.artifacts import (  # noqa: E402
    ManifestIntegrityError,
    VerifiedArtifactStore,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preflight or execute the versioned Crawl Control reset"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    dry_run = commands.add_parser("dry-run", help="Inspect without mutating")
    dry_run.add_argument("--backup-id", required=True)
    dry_run.add_argument("--confirm-backup", action="store_true")
    dry_run.add_argument("--output", type=Path, required=True)

    reset = commands.add_parser("reset", help="Run the approved atomic reset")
    reset.add_argument("--report", type=Path, required=True)
    reset.add_argument("--backup-id", required=True)
    reset.add_argument("--confirm-backup", action="store_true")
    reset.add_argument(
        "--confirm-reset",
        metavar=RESET_CONFIRMATION,
        required=True,
        help=f"must equal {RESET_CONFIRMATION}",
    )
    reset.add_argument("--output", type=Path, required=True)

    rehearsal = commands.add_parser(
        "backup-rehearsal",
        help="Dump and restore only a disposable *_test source database",
    )
    rehearsal.add_argument("--restore-database-url", required=True)
    rehearsal.add_argument("--backup-id", required=True)
    rehearsal.add_argument("--checkpoint-dir", type=Path, required=True)
    rehearsal.add_argument("--output", type=Path, required=True)
    return parser


def _write_result(output: Path, payload: dict[str, object]) -> str:
    payload_hash = VerifiedArtifactStore().write(output, payload)
    print(
        json.dumps(
            {"artifact": str(output), "payload_hash": payload_hash},
            sort_keys=True,
        )
    )
    return payload_hash


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    cutover = CrawlControlCutover(engine)
    try:
        if args.command == "dry-run":
            report = cutover.dry_run(
                backup_id=args.backup_id,
                backup_acknowledged=args.confirm_backup,
            )
            _write_result(args.output, report.artifact_payload())
            return 0 if report.ready else 2

        if args.command == "reset":
            reviewed = VerifiedArtifactStore().read(args.report)
            if reviewed.get("mode") != "dry-run" or not isinstance(
                reviewed.get("report_hash"), str
            ):
                raise ManifestIntegrityError(
                    "Reviewed artifact is not a Crawl Control dry-run report"
                )
            if reviewed.get("backup_id") != args.backup_id:
                raise CrawlControlCutoverError(
                    "CUTOVER_BACKUP_ID_MISMATCH",
                    "Reset backup ID does not match the reviewed report",
                )
            result = cutover.execute(
                backup_id=args.backup_id,
                backup_acknowledged=args.confirm_backup,
                expected_report_hash=str(reviewed["report_hash"]),
                confirmation=args.confirm_reset,
            )
            _write_result(args.output, result.payload())
            return 0

        backup_result = cutover.rehearse_backup(
            restore_database_url=args.restore_database_url,
            backup_id=args.backup_id,
            checkpoint_dir=args.checkpoint_dir,
        )
        _write_result(args.output, backup_result.payload())
        return 0
    except (CrawlControlCutoverError, ManifestIntegrityError, ValueError) as exc:
        payload: dict[str, Any] = {
            "error": getattr(exc, "code", type(exc).__name__),
            "message": str(exc),
        }
        details = getattr(exc, "details", None)
        if details:
            payload["details"] = details
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
