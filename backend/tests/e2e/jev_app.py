from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.jev import router as jev_router
from app.api.jev_operations import router as jev_operations_router
from app.api.ai import router as ai_router
from app.api.settings import router as settings_router
from app.api.skill_candidates import router as skill_candidates_router
from app.api.current_taxonomies import router as current_taxonomies_router
from app.api.jobs import router as jobs_router
from app.api.capabilities import router as capabilities_router
from app.api.crawl_jobs import router as crawl_jobs_router
from app.api.recommendations import router as recommendations_router
from app.database import get_db
from app.models.company import Company
from app.models.crawl_job import CrawlJob, CrawlJobEvent
from app.models.crawl_job_listing import CrawlJobListing
from app.models.current_taxonomy import (
    CurrentJobSkillAssignment,
    CurrentJobSkillMention,
    CurrentSkillCandidate,
    CurrentTaxonomyNodeRecord,
)
from app.models.jev import (
    JevOnlineSkillClassification,
)
from app.models.job import Job
from app.services.ai_runtime_settings_service import AIRuntimeSettingsService
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService
from app.services.enrichment_run_service import EnrichmentRunService
from app.services.jev_skill_backfill import JevSkillBackfillService
from app.utils.time import utc_now
import app.services.jev_skill_backfill as jev_skill_backfill_module
from scripts.bootstrap_db import bootstrap_database
from app.database import Base
import app.models  # noqa: F401


_database_url = os.environ["JEV_E2E_DATABASE_URL"]
if not (make_url(_database_url).database or "").endswith("_test"):
    raise RuntimeError("JEV_E2E_DATABASE_URL must name a disposable _test database")
_engine = create_engine(_database_url)
with _engine.begin() as _connection:
    _connection.execute(text("DROP SCHEMA public CASCADE"))
    _connection.execute(text("CREATE SCHEMA public"))
bootstrap_database(db_engine=_engine, metadata=Base.metadata)
_session_factory = sessionmaker(bind=_engine, autoflush=False)
_provider_requests: list[dict[str, object]] = []
_provider_mode = "normal"

app = FastAPI(title="Jev browser E2E")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(settings_router)
app.include_router(jev_router, prefix="/api")
app.include_router(jev_operations_router, prefix="/api")
app.include_router(skill_candidates_router, prefix="/api")
app.include_router(current_taxonomies_router, prefix="/api")
app.include_router(ai_router)
app.include_router(jobs_router, prefix="/api")
app.include_router(capabilities_router, prefix="/api")
app.include_router(recommendations_router, prefix="/api")
app.include_router(crawl_jobs_router, prefix="/api")


def _override_db():
    db = _session_factory()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_db
