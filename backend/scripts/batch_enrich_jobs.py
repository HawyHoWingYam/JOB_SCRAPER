"""
Batch enrich all unenriched jobs with AI classification and skills.
"""
import argparse
import sys
import os
import asyncio
from dotenv import load_dotenv
from sqlalchemy.orm import joinedload

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"), override=True)

from app.database import SessionLocal
from app.models.job import Job
from app.models.job_skill_mention import JobSkillMention
from app.models.skill import Skill
from app.models.skill_category import SkillCategory
from app.models.skill_technology import SkillTechnology
from app.services.ai_enrichment_service import get_ai_enrichment_service


def build_parser() -> argparse.ArgumentParser:
    """Create the batch enrichment CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Only process up to N unenriched jobs")
    parser.add_argument("--dry-run", action="store_true", help="Preview target jobs without calling AI or writing data")
    parser.add_argument(
        "--include-enriched",
        action="store_true",
        help="Allow re-enriching jobs that already have ai_enriched_at set",
    )
    parser.add_argument(
        "--max-governed-skills",
        type=int,
        help="Only include jobs with at most N governed visible skills",
    )
    parser.add_argument(
        "--rerun-below-governed-skills",
        type=int,
        help="Only include jobs with fewer than N governed visible skills",
    )
    parser.add_argument(
        "--max-provisional-skills",
        type=int,
        help="Only include jobs with at most N provisional review-candidate skills",
    )
    parser.add_argument(
        "--require-no-mentions",
        action="store_true",
        help="Only include jobs with no skill mentions at all",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.5,
        help="Delay between jobs during live enrichment runs",
    )
    return parser


def _build_candidate_query(db, *, include_enriched: bool):
    query = (
        db.query(Job)
        .options(
            joinedload(Job.job_skill_mentions)
            .joinedload(JobSkillMention.skill)
            .joinedload(Skill.technology)
            .joinedload(SkillTechnology.category),
        )
        .filter(
            Job.is_deleted.is_(False),
            Job.source_classification_id.isnot(None),
            Job.source_classification_id != "",
        )
        .order_by(Job.created_at.asc(), Job.id.asc())
    )
    if not include_enriched:
        query = query.filter(Job.ai_enriched_at.is_(None))
    return query


def _job_matches_filters(
    job: Job,
    *,
    max_governed_skills: int | None = None,
    rerun_below_governed_skills: int | None = None,
    max_provisional_skills: int | None = None,
    require_no_mentions: bool = False,
) -> bool:
    governed_count = len(job.skills)
    provisional_count = len(job.provisional_skills)
    mention_count = len(job.job_skill_mentions or [])

    if max_governed_skills is not None and governed_count > max_governed_skills:
        return False
    if (
        rerun_below_governed_skills is not None
        and governed_count >= rerun_below_governed_skills
    ):
        return False
    if max_provisional_skills is not None and provisional_count > max_provisional_skills:
        return False
    if require_no_mentions and mention_count > 0:
        return False
    return True


async def batch_enrich(
    db_factory=SessionLocal,
    service=None,
    limit: int | None = None,
    dry_run: bool = False,
    delay_seconds: float = 0.5,
    include_enriched: bool = False,
    max_governed_skills: int | None = None,
    rerun_below_governed_skills: int | None = None,
    max_provisional_skills: int | None = None,
    require_no_mentions: bool = False,
):
    db = db_factory()

    try:
        query = _build_candidate_query(db, include_enriched=include_enriched)
        jobs = [
            job
            for job in query.all()
            if _job_matches_filters(
                job,
                max_governed_skills=max_governed_skills,
                rerun_below_governed_skills=rerun_below_governed_skills,
                max_provisional_skills=max_provisional_skills,
                require_no_mentions=require_no_mentions,
            )
        ]
        if limit is not None:
            jobs = jobs[:limit]

        total = len(jobs)
        print(f"Found {total} jobs to enrich")

        if dry_run:
            print("Dry run only. No AI calls or database writes will be performed.")
            for idx, job in enumerate(jobs, 1):
                print(
                    f"[{idx}/{total}] Would process: {job.title} | "
                    f"governed={len(job.skills)} provisional={len(job.provisional_skills)} "
                    f"mentions={len(job.job_skill_mentions or [])}"
                )
            return {"total": total, "success": 0, "errors": 0, "dry_run": True}

        service = service or get_ai_enrichment_service()
        success_count = 0
        error_count = 0

        for idx, job in enumerate(jobs, 1):
            print(
                f"[{idx}/{total}] Processing: {job.title} | "
                f"governed={len(job.skills)} provisional={len(job.provisional_skills)} "
                f"mentions={len(job.job_skill_mentions or [])}"
            )
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
            include_enriched=args.include_enriched,
            max_governed_skills=args.max_governed_skills,
            rerun_below_governed_skills=args.rerun_below_governed_skills,
            max_provisional_skills=args.max_provisional_skills,
            require_no_mentions=args.require_no_mentions,
        )
    )
