from __future__ import annotations

import hashlib
import inspect
import json
from copy import deepcopy
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.crawl_job_runtime import CrawlJobRuntime
from app.services.offertoday_detail_pipeline import (
    OfferTodayDetailPipeline,
    OfferTodayDetailTarget,
)
from app.sources.offertoday.detail_identity import OfferTodayDetailIdentity
from app.sources.offertoday.response_policy import (
    OfferTodayResponseKind,
    OfferTodayTransportError,
)


@dataclass
class _TransactionalStore:
    rows: dict[str, dict[str, Any]]
    companies: dict[str, dict[str, Any]] = field(default_factory=dict)
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)


class _TransactionalSession:
    def __init__(self, store: _TransactionalStore, factory) -> None:
        self.store = store
        self.factory = factory
        self.working = deepcopy(store)
        self.commits = 0
        self.commit_failures = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self) -> None:
        is_success_commit = bool(self.working.jobs) and any(
            event["event_type"] == "crawl.detail_persisted"
            for event in self.working.events
        )
        if self.factory.fail_success_commit_once and is_success_commit:
            self.factory.fail_success_commit_once = False
            self.commit_failures += 1
            raise RuntimeError("injected success commit failure")
        self.store.rows = deepcopy(self.working.rows)
        self.store.companies = deepcopy(self.working.companies)
        self.store.jobs = deepcopy(self.working.jobs)
        self.store.events = deepcopy(self.working.events)
        self.store.metrics = deepcopy(self.working.metrics)
        self.commits += 1

    def rollback(self) -> None:
        self.working = deepcopy(self.store)
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class _SessionFactory:
    def __init__(
        self,
        store: _TransactionalStore,
        *,
        fail_success_commit_once: bool = False,
    ) -> None:
        self.store = store
        self.fail_success_commit_once = fail_success_commit_once
        self.sessions: list[_TransactionalSession] = []

    def __call__(self) -> _TransactionalSession:
        session = _TransactionalSession(self.store, self)
        self.sessions.append(session)
        return session


class _ListingRepository:
    _OUTCOME_STATUSES = {
        "failed",
        "manual_action_required",
        "terminal_unavailable",
        "identity_conflict",
    }

    def __init__(self, *, fail_detail_completed_after: int | None = None) -> None:
        self.fail_detail_completed_after = fail_detail_completed_after
        self.completed_before_failure: list[str] = []

    @staticmethod
    def _row(db: _TransactionalSession, listing_id: str) -> dict[str, Any]:
        return db.working.rows[str(listing_id)]

    def mark_detail_running(
        self,
        db,
        *,
        listing_id,
        detail_crawl_job_id,
        auto_commit=True,
    ):
        row = self._row(db, listing_id)
        row["detail_status"] = "running"
        row["detail_attempts"] = int(row.get("detail_attempts") or 0) + 1
        row["last_detail_crawl_job_id"] = str(detail_crawl_job_id)
        row["detail_error_message"] = None
        if auto_commit:
            db.commit()
        return SimpleNamespace(**row)

    def mark_detail_completed(
        self,
        db,
        *,
        listing_id,
        detail_crawl_job_id,
        detail_payload=None,
        published_job_id=None,
        auto_commit=True,
    ):
        row = self._row(db, listing_id)
        row["detail_status"] = "completed"
        row["last_detail_crawl_job_id"] = str(detail_crawl_job_id)
        row["detail_payload"] = deepcopy(detail_payload)
        row["published_job_id"] = published_job_id
        row["detail_error_message"] = None
        self.completed_before_failure.append(str(listing_id))
        if (
            self.fail_detail_completed_after is not None
            and len(self.completed_before_failure)
            == self.fail_detail_completed_after
        ):
            raise RuntimeError("injected group completion transition failure")
        if auto_commit:
            db.commit()
        return SimpleNamespace(**row)

    def mark_detail_outcome(
        self,
        db,
        *,
        listing_id,
        detail_crawl_job_id,
        status=None,
        error_message,
        detail_payload=None,
        detail_status=None,
        auto_commit=True,
    ):
        detail_status = status if status is not None else detail_status
        assert detail_status in self._OUTCOME_STATUSES
        row = self._row(db, listing_id)
        row["detail_status"] = detail_status
        row["last_detail_crawl_job_id"] = str(detail_crawl_job_id)
        row["detail_error_message"] = error_message
        if detail_payload is not None:
            row["detail_payload"] = deepcopy(detail_payload)
        if auto_commit:
            db.commit()
        return SimpleNamespace(**row)

    def count_detail_statuses(
        self,
        db,
        *,
        source_site=None,
        source_listing_crawl_job_id=None,
        category_ids=None,
    ):
        counts: dict[str, int] = {}
        for row in db.working.rows.values():
            if source_site is not None and row["source_site"] != source_site:
                continue
            if (
                source_listing_crawl_job_id is not None
                and row["crawl_job_id"] != str(source_listing_crawl_job_id)
            ):
                continue
            status = row["detail_status"]
            counts[status] = counts.get(status, 0) + 1
        return counts

    def count_detail_statuses_for_detail_crawl_job(
        self,
        db,
        *,
        detail_crawl_job_id,
        source_site=None,
    ):
        counts: dict[str, int] = {}
        for row in db.working.rows.values():
            if row.get("last_detail_crawl_job_id") != str(detail_crawl_job_id):
                continue
            if source_site is not None and row["source_site"] != source_site:
                continue
            status = row["detail_status"]
            counts[status] = counts.get(status, 0) + 1
        return counts


