import redis
import json
import logging
from typing import Any, Optional
from app.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Redis client for pub/sub and caching operations."""

    def __init__(self):
        self.redis = redis.from_url(settings.redis_url, decode_responses=True)
        self.pubsub = self.redis.pubsub()

    async def publish(self, channel: str, message: dict) -> None:
        """Publish a message to a Redis channel."""
        try:
            self.redis.publish(channel, json.dumps(message))
            logger.debug(f"Published to {channel}: {message}")
        except Exception as e:
            logger.error(f"Failed to publish to {channel}: {e}")

    async def subscribe(self, channel: str) -> None:
        """Subscribe to a Redis channel."""
        try:
            self.pubsub.subscribe(channel)
            logger.info(f"Subscribed to {channel}")
        except Exception as e:
            logger.error(f"Failed to subscribe to {channel}: {e}")

    async def get_message(self) -> Optional[dict]:
        """Get the next message from subscribed channels."""
        try:
            message = self.pubsub.get_message()
            if message and message["type"] == "message":
                return json.loads(message["data"])
        except Exception as e:
            logger.error(f"Failed to get message: {e}")
        return None

    async def set_cache(self, key: str, value: Any, ttl: int = 3600) -> None:
        """Set a value in Redis cache with TTL."""
        try:
            self.redis.setex(key, ttl, json.dumps(value))
            logger.debug(f"Cached {key} with TTL {ttl}s")
        except Exception as e:
            logger.error(f"Failed to cache {key}: {e}")

    async def get_cache(self, key: str) -> Optional[Any]:
        """Get a value from Redis cache."""
        try:
            value = self.redis.get(key)
            if value:
                return json.loads(value)
        except Exception as e:
            logger.error(f"Failed to get cache {key}: {e}")
        return None

    async def delete_cache(self, key: str) -> None:
        """Delete a value from Redis cache."""
        try:
            self.redis.delete(key)
            logger.debug(f"Deleted cache {key}")
        except Exception as e:
            logger.error(f"Failed to delete cache {key}: {e}")

    def close(self) -> None:
        """Close Redis connection."""
        self.redis.close()
