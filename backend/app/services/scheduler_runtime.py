from __future__ import annotations

from app.services.scheduler_service import SchedulerService


async def initialize_scheduler_runtime() -> SchedulerService:
    scheduler = SchedulerService.get_instance()
    await scheduler.initialize()
    return scheduler


def shutdown_scheduler_runtime() -> None:
    SchedulerService.get_instance().shutdown()