class _CrawlJobRepository:
    def __init__(
        self,
        *,
        fail_detail_attempt_once: bool = False,
        fail_detail_persisted_once: bool = False,
    ) -> None:
        self.fail_detail_attempt_once = fail_detail_attempt_once
        self.fail_detail_persisted_once = fail_detail_persisted_once

    def get_crawl_job_by_id(self, db, crawl_job_id):
        metrics = db.working.metrics.setdefault(str(crawl_job_id), {})
        return SimpleNamespace(id=str(crawl_job_id), metrics=metrics)

    def merge_metrics(self, db, *, crawl_job_id, metrics_patch, auto_commit=True):
        metrics = db.working.metrics.setdefault(str(crawl_job_id), {})
        metrics.update(deepcopy(metrics_patch))
        if auto_commit:
            db.commit()
        return SimpleNamespace(id=str(crawl_job_id), metrics=metrics)

    def append_event(self, db, **kwargs):
        if (
            kwargs["event_type"] == "crawl.detail_attempt"
            and self.fail_detail_attempt_once
        ):
            self.fail_detail_attempt_once = False
            raise RuntimeError("injected detail attempt event failure")
        if (
            kwargs["event_type"] == "crawl.detail_persisted"
            and self.fail_detail_persisted_once
        ):
            self.fail_detail_persisted_once = False
            raise RuntimeError("injected detail persistence event failure")
        db.working.events.append(deepcopy(kwargs))
        if kwargs.get("auto_commit", True):
            db.commit()
        return SimpleNamespace()


class _CompanyRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def upsert_company(self, db, company_data, *, auto_commit=True):
        self.calls.append(deepcopy(company_data))
        key = str(company_data["source_company_id"])
        action = "updated" if key in db.working.companies else "created"
        company = {**deepcopy(company_data), "id": f"company:{key}"}
        db.working.companies[key] = company
        if auto_commit:
            db.commit()
        return SimpleNamespace(**company), action


class _JobRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def upsert_source_job(
        self,
        db,
        job_data,
        *,
        skip_existing=False,
        auto_commit=True,
    ):
        assert skip_existing is False
        self.calls.append(deepcopy(job_data))
        key = str(job_data["source_job_id"])
        action = "updated" if key in db.working.jobs else "created"
        job = {**deepcopy(job_data), "id": f"job:{key}"}
        db.working.jobs[key] = job
        if auto_commit:
            db.commit()
        return SimpleNamespace(**job), action

    def list_existing_jobs_by_source_ids(self, *args, **kwargs):
        return {}


class _DetailFetcher:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, job_id: str, encrypted_job_id: str):
        self.calls.append((job_id, encrypted_job_id))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return deepcopy(outcome)


class _Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        self.value += 0.125
        return self.value


