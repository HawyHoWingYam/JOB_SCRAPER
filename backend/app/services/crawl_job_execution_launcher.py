from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.crawl_modes import normalize_source_site


DIRECT_LAUNCH_SCRIPT_MAP = {
    "offertoday": "offertoday_standalone_crawl.py",
    "jobsdb": "jobsdb_standalone_crawl.py",
    "ctgoodjobs": "ctgoodjobs_standalone_crawl.py",
}


@dataclass(frozen=True)
class CrawlJobLaunchResult:
    launched: bool
    command: list[str] | None = None


class CrawlJobExecutionLauncher:
    def __init__(self, *, popen: Callable[..., Any] | None = None) -> None:
        self._popen = popen or subprocess.Popen

    def should_launch_locally(self, crawl_job) -> bool:
        return normalize_source_site(getattr(crawl_job, "source_site", "")) in DIRECT_LAUNCH_SCRIPT_MAP

    def build_command(self, crawl_job) -> list[str]:
        source_site = normalize_source_site(getattr(crawl_job, "source_site", ""))
        script_name = DIRECT_LAUNCH_SCRIPT_MAP.get(source_site)
        if not script_name:
            raise ValueError(f"Unsupported local crawl execution source_site: {source_site}")
        return [
            "python",
            self._resolve_script_path(script_name),
            "--crawl-job-id",
            str(crawl_job.id),
        ]

    def launch(self, crawl_job) -> CrawlJobLaunchResult:
        if not self.should_launch_locally(crawl_job):
            return CrawlJobLaunchResult(launched=False, command=None)
        command = self.build_command(crawl_job)
        self._popen(command)
        return CrawlJobLaunchResult(launched=True, command=command)

    @staticmethod
    def _resolve_script_path(script_name: str) -> str:
        container_path = Path("/app/scripts") / script_name
        if container_path.exists():
            return str(container_path)

        host_path = Path(__file__).resolve().parents[2] / "scripts" / script_name
        return str(host_path)
