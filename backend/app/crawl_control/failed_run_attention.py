from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.crawl_control.errors import (
    CrawlTaskNotFoundError,
    FailedAttentionRevisionConflictError,
    FailedAttentionStateInvalidError,
)
from app.crawl_control.task_control_board_contracts import (
    DismissFailedAttentionResponseV1,
)
from app.repositories.crawl_job_repository import CrawlJobRepository


FAILED_RUN_EVENT_TYPE = "crawl.failed"
FAILED_ATTENTION_DISMISSED_EVENT_TYPE = "crawl.failed_attention_dismissed"
FAILED_ATTENTION_EVENT_TYPES = frozenset(
    {FAILED_RUN_EVENT_TYPE, FAILED_ATTENTION_DISMISSED_EVENT_TYPE}
)


@dataclass(frozen=True)
class FailedAttentionState:
    failure_event_sequence: int | None
    dismissed: bool


def project_failed_attention_state(events) -> FailedAttentionState:
    latest_failure_sequence = None
    dismissed_sequences: set[int] = set()
    for event in events or ():
        if event.event_type == FAILED_RUN_EVENT_TYPE:
            latest_failure_sequence = int(event.sequence_no)
        elif event.event_type == FAILED_ATTENTION_DISMISSED_EVENT_TYPE:
            payload = event.payload if isinstance(event.payload, dict) else {}
            try:
                dismissed_sequences.add(int(payload.get("failure_event_sequence")))
            except (TypeError, ValueError):
                continue
    return FailedAttentionState(
        failure_event_sequence=latest_failure_sequence,
        dismissed=(
            latest_failure_sequence is not None
            and latest_failure_sequence in dismissed_sequences
        ),
    )


class FailedRunAttentionService:
    def __init__(self, repository: CrawlJobRepository | None = None) -> None:
        self.repository = repository or CrawlJobRepository()

    def dismiss(
        self,
        db: Session,
        *,
        crawl_job_id: UUID,
        expected_failure_event_sequence: int,
        actor: str = "local-operator",
    ) -> DismissFailedAttentionResponseV1:
        crawl_job = self.repository.get_crawl_job_by_id_for_update(
            db,
            crawl_job_id,
        )
        if crawl_job is None:
            raise CrawlTaskNotFoundError(crawl_job_id)
        if crawl_job.status != "failed":
            raise FailedAttentionStateInvalidError(
                crawl_job_id=crawl_job_id,
                current_status=str(crawl_job.status),
            )

        events = self.repository.list_events(
            db,
            crawl_job_id,
            event_types=set(FAILED_ATTENTION_EVENT_TYPES),
        )
        state = project_failed_attention_state(events)
        if state.failure_event_sequence != expected_failure_event_sequence:
            raise FailedAttentionRevisionConflictError(
                crawl_job_id=crawl_job_id,
                expected_failure_event_sequence=expected_failure_event_sequence,
                current_failure_event_sequence=state.failure_event_sequence,
            )

        for event in events:
            if event.event_type != FAILED_ATTENTION_DISMISSED_EVENT_TYPE:
                continue
            payload = event.payload if isinstance(event.payload, dict) else {}
            if payload.get("failure_event_sequence") == expected_failure_event_sequence:
                return DismissFailedAttentionResponseV1(
                    crawl_job_id=crawl_job_id,
                    failure_event_sequence=expected_failure_event_sequence,
                    dismissal_event_sequence=int(event.sequence_no),
                    replayed=True,
                )

        dismissal = self.repository.append_event(
            db,
            crawl_job_id=crawl_job_id,
            event_type=FAILED_ATTENTION_DISMISSED_EVENT_TYPE,
            payload={
                "crawl_job_id": str(crawl_job_id),
                "failure_event_sequence": expected_failure_event_sequence,
                "actor": actor,
            },
            emitted_by=actor,
            auto_commit=False,
        )
        db.commit()
        return DismissFailedAttentionResponseV1(
            crawl_job_id=crawl_job_id,
            failure_event_sequence=expected_failure_event_sequence,
            dismissal_event_sequence=int(dismissal.sequence_no),
            replayed=False,
        )
