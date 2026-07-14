from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import PureWindowsPath
from pathlib import Path
import socket
import subprocess
import threading
import time
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import urlopen
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database import SessionLocal
from app.manual_actions.live_browser_registry import (
    LiveBrowserRegistry,
    get_live_browser_registry,
    normalize_browser_profile_path,
)
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.scraper.manual_action import (
    RESUME_STRATEGY_FRESH_PROFILE,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
    normalize_manual_action_payload,
)


logger = logging.getLogger(__name__)


class ManualActionRequest(BaseModel):
    crawl_job_id: UUID


def reserve_remote_debugging_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _is_default_browser_profile_path(browser_profile_path: str) -> bool:
    normalized = normalize_browser_profile_path(browser_profile_path)
    if not normalized:
        return True

    path_obj = PureWindowsPath(normalized)
    parts = list(path_obj.parts)
    if len(parts) < 4:
        return False

    lower_parts = [part.lower() for part in parts]
    known_user_data_prefixes = [
        ["google", "chrome", "user data"],
        ["microsoft", "edge", "user data"],
    ]
    for prefix in known_user_data_prefixes:
        for index in range(len(lower_parts) - len(prefix) + 1):
            if lower_parts[index:index + len(prefix)] != prefix:
                continue
            tail = lower_parts[index + len(prefix):]
            if not tail:
                return True
            if len(tail) == 1 and (tail[0] == "default" or re.fullmatch(r"profile \d+", tail[0])):
                return True
    return False


def probe_live_browser_session(session: Any) -> bool:
    debug_port = getattr(session, "debug_port", None)
    if not debug_port:
        return False

    try:
        with urlopen(f"http://127.0.0.1:{int(debug_port)}/json/version", timeout=1.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError, TimeoutError):
        return False

    return bool(payload.get("webSocketDebuggerUrl") or payload.get("Browser"))


