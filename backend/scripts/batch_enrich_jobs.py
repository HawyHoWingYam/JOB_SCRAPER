"""
Batch enrich jobs with optional source/taxonomy/text filters.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
import json
from pathlib import Path
import csv
import re

from dotenv import load_dotenv
from sqlalchemy.orm import joinedload

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"), override=True)

from app.database import SessionLocal
from app.models.job import Job
from app.models.job_skill_mention import JobSkillMention
from app.models.job_subcategory import JobSubcategory
from app.models.skill import Skill
from app.models.skill_technology import SkillTechnology
from app.services.ai_enrichment_service import get_ai_enrichment_service


def build_parser() -> argparse.ArgumentParser:
    """Create the batch enrichment CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Only process up to N jobs")
    parser.add_argument(
        "--job-id",
        action="append",
        default=[],
        help="Only include the specified job UUIDs. Repeatable.",
    )
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
    parser.add_argument("--source-site", help="Only include jobs from the specified source site")
    parser.add_argument(
        "--source-subclassification",
        help="Only include jobs with the specified source sub-classification name",
    )
    parser.add_argument(
        "--current-category",
        help="Only include jobs currently assigned to the specified governed category",
    )
    parser.add_argument(
        "--current-subcategory",
        help="Only include jobs currently assigned to the specified governed subcategory",
    )
    parser.add_argument(
        "--title-contains",
        action="append",
        default=[],
        help="Only include jobs whose title contains one of the provided case-insensitive fragments. Repeatable.",
    )
    parser.add_argument(
        "--title-not-contains",
        action="append",
        default=[],
        help="Exclude jobs whose title contains any of the provided case-insensitive fragments. Repeatable.",
    )
    parser.add_argument(
        "--min-title-fragment-hits",
        type=int,
        default=1,
        help="When --title-contains is used, require at least N matching fragments (default: 1).",
    )
    parser.add_argument(
        "--description-contains",
        action="append",
        default=[],
        help="Only include jobs whose description contains one of the provided case-insensitive fragments. Repeatable.",
    )
    parser.add_argument(
        "--description-not-contains",
        action="append",
        default=[],
        help="Exclude jobs whose description contains any of the provided case-insensitive fragments. Repeatable.",
    )
    parser.add_argument(
        "--min-description-fragment-hits",
        type=int,
        default=1,
        help="When --description-contains is used, require at least N matching fragments (default: 1).",
    )
    parser.add_argument(
        "--signal-bucket",
        action="append",
        default=[],
        help="Only include jobs whose inferred signal bucket matches one of the provided values. Repeatable.",
    )
    parser.add_argument(
        "--output-file",
        help="Optional path to write a structured JSON report for the selected jobs.",
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
            joinedload(Job.subcategory).joinedload(JobSubcategory.category),
        )
        .filter(
            Job.is_deleted.is_(False),
            Job.source_classification_id.isnot(None),
            Job.source_classification_id != "",
        )
        .order_by(Job.ai_enriched_at.isnot(None).asc(), Job.created_at.asc(), Job.id.asc())
    )
    if not include_enriched:
        query = query.filter(Job.ai_enriched_at.is_(None))
    return query


def _count_fragment_hits(text: str, fragments: list[str] | None) -> int:
    normalized_fragments = [fragment.strip().lower() for fragment in (fragments or []) if fragment.strip()]
    if not normalized_fragments:
        return 0
    return sum(1 for fragment in normalized_fragments if fragment in text)


def _matches_any_fragment(text: str, fragments: list[str] | None, *, min_hits: int = 1) -> bool:
    normalized_fragments = [fragment.strip().lower() for fragment in (fragments or []) if fragment.strip()]
    if not normalized_fragments:
        return True
    return _count_fragment_hits(text, normalized_fragments) >= max(1, int(min_hits or 1))


def _matches_no_fragments(text: str, fragments: list[str] | None) -> bool:
    normalized_fragments = [fragment.strip().lower() for fragment in (fragments or []) if fragment.strip()]
    if not normalized_fragments:
        return True
    return all(fragment not in text for fragment in normalized_fragments)


