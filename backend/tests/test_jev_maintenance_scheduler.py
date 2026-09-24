from app.services import scheduler_service


class _FakeScheduler:
    def __init__(self) -> None:
        self.calls = []

    def add_job(self, callback, **kwargs):
        self.calls.append((callback, kwargs))


def test_scheduler_has_no_automatic_jev_maintenance_entrypoint() -> None:
    service = scheduler_service.SchedulerService()

    assert not hasattr(service, "_register_jev_maintenance_job")
    assert not hasattr(scheduler_service, "run_scheduled_jev_skill_maintenance")
