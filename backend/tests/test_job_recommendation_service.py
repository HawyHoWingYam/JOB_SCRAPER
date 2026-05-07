from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.job_recommendation_service import JobRecommendationService


def _job(
    *,
    job_id: str,
    title: str,
    company_name: str,
    skills: list[str],
    taxonomy_path: str,
    posted_date: datetime,
    location: str = "Hong Kong",
    employment_type: str = "Full-time",
):
    company = SimpleNamespace(name=company_name)
    return SimpleNamespace(
        id=uuid4(),
        job_id=job_id,
        title=title,
        company=company,
        company_name=company_name,
        location=location,
        employment_type=employment_type,
        posted_date=posted_date,
        skills=skills,
        job_taxonomy_path=taxonomy_path,
        job_taxonomy={"path": taxonomy_path},
    )


def _embedding(vector: list[float]):
    return SimpleNamespace(embedding=vector)


def test_recommend_for_job_ranks_candidates_by_semantic_and_metadata_signals(monkeypatch):
    service = JobRecommendationService(db=object())
    source_job = _job(
        job_id="source-job",
        title="Senior Platform Engineer",
        company_name="Acme Health",
        skills=["Python", "Kubernetes"],
        taxonomy_path="ICT / Software Development / Backend Development",
        posted_date=datetime.now(UTC) - timedelta(days=2),
    )
    strongest_match = _job(
        job_id="candidate-a",
        title="Platform Backend Engineer",
        company_name="Atlas Systems",
        skills=["Python", "Kubernetes", "FastAPI"],
        taxonomy_path="ICT / Software Development / Backend Development",
        posted_date=datetime.now(UTC) - timedelta(days=1),
    )
    weaker_match = _job(
        job_id="candidate-b",
        title="ERP Delivery Lead",
        company_name="Ops Forge",
        skills=["Python"],
        taxonomy_path="Business Systems / ERP / Delivery",
        posted_date=datetime.now(UTC) - timedelta(days=45),
    )

    monkeypatch.setattr(service, "_load_job", lambda job_id: source_job if job_id == source_job.id else None)
    monkeypatch.setattr(service, "_load_embedding", lambda job_id: _embedding([1.0, 0.0]) if job_id == source_job.id else None)
    monkeypatch.setattr(
        service,
        "_load_candidate_rows",
        lambda excluded_job_id: [
            (strongest_match, strongest_match.company, _embedding([0.99, 0.01])),
            (weaker_match, weaker_match.company, _embedding([0.72, 0.28])),
        ],
    )

    recommendations = service.recommend_for_job(source_job.id, limit=2)

    assert [item["job_id"] for item in recommendations] == ["candidate-a", "candidate-b"]
    assert recommendations[0]["semantic_score"] > recommendations[1]["semantic_score"]
    assert recommendations[0]["skill_overlap_score"] > recommendations[1]["skill_overlap_score"]
    assert recommendations[0]["taxonomy_score"] > recommendations[1]["taxonomy_score"]
    assert recommendations[0]["combined_score"] > recommendations[1]["combined_score"]


def test_recommend_for_job_returns_empty_list_when_source_embedding_is_missing(monkeypatch):
    service = JobRecommendationService(db=object())
    source_job = _job(
        job_id="source-job",
        title="Senior Platform Engineer",
        company_name="Acme Health",
        skills=["Python"],
        taxonomy_path="ICT / Software Development / Backend Development",
        posted_date=datetime.now(UTC) - timedelta(days=2),
    )

    monkeypatch.setattr(service, "_load_job", lambda _job_id: source_job)
    monkeypatch.setattr(service, "_load_embedding", lambda _job_id: None)
    monkeypatch.setattr(service, "_load_candidate_rows", lambda _excluded_job_id: (_ for _ in ()).throw(AssertionError("candidate loading should be skipped")))

    assert service.recommend_for_job(source_job.id, limit=5) == []


def test_recommend_for_job_raises_for_missing_source_job():
    service = JobRecommendationService(db=object())
    missing_job_id = uuid4()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(service, "_load_job", lambda job_id: None if job_id == missing_job_id else object())

    with pytest.raises(ValueError, match="Job not found"):
        service.recommend_for_job(missing_job_id)

    monkeypatch.undo()
