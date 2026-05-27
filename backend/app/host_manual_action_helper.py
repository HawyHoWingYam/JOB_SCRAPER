from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Callable
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.repositories.crawl_job_repository import CrawlJobRepository


class ManualActionRequest(BaseModel):
    crawl_job_id: UUID


def _get_db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _load_manual_action_payload(
    db: Session,
    *,
    crawl_job_id: UUID,
    crawl_job_repository: CrawlJobRepository,
) -> dict[str, Any]:
    crawl_job = crawl_job_repository.get_crawl_job_by_id(db, crawl_job_id)
    if crawl_job is None:
        raise HTTPException(status_code=404, detail=f"Crawl job not found: {crawl_job_id}")
    if crawl_job.status != "manual_action_required":
        raise HTTPException(
            status_code=409,
            detail=f"Crawl job must be manual_action_required (got {crawl_job.status})",
        )

    latest_event = crawl_job_repository.get_latest_manual_action_event(db, crawl_job_id)
    if latest_event is None:
        raise HTTPException(status_code=409, detail="Crawl job has no resumable manual action payload")

    manual_action = dict((latest_event.payload or {}).get("manual_action") or {})
    if not manual_action:
        raise HTTPException(status_code=409, detail="Manual action payload is empty")
    return manual_action


def _default_browser_executable(browser_channel: str) -> str | None:
    normalized = str(browser_channel or "").strip().lower()
    candidates: dict[str, list[str]] = {
        "msedge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ],
        "chrome": [
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        ],
    }
    for candidate in candidates.get(normalized, []):
        if Path(candidate).exists():
            return candidate
    return None