def _row(listing_id: str, source_job_id: str, *, crawl_job_id="listing-run"):
    return {
        "id": listing_id,
        "crawl_job_id": crawl_job_id,
        "source_site": "offertoday",
        "source_job_id": source_job_id,
        "detail_status": "pending",
        "detail_attempts": 0,
        "last_detail_crawl_job_id": None,
        "detail_payload": None,
        "published_job_id": None,
        "detail_error_message": None,
    }


def _runtime_target(
    source_job_id="100",
    *,
    listing_id="listing-a",
    duplicate_listing_ids=("listing-b",),
):
    encrypted_job_id = f"enc-{source_job_id}"
    listing_payload = {
        "job_id": source_job_id,
        "encrypted_job_id": encrypted_job_id,
        "title": "Listing title",
        "company_name": "Listing company",
        "listing_only_marker": "do-not-copy-to-detail-payload",
        "raw_data": {
            "jobId": source_job_id,
            "encryptJobId": encrypted_job_id,
        },
    }
    return {
        "listing_id": listing_id,
        "duplicate_listing_ids": tuple(duplicate_listing_ids),
        "source_job_id": source_job_id,
        "listing_payload": listing_payload,
        "identity": OfferTodayDetailIdentity(
            job_id=source_job_id,
            encrypted_job_id=encrypted_job_id,
        ),
    }


def _success_response(source_job_id="100", *, include_encrypted=True):
    data = {
        "jobId": source_job_id,
        "jobName": "Platform Engineer",
        "companyName": "Example Limited",
        "jobDesc": "<p>Build reliable systems.</p>",
        "industry": {"name": "Technology"},
        "employType": {"name": "Full time"},
        "addressVO": {},
        "benefits": [],
        "skills": [],
        "skillList": [],
        "keywords": [],
    }
    if include_encrypted:
        data["encryptJobId"] = f"enc-{source_job_id}"
    return {"code": 0, "msg": "ok", "data": data}


def _build_pipeline(
    outcomes,
    *,
    rows=None,
    fail_detail_attempt_once=False,
    fail_detail_persisted_once=False,
    fail_success_commit_once=False,
    fail_detail_completed_after=None,
):
    store = _TransactionalStore(
        rows=deepcopy(
            rows
            or {
                "listing-a": _row("listing-a", "100"),
                "listing-b": _row("listing-b", "100"),
            }
        )
    )
    sessions = _SessionFactory(
        store,
        fail_success_commit_once=fail_success_commit_once,
    )
    listings = _ListingRepository(
        fail_detail_completed_after=fail_detail_completed_after
    )
    crawl_jobs = _CrawlJobRepository(
        fail_detail_attempt_once=fail_detail_attempt_once,
        fail_detail_persisted_once=fail_detail_persisted_once
    )
    companies = _CompanyRepository()
    jobs = _JobRepository()
    runtime = CrawlJobRuntime(
        sessions,
        crawl_job_repository=crawl_jobs,
        crawl_job_listing_repository=listings,
        job_repository=jobs,
    )
    fetcher = _DetailFetcher(list(outcomes))
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    pipeline = OfferTodayDetailPipeline(
        session_factory=sessions,
        crawl_runtime=runtime,
        company_repository=companies,
        job_repository=jobs,
        sleep=sleep,
        clock=_Clock(),
        max_attempts=3,
        retry_delays_seconds=(1.0, 2.0),
    )
    return SimpleNamespace(
        pipeline=pipeline,
        runtime=runtime,
        store=store,
        sessions=sessions,
        listings=listings,
        crawl_jobs=crawl_jobs,
        companies=companies,
        jobs=jobs,
        fetcher=fetcher,
        sleeps=sleeps,
    )


def _attempt_events(store: _TransactionalStore):
    return [
        event
        for event in store.events
        if event["event_type"] == "crawl.detail_attempt"
    ]


def test_detail_fetcher_is_a_per_call_dependency_not_constructor_state():
    constructor_parameters = inspect.signature(
        OfferTodayDetailPipeline
    ).parameters

    assert "detail_fetcher" not in constructor_parameters


