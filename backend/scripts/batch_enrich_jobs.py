"""
Batch enrich all unenriched jobs with AI classification and skills.
"""
import argparse
import sys
import os
import asyncio
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"), override=True)

from app.database import SessionLocal
from app.models.job import Job
from app.services.ai_enrichment_service import get_ai_enrichment_service


def build_parser() -> argparse.ArgumentParser:
    """Create the batch enrichment CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Only process up to N unenriched jobs")
    parser.add_argument("--dry-run", action="store_true", help="Preview target jobs without calling AI or writing data")
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.5,
        help="Delay between jobs during live enrichment runs",
    )
    return parser


async def batch_enrich(
    db_factory=SessionLocal,
    service=None,
    limit: int | None = None,
    dry_run: bool = False,
    delay_seconds: float = 0.5,
):
    db = db_factory()

    try:
        # Get all unenriched jobs
        query = db.query(Job).filter(
            Job.ai_enriched_at.is_(None),
            Job.is_deleted == False,
            Job.source_classification_id.isnot(None),
            Job.source_classification_id != "",
        )
        if limit is not None:
            query = query.limit(limit)

        jobs = query.all()

        total = len(jobs)
        print(f"Found {total} jobs to enrich")

        if dry_run:
            print("Dry run only. No AI calls or database writes will be performed.")
            for idx, job in enumerate(jobs, 1):
                print(f"[{idx}/{total}] Would process: {job.title}")
            return {"total": total, "success": 0, "errors": 0, "dry_run": True}

        service = service or get_ai_enrichment_service()
        success_count = 0
        error_count = 0

        for idx, job in enumerate(jobs, 1):
            print(f"[{idx}/{total}] Processing: {job.title}")
            result = await service.enrich_job(job, db)

            if result["status"] == "success":
                success_count += 1
            else:
                error_count += 1
                print(f"  ✗ Error: {result.get('error', 'Unknown')}")

            if total and idx % 10 == 0:
                print(f"Progress: {idx}/{total} ({idx*100//total}%) - Success: {success_count}, Errors: {error_count}")

            # Small delay to avoid rate limits
            if delay_seconds:
                await asyncio.sleep(delay_seconds)

        print(f"\n✓ Completed!")
        print(f"  Total: {total}")
        print(f"  Success: {success_count}")
        print(f"  Errors: {error_count}")
        return {"total": total, "success": success_count, "errors": error_count, "dry_run": False}

    except Exception as e:
        print(f"Fatal error: {e}")
        db.rollback()
        return {"total": 0, "success": 0, "errors": 1, "dry_run": dry_run}
    finally:
        db.close()


if __name__ == "__main__":
    args = build_parser().parse_args()
    asyncio.run(
        batch_enrich(
            limit=args.limit,
            dry_run=args.dry_run,
            delay_seconds=args.delay_seconds,
        )
    )
