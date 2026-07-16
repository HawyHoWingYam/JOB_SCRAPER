from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.crawl_cancellation import ACTIVE_EXECUTION_STATUSES
from app.models.crawl_job_execution import CrawlJobExecution
from app.utils.time import utc_now


class CrawlJobExecutionRepository:
    def create_launch(
        self,
        db: Session,
        *,
        crawl_job_id,
        generation,
        launcher_instance_id: str,
        command: list[str],
    ) -> CrawlJobExecution:
        execution = CrawlJobExecution(
            crawl_job_id=crawl_job_id,
            generation=generation,
            launcher_instance_id=launcher_instance_id,
            status="launching",
            command=list(command),
        )
        db.add(execution)
        db.flush()
        return execution

    def get_by_generation(
        self,
        db: Session,
        generation,
        *,
        for_update: bool = False,
    ) -> CrawlJobExecution | None:
        query = db.query(CrawlJobExecution).filter(
            CrawlJobExecution.generation == generation
        )
        if for_update:
            query = query.with_for_update()
        return query.one_or_none()

    def get_latest_active_for_job(
        self,
        db: Session,
        crawl_job_id,
        *,
        for_update: bool = False,
    ) -> CrawlJobExecution | None:
        query = (
            db.query(CrawlJobExecution)
            .filter(
                CrawlJobExecution.crawl_job_id == crawl_job_id,
                CrawlJobExecution.status.in_(list(ACTIVE_EXECUTION_STATUSES)),
            )
            .order_by(CrawlJobExecution.created_at.desc())
        )
        if for_update:
            query = query.with_for_update()
        return query.first()

    def list_stop_requested(self, db: Session) -> list[CrawlJobExecution]:
        return (
            db.query(CrawlJobExecution)
            .filter(CrawlJobExecution.status == "stop_requested")
            .order_by(CrawlJobExecution.stop_requested_at.asc())
            .all()
        )

    def mark_running(
        self,
        execution: CrawlJobExecution,
        *,
        pid: int,
        process_create_time: float,
    ) -> None:
        timestamp = utc_now()
        execution.status = "running"
        execution.pid = int(pid)
        execution.process_create_time = float(process_create_time)
        execution.launched_at = execution.launched_at or timestamp
        execution.heartbeat_at = timestamp

    def request_stop(self, execution: CrawlJobExecution) -> None:
        execution.status = "stop_requested"
        execution.stop_requested_at = execution.stop_requested_at or utc_now()

    def heartbeat(self, execution: CrawlJobExecution) -> None:
        execution.heartbeat_at = utc_now()

    def mark_exit(
        self,
        execution: CrawlJobExecution,
        *,
        status: str,
        exit_code: int | None,
    ) -> None:
        execution.status = status
        execution.exit_code = exit_code
        execution.exited_at = execution.exited_at or utc_now()

    @staticmethod
    def snapshot(execution: CrawlJobExecution) -> dict[str, Any]:
        return {
            "generation": str(execution.generation),
            "crawl_job_id": str(execution.crawl_job_id),
            "status": execution.status,
            "pid": execution.pid,
            "process_create_time": execution.process_create_time,
            "command": list(execution.command or []),
            "stop_requested_at": execution.stop_requested_at,
        }