jev_skill_backfill_module.SessionLocal = _session_factory


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/fake/systemone")
async def fake_system_one(request: Request) -> dict[str, object]:
    global _provider_mode
    payload = await request.json()
    _provider_requests.append(
        {
            "path": request.url.path,
            "has_bearer": request.headers.get("authorization", "").startswith(
                "Bearer "
            ),
            "model": payload.get("model"),
            "question_names": sorted((payload.get("questions") or {}).keys()),
        }
    )
    if _provider_mode == "unavailable":
        return JSONResponse(status_code=503, content={"error": "temporary"})
    questions = payload.get("questions") or {}
    if _provider_mode == "crawl_quality_problem" and {
        "quality",
        "problem_kind",
    }.issubset(questions):
        answers = {
            "quality": {
                "type": "choice",
                "choice": "quality_problem",
                "confidence": 0.99,
                "probabilities": {
                    "usable_job_detail": 0.0,
                    "quality_problem": 1.0,
                    "insufficient": 0.0,
                },
            },
            "problem_kind": {
                "type": "choice",
                "choice": "listing_or_template",
                "confidence": 0.99,
                "probabilities": {
                    key: 1.0 if key == "listing_or_template" else 0.0
                    for key in questions["problem_kind"]["criteria"]
                },
            },
        }
    elif _provider_mode == "search_rerank" and questions and all(
        question.get("type") == "score" for question in questions.values()
    ):
        answers = {
            name: {
                "type": "score",
                "score": float(min(position, 3)),
                "confidence": 0.99,
                "legend": {0: "irrelevant", 3: "highly relevant"},
                "probabilities": {min(position, 3): 1.0},
            }
            for position, name in enumerate(questions)
        }
    elif _provider_mode == "incident_triage" and questions and all(
        name.startswith("cluster_") for name in questions
    ):
        answers = {
            name: {
                "type": "choice",
                "choice": "investigate_now",
                "confidence": 0.99,
                "probabilities": {
                    key: 1.0 if key == "investigate_now" else 0.0
                    for key in question["criteria"]
                },
            }
            for name, question in questions.items()
        }
    elif "requires_python" in questions:
        answers = {"requires_python": {"type": "noul", "noul": 0.99}}
    else:
        answers = {}
        for name, question in questions.items():
            criteria = question.get("criteria") or {}
            if name.endswith("_action"):
                choice = "propose_new"
            elif name.endswith("_parent"):
                choice = next(iter(criteria))
            else:
                choice = next(iter(criteria))
            probabilities = {key: 0.0 for key in criteria}
            probabilities[choice] = 1.0
            answers[name] = {
                "type": "choice",
                "choice": choice,
                "confidence": 0.99,
                "probabilities": probabilities,
            }
    usage = {"input_tokens": 10, "output_tokens": 1}
    if "requires_python" not in questions:
        usage["cost"] = 0.00005
    return {
        "id": f"e2e-request-{len(_provider_requests)}",
        "model": "jev-e2e-resolved",
        "provider": "local-e2e",
        "answers": answers,
        "usage": usage,
    }


@app.get("/fake/requests")
def fake_requests() -> dict[str, object]:
    return {"count": len(_provider_requests), "requests": _provider_requests}


@app.post("/fake/mode/{mode}")
def fake_mode(mode: str) -> dict[str, str]:
    global _provider_mode
    if mode not in {
        "normal",
        "unavailable",
        "crawl_quality_problem",
        "search_rerank",
        "incident_triage",
    }:
        return JSONResponse(status_code=400, content={"error": "unknown mode"})
    _provider_mode = mode
    return {"mode": mode}


def _seed_skill_exception(index: int = 1, *, create_taxonomy: bool = True) -> None:
    db = _session_factory()
    try:
        ai_settings = AIRuntimeSettingsService(db).get_or_create()
        ai_settings.skill_auto_create_distinct_job_threshold = 10
        ai_settings.skill_candidate_recommendation_limit = 5
        ai_settings.skill_candidate_evidence_limit = 5
        jev = JevRuntimeSettingsService(db).get_or_create()
        jev.maintenance_enabled = True
        jev.maintenance_min_candidates = 1
        jev.maintenance_batch_size = 10
        jev.maintenance_model = "jev-e2e-maintenance"
        company_id = UUID(f"10000000-0000-0000-0000-{index:012d}")
        job_id = UUID(f"20000000-0000-0000-0000-{index:012d}")
        candidate_id = UUID(f"30000000-0000-0000-0000-{index:012d}")
        name = "NovelDB" if index == 1 else f"NovelDB{index}"
        company = Company(
            id=company_id,
            company_id=f"e2e-company-{index}",
            source_site="jobsdb",
            source_company_id=f"e2e-company-{index}",
            name=f"E2E Company {index}",
        )
        job = Job(
            id=job_id,
            job_id=f"e2e-job-{index}",
            source_site="jobsdb",
            source_job_id=f"e2e-job-{index}",
            company_id=company.id,
            title="Novel Database Engineer",
            description=f"{name} experience is preferred.",
        )
        category = CurrentTaxonomyNodeRecord(
            taxonomy="skill",
            code="backend",
            parent_code=None,
            level="category",
            labels={"en": "Backend"},
            sort_order=1,
            is_assignable=False,
            is_active=True,
        )
        technology = CurrentTaxonomyNodeRecord(
            taxonomy="skill",
            code="backend.databases",
            parent_code="backend",
            level="technology",
            labels={"en": "Databases"},
            sort_order=1,
            is_assignable=False,
            is_active=True,
        )
        candidate = CurrentSkillCandidate(
            id=candidate_id,
            normalized_key=name.casefold(),
            canonical_raw_name=name,
            raw_variants=[name],
            occurrence_count=10,
            distinct_job_count=10,
            evidence_summary={"active_mentions": 10, "distinct_jobs": 10},
        )
        rows = [company, job, candidate]
        if create_taxonomy:
            rows.extend((category, technology))
        db.add_all(rows)
        db.flush()
        db.add(
            CurrentJobSkillMention(
                job_id=job.id,
                taxonomy="skill",
                raw_name=name,
                normalized_key=name.casefold(),
                resolution="candidate",
                status="active",
                candidate_id=candidate.id,
                source="jev-classification",
                confidence=0.84,
                provenance={"method": "jev-online-classification"},
                evidence_hash="a" * 64,
            )
        )
        db.commit()
    finally:
        db.close()


