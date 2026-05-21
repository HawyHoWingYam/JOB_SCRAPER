import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class _CompletedProcess:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def test_collect_operator_health_report_includes_runtime_and_docker_summary():
    from scripts.operator_health_report import collect_operator_health_report, format_text_report

    def fake_health_summary():
        return {
            "status": "critical",
            "issues": ["stream.job.ingest group ingest-workers lag is 5764"],
            "queues": {"stream.job.ingest": {"lag": 5764, "pending": 42}},
            "workers": {"ingest-worker": {"status": "degraded"}},
            "freshness": {
                "jobs": {"total": 330, "newest_updated_at": "2026-05-20T13:40:46"},
                "crawl_job_listings": {"pending": 5436},
                "ai": {"pending_jobs": 270, "run_status_counts": {"failed": 17}},
                "skills": {"newest_mention_at": "2026-05-13T07:44:13"},
                "embeddings": {"newest_updated_at": "2026-05-20T13:40:54"},
            },
        }

    def fake_docker_runner(*args, **kwargs):
        assert args[0] == ["docker", "compose", "ps", "-a", "--format", "json"]
        return _CompletedProcess(
            '{"Service":"backend-api","State":"running"}\n'
            '{"Service":"ingest-worker","State":"exited"}\n'
        )

    report = collect_operator_health_report(
        health_builder=fake_health_summary,
        docker_runner=fake_docker_runner,
        now=lambda: datetime(2026, 5, 21, 9, 0, tzinfo=timezone.utc),
    )

    assert report["generated_at"] == "2026-05-21T09:00:00+00:00"
    assert report["operator"]["queues"]["stream.job.ingest"]["lag"] == 5764
    assert report["docker"]["status"] == "available"
    assert report["docker"]["services"] == [
        {"Service": "backend-api", "State": "running"},
        {"Service": "ingest-worker", "State": "exited"},
    ]

    text_report = format_text_report(report)
    assert "Operator status: critical" in text_report
    assert "stream.job.ingest group ingest-workers lag is 5764" in text_report
    assert "ingest-worker: exited" in text_report
