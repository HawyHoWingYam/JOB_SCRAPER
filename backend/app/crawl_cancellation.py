from __future__ import annotations


CANCELLABLE_CRAWL_JOB_STATUSES = frozenset(
    {"queued", "dispatching", "running", "manual_action_required"}
)
ACTIVE_MANUAL_DETAIL_STATUSES = frozenset(
    {*CANCELLABLE_CRAWL_JOB_STATUSES, "cancelling"}
)
CANCELLATION_PROTECTED_STATUSES = frozenset({"cancelling", "cancelled"})
TERMINAL_CRAWL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled"})

ACTIVE_EXECUTION_STATUSES = frozenset({"launching", "running", "stop_requested"})
TERMINAL_EXECUTION_STATUSES = frozenset(
    {"exited", "terminated", "launch_failed", "stale"}
)


def runtime_transition_allowed(*, current_status: str, next_status: str) -> bool:
    """Prevent late workers from resurrecting cancellation-protected jobs."""

    current = str(current_status or "").strip().lower()
    next_value = str(next_status or "").strip().lower()
    if current in CANCELLATION_PROTECTED_STATUSES:
        return next_value == current
    return True


def can_request_cancellation(
    *, trigger_type: str, status: str, schedule_id=None
) -> bool:
    return (
        str(trigger_type or "").strip().lower() == "manual"
        and schedule_id is None
        and str(status or "").strip().lower() in CANCELLABLE_CRAWL_JOB_STATUSES
    )