_seed_skill_exception()


@app.post("/fake/seed/{index}")
def fake_seed(index: int) -> dict[str, object]:
    _seed_skill_exception(index, create_taxonomy=False)
    return {"seeded": index}


@app.post("/fake/seed-duplicate-pair/{index}")
def fake_seed_duplicate_pair(index: int) -> dict[str, object]:
    if not 1 <= index <= 9:
        return JSONResponse(status_code=400, content={"error": "index must be 1..9"})
    db = _session_factory()
    try:
        company = Company(
            id=UUID(f"41000000-0000-0000-0000-{index:012d}"),
            company_id=f"e2e-duplicate-company-{index}",
            source_site="jobsdb",
            source_company_id=f"e2e-duplicate-company-{index}",
            name=f"Duplicate E2E Company {index}",
        )
        left = Job(
            id=UUID(f"42000000-0000-0000-0001-{index:012d}"),
            job_id=f"jobsdb:e2e-duplicate-left-{index}",
            source_site="jobsdb",
            source_job_id=f"e2e-duplicate-left-{index}",
            company_id=company.id,
            title=f"Senior Backend Engineer E2E {index}",
            description="Build Python payment APIs for the platform team.",
            location="Hong Kong",
            is_deleted=False,
        )
        right = Job(
            id=UUID(f"42000000-0000-0000-0002-{index:012d}"),
            job_id=f"ctgoodjobs:e2e-duplicate-right-{index}",
            source_site="ctgoodjobs",
            source_job_id=f"e2e-duplicate-right-{index}",
            company_id=company.id,
            title=f"Backend Engineer E2E {index}",
            description="Build Python payment APIs for the platform team.",
            location="Hong Kong",
            is_deleted=False,
        )
        db.add_all((company, left, right))
        settings = JevRuntimeSettingsService(db).get_or_create()
        settings.duplicate_enabled = True
        settings.duplicate_candidate_limit = 1
        settings.duplicate_corpus_limit = 100
        db.commit()
        return {"left_job_id": str(left.id), "right_job_id": str(right.id)}
    finally:
        db.close()


