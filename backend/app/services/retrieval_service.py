from __future__ import annotations

from threading import Lock
import logging
import time
from typing import Any

from app.search.hybrid_ranker import rank_hybrid_rows
from app.search.embedding_contract import (
    EMBEDDING_MODEL_NAME,
    HYBRID_CANDIDATE_LIMIT,
    RANKED_RESULT_LIMIT,
)
from app.search.lexical_query import build_lexical_query
from app.search.semantic_query import (
    build_semantic_candidate_scope,
    extract_semantic_query_text,
    fetch_embedding_rows,
)

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - optional import gate
    SentenceTransformer = None


logger = logging.getLogger(__name__)


def _build_default_query_embedding_model():
    if SentenceTransformer is None:  # pragma: no cover - import gate
        raise RuntimeError("sentence-transformers is not installed")
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


class QueryEmbeddingModelProvider:
    """Own one lazily initialized query model for the retrieval process."""

    def __init__(self, *, factory=_build_default_query_embedding_model):
        self.factory = factory
        self._model = None
        self._lock = Lock()

    def get(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                started_at = time.perf_counter()
                self._model = self.factory()
                logger.info(
                    "Initialized query embedding model name=%s duration_ms=%.1f",
                    EMBEDDING_MODEL_NAME,
                    (time.perf_counter() - started_at) * 1000,
                )
        return self._model


DEFAULT_QUERY_EMBEDDING_MODEL_PROVIDER = QueryEmbeddingModelProvider()


class RetrievalService:
    def __init__(
        self,
        db,
        *,
        query_embedding_model: Any | None = None,
        query_embedding_model_provider: QueryEmbeddingModelProvider | None = None,
    ):
        self.db = db
        self.query_embedding_model = query_embedding_model
        self.query_embedding_model_provider = (
            query_embedding_model_provider or DEFAULT_QUERY_EMBEDDING_MODEL_PROVIDER
        )

    def _get_query_embedding_model(self):
        if self.query_embedding_model is None:
            self.query_embedding_model = self.query_embedding_model_provider.get()
        return self.query_embedding_model

    def facets(self, request):
        from app.services.job_search_facets import JobSearchFacets

        facet_scope = request.scope
        retrieval_mode = getattr(request, "retrieval_mode", "lexical")
        if retrieval_mode in {"semantic", "hybrid"} and extract_semantic_query_text(
            request.scope
        ):
            facet_scope = build_semantic_candidate_scope(request.scope)
        return JobSearchFacets(self.db).build(facet_scope)

    def search(self, request, *, layer_summaries=None):
        from app.api import jobs as jobs_api

        retrieval_mode = getattr(request, "retrieval_mode", "lexical")
        include_facets = getattr(request, "include_facets", True)
        if retrieval_mode == "lexical":
            query = build_lexical_query(self.db, request.scope)
            return jobs_api._build_search_response(
                query,
                page=request.page,
                page_size=request.page_size,
                applied_scope=request.scope,
                layer_summaries=layer_summaries,
                include_facets=include_facets,
                preserve_query_order=False,
                facets_override=None,
            )

        query_text = extract_semantic_query_text(request.scope)
        if not query_text:
            query = build_lexical_query(self.db, request.scope)
            return jobs_api._build_search_response(
                query,
                page=request.page,
                page_size=request.page_size,
                applied_scope=request.scope,
                layer_summaries=layer_summaries,
                include_facets=include_facets,
            )

        candidate_scope = build_semantic_candidate_scope(request.scope)
        query_vector = self._get_query_embedding_model().encode(
            query_text,
            normalize_embeddings=True,
        )

        from app.services.job_search_facets import JobSearchFacets

        if retrieval_mode == "semantic":
            query = build_lexical_query(self.db, candidate_scope)
            rows = fetch_embedding_rows(
                query,
                query_vector=query_vector,
                limit=RANKED_RESULT_LIMIT,
            )
            ranked_rows = [(job, company) for job, company, _embedding in rows]
            offset = (request.page - 1) * request.page_size
            return jobs_api._build_search_response_from_results(
                ranked_rows[offset : offset + request.page_size],
                total=len(ranked_rows),
                page=request.page,
                page_size=request.page_size,
                applied_scope=request.scope,
                layer_summaries=layer_summaries,
                facets=(
                    JobSearchFacets(self.db).build(candidate_scope)
                    if include_facets
                    else None
                ),
                db=self.db,
                result_kind="ranked",
                result_limit=RANKED_RESULT_LIMIT,
                ranked_candidate_count=len(rows),
            )

        if retrieval_mode == "hybrid":
            candidate_query = build_lexical_query(self.db, candidate_scope)
            rows = fetch_embedding_rows(
                candidate_query,
                query_vector=query_vector,
                limit=HYBRID_CANDIDATE_LIMIT,
            )
            ranked_rows = rank_hybrid_rows(
                rows,
                query_text=query_text,
                query_vector=list(query_vector),
            )[:RANKED_RESULT_LIMIT]
            offset = (request.page - 1) * request.page_size
            page_rows = ranked_rows[offset : offset + request.page_size]
            return jobs_api._build_search_response_from_results(
                page_rows,
                total=len(ranked_rows),
                page=request.page,
                page_size=request.page_size,
                applied_scope=request.scope,
                layer_summaries=layer_summaries,
                facets=(
                    JobSearchFacets(self.db).build(candidate_scope)
                    if include_facets
                    else None
                ),
                db=self.db,
                result_kind="ranked",
                result_limit=RANKED_RESULT_LIMIT,
                ranked_candidate_count=len(rows),
            )

        raise ValueError(f"Unsupported retrieval_mode: {retrieval_mode}")

    def export_csv(self, request) -> str:
        from app.api import jobs as jobs_api

        rows = self._collect_export_rows(request)
        return jobs_api._serialize_export_rows(rows)

    def _collect_export_rows(self, request):
        from app.api import jobs as jobs_api

        retrieval_mode = getattr(request, "retrieval_mode", "lexical")
        if retrieval_mode == "lexical":
            query = build_lexical_query(self.db, request.scope)
            jobs_api._validate_export_row_limit(query.order_by(None).count())
            return jobs_api._build_export_rows(query)

        query_text = extract_semantic_query_text(request.scope)
        if not query_text:
            query = build_lexical_query(self.db, request.scope)
            total = query.order_by(None).count()
            jobs_api._validate_export_row_limit(total)
            return jobs_api._build_export_rows(query)

        candidate_scope = build_semantic_candidate_scope(request.scope)
        query_vector = self._get_query_embedding_model().encode(
            query_text,
            normalize_embeddings=True,
        )

        if retrieval_mode == "semantic":
            query = build_lexical_query(self.db, candidate_scope)
            rows = fetch_embedding_rows(
                query,
                query_vector=query_vector,
                limit=RANKED_RESULT_LIMIT,
            )
            ranked_rows = [(job, company) for job, company, _embedding in rows]
            jobs_api._validate_export_row_limit(len(ranked_rows))
            return jobs_api._build_export_rows_from_results(ranked_rows)

        if retrieval_mode == "hybrid":
            candidate_query = build_lexical_query(self.db, candidate_scope)
            rows = fetch_embedding_rows(
                candidate_query,
                query_vector=query_vector,
                limit=HYBRID_CANDIDATE_LIMIT,
            )
            ranked_rows = rank_hybrid_rows(
                rows,
                query_text=query_text,
                query_vector=list(query_vector),
            )[:RANKED_RESULT_LIMIT]
            jobs_api._validate_export_row_limit(len(ranked_rows))
            return jobs_api._build_export_rows_from_results(ranked_rows)

        raise ValueError(f"Unsupported retrieval_mode: {retrieval_mode}")