@pytest.mark.asyncio
async def test_success_persists_job_and_completes_canonical_group_atomically():
    env = _build_pipeline([_success_response()])
    target = OfferTodayDetailTarget.from_runtime_target(_runtime_target())

    result = await env.pipeline.process_target(
        target=target,
        detail_crawl_job_id="detail-run",
        fetch_detail=env.fetcher,
    )

    assert env.fetcher.calls == [("100", "enc-100")]
    assert result.outcome is OfferTodayResponseKind.SUCCESS
    assert result.job_action == "created"
    assert result.company_action == "created"
    assert result.stop_batch is False
    assert set(env.store.jobs) == {"100"}
    assert set(env.store.companies)
    assert [env.store.rows[key]["detail_status"] for key in target.listing_ids] == [
        "completed",
        "completed",
    ]
    assert env.store.rows["listing-a"]["detail_attempts"] == 1
    assert env.store.rows["listing-b"]["detail_attempts"] == 0
    assert env.store.rows["listing-a"]["detail_payload"]["job_id"] == "100"
    assert (
        "listing_only_marker"
        not in env.store.rows["listing-a"]["detail_payload"]
    )
    persisted = [
        event
        for event in env.store.events
        if event["event_type"] == "crawl.detail_persisted"
    ]
    assert len(persisted) == 1
    payload = persisted[0]["payload"]
    assert payload["listing_ids"] == ["listing-a", "listing-b"]
    assert payload["source_job_id"] == "100"
    assert payload["published_job_id"] == "job:100"
    success_sessions = [
        session
        for session in env.sessions.sessions
        if "100" in session.working.jobs
    ]
    assert len(success_sessions) == 1
    assert success_sessions[0].commits == 1
    expected_hash = hashlib.sha256(
        json.dumps(
            {"encrypted_job_id": "enc-100", "job_id": "100"},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    assert payload["response_identity_hash"] == expected_hash


@pytest.mark.asyncio
async def test_success_without_response_encrypted_id_preserves_request_url():
    env = _build_pipeline([_success_response(include_encrypted=False)])

    result = await env.pipeline.process_target(
        target=OfferTodayDetailTarget.from_runtime_target(_runtime_target()),
        detail_crawl_job_id="detail-run",
        fetch_detail=env.fetcher,
    )

    assert result.outcome is OfferTodayResponseKind.SUCCESS
    published = env.store.jobs["100"]
    assert published["raw_data"]["encrypted_job_id"] == "enc-100"
    assert published["raw_data"]["canonical_job_url"].endswith("/enc-100")


@pytest.mark.asyncio
async def test_terminal_2520_marks_every_group_row_without_retry_or_job():
    env = _build_pipeline([{"code": 2520, "msg": "position unavailable"}])
    target = OfferTodayDetailTarget.from_runtime_target(_runtime_target())

    result = await env.pipeline.process_target(
        target=target,
        detail_crawl_job_id="detail-run",
        fetch_detail=env.fetcher,
    )

    assert result.outcome is OfferTodayResponseKind.TERMINAL_UNAVAILABLE
    assert result.stop_batch is False
    assert env.fetcher.calls == [("100", "enc-100")]
    assert env.store.jobs == {}
    assert env.store.companies == {}
    assert {env.store.rows[key]["detail_status"] for key in target.listing_ids} == {
        "terminal_unavailable"
    }


@pytest.mark.asyncio
async def test_transient_transport_retries_three_times_and_only_authoritative_attempts_increment():
    env = _build_pipeline(
        [
            TimeoutError("temporary 1"),
            TimeoutError("temporary 2"),
            TimeoutError("temporary 3"),
        ]
    )
    target = OfferTodayDetailTarget.from_runtime_target(_runtime_target())

    result = await env.pipeline.process_target(
        target=target,
        detail_crawl_job_id="detail-run",
        fetch_detail=env.fetcher,
    )

    assert result.outcome is OfferTodayResponseKind.TRANSIENT_TRANSPORT
    assert env.sleeps == [1.0, 2.0]
    assert env.store.rows["listing-a"]["detail_attempts"] == 3
    assert env.store.rows["listing-b"]["detail_attempts"] == 0
    assert {env.store.rows[key]["detail_status"] for key in target.listing_ids} == {
        "failed"
    }
    attempts = _attempt_events(env.store)
    assert [event["payload"]["attempt"] for event in attempts] == [1, 2, 3]
    assert [event["payload"]["will_retry"] for event in attempts] == [
        True,
        True,
        False,
    ]
    assert all(event["payload"]["latency_ms"] >= 0 for event in attempts)
    expected_event_keys = {
        "source_job_id",
        "encrypted_job_id",
        "attempt",
        "classification",
        "api_code",
        "http_status",
        "latency_ms",
        "will_retry",
        "stop_batch",
    }
    assert all(set(event["payload"]) == expected_event_keys for event in attempts)
    forbidden_fragments = {
        "authorization",
        "cookie",
        "csrf",
        "header",
        "token",
    }
    assert all(
        not any(
            fragment in str(key).lower()
            for fragment in forbidden_fragments
            for key in event["payload"]
        )
        for event in attempts
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception_type",
    (AssertionError, TypeError, RuntimeError, FileNotFoundError),
)
async def test_unexpected_fetch_error_fails_group_and_propagates_same_exception(
    exception_type,
):
    unexpected = exception_type(
        r"sensitive fetch detail C:\private\offertoday-response.json"
    )
    env = _build_pipeline([unexpected])
    target = OfferTodayDetailTarget.from_runtime_target(_runtime_target())

    with pytest.raises(exception_type) as raised:
        await env.pipeline.process_target(
            target=target,
            detail_crawl_job_id="detail-run",
            fetch_detail=env.fetcher,
        )

    assert raised.value is unexpected
    assert env.fetcher.calls == [("100", "enc-100")]
    assert env.sleeps == []
    assert _attempt_events(env.store) == []
    assert {env.store.rows[key]["detail_status"] for key in target.listing_ids} == {
        "failed"
    }
    assert all(
        env.store.rows[key]["detail_error_message"]
        == f"unexpected_fetch_error:{exception_type.__name__}"
        for key in target.listing_ids
    )
    assert all(
        "sensitive fetch detail" not in env.store.rows[key]["detail_error_message"]
        and "private" not in env.store.rows[key]["detail_error_message"]
        for key in target.listing_ids
    )
    assert all(
        env.store.rows[key]["last_detail_crawl_job_id"] == "detail-run"
        for key in target.listing_ids
    )
    assert env.store.rows["listing-a"]["detail_attempts"] == 1
    assert env.store.rows["listing-b"]["detail_attempts"] == 0
    assert env.store.jobs == {}
    assert env.store.companies == {}
    assert env.jobs.calls == []
    assert env.companies.calls == []
    assert len(env.sessions.sessions) == 2
    assert all(session.commits == 1 for session in env.sessions.sessions)
    assert all(session.closed for session in env.sessions.sessions)


@pytest.mark.asyncio
async def test_id_mismatch_stops_batch_and_skips_company_and_job_repositories():
    env = _build_pipeline([_success_response("different")])
    target = OfferTodayDetailTarget.from_runtime_target(_runtime_target())

    result = await env.pipeline.process_target(
        target=target,
        detail_crawl_job_id="detail-run",
        fetch_detail=env.fetcher,
    )

    assert result.outcome is OfferTodayResponseKind.ID_MISMATCH
    assert result.stop_batch is True
    assert {env.store.rows[key]["detail_status"] for key in target.listing_ids} == {
        "identity_conflict"
    }
    assert env.companies.calls == []
    assert env.jobs.calls == []


@pytest.mark.asyncio
async def test_ip_block_marks_only_attempted_group_manual_and_leaves_later_row_pending():
    rows = {
        "listing-a": _row("listing-a", "100"),
        "listing-b": _row("listing-b", "100"),
        "later": _row("later", "200"),
    }
    env = _build_pipeline(
        [{"code": -1000035, "msg": "blocked"}],
        rows=rows,
    )
    target = OfferTodayDetailTarget.from_runtime_target(_runtime_target())

    result = await env.pipeline.process_target(
        target=target,
        detail_crawl_job_id="detail-run",
        fetch_detail=env.fetcher,
    )

    assert result.outcome is OfferTodayResponseKind.IP_BLOCKED
    assert result.stop_batch is True
    assert {env.store.rows[key]["detail_status"] for key in target.listing_ids} == {
        "manual_action_required"
    }
    assert env.store.rows["later"]["detail_status"] == "pending"
    assert env.store.rows["later"]["detail_attempts"] == 0


@pytest.mark.asyncio
async def test_empty_canonical_payload_fails_group_without_repository_calls():
    response = _success_response()
    response["data"].update(jobName="", companyName="", jobDesc="")
    env = _build_pipeline([response])
    target = OfferTodayDetailTarget.from_runtime_target(
        {
            **_runtime_target(),
            "listing_payload": {
                "job_id": "100",
                "encrypted_job_id": "enc-100",
                "raw_data": {"jobId": "100", "encryptJobId": "enc-100"},
            },
        }
    )

    result = await env.pipeline.process_target(
        target=target,
        detail_crawl_job_id="detail-run",
        fetch_detail=env.fetcher,
    )

    assert result.outcome is OfferTodayResponseKind.INVALID_PAYLOAD
    assert {env.store.rows[key]["detail_status"] for key in target.listing_ids} == {
        "failed"
    }
    assert env.companies.calls == []
    assert env.jobs.calls == []


@pytest.mark.asyncio
async def test_success_persistence_interruption_rolls_back_all_then_marks_group_failed():
    raw_response = _success_response()
    env = _build_pipeline(
        [raw_response],
        fail_detail_persisted_once=True,
    )
    target = OfferTodayDetailTarget.from_runtime_target(_runtime_target())

    result = await env.pipeline.process_target(
        target=target,
        detail_crawl_job_id="detail-run",
        fetch_detail=env.fetcher,
    )

    assert result.outcome is OfferTodayResponseKind.PERSIST_FAILURE
    assert result.stop_batch is False
    assert env.store.jobs == {}
    assert env.store.companies == {}
    assert {env.store.rows[key]["detail_status"] for key in target.listing_ids} == {
        "failed"
    }
    assert all(
        env.store.rows[key]["detail_error_message"] == "persist_failure:RuntimeError"
        for key in target.listing_ids
    )
    assert all(
        env.store.rows[key]["detail_payload"] == raw_response
        for key in target.listing_ids
    )
    assert not any(
        event["event_type"] == "crawl.detail_persisted"
        for event in env.store.events
    )
    assert any(session.rollbacks == 1 for session in env.sessions.sessions)


@pytest.mark.asyncio
async def test_attempt_event_failure_marks_entire_group_failed_in_fresh_transaction():
    env = _build_pipeline(
        [_success_response()],
        fail_detail_attempt_once=True,
    )
    target = OfferTodayDetailTarget.from_runtime_target(_runtime_target())

    result = await env.pipeline.process_target(
        target=target,
        detail_crawl_job_id="detail-run",
        fetch_detail=env.fetcher,
    )

    assert result.outcome is OfferTodayResponseKind.PERSIST_FAILURE
    assert result.stop_batch is False
    assert {env.store.rows[key]["detail_status"] for key in target.listing_ids} == {
        "failed"
    }
    assert env.store.rows["listing-a"]["detail_attempts"] == 1
    assert env.store.rows["listing-b"]["detail_attempts"] == 0
    assert all(
        env.store.rows[key]["detail_error_message"]
        == "attempt_event_failure:RuntimeError"
        for key in target.listing_ids
    )
    assert env.store.jobs == {}
    assert env.store.companies == {}
    assert _attempt_events(env.store) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "fetch_outcome",
        "expected_kind",
        "expected_status",
        "expected_stop_batch",
        "expected_error",
        "expected_payload",
    ),
    [
        pytest.param(
            _success_response("different"),
            OfferTodayResponseKind.ID_MISMATCH,
            "identity_conflict",
            True,
            (
                "id_mismatch:Expected jobId=100, got jobId=different;"
                "attempt_event_failure:RuntimeError"
            ),
            _success_response("different"),
            id="id-mismatch",
        ),
        pytest.param(
            {"code": 1002, "msg": "login expired", "data": {}},
            OfferTodayResponseKind.AUTH_EXPIRED,
            "manual_action_required",
            True,
            "auth_expired:login expired;attempt_event_failure:RuntimeError",
            {"code": 1002, "msg": "login expired", "data": {}},
            id="auth-expired",
        ),
        pytest.param(
            OfferTodayTransportError(
                "sensitive upstream diagnostic",
                http_status=200,
                response_url="https://www.offertoday.com/web/passport/cm/verify",
                payload={"challenge": "verification-page"},
                error_kind="http",
            ),
            OfferTodayResponseKind.WAF_CHALLENGE,
            "manual_action_required",
            True,
            (
                "waf_challenge:OfferToday verification challenge;"
                "attempt_event_failure:RuntimeError"
            ),
            {"challenge": "verification-page"},
            id="waf-challenge",
        ),
        pytest.param(
            {"code": -1000035, "msg": "IP blocked", "data": {}},
            OfferTodayResponseKind.IP_BLOCKED,
            "manual_action_required",
            True,
            "ip_blocked:IP blocked;attempt_event_failure:RuntimeError",
            {"code": -1000035, "msg": "IP blocked", "data": {}},
            id="ip-blocked",
        ),
        pytest.param(
            {"code": 2520, "msg": "position unavailable", "data": {}},
            OfferTodayResponseKind.TERMINAL_UNAVAILABLE,
            "terminal_unavailable",
            False,
            (
                "terminal_unavailable:position unavailable;"
                "attempt_event_failure:RuntimeError"
            ),
            {"code": 2520, "msg": "position unavailable", "data": {}},
            id="terminal-unavailable",
        ),
    ],
)
async def test_final_classification_survives_attempt_event_persistence_failure(
    fetch_outcome,
    expected_kind,
    expected_status,
    expected_stop_batch,
    expected_error,
    expected_payload,
):
    env = _build_pipeline(
        [fetch_outcome],
        fail_detail_attempt_once=True,
    )
    target = OfferTodayDetailTarget.from_runtime_target(_runtime_target())

    result = await env.pipeline.process_target(
        target=target,
        detail_crawl_job_id="detail-run",
        fetch_detail=env.fetcher,
    )

    assert result.outcome is expected_kind
    assert result.stop_batch is expected_stop_batch
    assert {env.store.rows[key]["detail_status"] for key in target.listing_ids} == {
        expected_status
    }
    assert all(
        env.store.rows[key]["detail_error_message"] == expected_error
        for key in target.listing_ids
    )
    assert all(
        env.store.rows[key]["detail_payload"] == expected_payload
        for key in target.listing_ids
    )
    assert all(
        "sensitive upstream diagnostic"
        not in env.store.rows[key]["detail_error_message"]
        for key in target.listing_ids
    )
    assert env.store.rows["listing-a"]["detail_attempts"] == 1
    assert env.store.rows["listing-b"]["detail_attempts"] == 0
    assert env.store.jobs == {}
    assert env.store.companies == {}
    assert _attempt_events(env.store) == []


