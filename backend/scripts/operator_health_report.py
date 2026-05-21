#!/usr/bin/env python3
"""Print a single operator health report for the local runtime."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Callable

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.health import build_operator_health_summary


def _parse_docker_json(stdout: str) -> list[dict[str, Any]]:
    text = str(stdout or "").strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [row for row in parsed if isinstance(row, dict)]
    if isinstance(parsed, dict):
        return [parsed]

    services: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            services.append(row)
    return services


def collect_docker_compose_status(
    *,
    docker_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, Any]:
    try:
        result = docker_runner(
            ["docker", "compose", "ps", "-a", "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        return {"status": "unavailable", "services": [], "error": str(exc)}

    if result.returncode != 0:
        return {
            "status": "unavailable",
            "services": [],
            "error": str(result.stderr or result.stdout or "").strip(),
        }

    return {
        "status": "available",
        "services": _parse_docker_json(result.stdout),
    }


def collect_operator_health_report(
    *,
    health_builder: Callable[[], dict[str, Any]] = build_operator_health_summary,
    docker_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    include_docker: bool = True,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    timestamp = (now or (lambda: datetime.now(timezone.utc)))()
    report = {
        "generated_at": timestamp.isoformat(),
        "operator": health_builder(),
    }
    if include_docker:
        report["docker"] = collect_docker_compose_status(docker_runner=docker_runner)
    else:
        report["docker"] = {"status": "skipped", "services": []}
    return report


def _docker_service_name(row: dict[str, Any]) -> str:
    return str(row.get("Service") or row.get("Name") or row.get("service") or "unknown")


def _docker_service_state(row: dict[str, Any]) -> str:
    return str(row.get("State") or row.get("Status") or row.get("state") or "unknown")


def format_text_report(report: dict[str, Any]) -> str:
    operator = report.get("operator") or {}
    docker = report.get("docker") or {}
    freshness = operator.get("freshness") or {}

    lines = [
        f"Generated at: {report.get('generated_at')}",
        f"Operator status: {operator.get('status', 'unknown')}",
    ]

    issues = list(operator.get("issues") or [])
    if issues:
        lines.append("")
        lines.append("Issues:")
        lines.extend(f"- {issue}" for issue in issues)

    services = list(docker.get("services") or [])
    lines.append("")
    lines.append(f"Docker: {docker.get('status', 'unknown')}")
    if docker.get("error"):
        lines.append(f"- error: {docker['error']}")
    for row in services:
        lines.append(f"- {_docker_service_name(row)}: {_docker_service_state(row)}")

    queues = operator.get("queues") or {}
    if queues:
        lines.append("")
        lines.append("Queues:")
        for queue_name, queue in queues.items():
            lines.append(
                f"- {queue_name}: length={queue.get('length', 0)} "
                f"pending={queue.get('pending', 0)} lag={queue.get('lag', 0)}"
            )

    if freshness:
        lines.append("")
        lines.append("Freshness:")
        jobs = freshness.get("jobs") or {}
        lines.append(
            f"- jobs: total={jobs.get('total', 0)} newest_updated_at={jobs.get('newest_updated_at')}"
        )
        lines.append(f"- crawl_job_listings: {freshness.get('crawl_job_listings') or {}}")
        lines.append(f"- ai: {freshness.get('ai') or {}}")
        lines.append(f"- skills: {freshness.get('skills') or {}}")
        lines.append(f"- embeddings: {freshness.get('embeddings') or {}}")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--skip-docker", action="store_true", help="Skip docker compose ps")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = collect_operator_health_report(include_docker=not args.skip_docker)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_text_report(report))

    status = (report.get("operator") or {}).get("status")
    if status == "critical":
        return 2
    if status == "degraded":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
