from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.embedding_document_builder import (
    EmbeddingDocument,
    EmbeddingDocumentBuilder,
)


SUPPORTED_CURRENT_EMBEDDING_EVENTS = frozenset(
    {
        "job.enriched",
        "job.ingested",
        "job.skill_projection_changed",
    }
)


class CurrentEmbeddingDocumentBuilder:
    """Build the current Description-only Job Browser embedding document."""

    def __init__(
        self,
        *,
        document_builder: EmbeddingDocumentBuilder | None = None,
    ) -> None:
        self.document_builder = document_builder or EmbeddingDocumentBuilder()

    def build_for_job(self, db: Session, job) -> EmbeddingDocument:
        return self.document_builder.build_for_job(job)


__all__ = [
    "CurrentEmbeddingDocumentBuilder",
    "SUPPORTED_CURRENT_EMBEDDING_EVENTS",
]