@pytest.mark.asyncio
async def test_success_commit_interruption_publishes_nothing_then_fails_group():
    env = _build_pipeline(
        [_success_response()],
        fail_success_commit_once=True,
    )
    target = OfferTodayDetailTarget.from_runtime_target(_runtime_target())

    result = await env.pipeline.process_target(
        target=target,
        detail_crawl_job_id="detail-run",
        fetch_detail=env.fetcher,
    )

    assert result.outcome is OfferTodayResponseKind.PERSIST_FAILURE
    assert env.store.jobs == {}
    assert env.store.companies == {}
    assert not any(
        event["event_type"] == "crawl.detail_persisted"
        for event in env.store.events
    )
    assert {env.store.rows[key]["detail_status"] for key in target.listing_ids} == {
        "failed"
    }
    assert all(env.store.rows[key]["published_job_id"] is None for key in target.listing_ids)
    failed_commit_sessions = [
        session
        for session in env.sessions.sessions
        if session.commit_failures == 1
    ]
    assert len(failed_commit_sessions) == 1
    assert failed_commit_sessions[0].rollbacks == 1


@pytest.mark.asyncio
async def test_group_completion_interruption_rolls_back_publish_then_fails_group():
    raw_response = _success_response()
    env = _build_pipeline(
        [raw_response],
        fail_detail_completed_after=2,
    )
    target = OfferTodayDetailTarget.from_runtime_target(_runtime_target())

    result = await env.pipeline.process_target(
        target=target,
        detail_crawl_job_id="detail-run",
        fetch_detail=env.fetcher,
    )

    assert env.listings.completed_before_failure == ["listing-a", "listing-b"]
    assert result.outcome is OfferTodayResponseKind.PERSIST_FAILURE
    assert env.store.jobs == {}
    assert env.store.companies == {}
    assert not any(
        event["event_type"] == "crawl.detail_persisted"
        for event in env.store.events
    )
    assert {env.store.rows[key]["detail_status"] for key in target.listing_ids} == {
        "failed"
    }
    assert all(env.store.rows[key]["published_job_id"] is None for key in target.listing_ids)
    assert all(
        env.store.rows[key]["detail_payload"] == raw_response
        for key in target.listing_ids
    )
    assert any(session.rollbacks == 1 for session in env.sessions.sessions)