def _ensure_non_default_browser_profile(browser_profile_path: str) -> None:
    if _is_default_browser_profile_path(browser_profile_path):
        raise HTTPException(
            status_code=409,
            detail="Remote debugging requires a non-default automation browser profile",
        )


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

    latest_event_payload = dict(latest_event.payload or {})
    manual_action = normalize_manual_action_payload(
        latest_event_payload.get("manual_action"),
        source_site=crawl_job.source_site,
        request_payload=(
            latest_event_payload.get("request_payload")
            or crawl_job.request_payload
            or {}
        ),
        default_browser_channel=settings.jobsdb_headed_browser_channel,
        default_browser_profile_path=settings.jobsdb_headed_browser_user_data_dir,
    )
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
    live_browser_registry: LiveBrowserRegistry | None = None,
    port_reserver: Callable[[], int] = reserve_remote_debugging_port,
    process_launcher: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> dict[str, Any]:
    executable_path = _default_browser_executable(browser_channel)
    if not executable_path:
        raise HTTPException(
            status_code=409,
            detail=f"Unsupported or unavailable browser channel: {browser_channel}",
        )
    _ensure_non_default_browser_profile(browser_profile_path)

    debug_port = int(port_reserver())
    logger.info(
        "manual_action_browser_launch",
        extra={
            "browser_channel": browser_channel,
            "browser_profile_path": browser_profile_path,
            "blocked_url": blocked_url,
            "debug_port": debug_port,
        },
    )

    process_launcher(
        [
            executable_path,
            f"--user-data-dir={browser_profile_path}",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={debug_port}",
            blocked_url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        close_fds=True,
    )
    registry = live_browser_registry or get_live_browser_registry()
    session = registry.register(
        browser_channel=browser_channel,
        browser_profile_path=browser_profile_path,
        blocked_url=blocked_url,
        debug_port=debug_port,
        status="live",
    )
    return session.to_dict()


def _build_screenshot_payload(screenshot_bytes: bytes) -> dict[str, Any]:
    encoded_image = base64.b64encode(screenshot_bytes).decode("ascii")
    filename = f"manual-action-{int(time.time())}.png"
    return {
        "filename": filename,
        "content_type": "image/png",
        "image_base64": encoded_image,
    }


def capture_manual_action_screenshot(
    *,
    browser_channel: str,
    browser_profile_path: str,
    blocked_url: str,
    crawl_job_id: UUID | None = None,
    resume_strategy: str | None = None,
    live_browser_registry: LiveBrowserRegistry | None = None,
    session_reachability_probe: Callable[[Any], bool] = probe_live_browser_session,
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    registry = live_browser_registry or get_live_browser_registry()
    selected_strategy = str(resume_strategy or "").strip() or RESUME_STRATEGY_FRESH_PROFILE
    playwright = sync_playwright().start()
    try:
        if selected_strategy == RESUME_STRATEGY_REUSE_OPEN_BROWSER:
            live_session = _get_reusable_live_browser_session(
                registry=registry,
                browser_profile_path=browser_profile_path,
                reachability_probe=session_reachability_probe,
            )
            if live_session is not None:
                logger.info(
                    "manual_action_registry_reuse_hit",
                    extra={
                        "crawl_job_id": crawl_job_id,
                        "strategy": selected_strategy,
                        "browser_channel": browser_channel,
                        "browser_profile_path": browser_profile_path,
                        "debug_port": live_session.debug_port,
                    },
                )
                logger.info(
                    "manual_action_screenshot_attach_attempt",
                    extra={
                        "crawl_job_id": crawl_job_id,
                        "strategy": selected_strategy,
                        "browser_channel": browser_channel,
                        "browser_profile_path": browser_profile_path,
                        "debug_port": live_session.debug_port,
                    },
                )
                try:
                    browser = playwright.chromium.connect_over_cdp(
                        f"http://127.0.0.1:{live_session.debug_port}"
                    )
                    context = browser.contexts[0] if browser.contexts else None
                    if context is None:
                        raise RuntimeError("Attached browser exposes no reusable context")
                    page = context.pages[0] if context.pages else context.new_page()
                    page.goto(blocked_url, wait_until="domcontentloaded", timeout=30_000)
                    page.wait_for_timeout(1500)
                    screenshot_bytes = page.screenshot(type="png", full_page=True)
                    logger.info(
                        "manual_action_screenshot_attach_success",
                        extra={
                            "crawl_job_id": crawl_job_id,
                            "strategy": selected_strategy,
                            "browser_channel": browser_channel,
                            "browser_profile_path": browser_profile_path,
                            "debug_port": live_session.debug_port,
                        },
                    )
                    return _build_screenshot_payload(screenshot_bytes)
                except Exception as exc:
                    logger.info(
                        "manual_action_screenshot_attach_failure",
                        extra={
                            "crawl_job_id": crawl_job_id,
                            "strategy": selected_strategy,
                            "browser_channel": browser_channel,
                            "browser_profile_path": browser_profile_path,
                            "debug_port": live_session.debug_port,
                            "error": str(exc),
                        },
                    )

            logger.info(
                "manual_action_screenshot_fallback_selected",
                extra={
                    "crawl_job_id": crawl_job_id,
                    "strategy": selected_strategy,
                    "browser_channel": browser_channel,
                    "browser_profile_path": browser_profile_path,
                },
            )

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
        return _build_screenshot_payload(screenshot_bytes)
    finally:
        playwright.stop()


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
) -> bool:
    result = process_runner(
        ["taskkill", "/PID", str(pid), "/F"],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.returncode == 0)


def _extract_user_data_dir_argument(command_line: str) -> str | None:
    match = re.search(r'--user-data-dir=(?:"([^"]+)"|([^\s"]+))', str(command_line or ""), re.IGNORECASE)
    if not match:
        return None
    raw_value = match.group(1) or match.group(2)
    normalized = normalize_browser_profile_path(raw_value)
    return normalized or None


def _matching_profile_process_pids(
    *,
    browser_channel: str,
    browser_profile_path: str,
    processes: list[dict[str, Any]],
) -> list[int]:
    normalized_channel = str(browser_channel or "").strip().lower()
    normalized_profile = normalize_browser_profile_path(browser_profile_path)
    if not normalized_profile:
        raise HTTPException(status_code=409, detail="Manual action is missing browser_profile_path")

    matched_pids: list[int] = []
    for process in processes:
        process_name = str(process.get("name") or "").strip().lower()
        if normalized_channel == "msedge" and process_name != "msedge.exe":
            continue
        if normalized_channel == "chrome" and process_name != "chrome.exe":
            continue
        user_data_dir = _extract_user_data_dir_argument(str(process.get("command_line") or ""))
        if user_data_dir == normalized_profile:
            matched_pids.append(int(process["pid"]))
    return matched_pids


def close_profile_windows(
    *,
    browser_channel: str,
    browser_profile_path: str,
    live_browser_registry: LiveBrowserRegistry | None = None,
    process_lister: Callable[[], list[dict[str, Any]]] | None = None,
    process_killer: Callable[[int], bool] | None = None,
) -> dict[str, int]:
    process_lister = process_lister or _list_browser_processes
    process_killer = process_killer or _kill_process

    matched_pids = _matching_profile_process_pids(
        browser_channel=browser_channel,
        browser_profile_path=browser_profile_path,
        processes=process_lister(),
    )

    for pid in matched_pids:
        process_killer(pid)

    remaining_pids = set(
        _matching_profile_process_pids(
            browser_channel=browser_channel,
            browser_profile_path=browser_profile_path,
            processes=process_lister(),
        )
    )
    closed_count = len([pid for pid in matched_pids if pid not in remaining_pids])

    registry = live_browser_registry or get_live_browser_registry()
    if not remaining_pids:
        registry.remove(browser_profile_path)

    return {
        "matched_processes": len(matched_pids),
        "closed_processes": closed_count,
    }


def _get_reusable_live_browser_session(
    *,
    registry: LiveBrowserRegistry,
    browser_profile_path: str,
    reachability_probe: Callable[[Any], bool],
):
    session = registry.get(browser_profile_path)
    if session is None:
        return None
    if reachability_probe(session):
        registry.touch(browser_profile_path, status="live")
        return registry.get(browser_profile_path)
    registry.mark_stale(browser_profile_path)
    return None


def _wait_for_live_browser_session_ready(
    *,
    registry: LiveBrowserRegistry,
    browser_profile_path: str,
    reachability_probe: Callable[[Any], bool],
    timeout_seconds: float = 3.0,
    poll_interval_seconds: float = 0.1,
):
    deadline = time.time() + max(float(timeout_seconds), 0.0)
    while time.time() < deadline:
        session = registry.get(browser_profile_path)
        if session is not None and reachability_probe(session):
            registry.touch(browser_profile_path, status="live")
            return registry.get(browser_profile_path)
        time.sleep(max(float(poll_interval_seconds), 0.01))
    return None


def _register_launch_result(
    *,
    registry: LiveBrowserRegistry,
    browser_channel: str,
    browser_profile_path: str,
    blocked_url: str,
    launch_result: dict[str, Any],
) -> dict[str, Any]:
    existing = registry.get(browser_profile_path)
    if existing is not None and int(existing.debug_port) == int(launch_result.get("debug_port") or 0):
        return existing.to_dict()

    session = registry.register(
        browser_channel=str(launch_result.get("browser_channel") or browser_channel),
        browser_profile_path=str(launch_result.get("browser_profile_path") or browser_profile_path),
        blocked_url=str(launch_result.get("blocked_url") or blocked_url),
        debug_port=int(launch_result.get("debug_port")),
        status=str(launch_result.get("status") or "live"),
    )
    return session.to_dict()


def build_host_manual_action_helper_app(
    *,
    session_factory: Callable[[], Session] = SessionLocal,
    crawl_job_repository: CrawlJobRepository | None = None,
    browser_launcher: Callable[..., dict[str, Any]] = launch_browser_process,
    close_profile_windows: Callable[..., dict[str, int]] = close_profile_windows,
    screenshot_capturer: Callable[..., dict[str, Any]] = capture_manual_action_screenshot,
    process_lister: Callable[[], list[dict[str, Any]]] | None = None,
    process_killer: Callable[[int], bool] | None = None,
    live_browser_registry: LiveBrowserRegistry | None = None,
    session_reachability_probe: Callable[[Any], bool] = probe_live_browser_session,
) -> FastAPI:
    crawl_job_repository = crawl_job_repository or CrawlJobRepository()
    live_browser_registry = live_browser_registry or get_live_browser_registry()
    app = FastAPI(title="Headed Manual Action Helper", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins.split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        sessions = live_browser_registry.list_sessions()
        return {
            "status": "ok",
            "total_sessions": len(sessions),
            "live_sessions": len([session for session in sessions if session.status == "live"]),
            "stale_sessions": len([session for session in sessions if session.status == "stale"]),
        }

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
        _ensure_non_default_browser_profile(browser_profile_path)
        existing_session = _get_reusable_live_browser_session(
            registry=live_browser_registry,
            browser_profile_path=browser_profile_path,
            reachability_probe=session_reachability_probe,
        )
        if existing_session is not None:
            logger.info(
                "manual_action_registry_reuse_hit",
                extra={
                    "crawl_job_id": request.crawl_job_id,
                    "strategy": RESUME_STRATEGY_REUSE_OPEN_BROWSER,
                    "browser_channel": browser_channel,
                    "browser_profile_path": browser_profile_path,
                    "debug_port": existing_session.debug_port,
                },
            )
            return existing_session.to_dict()

        launch_result = browser_launcher(
            browser_channel=browser_channel,
            browser_profile_path=browser_profile_path,
            blocked_url=blocked_url,
            live_browser_registry=live_browser_registry,
        )
        launch_payload = _register_launch_result(
            registry=live_browser_registry,
            browser_channel=browser_channel,
            browser_profile_path=browser_profile_path,
            blocked_url=blocked_url,
            launch_result=launch_result,
        )
        ready_session = _wait_for_live_browser_session_ready(
            registry=live_browser_registry,
            browser_profile_path=browser_profile_path,
            reachability_probe=session_reachability_probe,
        )
        if ready_session is not None:
            return ready_session.to_dict()
        return launch_payload

    @app.post("/manual-actions/reuse-status")
    async def reuse_status(request: ManualActionRequest):
        db = session_factory()
        try:
            manual_action = _load_manual_action_payload(
                db,
                crawl_job_id=request.crawl_job_id,
                crawl_job_repository=crawl_job_repository,
            )
        finally:
            db.close()

        browser_profile_path = str(manual_action.get("browser_profile_path") or "").strip()
        if not browser_profile_path:
            raise HTTPException(status_code=409, detail="Manual action is missing browser_profile_path")
        _ensure_non_default_browser_profile(browser_profile_path)

        existing_session = _get_reusable_live_browser_session(
            registry=live_browser_registry,
            browser_profile_path=browser_profile_path,
            reachability_probe=session_reachability_probe,
        )
        if existing_session is None:
            reason = "live_browser_unreachable" if live_browser_registry.get(browser_profile_path) else "live_browser_not_found"
            return {
                "available": False,
                "reason": reason,
            }

        payload = existing_session.to_dict()
        payload["available"] = True
        return payload

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
            live_browser_registry=live_browser_registry,
            process_lister=process_lister,
            process_killer=process_killer,
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
        return await run_in_threadpool(
            screenshot_capturer,
            browser_channel=browser_channel,
            browser_profile_path=browser_profile_path,
            blocked_url=blocked_url,
            crawl_job_id=request.crawl_job_id,
            resume_strategy=str(
                manual_action.get("preferred_resume_strategy") or RESUME_STRATEGY_FRESH_PROFILE
            ),
            live_browser_registry=live_browser_registry,
            session_reachability_probe=session_reachability_probe,
        )

    return app


class HostManualActionHelperServer:
    def __init__(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        live_browser_registry: LiveBrowserRegistry | None = None,
        session_reachability_probe: Callable[[Any], bool] = probe_live_browser_session,
    ) -> None:
        import uvicorn

        self.host = host or settings.manual_action_helper_host
        self.port = int(port or settings.jobsdb_headed_manual_action_helper_port)
        self.live_browser_registry = live_browser_registry or get_live_browser_registry()
        self.session_reachability_probe = session_reachability_probe
        self.app = build_host_manual_action_helper_app(
            live_browser_registry=self.live_browser_registry,
            session_reachability_probe=self.session_reachability_probe,
        )
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
        self.live_browser_registry.revalidate(self.session_reachability_probe)
        self.thread.start()
        deadline = time.time() + 5
        while time.time() < deadline:
            if self.server.started:
                return
            if not self.thread.is_alive():
                break
            time.sleep(0.05)
        self.server.should_exit = True
        raise RuntimeError(
            f"Manual action helper failed to start on http://{self.host}:{self.port}"
        )

    def stop(self) -> None:
        self.server.should_exit = True
        if self.thread.is_alive():
            self.thread.join(timeout=5)
