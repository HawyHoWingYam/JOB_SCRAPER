from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from app.database import Base
from app.utils.time import utc_now


class JobEmbedding(Base):
    """Dedicated embedding table for vector-backed job retrieval."""

    __tablename__ = "job_embeddings"

    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    embedding_model = Column(String(255), nullable=False)
    embedding_dimensions = Column(Integer, nullable=False)
    embedding_version = Column(Integer, nullable=False, default=1)
    document_text = Column(Text, nullable=False)
    document_hash = Column(String(64), nullable=False, index=True)
    embedding = Column(Vector(), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    job = relationship("Job")
