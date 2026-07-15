from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.runtime_capabilities_service import (
    _host_manual_action_helper_capability,
)
from app.services.crawl_job_runtime import CrawlJobRuntime, DetailTargetLoadResult
from app.sources.contracts import build_offertoday_canonical_job
from app.sources.offertoday.response_policy import OfferTodayResponseKind
from app.sources.offertoday.search_space import (
    resolve_offertoday_detail_category_ids,
)
from scripts import offertoday_standalone_crawl as offertoday_crawl


def _args(**overrides):
    values = {
        "crawl_job_id": "detail-task",
        "crawl_phase": "detail",
        "headed": False,
        "source_listing_crawl_job_id": "",
        "detail_scope": "global",
        "category_ids": "118000",
        "detail_limit": 2,
        "detail_statuses": "pending,failed,manual_action_required",
        "skip_existing": False,
        "resume_strategy": "fresh_profile",
        "keywords": "",
        "max_pages": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _load_result(
    source_job_ids: tuple[str, ...],
    *,
    eligible: int | None = None,
    pending: int = 0,
    failed: int = 0,
    manual: int = 0,
) -> DetailTargetLoadResult:
    targets = [
        {
            "source_job_id": source_job_id,
            "detail_target_kind": "new",
        }
        for source_job_id in source_job_ids
    ]
    return DetailTargetLoadResult(
        target_rows=len(targets),
        selected_rows=len(targets),
        skipped_existing_rows=0,
        distinct_selected_ids=len(targets),
        reconciled_rows=0,
        duplicate_rows=0,
        fetch_cohort_source_job_ids=source_job_ids,
        fetch_cohort_hash="cohort",
        reconciled_source_job_ids=(),
        identity_conflict_ids=(),
        identity_conflict_evidence=(),
        reconciliation_records=(),
        targets=targets,
        new_detail_targets=len(targets),
        repair_detail_targets=0,
        eligible_distinct_target_rows=(
            len(targets) if eligible is None else eligible
        ),
        detail_scope="global",
        eligible_pending_rows=pending,
        eligible_failed_rows=failed,
        eligible_manual_action_rows=manual,
    )


def _phase_result(
    load_result: DetailTargetLoadResult,
    *,
    outcome: OfferTodayResponseKind = OfferTodayResponseKind.SUCCESS,
    stop_batch: bool = False,
    stop_reason: str | None = None,
) -> offertoday_crawl.OfferTodayDetailPhaseResult:
    processed = int(load_result.target_rows)
    return offertoday_crawl.OfferTodayDetailPhaseResult(
        detail_load_result=load_result,
        processed_targets=processed,
        outcome_counts={outcome.value: processed} if processed else {},
        jobs_created=processed if outcome is OfferTodayResponseKind.SUCCESS else 0,
        jobs_updated=0,
        jobs_reconciled=0,
        companies_created=0,
        companies_updated=0,
        terminal_unavailable=(
            processed
            if outcome is OfferTodayResponseKind.TERMINAL_UNAVAILABLE
            else 0
        ),
        persist_failure=(
            processed if outcome is OfferTodayResponseKind.PERSIST_FAILURE else 0
        ),
        stop_batch=stop_batch,
        total_target_rows=processed,
        segments_completed=1,
        stop_reason=stop_reason,
    )


class _RecoveryRuntime:
    def __init__(self, next_loads: list[DetailTargetLoadResult]) -> None:
        self.next_loads = list(next_loads)
        self.completed: list[dict] = []
        self.failed: list[dict] = []
        self.metrics: list[dict] = []
        self.events: list[tuple[str, dict]] = []

    def load_detail_targets(self, **_kwargs):
        return self.next_loads.pop(0)

    def mark_completed(self, **kwargs):
        self.completed.append(kwargs)

    def mark_failed(self, **kwargs):
        self.failed.append(kwargs)

    def merge_metrics(self, *, metrics_patch, **_kwargs):
        self.metrics.append(dict(metrics_patch))

    def write_progress_event(self, *, event_type, payload, **_kwargs):
        self.events.append((event_type, dict(payload)))


class _FakeSession:
    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


class _DetailCandidateRepository:
    def __init__(self, rows):
        self.rows = list(rows)
        self.candidate_kwargs = None

    def list_detail_candidates(self, _db, **kwargs):
        self.candidate_kwargs = dict(kwargs)
        return list(self.rows)

    def list_offertoday_identity_history(self, _db):
        return list(self.rows)

    def count_detail_statuses_for_detail_crawl_job(self, _db, **_kwargs):
        return {}


class _DetailCrawlJobRepository:
    def __init__(self):
        self.metrics = []

    def list_offertoday_listing_identity_observations(self, _db):
        return []

    def append_event(self, _db, **_kwargs):
        return None

    def merge_metrics(self, _db, *, metrics_patch, **_kwargs):
        self.metrics.append(dict(metrics_patch))


class _EmptyJobRepository:
    def list_existing_jobs_by_source_ids(self, _db, **_kwargs):
        return {}


def _candidate_row(row_id: str, source_job_id: str, status: str):
    return SimpleNamespace(
        id=row_id,
        crawl_job_id="listing-batch",
        source_site="offertoday",
        source_job_id=source_job_id,
        source_url=f"https://www.offertoday.com/job/{source_job_id}",
        source_classification_id=None,
        source_classification_name=None,
        listing_payload={
            "jobId": source_job_id,
            "encryptJobId": f"9000{source_job_id}",
            "job_functions": [{"code": "150000", "name": "Procurement"}],
        },
        detail_payload={},
        detail_status=status,
    )


def test_global_scope_ignores_categories_and_rejects_batch_conflict() -> None:
    args = _args()
    assert offertoday_crawl._resolve_detail_scope(
        args,
        listing_phase_completed=False,
    ) == (None, "global")
    assert resolve_offertoday_detail_category_ids(
        [118000],
        source_listing_crawl_job_id=None,
        detail_scope="global",
    ) == []

    args.source_listing_crawl_job_id = "listing-task"
    with pytest.raises(ValueError, match="cannot carry a listing batch ID"):
        offertoday_crawl._resolve_detail_scope(
            args,
            listing_phase_completed=False,
        )


def test_runtime_global_scope_includes_null_classification_and_groups_duplicates() -> None:
    candidate_repository = _DetailCandidateRepository(
        [
            _candidate_row("row-1", "1001", "pending"),
            _candidate_row("row-2", "1001", "pending"),
            _candidate_row("row-3", "1002", "failed"),
            _candidate_row("row-4", "1003", "manual_action_required"),
        ]
    )
    crawl_job_repository = _DetailCrawlJobRepository()
    runtime = CrawlJobRuntime(
        lambda: _FakeSession(),
        crawl_job_repository=crawl_job_repository,
        crawl_job_listing_repository=candidate_repository,
        job_repository=_EmptyJobRepository(),
    )

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={
            "crawl_phase": "detail",
            "detail_scope": "global",
            "category_ids": [118000],
            "detail_statuses": [
                "pending",
                "failed",
                "manual_action_required",
            ],
            "detail_limit": 2,
        },
        detail_crawl_job_id="detail-task",
    )

    assert candidate_repository.candidate_kwargs["detail_scope"] == "global"
    assert candidate_repository.candidate_kwargs["source_listing_crawl_job_id"] is None
    assert candidate_repository.candidate_kwargs["category_ids"] == []
    assert result.selected_rows == 4
    assert result.distinct_selected_ids == 3
    assert result.duplicate_rows == 1
    assert result.eligible_distinct_target_rows == 3
    assert result.eligible_pending_rows == 1
    assert result.eligible_failed_rows == 1
    assert result.eligible_manual_action_rows == 1
    assert result.target_rows == 2
    assert result.targets[0]["source_classification_id"] is None
    assert result.targets[0]["duplicate_listing_ids"] == ("row-2",)


