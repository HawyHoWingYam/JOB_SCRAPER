import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.api.health as health_module


@pytest.mark.asyncio
async def test_health_check_includes_operator_runtime_summary(monkeypatch):
    monkeypatch.setattr(
        health_module,
        "refresh_llm_status",
        lambda *args: {"is_degraded": False, "degradation_reason": None},
    )
    monkeypatch.setattr(
        health_module,
        "build_operator_health_summary",
        lambda: {
            "status": "critical",
            "issues": ["ingest-worker is down", "stream.job.ingest lag is 5764"],
            "workers": {"ingest-worker": {"status": "down"}},
            "queues": {"stream.job.ingest": {"lag": 5764}},
            "freshness": {"jobs": {"newest_updated_at": "2026-05-20T13:40:46"}},
        },
    )

    payload = await health_module.health_check()

    assert payload["status"] == "degraded"
    assert payload["service"] == "backend-api"
    assert payload["operator"]["status"] == "critical"
    assert "ingest-worker is down" in payload["issues"]
    assert "stream.job.ingest lag is 5764" in payload["issues"]


def test_operator_health_summary_includes_backlog_outbox_and_embedding_metrics(monkeypatch):
    class _Query:
        def __init__(self, value=None, rows=None, count_value=0, joined_count_value=None):
            self.value = value
            self.rows = rows or []
            self.count_value = count_value
            self.joined_count_value = joined_count_value

        def scalar(self):
            return self.value

        def count(self):
            return self.count_value

        def join(self, *args, **kwargs):
            if self.joined_count_value is not None:
                return _Query(count_value=self.joined_count_value)
            return self

        def filter(self, *args, **kwargs):
            return self

        def group_by(self, *args, **kwargs):
            return self

        def all(self):
            return self.rows

    class _DB:
        def query(self, *entities):
            names = [getattr(entity, "__name__", str(entity)) for entity in entities]
            text = " ".join(names)
            if "CrawlJobListing.detail_status" in text:
                return _Query(rows=[("pending", 7), ("failed", 2)])
            if "EnrichmentRun.status" in text:
                return _Query(rows=[("queued", 3)])
            if "EventOutbox.status" in text:
                return _Query(rows=[("pending", 5), ("failed", 1)])
            if "JobEmbedding" in text:
                return _Query(count_value=12, joined_count_value=4)
            if "Job" in text:
                return _Query(count_value=10)
            return _Query()

        def close(self):
            pass

    monkeypatch.setattr(health_module, "SessionLocal", lambda: _DB())
    monkeypatch.setattr(
        health_module,
        "RedisStreamBus",
        lambda: type(
            "Bus",
            (),
            {
                "redis": type(
                    "Redis",
                    (),
                    {
                        "xlen": lambda self, stream: 0,
                        "xinfo_groups": lambda self, stream: [],
                    },
                )()
            },
        )(),
    )

    payload = health_module.build_operator_health_summary()

    assert payload["freshness"]["crawl_job_listings"]["pending"] == 7
    assert payload["freshness"]["crawl_job_listings"]["failed"] == 2
    assert payload["freshness"]["outbox"]["pending"] == 5
    assert payload["freshness"]["outbox"]["failed"] == 1
    assert payload["freshness"]["embeddings"]["total_embeddings"] == 12
    assert payload["freshness"]["embeddings"]["current_embeddings"] == 4
    assert payload["freshness"]["embeddings"]["missing_current_embeddings"] == 6