def _safe_console_text(value: object) -> str:
    return str(value or "").encode("ascii", "backslashreplace").decode("ascii")


def _build_description_preview(description: object, *, max_length: int = 280) -> str:
    raw_text = str(description or "")
    without_tags = re.sub(r"<[^>]+>", " ", raw_text)
    normalized = " ".join(without_tags.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 3].rstrip()}..."


def _collect_signal_profile(job: Job) -> dict[str, object]:
    normalized_title = str(job.title or "").lower()
    normalized_description = str(job.description or "").lower()
    normalized_skill_names = {
        str(skill or "").strip().lower()
        for skill in list(job.skills or []) + list(job.provisional_skills or [])
        if str(skill or "").strip()
    }

    def _title_hits(signals: tuple[str, ...]) -> list[str]:
        return [signal for signal in signals if signal in normalized_title]

    def _text_hits(signals: tuple[str, ...]) -> list[str]:
        return [
            signal
            for signal in signals
            if signal in normalized_description or signal in normalized_skill_names
        ]

    infra_title_hits = _title_hits(
        (
            "devops",
            "site reliability",
            "sre",
            "platform engineer",
            "cloud engineer",
            "mlops",
        )
    )
    backend_title_hits = _title_hits(
        (
            "backend engineer",
            "back end",
            "microservice",
            "api developer",
            "java developer",
        )
    )
    infra_tool_hits = _text_hits(
        (
            "terraform",
            "kubernetes",
            "docker",
            "jenkins",
            "cloud infrastructure",
            "devsecops",
            "linux",
            "bash",
            "ansible",
            "puppet",
            "chef",
            "openshift",
        )
    )
    devtestops_hits = _text_hits(
        (
            "test environment",
            "test environments",
            "environment provisioning",
            "automated test framework",
            "automated test frameworks",
            "ci/cd pipeline",
            "ci/cd pipelines",
            "performance testing",
            "load testing",
            "reliability testing",
        )
    )
    backend_delivery_hits = _text_hits(
        (
            "backend api",
            "backend apis",
            "restful api",
            "microservices",
            "integration layer",
            "node.js",
            "java",
            "golang",
            "go code",
        )
    )

    if infra_title_hits and not backend_title_hits:
        bucket = "infra-devops"
    elif len(devtestops_hits) >= 3 and len(infra_tool_hits) >= 2 and not backend_title_hits:
        bucket = "devtestops"
    elif backend_title_hits or len(backend_delivery_hits) >= 3:
        bucket = "backend-platform"
    elif len(infra_tool_hits) >= 3:
        bucket = "mixed-infra"
    else:
        bucket = "ambiguous"

    return {
        "bucket": bucket,
        "infra_title_hits": infra_title_hits,
        "backend_title_hits": backend_title_hits,
        "infra_tool_hits": infra_tool_hits,
        "devtestops_hits": devtestops_hits,
        "backend_delivery_hits": backend_delivery_hits,
    }


def _format_signal_profile(profile: dict[str, object]) -> str:
    return (
        f"bucket={profile['bucket']} "
        f"title+infra={','.join(profile['infra_title_hits']) or '-'} "
        f"title+backend={','.join(profile['backend_title_hits']) or '-'} "
        f"infra={','.join(profile['infra_tool_hits']) or '-'} "
        f"devtestops={','.join(profile['devtestops_hits']) or '-'} "
        f"backend={','.join(profile['backend_delivery_hits']) or '-'}"
    )


def _suggest_review_action(profile: dict[str, object]) -> str:
    bucket = str(profile.get("bucket") or "")
    if bucket == "infra-devops":
        return "move_infra"
    if bucket == "backend-platform":
        return "keep_backend"
    if bucket in {"devtestops", "mixed-infra"}:
        backend_signal_count = len(profile.get("backend_delivery_hits") or [])
        backend_title_count = len(profile.get("backend_title_hits") or [])
        if backend_title_count > 0 or backend_signal_count >= 2:
            return "keep_backend"
        return "review_for_infra"
    return "manual_review"


