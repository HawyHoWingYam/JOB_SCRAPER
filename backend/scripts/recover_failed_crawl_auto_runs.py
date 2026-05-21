#!/usr/bin/env python3
"""Create retry enrichment runs from failed crawl-auto enrichment runs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import SessionLocal
from app.messaging.outbox_publisher import OutboxPublisher
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.services.enrichment_run_service import EnrichmentRunService

RECOVERABLE_RUN_STATUSES = ("failed", "completed_with_failures")


def _failed_item_count(db, run_id: str) -> int:
    return (
        db.query(EnrichmentRunItem)
        .filter(
            EnrichmentRunItem.run_id == run_id,
            EnrichmentRunItem.status == "failed",
        )
        .count()
    )


def recover_failed_crawl_auto_runs(
    db,
    *,
    limit: int = 20,
    execute: bool = False,
    publish_outbox: bool = False,
    publisher: OutboxPublisher | None = None,
) -> dict[str, Any]:
    service = EnrichmentRunService(db)
    failed_runs = (
        db.query(EnrichmentRun)
        .filter(
            EnrichmentRun.source_type == "crawl_auto",
            EnrichmentRun.status.in_(RECOVERABLE_RUN_STATUSES),
        )
        .order_by(EnrichmentRun.created_at.asc(), EnrichmentRun.id.asc())
        .limit(max(int(limit or 20), 1))
        .all()
    )

    summary: dict[str, Any] = {
        "mode": "execute" if execute else "dry_run",
        "selected_count": len(failed_runs),
        "created_count": 0,
        "requested_count": 0,
        "skipped_count": 0,
        "published_count": 0,
        "failed_publish_count": 0,
        "runs": [],
    }

    for run in failed_runs:
        failed_count = _failed_item_count(db, run.id)
        row = {
            "source_run_id": run.id,
            "trigger_crawl_job_id": str(run.trigger_crawl_job_id) if run.trigger_crawl_job_id else None,
            "status": run.status,
            "failed_items": failed_count,
            "action": "preview",
        }
        if failed_count <= 0:
            row["action"] = "skipped"
            row["reason"] = "no_failed_items"
            summary["skipped_count"] += 1
            summary["runs"].append(row)
            continue

        if execute:
            try:
                retry_run = service.create_retry_run_from_failed_items(run.id)
            except ValueError as exc:
                row["action"] = "skipped"
                row["reason"] = str(exc)
                summary["skipped_count"] += 1
            else:
                requested = service.request_run_execution(
                    retry_run.id,
                    source_service="enrichment-recovery",
                )
                row["action"] = "created"
                row["retry_run_id"] = retry_run.id
                row["requested"] = requested
                summary["created_count"] += 1
                if requested:
                    summary["requested_count"] += 1
        summary["runs"].append(row)

    if execute:
        db.commit()
        if publish_outbox:
            publish_result = (publisher or OutboxPublisher()).publish_pending_batch(
                db,
                limit=max(summary["requested_count"], 1),
            )
            summary["published_count"] = publish_result.published_count
            summary["failed_publish_count"] = publish_result.failed_count
    else:
        db.rollback()

    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20, help="Maximum failed crawl-auto runs to inspect")
    parser.add_argument("--execute", action="store_true", help="Create retry runs and enqueue execution requests")
    parser.add_argument("--publish-outbox", action="store_true", help="Publish created outbox rows immediately")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = SessionLocal()
    try:
        summary = recover_failed_crawl_auto_runs(
            db,
            limit=args.limit,
            execute=args.execute,
            publish_outbox=args.publish_outbox,
        )
    finally:
        db.close()

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"Mode: {summary['mode']}")
        print(f"Selected failed crawl-auto runs: {summary['selected_count']}")
        print(f"Retry runs created: {summary['created_count']}")
        print(f"Execution requests queued: {summary['requested_count']}")
        print(f"Skipped: {summary['skipped_count']}")
        if summary["published_count"] or summary["failed_publish_count"]:
            print(
                f"Outbox publish: {summary['published_count']} published, "
                f"{summary['failed_publish_count']} failed"
            )
        for row in summary["runs"]:
            print(json.dumps(row, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