def launch_browser_process(
    *,
    browser_channel: str,
    browser_profile_path: str,
    blocked_url: str,
    process_launcher: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> dict[str, Any]:
    executable_path = _default_browser_executable(browser_channel)
    if not executable_path:
        raise HTTPException(
            status_code=409,
            detail=f"Unsupported or unavailable browser channel: {browser_channel}",
        )

    process_launcher(
        [
            executable_path,
            f"--user-data-dir={browser_profile_path}",
            blocked_url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        close_fds=True,
    )
    return {
        "browser_channel": browser_channel,
        "browser_profile_path": browser_profile_path,
        "blocked_url": blocked_url,
    }


def capture_manual_action_screenshot(
    *,
    browser_channel: str,
    browser_profile_path: str,
    blocked_url: str,
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        launch_kwargs: dict[str, Any] = {
            "user_data_dir": browser_profile_path,
            "headless": True,
        }
        if browser_channel:
            launch_kwargs["channel"] = browser_channel
        executable_path = settings.jobsdb_headed_browser_executable_path
        if executable_path:
            launch_kwargs["executable_path"] = executable_path

        context = playwright.chromium.launch_persistent_context(**launch_kwargs)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(blocked_url, wait_until="domcontentloaded", timeout=30_000)
            screenshot_bytes = page.screenshot(type="png", full_page=True)
        finally:
            context.close()

    encoded_image = base64.b64encode(screenshot_bytes).decode("ascii")
    filename = f"manual-action-{int(time.time())}.png"
    return {
        "filename": filename,
        "content_type": "image/png",
        "image_base64": encoded_image,
    }


def _list_browser_processes(
    *,
    process_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[dict[str, Any]]:
    result = process_runner(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-CimInstance Win32_Process -Filter "
                "\"Name='msedge.exe' OR Name='chrome.exe'\" | "
                "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []

    payload = json.loads(result.stdout)
    if isinstance(payload, dict):
        payload = [payload]

    processes = []
    for row in payload:
        processes.append(
            {
                "pid": int(row.get("ProcessId")),
                "name": str(row.get("Name") or ""),
                "command_line": str(row.get("CommandLine") or ""),
            }
        )
    return processes


def _kill_process(
    pid: int,
    *,
    process_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    process_runner(
        ["taskkill", "/PID", str(pid), "/F"],
        capture_output=True,
        text=True,
        check=False,
    )


def close_profile_windows(
    *,
    browser_channel: str,
    browser_profile_path: str,
    process_lister: Callable[[], list[dict[str, Any]]] | None = None,
    process_killer: Callable[[int], None] | None = None,
) -> dict[str, int]:
    process_lister = process_lister or _list_browser_processes
    process_killer = process_killer or _kill_process

    normalized_channel = str(browser_channel or "").strip().lower()
    normalized_profile = str(browser_profile_path or "").strip().lower()
    if not normalized_profile:
        raise HTTPException(status_code=409, detail="Manual action is missing browser_profile_path")

    matched_pids: list[int] = []
    for process in process_lister():
        process_name = str(process.get("name") or "").strip().lower()
        if normalized_channel == "msedge" and process_name != "msedge.exe":
            continue
        if normalized_channel == "chrome" and process_name != "chrome.exe":
            continue
        command_line = str(process.get("command_line") or "").lower()
        if normalized_profile in command_line:
            matched_pids.append(int(process["pid"]))

    closed_count = 0
    for pid in matched_pids:
        process_killer(pid)
        closed_count += 1

    return {
        "matched_processes": len(matched_pids),
        "closed_processes": closed_count,
    }


def build_host_manual_action_helper_app(
    *,
    session_factory: Callable[[], Session] = SessionLocal,
    crawl_job_repository: CrawlJobRepository | None = None,
    browser_launcher: Callable[..., dict[str, Any]] = launch_browser_process,
    close_profile_windows: Callable[..., dict[str, int]] = close_profile_windows,
    screenshot_capturer: Callable[..., dict[str, Any]] = capture_manual_action_screenshot,
) -> FastAPI:
    crawl_job_repository = crawl_job_repository or CrawlJobRepository()
    app = FastAPI(title="Headed Manual Action Helper", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins.split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/manual-actions/open-browser")
    async def open_browser(request: ManualActionRequest):
        db = session_factory()
        try:
            manual_action = _load_manual_action_payload(
                db,
                crawl_job_id=request.crawl_job_id,
                crawl_job_repository=crawl_job_repository,
            )
        finally:
            db.close()

        blocked_url = str(manual_action.get("blocked_url") or "").strip()
        browser_channel = str(manual_action.get("browser_channel") or "").strip()
        browser_profile_path = str(manual_action.get("browser_profile_path") or "").strip()
        if not blocked_url or not browser_channel or not browser_profile_path:
            raise HTTPException(status_code=409, detail="Manual action is missing browser launch fields")
        return browser_launcher(
            browser_channel=browser_channel,
            browser_profile_path=browser_profile_path,
            blocked_url=blocked_url,
        )

    @app.post("/manual-actions/close-profile-windows")
    async def close_windows(request: ManualActionRequest):
        db = session_factory()
        try:
            manual_action = _load_manual_action_payload(
                db,
                crawl_job_id=request.crawl_job_id,
                crawl_job_repository=crawl_job_repository,
            )
        finally:
            db.close()

        browser_channel = str(manual_action.get("browser_channel") or "").strip()
        browser_profile_path = str(manual_action.get("browser_profile_path") or "").strip()
        if not browser_channel or not browser_profile_path:
            raise HTTPException(status_code=409, detail="Manual action is missing profile recovery fields")
        return close_profile_windows(
            browser_channel=browser_channel,
            browser_profile_path=browser_profile_path,
        )

    @app.post("/manual-actions/capture-screenshot")
    async def capture_screenshot(request: ManualActionRequest):
        db = session_factory()
        try:
            manual_action = _load_manual_action_payload(
                db,
                crawl_job_id=request.crawl_job_id,
                crawl_job_repository=crawl_job_repository,
            )
        finally:
            db.close()

        blocked_url = str(manual_action.get("blocked_url") or "").strip()
        browser_channel = str(manual_action.get("browser_channel") or "").strip()
        browser_profile_path = str(manual_action.get("browser_profile_path") or "").strip()
        if not blocked_url or not browser_channel or not browser_profile_path:
            raise HTTPException(status_code=409, detail="Manual action is missing screenshot capture fields")
        return screenshot_capturer(
            browser_channel=browser_channel,
            browser_profile_path=browser_profile_path,
            blocked_url=blocked_url,
        )

    return app


class HostManualActionHelperServer:
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int | None = None,
    ) -> None:
        import uvicorn

        self.host = host
        self.port = int(port or settings.jobsdb_headed_manual_action_helper_port)
        self.app = build_host_manual_action_helper_app()
        self.server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host=self.host,
                port=self.port,
                log_level="warning",
                access_log=False,
            )
        )
        self.server.install_signal_handlers = lambda: None
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        self.thread.start()
        deadline = time.time() + 5
        while time.time() < deadline:
            if self.server.started:
                return
            time.sleep(0.05)

    def stop(self) -> None:
        self.server.should_exit = True
        if self.thread.is_alive():
            self.thread.join(timeout=5)
