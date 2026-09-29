"""Manually rebuild Job Browser embeddings from Job Description only."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from importlib import import_module

from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.models import Job, JobEmbedding
from app.search.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL_NAME
from app.repositories.job_embedding_repository import JobEmbeddingRepository
from app.services.embedding_document_builder import EmbeddingDocumentBuilder
from scripts.upgrade_job_embedding_contract import upgrade_job_embedding_contract


@dataclass
class RebuildSummary:
    inspected: int = 0
    rebuilt: int = 0
    skipped: int = 0


def rebuild_embeddings(*, batch_size: int, limit: int | None = None) -> RebuildSummary:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    model = import_module("sentence_transformers").SentenceTransformer(
        EMBEDDING_MODEL_NAME
    )
    builder = EmbeddingDocumentBuilder()
    repository = JobEmbeddingRepository()
    summary = RebuildSummary()
    db = SessionLocal()
    try:
        last_job_id = None
        while limit is None or summary.inspected < limit:
            page_size = batch_size
            if limit is not None:
                page_size = min(page_size, limit - summary.inspected)
            page_query = (
                db.query(Job)
                .options(joinedload(Job.company))
                .filter(Job.is_deleted.is_(False))
                .order_by(Job.id.asc())
            )
            if last_job_id is not None:
                page_query = page_query.filter(Job.id > last_job_id)
            jobs = page_query.limit(page_size).all()
            if not jobs:
                break

            stale_documents = []
            for job in jobs:
                summary.inspected += 1
                document = builder.build_for_job(job)
                existing = db.get(JobEmbedding, job.id)
                if (
                    existing is not None
                    and existing.document_hash == document.document_hash
                    and existing.document_contract == document.document_contract
                    and existing.embedding_dimensions == EMBEDDING_DIMENSIONS
                ):
                    summary.skipped += 1
                else:
                    stale_documents.append((job.id, document))
                last_job_id = job.id

            if stale_documents:
                vectors = model.encode(
                    [document.document_text for _job_id, document in stale_documents],
                    normalize_embeddings=True,
                )
                for (job_id, document), raw_vector in zip(
                    stale_documents,
                    vectors,
                    strict=True,
                ):
                    vector = list(raw_vector)
                    repository.upsert_embedding(
                        db,
                        job_id=job_id,
                        embedding_dimensions=len(vector),
                        document_text=document.document_text,
                        document_hash=document.document_hash,
                        document_contract=document.document_contract,
                        embedding=vector,
                        auto_commit=False,
                    )
                    summary.rebuilt += 1

            db.commit()
            print(
                f"inspected={summary.inspected} rebuilt={summary.rebuilt} "
                f"skipped={summary.skipped}",
                flush=True,
            )
        return summary
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    upgrade_job_embedding_contract()
    summary = rebuild_embeddings(batch_size=args.batch_size, limit=args.limit)
    print(
        f"complete inspected={summary.inspected} rebuilt={summary.rebuilt} "
        f"skipped={summary.skipped}"
    )


if __name__ == "__main__":
    main()