def test_target_uses_authoritative_and_duplicate_ids_and_validates_identity():
    target = OfferTodayDetailTarget.from_runtime_target(_runtime_target())

    assert target.listing_ids == ("listing-a", "listing-b")
    assert target.identity == OfferTodayDetailIdentity("100", "enc-100")

    invalid = _runtime_target()
    invalid["identity"] = OfferTodayDetailIdentity("other", "enc-100")
    with pytest.raises(ValueError, match="identity"):
        OfferTodayDetailTarget.from_runtime_target(invalid)


def test_target_accepts_explicit_authority_over_fallback_listing_without_rewrite():
    runtime_target = _runtime_target("100")
    runtime_target["listing_payload"] = {
        "job_id": "100",
        "encrypted_job_id": "100",
        "encrypted_job_id_source": "jobId_fallback",
        "raw_data": {"jobId": "100"},
    }
    runtime_target["identity"] = OfferTodayDetailIdentity(
        job_id="100",
        encrypted_job_id="enc-100",
        encrypted_job_id_source="encryptJobId",
    )
    before = deepcopy(runtime_target["listing_payload"])

    target = OfferTodayDetailTarget.from_runtime_target(runtime_target)

    assert target.identity.encrypted_job_id == "enc-100"
    assert target.identity.encrypted_job_id_source == "encryptJobId"
    assert runtime_target["listing_payload"] == before


