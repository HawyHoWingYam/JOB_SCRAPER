"""Tests for ScrapydClient."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.scrapyd_client import ScrapydClient, ScrapydClientError


class TestScrapydClient:
    def test_init_default_url(self) -> None:
        client = ScrapydClient()
        assert client._base_url == "http://scrapyd:6800"
        assert client._timeout == 10.0

    def test_init_custom_url(self) -> None:
        client = ScrapydClient("http://localhost:6800", timeout=5.0)
        assert client._base_url == "http://localhost:6800"
        assert client._timeout == 5.0

    @patch("app.services.scrapyd_client.httpx.get")
    def test_daemon_status_ok(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "status": "ok",
                "node_name": "node1",
                "pending": 2,
                "running": 1,
                "finished": 10,
            },
            raise_for_status=lambda: None,
        )
        client = ScrapydClient()
        result = client.daemon_status()
        assert result["status"] == "ok"
        assert result["node_name"] == "node1"

    @patch("app.services.scrapyd_client.httpx.post")
    def test_schedule_ok(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": "ok", "jobid": "abc123"},
            raise_for_status=lambda: None,
        )
        client = ScrapydClient()
        job_id = client.schedule("my_project", "my_spider")
        assert job_id == "abc123"

    @patch("app.services.scrapyd_client.httpx.post")
    def test_schedule_with_args(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": "ok", "jobid": "xyz789"},
            raise_for_status=lambda: None,
        )
        client = ScrapydClient()
        job_id = client.schedule(
            "proj", "spider", crawl_run_id="run-1", category_ids="112000"
        )
        assert job_id == "xyz789"
        # Verify the request data included spider args
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["data"]["crawl_run_id"] == "run-1"
        assert call_kwargs["data"]["category_ids"] == "112000"

    @patch("app.services.scrapyd_client.httpx.post")
    def test_schedule_failure(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": "error", "message": "unknown project"},
            raise_for_status=lambda: None,
        )
        client = ScrapydClient()
        with pytest.raises(ScrapydClientError, match="unknown project"):
            client.schedule("bad_project", "spider")

    @patch("app.services.scrapyd_client.httpx.post")
    def test_schedule_empty_jobid(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": "ok", "jobid": ""},
            raise_for_status=lambda: None,
        )
        client = ScrapydClient()
        with pytest.raises(ScrapydClientError, match="empty jobid"):
            client.schedule("proj", "spider")

    @patch("app.services.scrapyd_client.httpx.post")
    def test_cancel_ok(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": "ok", "prevstate": "running"},
            raise_for_status=lambda: None,
        )
        client = ScrapydClient()
        result = client.cancel("proj", "job-1")
        assert result is True

    @patch("app.services.scrapyd_client.httpx.post")
    def test_cancel_already_finished(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": "ok", "prevstate": None},
            raise_for_status=lambda: None,
        )
        client = ScrapydClient()
        result = client.cancel("proj", "job-1")
        assert result is False

    @patch("app.services.scrapyd_client.httpx.get")
    def test_list_jobs_ok(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "status": "ok",
                "pending": [],
                "running": [{"id": "job-1"}],
                "finished": [{"id": "job-2"}],
            },
            raise_for_status=lambda: None,
        )
        client = ScrapydClient()
        result = client.list_jobs("proj")
        assert len(result["running"]) == 1
        assert result["running"][0]["id"] == "job-1"

    @patch("app.services.scrapyd_client.httpx.get")
    def test_list_spiders_ok(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "status": "ok",
                "spiders": ["spider_a", "spider_b"],
            },
            raise_for_status=lambda: None,
        )
        client = ScrapydClient()
        result = client.list_spiders("proj")
        assert result == ["spider_a", "spider_b"]

    @patch("app.services.scrapyd_client.httpx.get")
    def test_http_error(self, mock_get: MagicMock) -> None:
        """Non-2xx response should raise the original HTTP error."""
        mock_get.return_value = MagicMock(
            status_code=502,
            raise_for_status=lambda: (_ for _ in ()).throw(
                httpx.HTTPStatusError("502", request=MagicMock(), response=MagicMock())
            ),
        )
        client = ScrapydClient()
        with pytest.raises(httpx.HTTPError):
            client.daemon_status()