def test_listing_batch_scope_requires_and_persists_batch_id() -> None:
    args = _args(
        detail_scope="listing_batch",
        source_listing_crawl_job_id="listing-task",
    )
    assert offertoday_crawl._resolve_detail_scope(
        args,
        listing_phase_completed=False,
    ) == ("listing-task", "listing_batch")
    payload = offertoday_crawl._build_runtime_request_payload(
        args,
        crawl_phase="detail",
        source_listing_crawl_job_id="listing-task",
        detail_scope="listing_batch",
    )
    assert payload["detail_scope"] == "listing_batch"
    assert payload["source_listing_crawl_job_id"] == "listing-task"


@pytest.mark.asyncio
async def test_successful_segments_continue_until_refreshed_backlog_is_empty(
    monkeypatch,
) -> None:
    first = _load_result(("job-1", "job-2"), eligible=3, pending=3)
    second = _load_result(("job-3",), eligible=1, pending=1)
    empty = _load_result((), eligible=0)
    runtime = _RecoveryRuntime([second, empty])
    seen_segments: list[int] = []

    async def fake_run_detail_phase(*, detail_load_result, segment_index, **_kwargs):
        seen_segments.append(segment_index)
        return _phase_result(detail_load_result)

    monkeypatch.setattr(
        offertoday_crawl,
        "_run_detail_phase",
        fake_run_detail_phase,
    )
    result = await offertoday_crawl._run_detail_recovery(
        args=_args(),
        browser_runtime=object(),
        crawl_runtime=runtime,
        crawl_job_id="detail-task",
        detail_load_result=first,
    )

    assert seen_segments == [1, 2]
    assert result.processed_targets == 3
    assert result.total_target_rows == 3
    assert result.segments_completed == 2
    assert result.stop_batch is False
    assert len(runtime.completed) == 1
    assert runtime.completed[0]["metrics"]["detail_backlog_remaining"] == 0
    assert runtime.failed == []


