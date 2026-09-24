from __future__ import annotations

import uuid

from sqlalchemy import UUID, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.api.skill_candidates import _candidate_evidence
from app.models.company import Company
from app.models.current_taxonomy import (
    CurrentJobSkillAssignment,
    CurrentJobSkillMention,
    CurrentSkillCandidate,
    CurrentTaxonomyAliasRecord,
    CurrentTaxonomyNodeRecord,
)
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.jev import (
    JevOnlineSkillClassification,
    JevRun,
    JevRunAttempt,
    JevRunItem,
    JevRuntimeSettings,
)
from app.models.job import Job
from app.models.manual_job import ManualJobEvidence
from app.models.source_job_attributes import EmploymentType, JobEmploymentType
from app.services.ai_enrichment_service import AIEnrichmentService
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService
from app.services.jev_skill_backfill import JevSkillBackfillPlanner


@compiles(UUID, "sqlite")
def _compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


class _InsightExtractor:
    async def extract(self, **_kwargs):
        return {
            "summary": "Build backend services",
            "skills": [
                {
                    "name": "Python",
                    "existing_skill": "Python",
                    "evidence": "Python is required.",
                }
            ],
            "confidence": 0.96,
            "experience": {
                "experience_level": "not_specified",
                "experience_min_years": None,
                "experience_max_years": None,
                "summary": None,
                "evidence": [],
            },
        }


def _session():
    engine = create_engine("sqlite:///:memory:")
    for table in (
        Company.__table__,
        Job.__table__,
        ManualJobEvidence.__table__,
        EmploymentType.__table__,
        JobEmploymentType.__table__,
        CurrentTaxonomyNodeRecord.__table__,
        CurrentTaxonomyAliasRecord.__table__,
        CurrentJobSkillAssignment.__table__,
        CurrentSkillCandidate.__table__,
        CurrentJobSkillMention.__table__,
        JevRuntimeSettings.__table__,
        JevRun.__table__,
        JevRunItem.__table__,
        JevRunAttempt.__table__,
        JevOnlineSkillClassification.__table__,
        EnrichmentRun.__table__,
        EnrichmentRunItem.__table__,
    ):
        table.create(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)()


async def _run_enrichment(db, monkeypatch):
    company = Company(
        company_id="manual-company",
        source_site="manual",
        source_company_id="manual-company",
        name="Example Co",
    )
    db.add(company)
    db.flush()
    job = Job(
        id=uuid.uuid4(),
        job_id="manual-job",
        source_site="manual",
        source_job_id="manual-job",
        company_id=company.id,
        title="Backend Engineer",
        description="Python is required.",
    )
    db.add(job)
    db.flush()
    db.add(
        ManualJobEvidence(
            job_id=job.id,
            evidence_hash="a" * 64,
            operator_authored_fields=["title", "description"],
        )
    )
    db.add(
        CurrentTaxonomyNodeRecord(
            taxonomy="skill",
            code="backend.python",
            parent_code=None,
            level="skill",
            labels={"en": "Python"},
            sort_order=1,
            is_assignable=True,
            is_active=True,
        )
    )
    settings = JevRuntimeSettingsService(db).get_or_create()
    settings.enabled = True
    settings.endpoint = "https://openrouter.ai/api/v1/systemone"
    settings.api_key = "test-openrouter-key"
    settings.model = "typesafe/jev-1.13-20260917"
    settings.evidence_threshold_millis = 900
    settings.recommendation_threshold_millis = 900
    db.commit()

    monkeypatch.setattr(
        "app.services.ai_enrichment_service.get_llm_status",
        lambda _scope: {"active_provider": "test", "active_model": "discovery"},
    )
    service = AIEnrichmentService()
    service.insight_extractor = _InsightExtractor()
    return job, await service.enrich_job(job, db)


def test_enrichment_projects_skills_without_starting_jev(monkeypatch) -> None:
    import asyncio

    engine, db = _session()
    try:
        job, result = asyncio.run(_run_enrichment(db, monkeypatch))

        assert result["status"] == "success"
        assert result["jev_skill_classification"] == {
            "status": "not_started",
            "reason": "manual_start_required",
            "apply_projection": False,
        }
        assignment = db.get(
            CurrentJobSkillAssignment,
            (job.id, "backend.python"),
        )
        assert assignment.source == "ai-extraction"
        assert db.query(JevOnlineSkillClassification).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_backfill_preview_selects_ai_enriched_work_until_manual_jev_runs(
    monkeypatch,
) -> None:
    import asyncio

    engine, db = _session()
    try:
        job, _result = asyncio.run(_run_enrichment(db, monkeypatch))

        current = JevSkillBackfillPlanner(db).inspect(limit=50)

        assert current.matching_historical_count == 1
        assert current.already_current_count == 0
        assert current.eligible_count == 1
        assert current.selected_job_ids == (str(job.id),)
    finally:
        db.close()
        engine.dispose()


def test_candidate_evidence_read_exposes_secret_safe_jev_receipt() -> None:
    engine, db = _session()
    try:
        company = Company(
            company_id="candidate-company",
            source_site="manual",
            source_company_id="candidate-company",
            name="Candidate Co",
        )
        db.add(company)
        db.flush()
        job = Job(
            id=uuid.uuid4(),
            job_id="candidate-job",
            source_site="manual",
            source_job_id="candidate-job",
            company_id=company.id,
            title="Frontend Engineer",
            description="React Native experience is useful.",
        )
        candidate = CurrentSkillCandidate(
            normalized_key="react native",
            canonical_raw_name="React Native",
            raw_variants=["React Native"],
            occurrence_count=1,
            distinct_job_count=1,
            evidence_summary={},
        )
        db.add_all((job, candidate))
        db.flush()
        db.add(
            CurrentJobSkillMention(
                job_id=job.id,
                taxonomy="skill",
                raw_name="React Native",
                normalized_key="react native",
                resolution="candidate",
                status="active",
                candidate_id=candidate.id,
                source="jev-classification",
                confidence=0.82,
                provenance={"method": "jev-online-classification"},
                evidence_hash="b" * 64,
            )
        )
        db.add(
            JevOnlineSkillClassification(
                job_id=job.id,
                input_fingerprint="c" * 64,
                taxonomy_snapshot_sha256="d" * 64,
                rubric_version="jev-online-skill-v1",
                status="answered",
                apply_projection=True,
                evidence_snapshot={
                    "candidates": [
                        {
                            "raw_name": "React Native",
                            "evidence": "React Native experience is useful.",
                        }
                    ]
                },
                decisions=[
                    {
                        "raw_name": "React Native",
                        "route": "candidate",
                        "evidence_disposition": "preferred",
                        "skill_code": None,
                        "confidence": 0.82,
                        "reason": "mapping_below_auto_threshold",
                        "probabilities": {"keep_candidate": 0.82},
                    }
                ],
                receipt={
                    "request_id": "gen-candidate-1",
                    "provider": "OpenRouter",
                    "model": "typesafe/jev-1.13",
                    "usage": {"input_tokens": 20, "output_tokens": 5},
                },
            )
        )
        db.flush()

        evidence = _candidate_evidence(db, (candidate.id,), limit=5)[candidate.id]

        assert evidence[0]["evidence_excerpt"] == ("React Native experience is useful.")
        assert evidence[0]["jev"]["status"] == "answered"
        assert evidence[0]["jev"]["decision"]["route"] == "candidate"
        assert evidence[0]["jev"]["request_id"] == "gen-candidate-1"
        assert "api_key" not in str(evidence[0])
    finally:
        db.close()
        engine.dispose()
