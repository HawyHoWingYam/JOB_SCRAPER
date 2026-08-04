#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.services.crawl_listing_deduplication_service import (  # noqa: E402
    APPROVED_CRAWL_JOB_SOURCES,
    CrawlListingDeduplicationService,
)


def remove_existing_job_listings(
    *,
    execute: bool = False,
    expected_matched_rows: dict[UUID, int] | None = None,
) -> dict[str, object]:
    db = SessionLocal()
    try:
        previews = CrawlListingDeduplicationService(db).run(
            execute=execute,
            expected_matched_rows=expected_matched_rows,
        )
        if execute:
            db.commit()
        else:
            db.rollback()
        return {
            "mode": "execute" if execute else "dry-run",
            "committed": execute,
            "tasks": [preview.to_payload() for preview in previews],
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Remove published-identity listing rows from the two approved crawl jobs. "
            "Default is dry-run."
        )
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Commit the guarded deletion. Default is dry-run.",
    )
    parser.add_argument(
        "--expect-ctgoodjobs-matched",
        type=int,
        default=None,
        help="Required execute fence from the latest dry-run.",
    )
    parser.add_argument(
        "--expect-jobsdb-matched",
        type=int,
        default=None,
        help="Required execute fence from the latest dry-run.",
    )
    args = parser.parse_args()

    expected = None
    if args.execute:
        if args.expect_ctgoodjobs_matched is None or args.expect_jobsdb_matched is None:
            parser.error(
                "--execute requires both --expect-ctgoodjobs-matched and "
                "--expect-jobsdb-matched"
            )
        expected = {
            crawl_job_id: (
                args.expect_ctgoodjobs_matched
                if source_site == "ctgoodjobs"
                else args.expect_jobsdb_matched
            )
            for crawl_job_id, source_site in APPROVED_CRAWL_JOB_SOURCES.items()
        }

    result = remove_existing_job_listings(
        execute=args.execute,
        expected_matched_rows=expected,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
