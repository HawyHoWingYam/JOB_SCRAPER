from __future__ import annotations

import asyncio
import os

from app.database import SessionLocal
from app.models.crawl_job import CrawlJob
from app.models.crawl_job_execution import CrawlJobExecution
from app.utils.time import utc_now


EXECUTION_GENERATION_ENV = "CRAWL_JOB_EXECUTION_GENERATION"


class CrawlCancellationRequested(RuntimeError):
    pass


class NoopCrawlCancellationToken:
    def raise_if_cancelled(self) -> None:
        return None

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(float(seconds), 0.0))


def resolve_cancellation_token(
    owner,
) -> CrawlCancellationToken | NoopCrawlCancellationToken:
    token = getattr(owner, "cancellation_token", None)
    return token if token is not None else NoopCrawlCancellationToken()


class CrawlCancellationToken:
    """Persisted cooperative cancellation gate used immediately before I/O."""

    def __init__(
        self,
        *,
        crawl_job_id,
        execution_generation: str | None = None,
        session_factory=SessionLocal,
    ) -> None:
        self.crawl_job_id = crawl_job_id
        self.execution_generation = (
            execution_generation or os.getenv(EXECUTION_GENERATION_ENV) or None
        )
        self.session_factory = session_factory

    def raise_if_cancelled(self) -> None:
        if not self.crawl_job_id:
            return
        db = self.session_factory()
        try:
            status = (
                db.query(CrawlJob.status)
                .filter(CrawlJob.id == self.crawl_job_id)
                .scalar()
            )
            if self.execution_generation:
                (
                    db.query(CrawlJobExecution)
                    .filter(CrawlJobExecution.generation == self.execution_generation)
                    .update(
                        {CrawlJobExecution.heartbeat_at: utc_now()},
                        synchronize_session=False,
                    )
                )
                db.commit()
            if str(status or "").strip().lower() in {"cancelling", "cancelled"}:
                raise CrawlCancellationRequested(
                    f"Cancellation requested for crawl job {self.crawl_job_id}"
                )
        finally:
            db.close()

    async def sleep(self, seconds: float) -> None:
        remaining = max(float(seconds), 0.0)
        while remaining > 0:
            self.raise_if_cancelled()
            slice_seconds = min(remaining, 1.0)
            await asyncio.sleep(slice_seconds)
            remaining -= slice_seconds
        self.raise_if_cancelled()
