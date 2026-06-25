from __future__ import annotations

from datetime import UTC, datetime
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.models.company import Company
from app.models.job import Job
from app.models.job_embedding import JobEmbedding
from app.models.job_skill_mention import JobSkillMention
from app.models.job_subcategory import JobSubcategory
from app.models.job_category import JobCategory
from app.models.job_domain import JobDomain


def _tokenize(value: str | None) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").lower())
        if token
    }


def _cosine_similarity(lhs: list[float], rhs: list[float]) -> float:
    numerator = sum(left * right for left, right in zip(lhs, rhs))
    lhs_magnitude = sum(value * value for value in lhs) ** 0.5
    rhs_magnitude = sum(value * value for value in rhs) ** 0.5
    if lhs_magnitude == 0 or rhs_magnitude == 0:
        return 0.0
    return numerator / (lhs_magnitude * rhs_magnitude)


def _freshness_score(posted_date) -> float:
    if posted_date is None:
        return 0.0
    if posted_date.tzinfo is None:
        posted_date = posted_date.replace(tzinfo=UTC)
    age_days = max(0, (datetime.now(UTC) - posted_date).days)
    if age_days <= 7:
        return 1.0
    if age_days <= 30:
        return 0.7
    if age_days <= 90:
        return 0.4
    return 0.0


def _skill_overlap_score(source_skills: set[str], candidate_skills: set[str]) -> float:
    if not source_skills or not candidate_skills:
        return 0.0
    return len(source_skills & candidate_skills) / len(source_skills)


def _split_taxonomy_path(path: str | None) -> list[str]:
    return [
        segment.strip().lower()
        for segment in str(path or "").split("/")
        if segment.strip()
    ]


def _taxonomy_score(source_path: str | None, candidate_path: str | None) -> float:
    source_segments = _split_taxonomy_path(source_path)
    candidate_segments = _split_taxonomy_path(candidate_path)
    if not source_segments or not candidate_segments:
        return 0.0

    common_prefix = 0
    for source_segment, candidate_segment in zip(source_segments, candidate_segments):
        if source_segment != candidate_segment:
            break
        common_prefix += 1

    if common_prefix == 0:
        return 0.0

    return common_prefix / max(len(source_segments), len(candidate_segments))


