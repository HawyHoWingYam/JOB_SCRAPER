from __future__ import annotations

from datetime import UTC, datetime
import re
from uuid import UUID

from sqlalchemy import select

from app.job_intelligence.product_read_model import JobIntelligenceProductReadModel
from app.models.company import Company
from app.models.job import Job
from app.models.job_embedding import JobEmbedding


def _tokenize(value: str | None) -> set[str]:
    return {
        token for token in re.split(r"[^a-z0-9]+", str(value or "").lower()) if token
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


def _normalized_governed_skill_names(state: object) -> set[str]:
    if not isinstance(state, dict):
        return set()
    names = state.get("governed_skill_names")
    if not isinstance(names, (list, tuple)):
        return set()
    return {normalized for name in names if (normalized := str(name).strip().lower())}


def _canonical_taxonomy_segments(state: object) -> list[str]:
    if not isinstance(state, dict) or state.get("state") != "assigned":
        return []
    assignment = state.get("assignment")
    if not isinstance(assignment, dict):
        return []
    breadcrumb = assignment.get("breadcrumb")
    if not isinstance(breadcrumb, dict):
        return []

    segments: list[str] = []
    for level in ("domain", "category", "subcategory"):
        node = breadcrumb.get(level)
        if not isinstance(node, dict):
            return []
        code = str(node.get("code") or "").strip().lower()
        if not code:
            return []
        segments.append(code)
    return segments


def _taxonomy_score(
    source_segments: list[str],
    candidate_segments: list[str],
) -> float:
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

        source_vector = list(source_embedding.embedding)
        top_n = max(limit * 10, 50)
        candidate_rows = list(self._load_top_candidates(job_id, source_vector, top_n))
        projection_job_ids = [
            source_job.id,
            *(job.id for job, _company, _embedding in candidate_rows),
        ]
        product_reads = JobIntelligenceProductReadModel(self.db)
        employment_states = product_reads.get_employment_type_states(projection_job_ids)
        canonical_states = product_reads.get_canonical_job_states(projection_job_ids)
        skill_states = product_reads.get_governed_skill_name_states(projection_job_ids)
        source_skills = _normalized_governed_skill_names(skill_states[source_job.id])
        source_taxonomy_segments = _canonical_taxonomy_segments(
            canonical_states[source_job.id]["canonical_taxonomy"]
        )

        ranked: list[tuple[float, float, float, Job, Company | None]] = []
        for job, company, embedding_row in candidate_rows:
            candidate_skills = _normalized_governed_skill_names(skill_states[job.id])
            semantic_score = _cosine_similarity(
                source_vector, list(embedding_row.embedding)
            )
            skill_overlap_score = _skill_overlap_score(source_skills, candidate_skills)
            taxonomy_score = _taxonomy_score(
                source_taxonomy_segments,
                _canonical_taxonomy_segments(
                    canonical_states[job.id]["canonical_taxonomy"]
                ),
            )
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
                getattr(entry[3], "posted_date", None)
                or datetime.min.replace(tzinfo=UTC),
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
        for combined_score, semantic_score, freshness_score, job, company in deduped[
            :limit
        ]:
            candidate_skills = _normalized_governed_skill_names(skill_states[job.id])
            employment_state = employment_states[job.id]
            canonical_state = canonical_states[job.id]
            skill_state = skill_states[job.id]
            recommendations.append(
                {
                    "id": job.id,
                    "job_id": job.job_id,
                    "title": job.title,
                    "company_name": company.name
                    if company
                    else getattr(job, "company_name", None),
                    "location": job.location,
                    "employment_types": employment_state["employment_types"],
                    "posted_date": job.posted_date.isoformat()
                    if job.posted_date
                    else None,
                    "canonical_taxonomy": canonical_state["canonical_taxonomy"],
                    "job_intelligence_availability": {
                        "source_attributes": employment_state[
                            "source_attributes_availability"
                        ],
                        "canonical_taxonomy": canonical_state[
                            "canonical_taxonomy_availability"
                        ],
                        "skills": skill_state["skills_availability"],
                    },
                    "semantic_score": round(semantic_score, 4),
                    "skill_overlap_score": round(
                        _skill_overlap_score(source_skills, candidate_skills), 4
                    ),
                    "taxonomy_score": round(
                        _taxonomy_score(
                            source_taxonomy_segments,
                            _canonical_taxonomy_segments(
                                canonical_state["canonical_taxonomy"]
                            ),
                        ),
                        4,
                    ),
                    "freshness_score": round(freshness_score, 4),
                    "combined_score": round(combined_score, 4),
                }
            )

        return recommendations

    def _load_job(self, job_id: UUID) -> Job | None:
        return (
            self.db.query(Job)
            .filter(Job.id == job_id, Job.is_deleted.is_(False))
            .one_or_none()
        )

    def _load_embedding(self, job_id: UUID) -> JobEmbedding | None:
        return (
            self.db.query(JobEmbedding)
            .filter(JobEmbedding.job_id == job_id)
            .one_or_none()
        )

    def _load_top_candidates(
        self, excluded_job_id: UUID, source_vector: list[float], top_n: int
    ):
        """Return top-N candidates ordered by cosine similarity using pgvector."""
        stmt = (
            select(Job, Company, JobEmbedding)
            .join(Company, Company.id == Job.company_id)
            .join(JobEmbedding, JobEmbedding.job_id == Job.id)
            .filter(Job.id != excluded_job_id, Job.is_deleted.is_(False))
            .order_by(JobEmbedding.embedding.cosine_distance(source_vector))
            .limit(top_n)
        )
        return self.db.execute(stmt).unique().all()
