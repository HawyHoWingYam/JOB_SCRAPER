import sys
import socket
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.workers import run_headed_crawl_worker


def test_validate_host_runtime_settings_rejects_docker_internal_database_host(tmp_path):
    profile_dir = tmp_path / "msedge"
    profile_dir.mkdir()

    with pytest.raises(RuntimeError, match="DATABASE_URL must point to a host-reachable address"):
        run_headed_crawl_worker.validate_host_runtime_settings(
            database_url="postgresql://admin:dev_password@postgres-db:5432/jobsdb",
            redis_url="redis://localhost:6379/0",
            browser_channel="msedge",
            browser_user_data_dir=str(profile_dir),
        )


def test_validate_host_runtime_settings_rejects_docker_internal_redis_host(tmp_path):
    profile_dir = tmp_path / "msedge"
    profile_dir.mkdir()

    with pytest.raises(RuntimeError, match="REDIS_URL must point to a host-reachable address"):
        run_headed_crawl_worker.validate_host_runtime_settings(
            database_url="postgresql://admin:dev_password@localhost:5433/jobsdb",
            redis_url="redis://redis-mq:6379/0",
            browser_channel="msedge",
            browser_user_data_dir=str(profile_dir),
        )


def test_validate_host_runtime_settings_rejects_missing_browser_profile_dir(tmp_path):
    missing_profile_dir = tmp_path / "missing-profile"

    with pytest.raises(RuntimeError, match="browser profile directory does not exist"):
        run_headed_crawl_worker.validate_host_runtime_settings(
            database_url="postgresql://admin:dev_password@localhost:5433/jobsdb",
            redis_url="redis://localhost:6379/0",
            browser_channel="msedge",
            browser_user_data_dir=str(missing_profile_dir),
        )


def test_validate_host_runtime_settings_accepts_localhost_services_and_existing_profile(tmp_path):
    profile_dir = tmp_path / "msedge"
    profile_dir.mkdir()

    result = run_headed_crawl_worker.validate_host_runtime_settings(
        database_url="postgresql://admin:dev_password@localhost:5433/jobsdb",
        redis_url="redis://localhost:6379/0",
        browser_channel="msedge",
        browser_user_data_dir=str(profile_dir),
    )

    assert result["database_url"] == "postgresql://admin:dev_password@localhost:5433/jobsdb"
    assert result["redis_url"] == "redis://localhost:6379/0"
    assert result["browser_channel"] == "msedge"
    assert result["browser_user_data_dir"] == str(profile_dir)


def test_acquire_single_instance_lock_rejects_second_holder():
    first = run_headed_crawl_worker.acquire_single_instance_lock(port=0)
    try:
        assigned_port = first.getsockname()[1]
        with pytest.raises(RuntimeError, match="Headed crawl worker is already running"):
            run_headed_crawl_worker.acquire_single_instance_lock(port=assigned_port)
    finally:
        first.close()


def test_headed_runner_registry_uses_ctgoodjobs_headed_spider(monkeypatch):
    class FakeJobsDBHeadedSpider:
        pass

    class FakeCTGoodJobsHeadedSpider:
        pass

    monkeypatch.setitem(
        sys.modules,
        "crawler.job_crawler.spiders.jobsdb_headed_spider",
        type("Module", (), {"JobsDBHeadedSpider": FakeJobsDBHeadedSpider})(),
    )
    monkeypatch.setitem(
        sys.modules,
        "crawler.job_crawler.spiders.ctgoodjobs_headed_spider",
        type("Module", (), {"CTGoodJobsHeadedSpider": FakeCTGoodJobsHeadedSpider})(),
    )

    registry = run_headed_crawl_worker._headed_runner_registry()

    assert isinstance(registry["jobsdb"], FakeJobsDBHeadedSpider)
    assert isinstance(registry["ctgoodjobs"], FakeCTGoodJobsHeadedSpider)