@pytest.mark.asyncio
async def test_failed_segment_stops_without_selecting_it_forever(monkeypatch) -> None:
    first = _load_result(("job-1",), eligible=1, failed=1)
    remaining = _load_result(("job-1",), eligible=1, failed=1)
    runtime = _RecoveryRuntime([remaining])

    async def fake_run_detail_phase(*, detail_load_result, **_kwargs):
        return _phase_result(
            detail_load_result,
            outcome=OfferTodayResponseKind.PERSIST_FAILURE,
        )

    monkeypatch.setattr(
        offertoday_crawl,
        "_run_detail_phase",
        fake_run_detail_phase,
    )
    result = await offertoday_crawl._run_detail_recovery(
        args=_args(),
        browser_runtime=object(),
        crawl_runtime=runtime,
        crawl_job_id="detail-task",
        detail_load_result=first,
    )

    assert result.stop_batch is True
    assert result.stop_reason == "failed"
    assert len(runtime.failed) == 1
    assert runtime.failed[0]["metrics"]["detail_backlog_failed"] == 1
    assert runtime.completed == []


@pytest.mark.asyncio
async def test_manual_action_segment_preserves_remaining_backlog(monkeypatch) -> None:
    first = _load_result(("job-1", "job-2"), eligible=3, pending=3)
    remaining = _load_result(("job-2",), eligible=1, manual=1)
    runtime = _RecoveryRuntime([remaining])

    async def fake_run_detail_phase(*, detail_load_result, **_kwargs):
        return _phase_result(
            detail_load_result,
            stop_batch=True,
            stop_reason="manual_action_required",
        )

    monkeypatch.setattr(offertoday_crawl, "_run_detail_phase", fake_run_detail_phase)
    result = await offertoday_crawl._run_detail_recovery(
        args=_args(),
        browser_runtime=object(),
        crawl_runtime=runtime,
        crawl_job_id="detail-task",
        detail_load_result=first,
    )

    assert result.stop_batch is True
    assert result.stop_reason == "manual_action_required"
    assert runtime.completed == []
    assert runtime.failed == []
    assert runtime.metrics[-1]["detail_backlog_remaining"] == 1
    assert runtime.metrics[-1]["detail_backlog_manual_action_required"] == 1
    assert runtime.metrics[-1]["detail_continuation_state"] == "manual_action_required"


def test_manual_action_helper_capability_requires_live_health_check() -> None:
    capability = _host_manual_action_helper_capability()

    assert capability["available"] is None
    assert capability["reachable"] is None
    assert capability["reason"] == "health_check_required"
    assert capability["health_url"].endswith("/health")
    assert capability["manual_start_workdir"] == "backend"
    assert capability["manual_start_command"] == (
        "python -m app.workers.run_manual_action_helper"
    )


def test_canonical_classification_comes_from_merged_job_functions() -> None:
    listing_payload = {
        "job_id": "123",
        "encrypted_job_id": "encrypted-123",
        "title": "Procurement Officer",
        "job_functions": [
            {
                "code": "150000",
                "name": "Procurement",
                "children": [{"code": "150100", "name": "Purchasing"}],
            }
        ],
    }
    detail_payload = {"description_text": "Source detail"}

    canonical = build_offertoday_canonical_job(
        {**listing_payload, **detail_payload}
    )

    assert canonical.source_classification_id == "offertoday:150000"
    assert canonical.source_classification_name == "Procurement"
    assert canonical.source_subclassification_id == "offertoday:150100"
    assert canonical.source_subclassification_name == "Purchasing"


def test_canonical_classification_stays_null_without_job_functions() -> None:
    canonical = build_offertoday_canonical_job(
        {
            "job_id": "124",
            "encrypted_job_id": "encrypted-124",
            "title": "Unclassified Role",
        }
    )

    assert canonical.source_classification_id is None
    assert canonical.source_classification_name is None
    assert canonical.source_subclassification_id is None
    assert canonical.source_subclassification_name is None
