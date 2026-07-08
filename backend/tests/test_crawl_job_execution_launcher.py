from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.services.crawl_job_execution_launcher import CrawlJobExecutionLauncher


def _crawl_job(source_site: str, payload: dict):
    return SimpleNamespace(
        id=uuid4(),
        source_site=source_site,
        request_payload=payload,
    )


def test_launcher_routes_offertoday_listing_to_standalone_script():
    launcher = CrawlJobExecutionLauncher(popen=lambda *args, **kwargs: None)
    job = _crawl_job("offertoday", {"crawl_phase": "listing", "max_pages": 1, "category_ids": [118000]})

    command = launcher.build_command(job)

    assert command[0] == "python"
    assert command[1].endswith("offertoday_standalone_crawl.py")
    assert command[-2:] == ["--crawl-job-id", str(job.id)]


def test_launcher_routes_jobsdb_listing_to_jobsdb_script():
    launcher = CrawlJobExecutionLauncher(popen=lambda *args, **kwargs: None)
    job = _crawl_job("jobsdb", {"crawl_phase": "listing", "max_pages": 1, "category_ids": [6281]})

    command = launcher.build_command(job)

    assert command[0] == "python"
    assert command[1].endswith("jobsdb_standalone_crawl.py")
    assert command[-2:] == ["--crawl-job-id", str(job.id)]


def test_launcher_routes_ctgoodjobs_listing_to_ctgoodjobs_script():
    launcher = CrawlJobExecutionLauncher(popen=lambda *args, **kwargs: None)
    job = _crawl_job("ctgoodjobs", {"crawl_phase": "listing", "max_pages": 1, "category_ids": ["it-jobs"]})

    command = launcher.build_command(job)

    assert command[0] == "python"
    assert command[1].endswith("ctgoodjobs_standalone_crawl.py")
    assert command[-2:] == ["--crawl-job-id", str(job.id)]
