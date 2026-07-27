from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.messaging.topics import ALL_STREAM_TOPICS


@dataclass(frozen=True)
class RedisClearReport:
    cleared_topics: tuple[str, ...]


class RedisRuntimeStateCleaner:
    """Delete complete stream keys, which also removes groups and pending entries."""

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    def clear(self) -> RedisClearReport:
        topics = tuple(sorted(ALL_STREAM_TOPICS))
        self._redis.delete(*topics)
        remaining = tuple(topic for topic in topics if self._redis.exists(topic))
        if remaining:
            raise RuntimeError(
                "Redis runtime state was not fully cleared: " + ", ".join(remaining)
            )
        return RedisClearReport(cleared_topics=topics)


__all__ = ["RedisClearReport", "RedisRuntimeStateCleaner"]
