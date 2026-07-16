from __future__ import annotations

import inspect
import random
from collections.abc import Callable
from typing import Any

from app.services.crawl_cancellation_token import resolve_cancellation_token
from app.services.scraper_pacing_settings_service import ResolvedDetailPacing


class DetailPacingController:
    """Admit serial outbound detail attempts using a cumulative task position."""

    def __init__(
        self,
        *,
        config: ResolvedDetailPacing,
        attempt_count: int = 0,
        cancellation_owner: Any,
        persist_attempt_count: Callable[[int], Any],
        uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.config = config
        self.attempt_count = max(int(attempt_count), 0)
        self.cancellation_token = resolve_cancellation_token(cancellation_owner)
        self.persist_attempt_count = persist_attempt_count
        self.uniform = uniform

    async def before_attempt(self) -> int:
        self.cancellation_token.raise_if_cancelled()
        if self.attempt_count > 0:
            if self.attempt_count % self.config.burst_size == 0:
                delay = self.config.burst_pause_seconds
            else:
                delay = self.uniform(
                    self.config.interval_min_seconds,
                    self.config.interval_max_seconds,
                )
            if delay > 0:
                await self.cancellation_token.sleep(delay)
        self.cancellation_token.raise_if_cancelled()
        self.attempt_count += 1
        result = self.persist_attempt_count(self.attempt_count)
        if inspect.isawaitable(result):
            await result
        return self.attempt_count


def build_detail_pacing_controller(
    *,
    request_payload: dict[str, Any] | None,
    crawl_job_id,
    crawl_runtime,
    cancellation_owner: Any,
    session_factory=None,
) -> DetailPacingController | None:
    raw_config = dict(request_payload or {}).get("detail_pacing")
    if not isinstance(raw_config, dict):
        return None

    if session_factory is None:
        from app.database import SessionLocal

        session_factory = SessionLocal

    attempt_count = 0
    if crawl_job_id:
        from app.models.crawl_job import CrawlJob

        db = session_factory()
        try:
            metrics = (
                db.query(CrawlJob.metrics)
                .filter(CrawlJob.id == crawl_job_id)
                .scalar()
            )
            if isinstance(metrics, dict):
                attempt_count = max(int(metrics.get("detail_attempt_count") or 0), 0)
        finally:
            db.close()

    def persist(value: int) -> None:
        if crawl_job_id:
            crawl_runtime.merge_metrics(
                crawl_job_id=crawl_job_id,
                metrics_patch={"detail_attempt_count": value},
            )

    return DetailPacingController(
        config=ResolvedDetailPacing.from_payload(raw_config),
        attempt_count=attempt_count,
        cancellation_owner=cancellation_owner,
        persist_attempt_count=persist,
    )
