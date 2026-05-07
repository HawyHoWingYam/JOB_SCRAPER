from __future__ import annotations

from copy import deepcopy

from app.models import Job, JobEmbedding
from app.api.job_search_parser import parse_search_expression
from app.schemas.job_search import JobSearchScopeSchema


def build_semantic_candidate_scope(scope: JobSearchScopeSchema) -> JobSearchScopeSchema:
    if not scope.layers:
        return scope

    cloned_scope = deepcopy(scope)
    cloned_scope.layers[-1].text_expression = ""
    return cloned_scope


def extract_semantic_query_text(scope: JobSearchScopeSchema) -> str:
    if not scope.layers:
        return ""
    last_expression = scope.layers[-1].text_expression
    parts = [clause.value.strip() for clause in parse_search_expression(last_expression) if clause.value.strip()]
    return " ".join(parts).strip()


def apply_semantic_order(query, query_vector):
    return (
        query.join(JobEmbedding, JobEmbedding.job_id == Job.id)
        .order_by(
            JobEmbedding.embedding.cosine_distance(query_vector),
            Job.posted_date.desc().nullslast(),
        )
    )


def fetch_embedding_rows(candidate_query):
    return (
        candidate_query.join(JobEmbedding, JobEmbedding.job_id == Job.id)
        .add_entity(JobEmbedding)
        .all()
    )
