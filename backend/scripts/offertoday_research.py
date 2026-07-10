#!/usr/bin/env python3
"""Offline OfferToday research baseline, export, and conservation tools."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

BACKEND = str(Path(__file__).resolve().parents[1])
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from app.database import SessionLocal  # noqa: E402
from app.repositories.offertoday_research_repository import (  # noqa: E402
    OfferTodayResearchRepository,
)
from app.sources.offertoday.listing_runner import (  # noqa: E402
    listing_observation_to_payload,
)
from app.sources.offertoday.research.artifacts import (  # noqa: E402
    capture_research_provenance,
    export_research_artifact,
    verify_research_artifact,
)
from app.sources.offertoday.research.baseline import (  # noqa: E402
    build_baseline_snapshot,
    build_run_start_inventory,
)
from app.sources.offertoday.research.conservation import (  # noqa: E402
    replay_research_conservation,
)
from app.utils.time import utc_now  # noqa: E402


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INCOMPLETE = 3
EXIT_HARD_STOP = 4
EXIT_EVIDENCE_FAILURE = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline OfferToday research tools")
    commands = parser.add_subparsers(dest="command", required=True)

    baseline = commands.add_parser("baseline")
    baseline.add_argument("--run-id", default=None)
    _add_export_roots(baseline)

    conservation = commands.add_parser("conservation")
    conservation.add_argument("--crawl-job-id", required=True)
    _add_export_roots(conservation)

    export_run = commands.add_parser("export-run")
    export_run.add_argument("--crawl-job-id", required=True)
    _add_export_roots(export_run)

    verify = commands.add_parser("verify-artifact")
    verify.add_argument("--artifact", type=Path, required=True)
    return parser


def _add_export_roots(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )


def _event_dict(event: Any) -> dict[str, Any]:
    created_at = event.created_at
    return {
        "sequence_no": int(event.sequence_no),
        "event_type": str(event.event_type),
        "payload": listing_observation_to_payload(event.payload or {}),
        "emitted_by": event.emitted_by,
        "created_at": (
            created_at.isoformat()
            if hasattr(created_at, "isoformat")
            else str(created_at)
        ),
    }


def _ordered_events(events: list[Any]) -> list[dict[str, Any]]:
    return [
        _event_dict(event)
        for event in sorted(events, key=lambda item: int(item.sequence_no))
    ]


def _print_json(value: dict[str, Any], *, stream=None) -> None:
    print(
        json.dumps(value, ensure_ascii=True, sort_keys=True),
        file=stream,
    )


def main(
    argv: list[str] | None = None,
    *,
    session_factory=SessionLocal,
    repository: OfferTodayResearchRepository | None = None,
    browser_factory=None,
    provenance_provider=capture_research_provenance,
) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "verify-artifact":
        try:
            result = verify_research_artifact(args.artifact)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            _print_json({"error": str(exc)}, stream=sys.stderr)
            return EXIT_EVIDENCE_FAILURE
        else:
            _print_json(asdict(result))
            return EXIT_OK if result.valid else EXIT_EVIDENCE_FAILURE

    research_repository = repository or OfferTodayResearchRepository()
    db = session_factory()
    try:
        staged = research_repository.list_staged_snapshots(db)
        published = research_repository.list_published_snapshots(db)
        recent_runs = research_repository.list_recent_crawl_jobs(db)

        snapshot = None
        inventory = None
        if args.command == "baseline":
            run_id = str(UUID(args.run_id)) if args.run_id else str(uuid4())
            snapshot = build_baseline_snapshot(listings=staged, jobs=published)
            inventory = build_run_start_inventory(listings=staged, jobs=published)
            events = [
                {
                    "sequence_no": 1,
                    "event_type": "research.baseline",
                    "payload": {
                        "snapshot": asdict(snapshot),
                        "run_start_inventory": inventory.to_dict(),
                        "recent_crawl_jobs": [
                            asdict(item) for item in recent_runs
                        ],
                    },
                }
            ]
            metadata = {
                "experiment": "foundation-baseline",
                "data_hash": snapshot.data_hash,
            }
            valid = True
        else:
            crawl_job_id = UUID(args.crawl_job_id)
            crawl_job = research_repository.get_crawl_job(db, crawl_job_id)
            if crawl_job is None:
                raise ValueError(f"Crawl job not found: {crawl_job_id}")
            db_events = research_repository.list_research_events(db, crawl_job_id)
            events = _ordered_events(db_events)
            run_id = str(crawl_job_id)
            metadata = {
                "experiment": (
                    "conservation"
                    if args.command == "conservation"
                    else "export-run"
                ),
                "crawl_job_id": run_id,
            }
            valid = True
            if args.command == "conservation":
                report = replay_research_conservation(
                    crawl_job=crawl_job,
                    events=events,
                    listings=staged,
                    jobs=published,
                )
                next_sequence_no = max(
                    (event["sequence_no"] for event in events),
                    default=0,
                ) + 1
                events.append(
                    {
                        "sequence_no": next_sequence_no,
                        "event_type": "research.conservation",
                        "payload": listing_observation_to_payload(report),
                    }
                )
                metadata["conservation_valid"] = report.is_valid
                valid = report.is_valid

        latest_run = recent_runs[0] if recent_runs else None
        runtime_context = {
            "command": args.command,
            "latest_request_payload": (
                latest_run.request_payload if latest_run else {}
            ),
            "latest_metrics": latest_run.metrics if latest_run else {},
        }
        provenance = provenance_provider(
            repo_root=args.repo_root.resolve(),
            runtime_context=runtime_context,
            captured_at=utc_now().isoformat(),
        )
        artifact_dir = export_research_artifact(
            root=args.artifact_root,
            run_id=run_id,
            metadata=metadata,
            events=events,
            provenance=provenance,
        )
        output = {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "valid": valid,
        }
        if snapshot is not None and inventory is not None:
            output.update(asdict(snapshot))
            output["inventory_data_hash"] = inventory.data_hash
        _print_json(output)
        return EXIT_OK if valid else EXIT_EVIDENCE_FAILURE
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
