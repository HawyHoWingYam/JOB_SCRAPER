#!/usr/bin/env python3
"""Explicit Source Catalog discovery, validation, publication, and rollback CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.repositories.source_catalog_repository import SourceCatalogRepository  # noqa: E402
from app.source_catalog.validation import CatalogValidationCoordinator  # noqa: E402
from app.services.source_catalog_service import (  # noqa: E402
    SourceCatalogService,
    build_production_source_catalog_adapters,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser("discover")
    discover.add_argument("--source", required=True, choices=["jobsdb", "ctgoodjobs", "offertoday"])

    validate = subparsers.add_parser("validate")
    validate.add_argument("--candidate-id", required=True)
    validate.add_argument("--run", action="store_true", help="Execute queued rows in this process")
    validate.add_argument("--worker-id", default="source-catalog-admin")

    publish = subparsers.add_parser("publish")
    publish.add_argument("--candidate-id", required=True)
    publish.add_argument("--review-token", required=True)
    publish.add_argument("--actor", required=True)
    publish.add_argument("--confirm-fingerprint", required=True)
    publish.add_argument("--confirm-publish", action="store_true", required=True)

    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--revision-id", required=True)
    rollback.add_argument("--review-token", required=True)
    rollback.add_argument("--actor", required=True)
    rollback.add_argument("--confirm-rollback", action="store_true", required=True)
    return parser


def _print(payload) -> None:
    print(json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db = SessionLocal()
    repository = SourceCatalogRepository()
    adapters = build_production_source_catalog_adapters()
    service = SourceCatalogService(db, repository=repository, adapters=adapters)
    try:
        if args.command == "discover":
            candidate, created = service.discover(args.source)
            _print(
                {
                    "created": created,
                    "candidate_id": candidate.id,
                    "source_site": candidate.source_site,
                    "fingerprint": candidate.fingerprint,
                    "state": candidate.state,
                }
            )
            return 0

        if args.command == "validate":
            coordinator = CatalogValidationCoordinator(
                db,
                repository=repository,
                adapters=adapters,
            )
            runs = coordinator.start(args.candidate_id)
            if args.run:
                asyncio.run(
                    coordinator.run_pending(
                        args.candidate_id,
                        worker_id=args.worker_id,
                    )
                )
                runs = repository.list_validation_runs(
                    db, candidate_id=args.candidate_id
                )
            _print(
                {
                    "candidate_id": args.candidate_id,
                    "runs": [
                        {
                            "id": run.id,
                            "kind": run.validation_kind,
                            "status": run.status,
                            "attempt": run.attempt,
                            "target_hash_prefix": run.expected_target_hash[:12],
                        }
                        for run in runs
                    ],
                }
            )
            return 0

        if args.command == "publish":
            candidate = repository.get_candidate(db, args.candidate_id)
            if candidate is None or candidate.fingerprint != args.confirm_fingerprint:
                raise RuntimeError("--confirm-fingerprint does not match the candidate")
            revision = service.publish(
                candidate.id,
                review_token=args.review_token,
                actor=args.actor,
            )
            _print(
                {
                    "published_revision_id": revision.id,
                    "source_site": revision.source_site,
                    "fingerprint": revision.fingerprint,
                }
            )
            return 0

        revision = service.rollback(
            args.revision_id,
            review_token=args.review_token,
            actor=args.actor,
        )
        _print(
            {
                "active_revision_id": revision.id,
                "source_site": revision.source_site,
                "fingerprint": revision.fingerprint,
            }
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