@app.post("/fake/seed-crawl-quality/{index}")
def fake_seed_crawl_quality(index: int) -> dict[str, object]:
    if not 1 <= index <= 9:
        return JSONResponse(status_code=400, content={"error": "index must be 1..9"})
    db = _session_factory()
    try:
        crawl_job_id = UUID(f"51000000-0000-0000-0000-{index:012d}")
        listing_id = UUID(f"52000000-0000-0000-0000-{index:012d}")
        plan_id = UUID(f"53000000-0000-0000-0000-{index:012d}")
        now = utc_now()
        crawl_job = CrawlJob(
            id=crawl_job_id,
            source_site="offertoday",
            trigger_type="manual",
            status="completed",
            request_payload={
                "source_site": "offertoday",
                "crawl_phase": "detail",
                "crawl_mode": "headless",
                "detail_scope": "crawl_scope",
                "detail_limit": 1,
                "removed_dispatch_plan": {
                    "reason": "historical_listing_deduplication",
                    "plan_id": str(plan_id),
                    "plan_fingerprint": "c" * 64,
                },
            },
            metrics={
                "detail_snapshot_target_count": 1,
                "detail_snapshot_fetched_count": 1,
                "detail_snapshot_saved_count": 1,
                "detail_snapshot_failed_count": 0,
                "detail_snapshot_unavailable_count": 0,
                "detail_snapshot_manual_action_count": 0,
                "detail_snapshot_remaining_count": 0,
                "detail_live_future_eligible_count": 0,
                "detail_run_cap": 1,
            },
            started_at=now,
            completed_at=now,
        )
        listing = CrawlJobListing(
            id=listing_id,
            crawl_job_id=crawl_job.id,
            source_site="offertoday",
            source_job_id=f"e2e-crawl-quality-{index}",
            source_url=f"https://example.invalid/e2e-crawl-quality-{index}",
            listing_rank=1,
            listing_payload={"title": "Search results"},
            detail_payload={
                "description": (
                    "Showing 1-20 of 532 jobs. Sort by relevance. "
                    "Create alert. Next page."
                )
            },
            detail_status="completed",
            detail_completed_at=now,
        )
        db.add_all((crawl_job, listing))
        settings = JevRuntimeSettingsService(db).get_or_create()
        settings.crawl_quality_enabled = True
        settings.crawl_quality_batch_limit = 20
        db.commit()
        return {
            "crawl_job_id": str(crawl_job_id),
            "listing_id": str(listing_id),
        }
    finally:
        db.close()


@app.get("/fake/crawl-quality-state/{crawl_job_id}/{listing_id}")
def fake_crawl_quality_state(crawl_job_id: UUID, listing_id: UUID) -> dict[str, object]:
    db = _session_factory()
    try:
        crawl_job = db.get(CrawlJob, crawl_job_id)
        listing = db.get(CrawlJobListing, listing_id)
        if crawl_job is None or listing is None:
            return JSONResponse(status_code=404, content={"error": "not found"})
        return {
            "crawl_job_status": crawl_job.status,
            "listing_detail_status": listing.detail_status,
        }
    finally:
        db.close()


@app.post("/fake/seed-search-rerank/{index}")
def fake_seed_search_rerank(index: int) -> dict[str, object]:
    if not 1 <= index <= 9:
        return JSONResponse(status_code=400, content={"error": "index must be 1..9"})
    db = _session_factory()
    try:
        company = Company(
            id=UUID(f"71000000-0000-0000-0000-{index:012d}"),
            company_id=f"e2e-search-company-{index}",
            source_site="jobsdb",
            source_company_id=f"e2e-search-company-{index}",
            name=f"Rerank Company {index}",
        )
        db.add(company)
        baseline_titles = []
        base_date = datetime(2026, 9, 20, tzinfo=UTC)
        for position in range(1, 6):
            title = f"Rerank Python Engineer {index}-{position}"
            baseline_titles.append(title)
            db.add(
                Job(
                    id=UUID(f"72000000-0000-0000-000{index}-{position:012d}"),
                    job_id=f"jobsdb:e2e-rerank-{index}-{position}",
                    source_site="jobsdb",
                    source_job_id=f"e2e-rerank-{index}-{position}",
                    company_id=company.id,
                    title=title,
                    description=(
                        f"rerank-batch-{index} Python ranking quality evidence "
                        f"for candidate {position}."
                    ),
                    location="Hong Kong",
                    posted_date=base_date - timedelta(days=position),
                    is_deleted=False,
                )
            )
        settings = JevRuntimeSettingsService(db).get_or_create()
        settings.search_rerank_enabled = True
        settings.search_rerank_candidate_limit = 5
        db.commit()
        return {"titles": baseline_titles}
    finally:
        db.close()


