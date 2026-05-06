from __future__ import annotations

from app.messaging.event_envelope import build_event_envelope
from app.messaging.redis_stream_bus import RedisStreamBus
from app.messaging.topics import STREAM_CRAWL_PROGRESS, STREAM_JOB_INGEST
from app.sources.contracts import CanonicalScrapedJob
from crawler.job_crawler.items import CrawlProgressEvent


class RedisStreamEmitter:
    def __init__(self, bus: RedisStreamBus | None = None):
        self.bus = bus or RedisStreamBus()

    def emit_job(self, item: CanonicalScrapedJob) -> str:
        payload = item.to_dict()
        envelope = build_event_envelope(
            event_type="crawl.item_emitted",
            aggregate_type="job",
            aggregate_id=payload["source_job_id"],
            payload=payload,
            source_service="crawl-worker",
        )
        return self.bus.publish(STREAM_JOB_INGEST, envelope)

    def emit_progress(self, event: CrawlProgressEvent) -> str:
        envelope = build_event_envelope(
            event_type=event.event_type,
            aggregate_type="crawl_job",
            aggregate_id=event.crawl_job_id,
            payload={
                "crawl_job_id": event.crawl_job_id,
                "source_site": event.source_site,
                **event.payload,
            },
            source_service="crawl-worker",
        )
        return self.bus.publish(STREAM_CRAWL_PROGRESS, envelope)

