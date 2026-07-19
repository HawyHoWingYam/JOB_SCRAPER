from __future__ import annotations

from typing import Any

from app.search.hybrid_ranker import rank_hybrid_rows
from app.search.lexical_query import build_lexical_query
from app.search.semantic_query import (
    apply_semantic_order,
    build_semantic_candidate_scope,
    extract_semantic_query_text,
    fetch_embedding_rows,
)

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - optional import gate
    SentenceTransformer = None


EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def _build_default_query_embedding_model():
    if SentenceTransformer is None:  # pragma: no cover - import gate
        raise RuntimeError("sentence-transformers is not installed")
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


class RetrievalService:
    def __init__(self, db, *, query_embedding_model: Any | None = None):
        self.db = db
        self.query_embedding_model = query_embedding_model

    def _get_query_embedding_model(self):
        if self.query_embedding_model is None:
            self.query_embedding_model = _build_default_query_embedding_model()
        return self.query_embedding_model

    def search(self, request, *, layer_summaries=None):
        from app.api import jobs as jobs_api

        retrieval_mode = getattr(request, "retrieval_mode", "lexical")
        if retrieval_mode == "lexical":
            query = build_lexical_query(self.db, request.scope)
            return jobs_api._build_search_response(
                query,
                page=request.page,
                page_size=request.page_size,
                applied_scope=request.scope,
                layer_summaries=layer_summaries,
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
            )

        candidate_scope = build_semantic_candidate_scope(request.scope)
        query_vector = self._get_query_embedding_model().encode(
            query_text,
            normalize_embeddings=True,
        )

        if retrieval_mode == "semantic":
            query = build_lexical_query(self.db, candidate_scope)
            ranked_query = apply_semantic_order(query, query_vector)
            return jobs_api._build_search_response(
                ranked_query,
                page=request.page,
                page_size=request.page_size,
                applied_scope=request.scope,
                layer_summaries=layer_summaries,
                preserve_query_order=True,
            )

        if retrieval_mode == "hybrid":
            candidate_query = build_lexical_query(self.db, candidate_scope)
            rows = fetch_embedding_rows(candidate_query)
            ranked_rows = rank_hybrid_rows(
                rows,
                query_text=query_text,
                query_vector=list(query_vector),
            )
            offset = (request.page - 1) * request.page_size
            page_rows = ranked_rows[offset:offset + request.page_size]
            return jobs_api._build_search_response_from_results(
                page_rows,
                total=len(ranked_rows),
                page=request.page,
                page_size=request.page_size,
                applied_scope=request.scope,
                layer_summaries=layer_summaries,
                db=self.db,
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
            total = query.order_by(None).count()
            jobs_api._validate_export_row_limit(total)
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
            ranked_query = apply_semantic_order(query, query_vector)
            total = ranked_query.order_by(None).count()
            jobs_api._validate_export_row_limit(total)
            return jobs_api._build_export_rows_from_results(ranked_query.all())

        if retrieval_mode == "hybrid":
            candidate_query = build_lexical_query(self.db, candidate_scope)
            rows = fetch_embedding_rows(candidate_query)
            ranked_rows = rank_hybrid_rows(
                rows,
                query_text=query_text,
                query_vector=list(query_vector),
            )
            jobs_api._validate_export_row_limit(len(ranked_rows))
            return jobs_api._build_export_rows_from_results(ranked_rows)

        raise ValueError(f"Unsupported retrieval_mode: {retrieval_mode}")
