from fastapi import APIRouter
from sqlalchemy import func

from app.ai.llm_client import refresh_llm_status
from app.database import SessionLocal
from app.messaging.redis_stream_bus import RedisStreamBus
from app.messaging.topics import STREAM_JOB_INGEST, STREAM_JOB_LIFECYCLE
from app.models import CrawlJobListing, EnrichmentRun, Job, JobEmbedding, JobSkillMention

router = APIRouter(tags=["health"])


def _decode_redis_mapping(row: dict) -> dict:
    decoded = {}
    for key, value in row.items():
        normalized_key = key.decode() if isinstance(key, bytes) else str(key)
        if isinstance(value, bytes):
            decoded[normalized_key] = value.decode()
        else:
            decoded[normalized_key] = value
    return decoded


def _isoformat_or_none(value):
    return value.isoformat() if value is not None else None


def build_operator_health_summary() -> dict:
    issues: list[str] = []
    workers: dict[str, dict] = {}
    queues: dict[str, dict] = {}
    freshness: dict[str, dict] = {}

    try:
        redis_client = RedisStreamBus().redis
        for stream_name, group_name, worker_name in [
            (STREAM_JOB_INGEST, "ingest-workers", "ingest-worker"),
            (STREAM_JOB_LIFECYCLE, "enrichment-workers", "enrichment-worker"),
            (STREAM_JOB_LIFECYCLE, "embedding-workers", "embedding-worker"),
        ]:
            try:
                stream_length = int(redis_client.xlen(stream_name))
                group_rows = [_decode_redis_mapping(row) for row in redis_client.xinfo_groups(stream_name)]
                group_row = next((row for row in group_rows if row.get("name") == group_name), None)
                pending = int(group_row.get("pending") or 0) if group_row else 0
                lag = int(group_row.get("lag") or 0) if group_row and group_row.get("lag") is not None else 0
                consumers = int(group_row.get("consumers") or 0) if group_row else 0
                queues[stream_name if group_name == "ingest-workers" else f"{stream_name}:{group_name}"] = {
                    "group": group_name,
                    "length": stream_length,
                    "pending": pending,
                    "lag": lag,
                    "consumers": consumers,
                }
                workers[worker_name] = {
                    "status": "degraded" if pending or lag else "healthy",
                    "stream": stream_name,
                    "group": group_name,
                    "pending": pending,
                    "lag": lag,
                    "consumers": consumers,
                }
                if lag:
                    issues.append(f"{stream_name} group {group_name} lag is {lag}")
                if pending:
                    issues.append(f"{stream_name} group {group_name} has {pending} pending messages")
            except Exception as exc:
                workers[worker_name] = {"status": "unknown", "error": str(exc)}
                issues.append(f"{worker_name} queue health unavailable: {exc}")
    except Exception as exc:
        issues.append(f"Redis health unavailable: {exc}")

    db = SessionLocal()
    try:
        newest_job_updated_at = db.query(func.max(Job.updated_at)).scalar()
        total_jobs = db.query(Job).filter(Job.is_deleted == False).count()
        enriched_jobs = db.query(Job).filter(Job.ai_enriched_at.isnot(None), Job.is_deleted == False).count()
        listing_status_rows = (
            db.query(CrawlJobListing.detail_status, func.count(CrawlJobListing.id))
            .group_by(CrawlJobListing.detail_status)
            .all()
        )
        enrichment_status_rows = (
            db.query(EnrichmentRun.status, func.count(EnrichmentRun.id))
            .group_by(EnrichmentRun.status)
            .all()
        )
        newest_skill_mention_at = db.query(func.max(JobSkillMention.created_at)).scalar()
        newest_embedding_at = db.query(func.max(JobEmbedding.updated_at)).scalar()

        detail_counts = {str(status): int(count) for status, count in listing_status_rows}
        enrichment_counts = {str(status): int(count) for status, count in enrichment_status_rows}
        pending_detail = int(detail_counts.get("pending", 0))
        pending_ai = max(total_jobs - enriched_jobs, 0)
        if pending_detail:
            issues.append(f"crawl_job_listings has {pending_detail} pending detail rows")
        if total_jobs and pending_ai:
            issues.append(f"AI enrichment pending for {pending_ai} of {total_jobs} jobs")

        freshness = {
            "jobs": {
                "total": total_jobs,
                "newest_updated_at": _isoformat_or_none(newest_job_updated_at),
            },
            "crawl_job_listings": detail_counts,
            "ai": {
                "total_jobs": total_jobs,
                "enriched_jobs": enriched_jobs,
                "pending_jobs": pending_ai,
                "run_status_counts": enrichment_counts,
            },
            "skills": {
                "newest_mention_at": _isoformat_or_none(newest_skill_mention_at),
            },
            "embeddings": {
                "newest_updated_at": _isoformat_or_none(newest_embedding_at),
            },
        }
    except Exception as exc:
        issues.append(f"Database freshness health unavailable: {exc}")
    finally:
        db.close()

    critical = any("lag is" in issue or "pending messages" in issue for issue in issues)
    status = "critical" if critical else "degraded" if issues else "healthy"
    return {
        "status": status,
        "issues": issues,
        "workers": workers,
        "queues": queues,
        "freshness": freshness,
    }


@router.get("/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    job_llm_status = refresh_llm_status()
    company_llm_status = refresh_llm_status("companies")
    operator_status = build_operator_health_summary()
    degraded_issues = []

    if job_llm_status["is_degraded"]:
        degraded_issues.append(f"Job LLM: {job_llm_status['degradation_reason']}")
    if company_llm_status["is_degraded"]:
        degraded_issues.append(f"Company LLM: {company_llm_status['degradation_reason']}")
    if operator_status["status"] != "healthy":
        degraded_issues.extend(operator_status.get("issues") or [])

    if degraded_issues:
        return {
            "status": "degraded",
            "service": "backend-api",
            "issues": degraded_issues,
            "operator": operator_status,
        }

    return {"status": "healthy", "service": "backend-api", "operator": operator_status}
