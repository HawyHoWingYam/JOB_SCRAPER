from __future__ import annotations

import json

from app.messaging.event_envelope import build_event_envelope
from app.messaging.redis_stream_bus import RedisStreamBus


class FakeRedis:
    def __init__(self, *, autoclaim_response=None, readgroup_response=None) -> None:
        self.autoclaim_response = autoclaim_response if autoclaim_response is not None else ["0-0", [], []]
        self.readgroup_response = readgroup_response if readgroup_response is not None else []
        self.xautoclaim_calls: list[dict[str, object]] = []
        self.xreadgroup_calls: list[dict[str, object]] = []

    def xautoclaim(self, topic, group_name, consumer_name, *, min_idle_time, start_id, count):
        self.xautoclaim_calls.append(
            {
                "topic": topic,
                "group_name": group_name,
                "consumer_name": consumer_name,
                "min_idle_time": min_idle_time,
                "start_id": start_id,
                "count": count,
            }
        )
        return self.autoclaim_response

    def xreadgroup(self, group_name, consumer_name, topics, *, count, block):
        self.xreadgroup_calls.append(
            {
                "group_name": group_name,
                "consumer_name": consumer_name,
                "topics": topics,
                "count": count,
                "block": block,
            }
        )
        return self.readgroup_response


def _build_stream_values(*, event_type: str = "job.ingested"):
    envelope = build_event_envelope(
        event_type=event_type,
        aggregate_type="job",
        aggregate_id="job-1",
        source_service="test",
        payload={"job_id": "job-1"},
    )
    return {"data": json.dumps(envelope.to_dict())}


def test_consume_group_reclaims_stale_pending_messages_before_reading_new_entries():
    redis_client = FakeRedis(
        autoclaim_response=[
            "0-0",
            [("1710000000000-0", _build_stream_values())],
            [],
        ],
    )
    bus = RedisStreamBus(redis_client=redis_client)

    messages = bus.consume_group(
        "stream.job.ingest",
        "ingest-workers",
        "ingest-worker",
        count=5,
        block_ms=100,
        reclaim_idle_ms=60_000,
    )

    assert [message.message_id for message in messages] == ["1710000000000-0"]
    assert redis_client.xautoclaim_calls == [
        {
            "topic": "stream.job.ingest",
            "group_name": "ingest-workers",
            "consumer_name": "ingest-worker",
            "min_idle_time": 60_000,
            "start_id": "0-0",
            "count": 5,
        }
    ]
    assert redis_client.xreadgroup_calls == []


def test_consume_group_falls_back_to_new_messages_when_no_stale_pending_entries_exist():
    redis_client = FakeRedis(
        autoclaim_response=["0-0", [], []],
        readgroup_response=[
            (
                "stream.job.ingest",
                [("1710000000001-0", _build_stream_values(event_type="crawl.item_emitted"))],
            )
        ],
    )
    bus = RedisStreamBus(redis_client=redis_client)

    messages = bus.consume_group(
        "stream.job.ingest",
        "ingest-workers",
        "ingest-worker",
        count=5,
        block_ms=100,
        reclaim_idle_ms=60_000,
    )

    assert [message.message_id for message in messages] == ["1710000000001-0"]
    assert len(redis_client.xautoclaim_calls) == 1
    assert redis_client.xreadgroup_calls == [
        {
            "group_name": "ingest-workers",
            "consumer_name": "ingest-worker",
            "topics": {"stream.job.ingest": ">"},
            "count": 5,
            "block": 100,
        }
    ]