@pytest.mark.asyncio
async def test_process_target_accepts_keyword_only_per_call_detail_fetcher():
    env = _build_pipeline([_success_response()])
    pipeline = OfferTodayDetailPipeline(
        session_factory=env.sessions,
        crawl_runtime=env.runtime,
        company_repository=env.companies,
        job_repository=env.jobs,
        sleep=env.pipeline.sleep,
        clock=_Clock(),
    )

    result = await pipeline.process_target(
        target=OfferTodayDetailTarget.from_runtime_target(_runtime_target()),
        detail_crawl_job_id="detail-run",
        fetch_detail=env.fetcher,
    )

    assert result.outcome is OfferTodayResponseKind.SUCCESS
    assert env.fetcher.calls == [("100", "enc-100")]


@pytest.mark.asyncio
async def test_canonical_key_error_becomes_invalid_payload_without_persistence(
    monkeypatch,
):
    pipeline_module = __import__(
        "app.services.offertoday_detail_pipeline",
        fromlist=["build_offertoday_canonical_job"],
    )

    def raise_missing_key(_payload):
        raise KeyError("required canonical field")

    monkeypatch.setattr(
        pipeline_module,
        "build_offertoday_canonical_job",
        raise_missing_key,
    )
    env = _build_pipeline([_success_response()])
    target = OfferTodayDetailTarget.from_runtime_target(_runtime_target())

    result = await env.pipeline.process_target(
        target=target,
        detail_crawl_job_id="detail-run",
        fetch_detail=env.fetcher,
    )

    assert result.outcome is OfferTodayResponseKind.INVALID_PAYLOAD
    assert {env.store.rows[key]["detail_status"] for key in target.listing_ids} == {
        "failed"
    }
    assert env.companies.calls == []
    assert env.jobs.calls == []
