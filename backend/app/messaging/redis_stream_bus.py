from __future__ import annotations

import json
from dataclasses import dataclass

import redis

from app.messaging.event_envelope import EventEnvelope
from app.messaging.topics import ALL_STREAM_TOPICS
from app.utils.redis_client import RedisClient


@dataclass(frozen=True)
class StreamMessage:
    message_id: str
    event: EventEnvelope


class RedisStreamBus:
    """Redis Streams transport for durable event delivery."""

    def __init__(self, redis_client: redis.Redis | None = None):
        self.redis = redis_client or RedisClient().redis

    def publish(self, topic: str, envelope: EventEnvelope) -> str:
        if topic not in ALL_STREAM_TOPICS:
            raise ValueError(f"Unsupported stream topic: {topic}")
        return self.redis.xadd(topic, {"data": json.dumps(envelope.to_dict())})

    def ensure_group(self, topic: str, group_name: str, start_id: str = "0") -> None:
        try:
            self.redis.xgroup_create(topic, group_name, id=start_id, mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def consume_group(
        self,
        topic: str,
        group_name: str,
        consumer_name: str,
        *,
        count: int = 10,
        block_ms: int = 1000,
    ) -> list[StreamMessage]:
        response = self.redis.xreadgroup(
            group_name,
            consumer_name,
            {topic: ">"},
            count=count,
            block=block_ms,
        )
        messages: list[StreamMessage] = []
        for _, stream_entries in response:
            for message_id, values in stream_entries:
                payload = json.loads(values["data"])
                messages.append(
                    StreamMessage(
                        message_id=message_id,
                        event=EventEnvelope(**payload),
                    )
                )
        return messages

    def ack(self, topic: str, group_name: str, message_id: str) -> int:
        return int(self.redis.xack(topic, group_name, message_id))
