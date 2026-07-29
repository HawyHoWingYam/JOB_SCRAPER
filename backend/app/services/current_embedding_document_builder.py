from __future__ import annotations

from sqlalchemy.orm import Session

from app.job_intelligence.current_taxonomies import CurrentTaxonomyReader
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
    """Compose embeddings from ordinary current taxonomy projections."""

    def __init__(
        self,
        *,
        document_builder: EmbeddingDocumentBuilder | None = None,
    ) -> None:
        self.document_builder = document_builder or EmbeddingDocumentBuilder()

    def build_for_job(self, db: Session, job) -> EmbeddingDocument:
        reader = CurrentTaxonomyReader(db)
        skill_state = reader.get_job_skills(job.id)
        return self.document_builder.build_for_job(
            job,
            governed_skill_names=(skill.name for skill in skill_state.skills),
        )


__all__ = [
    "CurrentEmbeddingDocumentBuilder",
    "SUPPORTED_CURRENT_EMBEDDING_EVENTS",
]
