from __future__ import annotations

from app.crawl_cancellation import can_request_cancellation, runtime_transition_allowed


def test_manual_non_terminal_states_are_cancellable() -> None:
    for status in ("queued", "dispatching", "running", "manual_action_required"):
        assert can_request_cancellation(
            trigger_type="manual", status=status, schedule_id=None
        )


def test_scheduled_and_terminal_jobs_are_not_cancellable() -> None:
    assert not can_request_cancellation(trigger_type="schedule", status="running")
    assert not can_request_cancellation(
        trigger_type="manual", status="running", schedule_id="schedule-id"
    )
    for status in ("completed", "failed", "cancelled", "cancelling"):
        assert not can_request_cancellation(trigger_type="manual", status=status)


def test_cancellation_protected_status_rejects_late_worker_transition() -> None:
    for current in ("cancelling", "cancelled"):
        for next_status in ("running", "completed", "failed", "manual_action_required"):
            assert not runtime_transition_allowed(
                current_status=current,
                next_status=next_status,
            )


def test_non_cancellation_state_keeps_existing_runtime_transitions() -> None:
    assert runtime_transition_allowed(current_status="running", next_status="completed")