@app.post("/fake/seed-incidents/{index}")
def fake_seed_incidents(index: int) -> dict[str, object]:
    db = _session_factory()
    try:
        crawl_job = CrawlJob(
            id=UUID(f"81000000-0000-0000-0000-{index:012d}"),
            source_site="jobsdb",
            trigger_type="manual",
            status="failed",
            request_payload={
                "source_site": "jobsdb",
                "crawl_phase": "detail",
                "crawl_mode": "headless",
                "detail_scope": "crawl_scope",
                "detail_limit": 1,
                "removed_dispatch_plan": {
                    "reason": "historical_listing_deduplication",
                    "plan_id": str(UUID(f"82000000-0000-0000-0000-{index:012d}")),
                    "plan_fingerprint": "d" * 64,
                },
            },
            metrics={
                "detail_snapshot_target_count": 1,
                "detail_snapshot_fetched_count": 0,
                "detail_snapshot_saved_count": 0,
                "detail_snapshot_failed_count": 1,
                "detail_snapshot_unavailable_count": 0,
                "detail_snapshot_manual_action_count": 0,
                "detail_snapshot_remaining_count": 0,
                "detail_live_future_eligible_count": 0,
                "detail_run_cap": 1,
            },
            error_message="Failed at https://private.invalid/jobs/999 token=secret",
        )
        db.add(crawl_job)
        db.flush()
        for sequence in range(1, 4):
            db.add(
                CrawlJobEvent(
                    crawl_job_id=crawl_job.id,
                    sequence_no=sequence,
                    event_type="crawl.failed",
                    payload={
                        "error": (
                            f"Failed at https://private.invalid/jobs/{sequence} "
                            f"Authorization: Bearer secret-{sequence}"
                        ),
                        "stage": "detail",
                    },
                    emitted_by="e2e",
                )
            )
        settings = JevRuntimeSettingsService(db).get_or_create()
        settings.incident_triage_enabled = True
        settings.incident_triage_event_limit = 100
        db.commit()
        return {"crawl_job_id": str(crawl_job.id), "event_count": 3}
    finally:
        db.close()


@app.get("/fake/incident-state/{crawl_job_id}")
def fake_incident_state(crawl_job_id: UUID) -> dict[str, object]:
    db = _session_factory()
    try:
        crawl_job = db.get(CrawlJob, crawl_job_id)
        return {
            "crawl_job_status": crawl_job.status,
            "event_count": db.query(CrawlJobEvent).filter(
                CrawlJobEvent.crawl_job_id == crawl_job_id
            ).count(),
        }
    finally:
        db.close()


@app.post("/fake/execute-backfill/{run_id}")
async def fake_execute_backfill(run_id: str) -> dict[str, object]:
    db = _session_factory()
    try:
        run = await EnrichmentRunService(db).execute_run(
            run_id,
            backfill_service=JevSkillBackfillService(),
        )
        return {
            "id": run.id,
            "status": run.status,
            "completed_items": run.completed_items,
            "failed_items": run.failed_items,
        }
    finally:
        db.close()


@app.get("/fake/backfill-state/{job_id}")
def fake_backfill_state(job_id: str) -> dict[str, object]:
    db = _session_factory()
    try:
        job_uuid = UUID(job_id)
        classification = (
            db.query(JevOnlineSkillClassification)
            .filter(JevOnlineSkillClassification.job_id == job_uuid)
            .order_by(JevOnlineSkillClassification.created_at.desc())
            .first()
        )
        assignments = (
            db.query(CurrentJobSkillAssignment)
            .filter(CurrentJobSkillAssignment.job_id == job_uuid)
            .all()
        )
        return {
            "classification_status": classification.status if classification else None,
            "request_id": (classification.receipt or {}).get("request_id")
            if classification
            else None,
            "skills": sorted(row.skill_code for row in assignments),
        }
    finally:
        db.close()