class JobRecommendationService:
    def __init__(self, db):
        self.db = db

    def recommend_for_job(self, job_id: UUID, *, limit: int = 5) -> list[dict]:
        source_job = self._load_job(job_id)
        if source_job is None:
            raise ValueError(f"Job not found: {job_id}")

        source_embedding = self._load_embedding(job_id)
        if source_embedding is None:
            return []

        source_skills = {
            skill.strip().lower()
            for skill in getattr(source_job, "skills", []) or []
            if str(skill).strip()
        }
        source_taxonomy_path = getattr(source_job, "job_taxonomy_path", None)
        source_vector = list(source_embedding.embedding)

        ranked: list[tuple[float, float, float, Job, Company | None]] = []
        top_n = max(limit * 10, 50)
        for job, company, embedding_row in self._load_top_candidates(job_id, source_vector, top_n):
            candidate_skills = {
                skill.strip().lower()
                for skill in getattr(job, "skills", []) or []
                if str(skill).strip()
            }
            semantic_score = _cosine_similarity(source_vector, list(embedding_row.embedding))
            skill_overlap_score = _skill_overlap_score(source_skills, candidate_skills)
            taxonomy_score = _taxonomy_score(source_taxonomy_path, getattr(job, "job_taxonomy_path", None))
            freshness_score = _freshness_score(getattr(job, "posted_date", None))
            combined_score = (
                (semantic_score * 0.65)
                + (skill_overlap_score * 0.15)
                + (taxonomy_score * 0.15)
                + (freshness_score * 0.05)
            )
            ranked.append(
                (
                    combined_score,
                    semantic_score,
                    freshness_score,
                    job,
                    company,
                )
            )

        ranked.sort(
            key=lambda entry: (
                entry[0],
                entry[1],
                entry[2],
                getattr(entry[3], "posted_date", None) or datetime.min.replace(tzinfo=UTC),
                getattr(entry[3], "title", "") or "",
            ),
            reverse=True,
        )

        # Deduplicate by title (case-insensitive), keeping the highest-scored entry
        seen_titles: set[str] = set()
        deduped: list[tuple[float, float, float, Job, Company | None]] = []
        for entry in ranked:
            title_normalized = (getattr(entry[3], "title", "") or "").strip().lower()
            if title_normalized and title_normalized in seen_titles:
                continue
            if title_normalized:
                seen_titles.add(title_normalized)
            deduped.append(entry)

        recommendations = []
        for combined_score, semantic_score, freshness_score, job, company in deduped[:limit]:
            candidate_skills = {
                skill.strip().lower()
                for skill in getattr(job, "skills", []) or []
                if str(skill).strip()
            }
            recommendations.append(
                {
                    "id": job.id,
                    "job_id": job.job_id,
                    "title": job.title,
                    "company_name": company.name if company else getattr(job, "company_name", None),
                    "location": job.location,
                    "employment_type": job.employment_type,
                    "posted_date": job.posted_date.isoformat() if job.posted_date else None,
                    "job_taxonomy": job.job_taxonomy,
                    "semantic_score": round(semantic_score, 4),
                    "skill_overlap_score": round(_skill_overlap_score(source_skills, candidate_skills), 4),
                    "taxonomy_score": round(_taxonomy_score(source_taxonomy_path, getattr(job, "job_taxonomy_path", None)), 4),
                    "freshness_score": round(freshness_score, 4),
                    "combined_score": round(combined_score, 4),
                }
            )

        return recommendations

    def _load_job(self, job_id: UUID) -> Job | None:
        return (
            self.db.query(Job)
            .options(
                joinedload(Job.company),
                joinedload(Job.job_skill_mentions).joinedload(JobSkillMention.skill),
                joinedload(Job.subcategory).joinedload(JobSubcategory.category).joinedload(JobCategory.domain),
            )
            .filter(Job.id == job_id, Job.is_deleted.is_(False))
            .one_or_none()
        )

    def _load_embedding(self, job_id: UUID) -> JobEmbedding | None:
        return (
            self.db.query(JobEmbedding)
            .filter(JobEmbedding.job_id == job_id)
            .one_or_none()
        )

    def _load_top_candidates(self, excluded_job_id: UUID, source_vector: list[float], top_n: int):
        """Return top-N candidates ordered by cosine similarity using pgvector."""
        stmt = (
            select(Job, Company, JobEmbedding)
            .join(Company, Company.id == Job.company_id)
            .join(JobEmbedding, JobEmbedding.job_id == Job.id)
            .options(
                joinedload(Job.company),
                joinedload(Job.job_skill_mentions).joinedload(JobSkillMention.skill),
                joinedload(Job.subcategory).joinedload(JobSubcategory.category).joinedload(JobCategory.domain),
            )
            .filter(Job.id != excluded_job_id, Job.is_deleted.is_(False))
            .order_by(JobEmbedding.embedding.cosine_distance(source_vector))
            .limit(top_n)
        )
        return self.db.execute(stmt).unique().all()

    def _load_job(self, job_id: UUID) -> Job | None:
        return (
            self.db.query(Job)
            .options(
                joinedload(Job.company),
                joinedload(Job.job_skill_mentions).joinedload(JobSkillMention.skill),
                joinedload(Job.subcategory).joinedload(JobSubcategory.category).joinedload(JobCategory.domain),
            )
            .filter(Job.id == job_id, Job.is_deleted.is_(False))
            .one_or_none()
        )

    def _load_embedding(self, job_id: UUID) -> JobEmbedding | None:
        return (
            self.db.query(JobEmbedding)
            .filter(JobEmbedding.job_id == job_id)
            .one_or_none()
        )

    def _load_candidate_rows(self, excluded_job_id: UUID):
        return (
            self.db.query(Job, Company, JobEmbedding)
            .join(Company, Company.id == Job.company_id)
            .join(JobEmbedding, JobEmbedding.job_id == Job.id)
            .options(
                joinedload(Job.company),
                joinedload(Job.job_skill_mentions).joinedload(JobSkillMention.skill),
                joinedload(Job.subcategory).joinedload(JobSubcategory.category).joinedload(JobCategory.domain),
            )
            .filter(Job.id != excluded_job_id, Job.is_deleted.is_(False))
            .all()
        )
