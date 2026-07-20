from __future__ import annotations

import asyncio
from importlib import import_module
import logging
from typing import Any
from uuid import UUID

from sqlalchemy.orm import joinedload

from app.config import settings
from app.database import SessionLocal
from app.logging_config import configure_logging
from app.messaging.outbox_publisher import OutboxPublisher
from app.messaging.redis_stream_bus import RedisStreamBus, StreamMessage
from app.messaging.topics import (
    STREAM_JOB_INTELLIGENCE_PROJECTIONS,
    STREAM_JOB_LIFECYCLE,
)
from app.models import Job
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.repositories.job_embedding_repository import JobEmbeddingRepository
from app.services.embedding_document_builder import EmbeddingDocumentBuilder
from app.services.embedding_indexer import EmbeddingIndexer
from app.services.governed_embedding_document_builder import (
    GovernedEmbeddingDocumentBuilder,
    SUPPORTED_GOVERNED_EMBEDDING_EVENTS,
)

try:
    SentenceTransformer = import_module("sentence_transformers").SentenceTransformer
except Exception:  # pragma: no cover - optional import gate
    SentenceTransformer = None


configure_logging(settings.log_level, settings.scraper_log_level)
logger = logging.getLogger(__name__)

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_VERSION = 1


def _build_default_embedding_model():
    if SentenceTransformer is None:  # pragma: no cover - import gate
        raise RuntimeError("sentence-transformers is not installed")
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


class EmbeddingWorkerService:
    def __init__(
        self,
        *,
        bus: RedisStreamBus | Any | None = None,
        outbox_publisher: OutboxPublisher | None = None,
        group_name: str = "embedding-workers",
        consumer_name: str = "embedding-worker",
        session_factory: Any | None = None,
        embedding_model=None,
        document_builder: EmbeddingDocumentBuilder | None = None,
        event_outbox_repository: EventOutboxRepository | None = None,
        job_embedding_repository: JobEmbeddingRepository | None = None,
        embedding_model_name: str = EMBEDDING_MODEL_NAME,
        embedding_version: int = EMBEDDING_VERSION,
    ):
        self.bus = bus or RedisStreamBus()
        self.outbox_publisher = outbox_publisher or OutboxPublisher(stream_bus=self.bus)
        self.group_name = group_name
        self.consumer_name = consumer_name
        self.session_factory = session_factory or SessionLocal
        self.embedding_model = embedding_model or _build_default_embedding_model()
        self.document_builder = document_builder or EmbeddingDocumentBuilder()
        self.event_outbox_repository = (
            event_outbox_repository or EventOutboxRepository()
        )
        self.job_embedding_repository = (
            job_embedding_repository or JobEmbeddingRepository()
        )
        self.embedding_model_name = embedding_model_name
        self.embedding_version = embedding_version
        self.governed_document_builder = GovernedEmbeddingDocumentBuilder(
            document_builder=self.document_builder,
        )
        self.embedding_indexer = EmbeddingIndexer(
            embedding_model=self.embedding_model,
            embedding_model_name=self.embedding_model_name,
            embedding_version=self.embedding_version,
            event_outbox_repository=self.event_outbox_repository,
            job_embedding_repository=self.job_embedding_repository,
        )
        self.bus.ensure_group(STREAM_JOB_LIFECYCLE, self.group_name)
        self.bus.ensure_group(
            STREAM_JOB_INTELLIGENCE_PROJECTIONS,
            self.group_name,
        )

    async def run_once(self) -> int:
        consumed: list[tuple[str, Any]] = []
        for topic, block_ms in (
            (STREAM_JOB_LIFECYCLE, 100),
            (STREAM_JOB_INTELLIGENCE_PROJECTIONS, 1),
        ):
            messages = self.bus.consume_group(
                topic,
                self.group_name,
                self.consumer_name,
                count=10,
                block_ms=block_ms,
            )
            consumed.extend((topic, message) for message in messages)
        for topic, message in consumed:
            await self._handle_message(message, topic=topic)
        return len(consumed)

    async def _handle_message(
        self,
        message: StreamMessage | Any,
        *,
        topic: str = STREAM_JOB_LIFECYCLE,
    ) -> None:
        event = message.event
        if event.event_type not in SUPPORTED_GOVERNED_EMBEDDING_EVENTS:
            self.bus.ack(topic, self.group_name, message.message_id)
            return

        db = self.session_factory()
        try:
            payload = dict(event.payload or {})
            job_id = UUID(str(payload.get("job_id") or event.aggregate_id))
            job = (
                db.query(Job)
                .options(
                    joinedload(Job.company),
                )
                .filter(Job.id == job_id)
                .one_or_none()
            )
            if job is None:
                raise ValueError(f"Job not found for embedding: {job_id}")

            document = self.governed_document_builder.build_for_job(
                db,
                job,
            )
            result = self.embedding_indexer.index(
                db,
                job_id=job_id,
                document=document,
                trigger_event_type=event.event_type,
                crawl_job_id=payload.get("crawl_job_id"),
            )
            if not result.changed:
                self.bus.ack(topic, self.group_name, message.message_id)
                return
            db.commit()
            self.outbox_publisher.publish_pending_batch(db, limit=100)
        except Exception:
            db.rollback()
            logger.exception(
                "embedding worker failed for event_id=%s",
                getattr(event, "event_id", None),
            )
            raise
        finally:
            db.close()

        self.bus.ack(topic, self.group_name, message.message_id)


async def main() -> None:
    logger.info("Starting embedding worker")
    service = EmbeddingWorkerService()
    while True:
        processed = await service.run_once()
        if processed == 0:
            await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())
