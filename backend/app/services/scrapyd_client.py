"""Scrapyd HTTP client for managing Scrapy spider deployments and jobs.

Scrapyd API (v1):
  - GET  /daemonstatus.json  → daemon status
  - POST /schedule.json      → schedule a spider run
  - POST /cancel.json        → cancel a job
  - GET  /listprojects.json  → list deployed projects
  - GET  /listspiders.json?project=... → list spiders for a project
  - GET  /listjobs.json?project=... → list jobs by status
  - POST /addversion.json    → deploy a project egg
  - POST /delversion.json    → delete a project version
  - POST /delproject.json    → delete a project

This client wraps the subset needed by the FastAPI crawl admin facade.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_SCRAPYD_URL = "http://scrapyd:6800"
DEFAULT_TIMEOUT = 10.0


class ScrapydClientError(RuntimeError):
    """Raised when Scrapyd returns an error response."""


class ScrapydClient:
    """Lightweight HTTP client for a single Scrapyd instance."""

    def __init__(
        self,
        base_url: str = DEFAULT_SCRAPYD_URL,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    # -- Status ----------------------------------------------------------------

    def daemon_status(self) -> dict[str, Any]:
        """Check Scrapyd daemon health."""
        resp = httpx.get(self._url("/daemonstatus.json"), timeout=self._timeout)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data

    # -- Schedule --------------------------------------------------------------

    def schedule(
        self,
        project: str,
        spider: str,
        *,
        settings: dict[str, Any] | None = None,
        **spider_args: Any,
    ) -> str:
        """Schedule a spider run and return the Scrapyd job ID.

        Args:
            project: Scrapyd project name (e.g. "job_scraper_spiders").
            spider: Spider name (e.g. "offertoday").
            settings: Optional Scrapy settings overrides (passed as keys).
            **spider_args: Spider arguments (passed as -a key=value).

        Returns:
            The Scrapyd job ID string.
        """
        data: dict[str, Any] = {
            "project": project,
            "spider": spider,
        }
        if settings:
            data["setting"] = [
                f"{key}={value}" for key, value in settings.items()
            ]
        for key, value in spider_args.items():
            data[key] = str(value)

        resp = httpx.post(
            self._url("/schedule.json"),
            data=data,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        if result.get("status") != "ok":
            raise ScrapydClientError(
                f"Scrapyd schedule failed: {result.get('message', 'unknown')}"
            )
        job_id: str = str(result.get("jobid", ""))
        if not job_id:
            raise ScrapydClientError("Scrapyd schedule returned empty jobid")
        logger.info(
            "Scheduled spider %s/%s → scrapyd_job_id=%s",
            project,
            spider,
            job_id,
        )
        return job_id

    # -- Cancel ----------------------------------------------------------------

    def cancel(self, project: str, job_id: str) -> bool:
        """Cancel a running/pending job.

        Returns True if a job was actually cancelled.
        """
        resp = httpx.post(
            self._url("/cancel.json"),
            data={"project": project, "job": job_id},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        prev_state = result.get("prevstate")
        was_cancelled = prev_state is not None
        logger.info(
            "Cancel scrapyd_job=%s prev_state=%s", job_id, prev_state
        )
        return was_cancelled

    # -- List Jobs -------------------------------------------------------------

    def list_jobs(self, project: str) -> dict[str, list[dict[str, Any]]]:
        """List all jobs (pending, running, finished) for a project.

        Returns a dict like {"pending": [...], "running": [...], "finished": [...]}.
        """
        resp = httpx.get(
            self._url("/listjobs.json"),
            params={"project": project},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        if result.get("status") != "ok":
            raise ScrapydClientError(
                f"Scrapyd listjobs failed: {result.get('message', 'unknown')}"
            )
        return {
            "pending": result.get("pending", []),
            "running": result.get("running", []),
            "finished": result.get("finished", []),
        }

    # -- List Spiders ----------------------------------------------------------

    def list_spiders(self, project: str) -> list[str]:
        """List available spider names for a project."""
        resp = httpx.get(
            self._url("/listspiders.json"),
            params={"project": project},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        if result.get("status") != "ok":
            raise ScrapydClientError(
                f"Scrapyd listspiders failed: {result.get('message', 'unknown')}"
            )
        spiders: list[str] = result.get("spiders", [])
        return spiders
