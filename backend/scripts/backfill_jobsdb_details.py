#!/usr/bin/env python3
"""Repair degraded JobsDB detail rows using the headed browser detail scraper."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.scraper.jobsdb_browser_detail_scraper import JobsDBBrowserDetailScraper
from app.services.jobsdb_detail_repair_service import JobsDBDetailRepairService


async def repair_jobs(*, limit: int = 100) -> dict[str, int]:
    db = SessionLocal()
    repaired = 0
    failed = 0
    skipped = 0
    try:
        service = JobsDBDetailRepairService(db)
        jobs = service.iter_repair_candidates(limit=limit)
        async with JobsDBBrowserDetailScraper() as scraper:
            for job in jobs:
                parsed = await scraper.fetch_job_detail(job.source_job_id)
                if not parsed:
                    failed += 1
                    continue
                before = str(job.description or "").strip()
                service.apply_parsed_detail(job, parsed)
                after = str(job.description or "").strip()
                if after and after != before:
                    repaired += 1
                else:
                    skipped += 1
        db.commit()
        return {"repaired": repaired, "failed": failed, "skipped": skipped}
    finally:
        db.close()


def main() -> None:
    result = asyncio.run(repair_jobs())
    print(result)


if __name__ == "__main__":
    main()
