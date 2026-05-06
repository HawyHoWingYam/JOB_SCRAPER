from __future__ import annotations

from typing import Sequence

from sqlalchemy.orm import Session

from app.models.job_embedding import EMBEDDING_DIMENSIONS, JobEmbedding


class JobEmbeddingRepository:
    """Repository for the current embedding snapshot of each job."""

    def upsert_embedding(
        self,
        db: Session,
        *,
        job_id,
        embedding_model: str,
        embedding_dimensions: int,
        embedding_version: int,
        document_text: str,
        document_hash: str,
        embedding: Sequence[float],
        auto_commit: bool = True,
    ) -> JobEmbedding:
        embedding_values = list(embedding)

        if embedding_dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Job embeddings must declare {EMBEDDING_DIMENSIONS} dimensions, received {embedding_dimensions}",
            )

        if len(embedding_values) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Job embedding vector must contain {EMBEDDING_DIMENSIONS} values, received {len(embedding_values)}",
            )

        row = db.query(JobEmbedding).filter(JobEmbedding.job_id == job_id).one_or_none()
        if row is None:
            row = JobEmbedding(
                job_id=job_id,
                embedding_model=embedding_model,
                embedding_dimensions=EMBEDDING_DIMENSIONS,
                embedding_version=embedding_version,
                document_text=document_text,
                document_hash=document_hash,
                embedding=embedding_values,
            )
            db.add(row)
        else:
            row.embedding_model = embedding_model
            row.embedding_dimensions = EMBEDDING_DIMENSIONS
            row.embedding_version = embedding_version
            row.document_text = document_text
            row.document_hash = document_hash
            row.embedding = embedding_values

        if auto_commit:
            db.commit()
            db.refresh(row)
        else:
            db.flush()
        return row
