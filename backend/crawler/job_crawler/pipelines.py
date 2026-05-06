from __future__ import annotations

from crawler.job_crawler.emitters.redis_stream_emitter import RedisStreamEmitter
from crawler.job_crawler.items import CrawlProgressEvent
from app.sources.contracts import CanonicalScrapedJob


class RedisStreamPipeline:
    def __init__(self, emitter: RedisStreamEmitter | None = None):
        self.emitter = emitter or RedisStreamEmitter()

    def process_item(self, item, spider):
        if isinstance(item, CanonicalScrapedJob):
            self.emitter.emit_job(item)
            return item
        if isinstance(item, CrawlProgressEvent):
            self.emitter.emit_progress(item)
            return item
        return item