def _build_audit_row(job: Job) -> dict[str, object]:
    current_taxonomy = getattr(job, "job_taxonomy", None) or {}
    profile = _collect_signal_profile(job)
    return {
        "job_id": str(getattr(job, "id", "") or ""),
        "title": str(getattr(job, "title", "") or ""),
        "original_job_url": getattr(job, "original_job_url", None),
        "taxonomy_path": current_taxonomy.get("path"),
        "category_name": current_taxonomy.get("category_name"),
        "subcategory_name": current_taxonomy.get("subcategory_name"),
        "source_site": str(getattr(job, "source_site", "") or ""),
        "source_subclassification_name": str(getattr(job, "source_subclassification_name", "") or ""),
        "description_preview": _build_description_preview(getattr(job, "description", None)),
        "governed_skill_count": len(job.skills),
        "provisional_skill_count": len(job.provisional_skills),
        "mention_count": len(job.job_skill_mentions or []),
        "skills": list(job.skills or []),
        "provisional_skills": list(job.provisional_skills or []),
        "suggested_action": _suggest_review_action(profile),
        "signal_profile": profile,
    }


def _write_json_report(*, output_file: str, audit_rows: list[dict[str, object]], bucket_summary: dict[str, int]) -> None:
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "total": len(audit_rows),
        "bucket_summary": dict(bucket_summary),
        "jobs": audit_rows,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv_report(*, output_file: str, audit_rows: list[dict[str, object]]) -> None:
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "job_id",
        "title",
        "source_site",
        "source_subclassification_name",
        "taxonomy_path",
        "category_name",
        "subcategory_name",
        "suggested_action",
        "description_preview",
        "original_job_url",
        "governed_skill_count",
        "provisional_skill_count",
        "mention_count",
        "skills",
        "provisional_skills",
        "signal_bucket",
        "signal_title_infra",
        "signal_title_backend",
        "signal_infra_tools",
        "signal_devtestops",
        "signal_backend_delivery",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as output_file_handle:
        writer = csv.DictWriter(output_file_handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in audit_rows:
            profile = row.get("signal_profile") or {}
            writer.writerow(
                {
                    "job_id": row.get("job_id"),
                    "title": row.get("title"),
                    "source_site": row.get("source_site"),
                    "source_subclassification_name": row.get("source_subclassification_name"),
                    "taxonomy_path": row.get("taxonomy_path"),
                    "category_name": row.get("category_name"),
                    "subcategory_name": row.get("subcategory_name"),
                    "suggested_action": row.get("suggested_action"),
                    "description_preview": row.get("description_preview"),
                    "original_job_url": row.get("original_job_url"),
                    "governed_skill_count": row.get("governed_skill_count"),
                    "provisional_skill_count": row.get("provisional_skill_count"),
                    "mention_count": row.get("mention_count"),
                    "skills": " | ".join(row.get("skills") or []),
                    "provisional_skills": " | ".join(row.get("provisional_skills") or []),
                    "signal_bucket": profile.get("bucket"),
                    "signal_title_infra": " | ".join(profile.get("infra_title_hits") or []),
                    "signal_title_backend": " | ".join(profile.get("backend_title_hits") or []),
                    "signal_infra_tools": " | ".join(profile.get("infra_tool_hits") or []),
                    "signal_devtestops": " | ".join(profile.get("devtestops_hits") or []),
                    "signal_backend_delivery": " | ".join(profile.get("backend_delivery_hits") or []),
                }
            )


def _write_report(*, output_file: str, audit_rows: list[dict[str, object]], bucket_summary: dict[str, int]) -> None:
    output_path = Path(output_file)
    if output_path.suffix.lower() == ".csv":
        _write_csv_report(output_file=output_file, audit_rows=audit_rows)
        return
    _write_json_report(
        output_file=output_file,
        audit_rows=audit_rows,
        bucket_summary=bucket_summary,
    )


def _job_matches_filters(
    job: Job,
    *,
    job_ids: set[str] | None = None,
    max_governed_skills: int | None = None,
    rerun_below_governed_skills: int | None = None,
    max_provisional_skills: int | None = None,
    require_no_mentions: bool = False,
    source_site: str | None = None,
    source_subclassification: str | None = None,
    current_category: str | None = None,
    current_subcategory: str | None = None,
    title_contains: list[str] | None = None,
    title_not_contains: list[str] | None = None,
    min_title_fragment_hits: int = 1,
    description_contains: list[str] | None = None,
    description_not_contains: list[str] | None = None,
    min_description_fragment_hits: int = 1,
    signal_buckets: set[str] | None = None,
) -> bool:
    governed_count = len(job.skills)
    provisional_count = len(job.provisional_skills)
    mention_count = len(job.job_skill_mentions or [])
    normalized_title = str(job.title or "").lower()
    normalized_description = str(job.description or "").lower()

    if job_ids and str(getattr(job, "id", "") or "") not in job_ids:
        return False
    if max_governed_skills is not None and governed_count > max_governed_skills:
        return False
    if rerun_below_governed_skills is not None and governed_count >= rerun_below_governed_skills:
        return False
    if max_provisional_skills is not None and provisional_count > max_provisional_skills:
        return False
    if require_no_mentions and mention_count > 0:
        return False
    if source_site and str(getattr(job, "source_site", "") or "").strip().lower() != source_site.strip().lower():
        return False
    if source_subclassification and str(getattr(job, "source_subclassification_name", "") or "").strip() != source_subclassification:
        return False

    current_taxonomy = getattr(job, "job_taxonomy", None) or {}
    if current_category and str(current_taxonomy.get("category_name") or "").strip() != current_category:
        return False
    if current_subcategory and str(current_taxonomy.get("subcategory_name") or "").strip() != current_subcategory:
        return False
    if not _matches_any_fragment(normalized_title, title_contains, min_hits=min_title_fragment_hits):
        return False
    if not _matches_no_fragments(normalized_title, title_not_contains):
        return False
    if not _matches_any_fragment(
        normalized_description,
        description_contains,
        min_hits=min_description_fragment_hits,
    ):
        return False
    if not _matches_no_fragments(normalized_description, description_not_contains):
        return False
    if signal_buckets and str(_collect_signal_profile(job)["bucket"]) not in signal_buckets:
        return False
    return True


async def batch_enrich(
    db_factory=SessionLocal,
    service=None,
    limit: int | None = None,
    job_ids: list[str] | None = None,
    dry_run: bool = False,
    delay_seconds: float = 0.5,
    include_enriched: bool = False,
    max_governed_skills: int | None = None,
    rerun_below_governed_skills: int | None = None,
    max_provisional_skills: int | None = None,
    require_no_mentions: bool = False,
    source_site: str | None = None,
    source_subclassification: str | None = None,
    current_category: str | None = None,
    current_subcategory: str | None = None,
    title_contains: list[str] | None = None,
    title_not_contains: list[str] | None = None,
    min_title_fragment_hits: int = 1,
    description_contains: list[str] | None = None,
    description_not_contains: list[str] | None = None,
    min_description_fragment_hits: int = 1,
    signal_buckets: list[str] | None = None,
    output_file: str | None = None,
):
    db = db_factory()

    try:
        normalized_job_ids = {str(job_id).strip() for job_id in (job_ids or []) if str(job_id).strip()}
        normalized_signal_buckets = {
            str(bucket).strip()
            for bucket in (signal_buckets or [])
            if str(bucket).strip()
        }
        query = _build_candidate_query(db, include_enriched=include_enriched)
        jobs = [
            job
            for job in query.all()
            if _job_matches_filters(
                job,
                job_ids=normalized_job_ids,
                max_governed_skills=max_governed_skills,
                rerun_below_governed_skills=rerun_below_governed_skills,
                max_provisional_skills=max_provisional_skills,
                require_no_mentions=require_no_mentions,
                source_site=source_site,
                source_subclassification=source_subclassification,
                current_category=current_category,
                current_subcategory=current_subcategory,
                title_contains=title_contains,
                title_not_contains=title_not_contains,
                min_title_fragment_hits=min_title_fragment_hits,
                description_contains=description_contains,
                description_not_contains=description_not_contains,
                min_description_fragment_hits=min_description_fragment_hits,
                signal_buckets=normalized_signal_buckets,
            )
        ]
        if limit is not None:
            jobs = jobs[:limit]

        total = len(jobs)
        print(f"Found {total} jobs to enrich")
        audit_rows = [_build_audit_row(job) for job in jobs]
        bucket_counter = Counter(row["signal_profile"]["bucket"] for row in audit_rows)
        if output_file:
            _write_report(
                output_file=output_file,
                audit_rows=audit_rows,
                bucket_summary=dict(bucket_counter),
            )
            print(f"Wrote report to {output_file}")

        if dry_run:
            print("Dry run only. No AI calls or database writes will be performed.")
            for idx, row in enumerate(audit_rows, 1):
                print(
                    f"[{idx}/{total}] Would process: {row['job_id']} | {_safe_console_text(row['title'])} | "
                    f"taxonomy={row['taxonomy_path'] or 'None'} | "
                    f"governed={row['governed_skill_count']} provisional={row['provisional_skill_count']} "
                    f"mentions={row['mention_count']} | "
                    f"{_format_signal_profile(row['signal_profile'])}"
                )
            if bucket_counter:
                print(f"Bucket summary: {dict(bucket_counter)}")
            return {"total": total, "success": 0, "errors": 0, "dry_run": True}

        service = service or get_ai_enrichment_service()
        success_count = 0
        error_count = 0

        for idx, job in enumerate(jobs, 1):
            current_taxonomy = getattr(job, "job_taxonomy", None) or {}
            profile = _collect_signal_profile(job)
            print(
                f"[{idx}/{total}] Processing: {job.id} | {_safe_console_text(job.title)} | "
                f"taxonomy={current_taxonomy.get('path') or 'None'} | "
                f"governed={len(job.skills)} provisional={len(job.provisional_skills)} "
                f"mentions={len(job.job_skill_mentions or [])} | "
                f"{_format_signal_profile(profile)}"
            )
            result = await service.enrich_job(job, db)

            if result["status"] == "success":
                success_count += 1
            else:
                error_count += 1
                print(f"  ERROR: {result.get('error', 'Unknown')}")

            if total and idx % 10 == 0:
                print(
                    f"Progress: {idx}/{total} ({idx * 100 // total}%) - "
                    f"Success: {success_count}, Errors: {error_count}"
                )

            if delay_seconds:
                await asyncio.sleep(delay_seconds)

        print("\nCompleted!")
        print(f"  Total: {total}")
        print(f"  Success: {success_count}")
        print(f"  Errors: {error_count}")
        return {"total": total, "success": success_count, "errors": error_count, "dry_run": False}

    except Exception as exc:
        print(f"Fatal error: {exc}")
        db.rollback()
        return {"total": 0, "success": 0, "errors": 1, "dry_run": dry_run}
    finally:
        db.close()


if __name__ == "__main__":
    args = build_parser().parse_args()
    asyncio.run(
        batch_enrich(
            limit=args.limit,
            job_ids=args.job_id,
            dry_run=args.dry_run,
            delay_seconds=args.delay_seconds,
            include_enriched=args.include_enriched,
            max_governed_skills=args.max_governed_skills,
            rerun_below_governed_skills=args.rerun_below_governed_skills,
            max_provisional_skills=args.max_provisional_skills,
            require_no_mentions=args.require_no_mentions,
            source_site=args.source_site,
            source_subclassification=args.source_subclassification,
            current_category=args.current_category,
            current_subcategory=args.current_subcategory,
            title_contains=args.title_contains,
            title_not_contains=args.title_not_contains,
            min_title_fragment_hits=args.min_title_fragment_hits,
            description_contains=args.description_contains,
            description_not_contains=args.description_not_contains,
            min_description_fragment_hits=args.min_description_fragment_hits,
            signal_buckets=args.signal_bucket,
            output_file=args.output_file,
        )
    )
