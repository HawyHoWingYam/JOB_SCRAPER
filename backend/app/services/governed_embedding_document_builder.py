from __future__ import annotations

from sqlalchemy.orm import Session

from app.job_intelligence.canonical_taxonomy.read_model import (
    CanonicalTaxonomyReader,
)
from app.job_intelligence.skill_governance import SkillGovernanceReader
from app.services.embedding_document_builder import (
    EmbeddingDocument,
    EmbeddingDocumentBuilder,
)


SUPPORTED_GOVERNED_EMBEDDING_EVENTS = frozenset(
    {
        "job.canonical_taxonomy_changed",
        "job.enriched",
        "job.ingested",
        "job.skill_projection_changed",
    }
)


class GovernedEmbeddingDocumentBuilder:
    """Compose one embedding document from governed projection readers."""

    def __init__(
        self,
        *,
        document_builder: EmbeddingDocumentBuilder | None = None,
    ) -> None:
        self.document_builder = document_builder or EmbeddingDocumentBuilder()

    def build_for_job(self, db: Session, job) -> EmbeddingDocument:
        skill_state = SkillGovernanceReader(db).get_job_state(job.id)
        taxonomy_document = CanonicalTaxonomyReader(db).build_embedding_document(job.id)
        return self.document_builder.build_for_job(
            job,
            governed_skill_names=(skill.name for skill in skill_state.skills),
            governed_taxonomy_document=(
                taxonomy_document.document_text
                if taxonomy_document is not None
                else None
            ),
        )


__all__ = [
    "GovernedEmbeddingDocumentBuilder",
    "SUPPORTED_GOVERNED_EMBEDDING_EVENTS",
]
