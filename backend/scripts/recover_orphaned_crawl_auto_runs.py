#!/usr/bin/env python3
"""Recover crawl-auto enrichment runs that were created but never requested."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Literal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import SessionLocal
from app.messaging.outbox_publisher import OutboxPublisher
from app.models.enrichment_run import EnrichmentRun
from app.models.event_outbox import EventOutbox
from app.services.enrichment_run_service import EnrichmentRunService

ORPHANED_CANCEL_MESSAGE = (
    "stale crawl_auto run cancelled: no enrichment.run.requested event was recorded; "
    "jobs remain eligible for manual pending enrichment"
)


def _has_run_request(db, run_id: str) -> bool:
    return (
        db.query(EventOutbox.id)
        .filter(
            EventOutbox.aggregate_type == "enrichment_run",
            EventOutbox.aggregate_id == run_id,
            EventOutbox.event_type == "enrichment.run.requested",
        )
        .first()
        is not None
    )


def recover_orphaned_crawl_auto_runs(
    db,
    *,
    action: Literal["preview", "request", "cancel"] = "preview",
    limit: int = 20,
    publish_outbox: bool = False,
    publisher: OutboxPublisher | None = None,
) -> dict[str, Any]:
    service = EnrichmentRunService(db)
    runs = (
        db.query(EnrichmentRun)
        .filter(
            EnrichmentRun.source_type == "crawl_auto",
            EnrichmentRun.status == "pending",
            EnrichmentRun.started_at.is_(None),
        )
        .order_by(EnrichmentRun.created_at.asc(), EnrichmentRun.id.asc())
        .limit(max(int(limit or 20), 1))
        .all()
    )

    summary: dict[str, Any] = {
        "mode": action,
        "selected_count": len(runs),
        "requested_count": 0,
        "cancelled_count": 0,
        "skipped_count": 0,
        "published_count": 0,
        "failed_publish_count": 0,
        "runs": [],
    }

    for run in runs:
        row = {
            "run_id": run.id,
            "trigger_crawl_job_id": str(run.trigger_crawl_job_id) if run.trigger_crawl_job_id else None,
            "total_items": int(run.total_items or 0),
            "pending_items": int(run.pending_items or 0),
            "action": "preview",
        }

        if _has_run_request(db, run.id):
            row["action"] = "skipped"
            row["reason"] = "execution_request_already_recorded"
            summary["skipped_count"] += 1
            summary["runs"].append(row)
            continue

        if action == "request":
            requested = False
            if run.trigger_crawl_job_id:
                requested = service.request_crawl_auto_run_if_ready(str(run.trigger_crawl_job_id))
            row["action"] = "requested" if requested else "skipped"
            if requested:
                summary["requested_count"] += 1
            else:
                row["reason"] = "run_not_ready"
                summary["skipped_count"] += 1
        elif action == "cancel":
            service.cancel_run(run.id, ORPHANED_CANCEL_MESSAGE)
            row["action"] = "cancelled"
            summary["cancelled_count"] += 1

        summary["runs"].append(row)

    if action == "preview":
        db.rollback()
    else:
        db.commit()
        if publish_outbox:
            publish_result = (publisher or OutboxPublisher()).publish_pending_batch(
                db,
                limit=max(summary["requested_count"], 1),
            )
            summary["published_count"] = publish_result.published_count
            summary["failed_publish_count"] = publish_result.failed_count

    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20, help="Maximum orphaned crawl-auto runs to inspect")
    parser.add_argument(
        "--action",
        choices=("preview", "request", "cancel"),
        default="preview",
        help="Preview, enqueue ready runs, or cancel stale unrequested runs",
    )
    parser.add_argument("--publish-outbox", action="store_true", help="Publish created outbox rows immediately")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = SessionLocal()
    try:
        summary = recover_orphaned_crawl_auto_runs(
            db,
            action=args.action,
            limit=args.limit,
            publish_outbox=args.publish_outbox,
        )
    finally:
        db.close()

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"Mode: {summary['mode']}")
        print(f"Selected orphaned crawl-auto runs: {summary['selected_count']}")
        print(f"Execution requests queued: {summary['requested_count']}")
        print(f"Runs cancelled: {summary['cancelled_count']}")
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
