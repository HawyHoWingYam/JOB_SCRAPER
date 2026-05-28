from __future__ import annotations

import asyncio

from app.workers.run_enrichment_worker import EnrichmentWorkerService


class FakeBus:
    def __init__(self) -> None:
        self.ensure_group_calls: list[tuple] = []
        self.consume_group_calls: list[dict[str, object]] = []

    def ensure_group(self, *args, **kwargs) -> None:
        self.ensure_group_calls.append((args, kwargs))

    def consume_group(self, topic, group_name, consumer_name, *, count=10, block_ms=100, reclaim_idle_ms=None):
        self.consume_group_calls.append(
            {
                "topic": topic,
                "group_name": group_name,
                "consumer_name": consumer_name,
                "count": count,
                "block_ms": block_ms,
                "reclaim_idle_ms": reclaim_idle_ms,
            }
        )
        return []


def test_enrichment_worker_attempts_to_reclaim_stale_pending_messages_before_waiting_for_new_work():
    bus = FakeBus()
    service = EnrichmentWorkerService(bus=bus)

    processed = asyncio.run(service.run_once())

    assert processed == 0
    assert bus.consume_group_calls == [
        {
            "topic": "stream.job.lifecycle",
            "group_name": "enrichment-workers",
            "consumer_name": "enrichment-worker",
            "count": 10,
            "block_ms": 100,
            "reclaim_idle_ms": 60_000,
        },
        {
            "topic": "stream.crawl.progress",
            "group_name": "enrichment-workers",
            "consumer_name": "enrichment-worker",
            "count": 10,
            "block_ms": 100,
            "reclaim_idle_ms": 60_000,
        },
    ]
