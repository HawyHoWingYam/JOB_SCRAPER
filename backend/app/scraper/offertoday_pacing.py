from __future__ import annotations

from app.utils.anti_detection import ExponentialBackoff, random_delay


async def pause_before_detail_request() -> None:
    await random_delay(0.75, 2.25)


async def pause_after_transient_detail_failure(attempt: int) -> None:
    backoff = ExponentialBackoff(
        base_delay=1.0,
        max_delay=8.0,
        max_retries=3,
        jitter=0.25,
    )
    await backoff.wait(attempt)
