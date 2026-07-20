from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.messaging.topics import STREAM_JOB_EMBEDDING
from app.models.job_embedding import EMBEDDING_DIMENSIONS, JobEmbedding
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.repositories.job_embedding_repository import JobEmbeddingRepository
from app.services.embedding_document_builder import EmbeddingDocument


@dataclass(frozen=True)
class EmbeddingIndexResult:
    job_id: UUID
    changed: bool
    document_hash: str
    embedding_model: str
    embedding_version: int


class EmbeddingIndexer:
    """Persist one current embedding snapshot without owning the transaction."""

    def __init__(
        self,
        *,
        embedding_model: Any,
        embedding_model_name: str,
        embedding_version: int,
        event_outbox_repository: EventOutboxRepository | None = None,
        job_embedding_repository: JobEmbeddingRepository | None = None,
    ) -> None:
        self.embedding_model = embedding_model
        self.embedding_model_name = embedding_model_name
        self.embedding_version = embedding_version
        self.event_outbox_repository = (
            event_outbox_repository or EventOutboxRepository()
        )
        self.job_embedding_repository = (
            job_embedding_repository or JobEmbeddingRepository()
        )

    def is_current(
        self,
        existing: JobEmbedding | None,
        document: EmbeddingDocument,
    ) -> bool:
        return bool(
            existing is not None
            and existing.document_hash == document.document_hash
            and existing.embedding_model == self.embedding_model_name
            and existing.embedding_version == self.embedding_version
            and existing.embedding_dimensions == EMBEDDING_DIMENSIONS
        )

    def index(
        self,
        db: Session,
        *,
        job_id: UUID,
        document: EmbeddingDocument,
        trigger_event_type: str,
        crawl_job_id: object = None,
        source_service: str = "embedding-worker",
    ) -> EmbeddingIndexResult:
        existing = db.get(JobEmbedding, job_id)
        if self.is_current(existing, document):
            return EmbeddingIndexResult(
                job_id=job_id,
                changed=False,
                document_hash=document.document_hash,
                embedding_model=self.embedding_model_name,
                embedding_version=self.embedding_version,
            )

        embedding = list(
            self.embedding_model.encode(
                document.document_text,
                normalize_embeddings=True,
            )
        )
        self.job_embedding_repository.upsert_embedding(
            db,
            job_id=job_id,
            embedding_model=self.embedding_model_name,
            embedding_dimensions=len(embedding),
            embedding_version=self.embedding_version,
            document_text=document.document_text,
            document_hash=document.document_hash,
            embedding=embedding,
            auto_commit=False,
        )
        self.event_outbox_repository.enqueue(
            db,
            topic=STREAM_JOB_EMBEDDING,
            aggregate_type="job",
            aggregate_id=str(job_id),
            event_type="job.embedded",
            payload={
                "job_id": str(job_id),
                "crawl_job_id": crawl_job_id,
                "trigger_event_type": trigger_event_type,
                "document_hash": document.document_hash,
                "embedding_model": self.embedding_model_name,
                "embedding_version": self.embedding_version,
            },
            source_service=source_service,
            auto_commit=False,
        )
        return EmbeddingIndexResult(
            job_id=job_id,
            changed=True,
            document_hash=document.document_hash,
            embedding_model=self.embedding_model_name,
            embedding_version=self.embedding_version,
        )


__all__ = ["EmbeddingIndexer", "EmbeddingIndexResult"]
