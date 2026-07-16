from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import psutil

from app.crawl_cancellation import ACTIVE_EXECUTION_STATUSES
from app.crawl_modes import normalize_source_site
from app.database import SessionLocal
from app.repositories.crawl_job_execution_repository import (
    CrawlJobExecutionRepository,
)
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.services.crawl_cancellation_token import EXECUTION_GENERATION_ENV
from app.services.crawl_job_cancellation_service import CrawlJobCancellationService
from app.utils.time import utc_now


logger = logging.getLogger(__name__)

DIRECT_LAUNCH_SCRIPT_MAP = {
    "offertoday": "offertoday_standalone_crawl.py",
    "jobsdb": "jobsdb_standalone_crawl.py",
    "ctgoodjobs": "ctgoodjobs_standalone_crawl.py",
}
CANCEL_GRACE_SECONDS = 30.0
PROCESS_CREATE_TIME_TOLERANCE_SECONDS = 0.01


class ProcessIdentityUnavailable(RuntimeError):
    """The PID exists but ownership cannot be verified safely enough to signal."""


@dataclass(frozen=True)
class CrawlJobLaunchResult:
    launched: bool
    command: list[str] | None = None
    execution_generation: str | None = None


class CrawlJobExecutionLauncher:
    def __init__(
        self,
        *,
        popen: Callable[..., Any] | None = None,
        session_factory=SessionLocal,
        process_factory: Callable[[int], Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        launcher_instance_id: str | None = None,
        cancellation_service: CrawlJobCancellationService | None = None,
    ) -> None:
        self._popen = popen or subprocess.Popen
        self._session_factory = session_factory
        self._process_factory = process_factory or psutil.Process
        self._sleep = sleep
        self._launcher_instance_id = launcher_instance_id or str(uuid4())
        self._execution_repository = CrawlJobExecutionRepository()
        self._crawl_job_repository = CrawlJobRepository()
        self._cancellation_service = (
            cancellation_service
            or CrawlJobCancellationService(session_factory=session_factory)
        )
        self._local_processes: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._supervised: set[str] = set()

    def should_launch_locally(self, crawl_job) -> bool:
        return (
            normalize_source_site(getattr(crawl_job, "source_site", ""))
            in DIRECT_LAUNCH_SCRIPT_MAP
        )

    def build_command(self, crawl_job, *, generation: str | None = None) -> list[str]:
        source_site = normalize_source_site(getattr(crawl_job, "source_site", ""))
        script_name = DIRECT_LAUNCH_SCRIPT_MAP.get(source_site)
        if not script_name:
            raise ValueError(
                f"Unsupported local crawl execution source_site: {source_site}"
            )
        command = [
            "python",
            self._resolve_script_path(script_name),
            "--crawl-job-id",
            str(crawl_job.id),
        ]
        if generation:
            command.extend(["--execution-generation", generation])
        return command

    def launch(self, crawl_job) -> CrawlJobLaunchResult:
        if not self.should_launch_locally(crawl_job):
            return CrawlJobLaunchResult(launched=False, command=None)

        generation = str(uuid4())
        command = self.build_command(crawl_job, generation=generation)
        db = self._session_factory()
        try:
            locked_job = self._crawl_job_repository.get_crawl_job_by_id_for_update(
                db, crawl_job.id
            )
            if locked_job is None:
                raise ValueError(f"Crawl job not found: {crawl_job.id}")
            if locked_job.status in {"cancelling", "cancelled"}:
                db.commit()
                self._cancellation_service.acknowledge_cancelled(
                    crawl_job_id=crawl_job.id,
                    reason=locked_job.error_message or "Cancelled before launch.",
                )
                return CrawlJobLaunchResult(launched=False, command=command)
            self._execution_repository.create_launch(
                db,
                crawl_job_id=crawl_job.id,
                generation=generation,
                launcher_instance_id=self._launcher_instance_id,
                command=command,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        env = dict(os.environ)
        env[EXECUTION_GENERATION_ENV] = generation
        popen_kwargs: dict[str, Any] = {"env": env}
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        if self._crawl_job_status(crawl_job.id) in {"cancelling", "cancelled"}:
            self._mark_execution_without_process(generation, status="stale")
            self._cancellation_service.acknowledge_cancelled(
                crawl_job_id=crawl_job.id,
                execution_generation=generation,
                reason="Cancelled before process launch.",
            )
            return CrawlJobLaunchResult(
                launched=False,
                command=command,
                execution_generation=generation,
            )

        process = None
        try:
            process = self._popen(command, **popen_kwargs)
            process_create_time = float(
                self._process_factory(process.pid).create_time()
            )
        except Exception as exc:
            if process is not None:
                self._terminate_unregistered_process(process)
            self._mark_launch_failed(generation)
            self._settle_launch_failure(
                crawl_job_id=crawl_job.id,
                generation=generation,
                error=exc,
            )
            raise

        db = self._session_factory()
        try:
            execution = self._execution_repository.get_by_generation(
                db, generation, for_update=True
            )
            if execution is None:
                raise RuntimeError(f"Missing crawl execution generation: {generation}")
            self._execution_repository.mark_running(
                execution,
                pid=process.pid,
                process_create_time=process_create_time,
            )
            persisted_job = self._crawl_job_repository.get_crawl_job_by_id(
                db, crawl_job.id
            )
            if persisted_job is None:
                raise RuntimeError(
                    f"Crawl job disappeared during launch: {crawl_job.id}"
                )
            crawl_status = persisted_job.status
            if crawl_status == "cancelling":
                self._execution_repository.request_stop(execution)
            db.commit()
        except Exception as exc:
            db.rollback()
            self._terminate_unregistered_process(process)
            self._mark_launch_failed(generation)
            self._settle_launch_failure(
                crawl_job_id=crawl_job.id,
                generation=generation,
                error=exc,
            )
            raise
        finally:
            db.close()

        with self._lock:
            self._local_processes[generation] = process
        self._start_monitor(generation)
        if crawl_status == "cancelling":
            self.supervise_cancellation(generation)
        return CrawlJobLaunchResult(
            launched=True,
            command=command,
            execution_generation=generation,
        )

    def request_cancel(self, *, crawl_job_id) -> bool:
        db = self._session_factory()
        try:
            execution = self._execution_repository.get_latest_active_for_job(
                db, crawl_job_id, for_update=True
            )
            if execution is None:
                return False
            self._execution_repository.request_stop(execution)
            generation = str(execution.generation)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        self.supervise_cancellation(generation)
        return True

    def acknowledge_without_execution(
        self,
        *,
        crawl_job_id,
        reason: str,
    ) -> bool:
        return self._cancellation_service.acknowledge_cancelled(
            crawl_job_id=crawl_job_id,
            reason=reason,
        )

    def recover_pending_cancellations(self) -> int:
        db = self._session_factory()
        try:
            cancelling_jobs = self._crawl_job_repository.list_crawl_jobs_by_statuses(
                db,
                statuses=["cancelling"],
            )
            generations: list[str] = []
            jobs_without_execution: list[tuple[Any, str]] = []
            for crawl_job in cancelling_jobs:
                execution = self._execution_repository.get_latest_active_for_job(
                    db,
                    crawl_job.id,
                    for_update=True,
                )
                if execution is None:
                    jobs_without_execution.append(
                        (
                            crawl_job.id,
                            crawl_job.error_message
                            or "Cancellation recovered at startup.",
                        )
                    )
                    continue
                self._execution_repository.request_stop(execution)
                generations.append(str(execution.generation))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        for generation in generations:
            self.supervise_cancellation(generation)
        for crawl_job_id, reason in jobs_without_execution:
            self.acknowledge_without_execution(
                crawl_job_id=crawl_job_id,
                reason=reason,
            )
        return len(generations) + len(jobs_without_execution)

    def supervise_cancellation(self, generation: str) -> None:
        with self._lock:
            if generation in self._supervised:
                return
            self._supervised.add(generation)
        thread = threading.Thread(
            target=self._supervise_cancellation,
            args=(generation,),
            name=f"crawl-cancel-{generation[:8]}",
            daemon=True,
        )
        thread.start()

    def _supervise_cancellation(self, generation: str) -> None:
        try:
            snapshot = self._execution_snapshot(generation)
            if snapshot is None:
                return
            deadline = self._cancellation_deadline(snapshot)
            while True:
                snapshot = self._execution_snapshot(generation)
                if snapshot is None:
                    return
                if snapshot.get("pid") is None:
                    if time.monotonic() >= deadline:
                        self._record_exit_and_acknowledge(
                            snapshot,
                            status="stale",
                            exit_code=None,
                        )
                        return
                    self._sleep(0.25)
                    continue
                try:
                    process = self._validated_process(snapshot)
                except ProcessIdentityUnavailable:
                    logger.warning(
                        "Crawl process identity is temporarily unverifiable "
                        "generation=%s pid=%s",
                        generation,
                        snapshot.get("pid"),
                    )
                    self._sleep(0.25)
                    continue
                if process is None or not process.is_running():
                    self._record_exit_and_acknowledge(
                        snapshot,
                        status="exited",
                        exit_code=self._local_exit_code(generation),
                    )
                    return
                if time.monotonic() >= deadline:
                    if not self._terminate_process_tree(process):
                        logger.error(
                            "Crawl process tree still alive after force-stop "
                            "generation=%s pid=%s",
                            generation,
                            snapshot.get("pid"),
                        )
                        self._sleep(0.25)
                        continue
                    self._record_exit_and_acknowledge(
                        snapshot,
                        status="terminated",
                        exit_code=self._local_exit_code(generation),
                    )
                    return
                self._sleep(0.25)
        except Exception:
            logger.exception(
                "Crawl cancellation supervision failed generation=%s", generation
            )
        finally:
            with self._lock:
                self._supervised.discard(generation)

    def _start_monitor(self, generation: str) -> None:
        thread = threading.Thread(
            target=self._monitor_local_process,
            args=(generation,),
            name=f"crawl-process-{generation[:8]}",
            daemon=True,
        )
        thread.start()

    def _monitor_local_process(self, generation: str) -> None:
        with self._lock:
            process = self._local_processes.get(generation)
        if process is None:
            return
        exit_code = process.wait()
        snapshot = self._execution_snapshot(generation)
        if snapshot is not None:
            self._record_exit(snapshot, status="exited", exit_code=exit_code)
            if self._crawl_job_status(snapshot["crawl_job_id"]) == "cancelling":
                self._cancellation_service.acknowledge_cancelled(
                    crawl_job_id=snapshot["crawl_job_id"],
                    execution_generation=generation,
                )
        with self._lock:
            self._local_processes.pop(generation, None)

    def _execution_snapshot(self, generation: str) -> dict[str, Any] | None:
        db = self._session_factory()
        try:
            execution = self._execution_repository.get_by_generation(db, generation)
            if execution is None:
                return None
            return self._execution_repository.snapshot(execution)
        finally:
            db.close()

    def _validated_process(self, snapshot: dict[str, Any]):
        pid = snapshot.get("pid")
        expected_create_time = snapshot.get("process_create_time")
        if pid is None or expected_create_time is None:
            return None
        try:
            process = self._process_factory(int(pid))
            if (
                abs(float(process.create_time()) - float(expected_create_time))
                > PROCESS_CREATE_TIME_TOLERANCE_SECONDS
            ):
                return None
            command_line = [str(value) for value in process.cmdline()]
        except psutil.NoSuchProcess:
            return None
        except (psutil.AccessDenied, OSError, ValueError) as exc:
            raise ProcessIdentityUnavailable(
                f"Cannot verify crawl process identity for pid={pid}"
            ) from exc
        required_tokens = {
            str(snapshot["generation"]),
            str(snapshot["crawl_job_id"]),
        }
        if not required_tokens.issubset(set(command_line)):
            return None
        if not self._command_matches(
            expected=[str(value) for value in snapshot.get("command") or []],
            actual=command_line,
        ):
            return None
        return process

    def _record_exit_and_acknowledge(
        self,
        snapshot: dict[str, Any],
        *,
        status: str,
        exit_code: int | None,
    ) -> None:
        self._record_exit(snapshot, status=status, exit_code=exit_code)
        self._cancellation_service.acknowledge_cancelled(
            crawl_job_id=snapshot["crawl_job_id"],
            execution_generation=snapshot["generation"],
        )

    def _record_exit(
        self,
        snapshot: dict[str, Any],
        *,
        status: str,
        exit_code: int | None,
    ) -> None:
        db = self._session_factory()
        try:
            execution = self._execution_repository.get_by_generation(
                db, snapshot["generation"], for_update=True
            )
            if execution is not None and execution.status in ACTIVE_EXECUTION_STATUSES:
                self._execution_repository.mark_exit(
                    execution, status=status, exit_code=exit_code
                )
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _mark_launch_failed(self, generation: str) -> None:
        self._mark_execution_without_process(generation, status="launch_failed")

    def _settle_launch_failure(
        self,
        *,
        crawl_job_id,
        generation: str,
        error: BaseException,
    ) -> None:
        message = f"Crawler process launch failed: {type(error).__name__}"
        db = self._session_factory()
        should_acknowledge = False
        try:
            crawl_job = self._crawl_job_repository.get_crawl_job_by_id_for_update(
                db, crawl_job_id
            )
            if crawl_job is None:
                return
            if crawl_job.status in {"cancelling", "cancelled"}:
                should_acknowledge = crawl_job.status == "cancelling"
                db.commit()
            else:
                self._crawl_job_repository.record_runtime_event(
                    db,
                    crawl_job_id=crawl_job_id,
                    status="failed",
                    event_type="crawl.failed",
                    payload={
                        "crawl_job_id": str(crawl_job_id),
                        "source_site": crawl_job.source_site,
                        "status": "failed",
                        "reason": message,
                        "execution_generation": generation,
                    },
                    emitted_by="crawl-execution-launcher",
                    completed_at=utc_now(),
                    error_message=message,
                    auto_commit=False,
                )
                db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "Failed to settle crawl launch failure crawl_job_id=%s generation=%s",
                crawl_job_id,
                generation,
            )
        finally:
            db.close()
        if should_acknowledge:
            self._cancellation_service.acknowledge_cancelled(
                crawl_job_id=crawl_job_id,
                execution_generation=generation,
                reason="Cancelled while crawler process was launching.",
            )

    def _mark_execution_without_process(self, generation: str, *, status: str) -> None:
        db = self._session_factory()
        try:
            execution = self._execution_repository.get_by_generation(
                db, generation, for_update=True
            )
            if execution is not None:
                self._execution_repository.mark_exit(
                    execution, status=status, exit_code=None
                )
                db.commit()
        finally:
            db.close()

    def _crawl_job_status(self, crawl_job_id) -> str | None:
        db = self._session_factory()
        try:
            row = self._crawl_job_repository.get_crawl_job_by_id(db, crawl_job_id)
            return row.status if row is not None else None
        finally:
            db.close()

    def _cancellation_deadline(self, snapshot: dict[str, Any]) -> float:
        requested_at = snapshot.get("stop_requested_at")
        elapsed = 0.0
        if requested_at is not None:
            elapsed = max((utc_now() - requested_at).total_seconds(), 0.0)
        return time.monotonic() + max(CANCEL_GRACE_SECONDS - elapsed, 0.0)

    def _local_exit_code(self, generation: str) -> int | None:
        with self._lock:
            process = self._local_processes.get(generation)
        return process.poll() if process is not None else None

    @staticmethod
    def _command_matches(*, expected: list[str], actual: list[str]) -> bool:
        if not expected or not actual or len(expected) != len(actual):
            return False
        expected_program = Path(expected[0]).stem.lower()
        actual_program = Path(actual[0]).stem.lower()
        if expected_program != actual_program:
            return False
        return [os.path.normcase(value) for value in expected[1:]] == [
            os.path.normcase(value) for value in actual[1:]
        ]

    @staticmethod
    def _terminate_process_tree(process) -> bool:
        try:
            descendants = process.children(recursive=True)
        except psutil.NoSuchProcess:
            return True
        except psutil.Error:
            return False
        for child in descendants:
            try:
                child.terminate()
            except psutil.Error:
                pass
        try:
            process.terminate()
        except psutil.Error:
            pass
        _, alive = psutil.wait_procs([*descendants, process], timeout=5.0)
        for remaining in alive:
            try:
                remaining.kill()
            except psutil.Error:
                pass
        if alive:
            _, alive = psutil.wait_procs(alive, timeout=5.0)
        return not alive

    def _terminate_unregistered_process(self, process) -> None:
        try:
            owned_process = self._process_factory(int(process.pid))
            if self._terminate_process_tree(owned_process):
                return
        except Exception:
            logger.warning(
                "Failed to terminate unregistered crawl process tree pid=%s",
                getattr(process, "pid", None),
                exc_info=True,
            )
        try:
            process.terminate()
        except Exception:
            return
        try:
            process.wait(timeout=5.0)
            return
        except Exception:
            pass
        try:
            process.kill()
            process.wait(timeout=5.0)
        except Exception:
            logger.error(
                "Failed to stop unregistered crawl process pid=%s",
                getattr(process, "pid", None),
                exc_info=True,
            )

    @staticmethod
    def _resolve_script_path(script_name: str) -> str:
        container_path = Path("/app/scripts") / script_name
        if container_path.exists():
            return str(container_path)
        return str(Path(__file__).resolve().parents[2] / "scripts" / script_name)
