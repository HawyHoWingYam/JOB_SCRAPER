# Audit Optimization Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]` / `- [x]`) syntax for tracking.

**Goal:** Build the first audit optimization foundation by adding truthful backend capabilities, richer operator health, shared crawl request validation, backlog-oriented listing batch filters, frontend capability gating, and audit documentation validation.

**Architecture:** Keep Batch 1 read-only and contract-focused. Backend changes add small service/schema modules and API surfaces that summarize current runtime capabilities without changing worker semantics. Frontend changes consume those capabilities through shared helpers so unavailable semantic/recommendation/scheduler states are visible before request failure.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy, pytest, React 19, Vite, Vitest, plain CSS.

---

## File Structure

- Create `backend/app/services/runtime_capabilities_service.py`: builds `/api/v1/capabilities` payload from settings, AI runtime metadata, scheduler runtime, optional sidecar URLs, and operator health.
- Create `backend/app/api/capabilities.py`: FastAPI router for `GET /api/v1/capabilities`.
- Modify `backend/app/api/__init__.py`: include capabilities router under `/api/v1`.
- Modify `backend/app/api/health.py`: add outbox, staged-to-published, pending detail, embedding freshness, and sidecar configuration/readiness fields to `operator`.
- Modify `backend/app/schemas/schedule.py` and `backend/app/schemas/crawl_job.py`: delegate duplicated crawl request normalization/validation to a shared helper.
- Create `backend/app/services/crawl_request_validation.py`: source/category/crawl phase/crawl mode validation functions shared by schedules and crawl jobs.
- Modify `backend/app/repositories/crawl_job_listing_repository.py`: replace recent-job loop with grouped listing batch query filters.
- Modify `backend/app/api/crawl_jobs.py`: expose listing batch filters: `category_id` and `detail_status`.
- Create `frontend/src/api/client.js`: shared JSON fetch helper with `detail` extraction and abortable timeout.
- Create `frontend/src/api/capabilities.js`: `fetchCapabilities()` wrapper.
- Modify `frontend/src/components/JobBrowser.jsx`: fetch capabilities and disable semantic/hybrid modes when retrieval is unavailable.
- Modify `frontend/src/components/JobDetailModal.jsx`: hide or message related jobs when recommendations are unavailable.
- Modify `frontend/src/components/scraper/ScheduleManager.jsx`: use shared client for health/capabilities and surface scheduler/crawl capability state.
- Create `backend/scripts/validate_audit_docs.py`: checks audit leaf required sections, README links, local referenced file paths, and placeholder text.

---

### Task 1: Backend Capability Endpoint

**Files:**
- Create: `backend/app/services/runtime_capabilities_service.py`
- Create: `backend/app/api/capabilities.py`
- Modify: `backend/app/api/__init__.py`
- Test: `backend/tests/test_capabilities_api.py`

- [x] **Step 1: Write failing tests for default capabilities**

Create `backend/tests/test_capabilities_api.py`:

```python
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.services.runtime_capabilities_service as service_module
from app.services.runtime_capabilities_service import build_runtime_capabilities


class _RuntimeStatus:
    is_ready = True
    is_degraded = False
    requires_test = False
    configured_provider = "custom"
    model = "deepseek-v4-flash"
    active_fingerprint = "fp-runtime"
    last_tested_fingerprint = "fp-runtime"
    degradation_reason = None
    last_tested_at = None


def test_build_runtime_capabilities_reports_lexical_baseline_without_sidecars(monkeypatch):
    monkeypatch.setattr(service_module.settings, "retrieval_api_url", None)
    monkeypatch.setattr(service_module.settings, "recommendation_api_url", None)
    monkeypatch.setattr(
        service_module,
        "get_profile_runtime_metadata",
        lambda scope: _RuntimeStatus(),
    )
    monkeypatch.setattr(
        service_module,
        "get_scheduler_runtime_status",
        lambda: {"enabled": True, "running": True, "owner": "backend-api"},
    )
    monkeypatch.setattr(
        service_module,
        "build_operator_health_summary",
        lambda: {"status": "healthy", "workers": {}, "queues": {}, "freshness": {}},
    )

    payload = build_runtime_capabilities()

    assert payload["search"]["lexical"]["available"] is True
    assert payload["search"]["semantic"]["available"] is False
    assert payload["search"]["hybrid"]["reason"] == "retrieval_api_url_not_configured"
    assert payload["recommendations"]["similar_jobs"]["available"] is False
    assert payload["ai"]["jobs"]["available"] is True
    assert payload["scheduler"]["available"] is True
    assert payload["sources"]["jobsdb"]["default_crawl_mode"] == "headed"
    assert payload["sources"]["ctgoodjobs"]["manual_action_supported"] is True
```

- [x] **Step 2: Run the failing backend capability test**

Run:

```bash
python -m pytest backend/tests/test_capabilities_api.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.runtime_capabilities_service'`.

- [x] **Step 3: Add runtime capability service**

Create `backend/app/services/runtime_capabilities_service.py`:

```python
from __future__ import annotations

from typing import Any

from app.config import settings
from app.api.health import build_operator_health_summary
from app.services.ai_runtime_settings_service import get_profile_runtime_metadata
from app.services.scheduler_runtime import get_scheduler_runtime_status


def _runtime_status(scope: str) -> dict[str, Any]:
    metadata = get_profile_runtime_metadata(scope)
    return {
        "available": bool(metadata.is_ready),
        "is_ready": bool(metadata.is_ready),
        "is_degraded": bool(metadata.is_degraded),
        "requires_test": bool(metadata.requires_test),
        "provider": metadata.configured_provider,
        "model": metadata.model,
        "active_fingerprint": metadata.active_fingerprint,
        "last_tested_fingerprint": metadata.last_tested_fingerprint,
        "reason": metadata.degradation_reason,
        "last_tested_at": metadata.last_tested_at.isoformat() if metadata.last_tested_at else None,
    }


def _sidecar_capability(url: str | None, *, configured_reason: str) -> dict[str, Any]:
    configured = bool((url or "").strip())
    return {
        "available": configured,
        "configured": configured,
        "url_configured": configured,
        "reason": None if configured else configured_reason,
    }


def _source_capabilities() -> dict[str, dict[str, Any]]:
    return {
        "jobsdb": {
            "available": True,
            "listing_supported": True,
            "detail_supported": True,
            "headless_supported": True,
            "headed_supported": True,
            "manual_action_supported": True,
            "default_crawl_mode": "headed",
            "category_id_type": "integer",
        },
        "ctgoodjobs": {
            "available": True,
            "listing_supported": True,
            "detail_supported": True,
            "headless_supported": True,
            "headed_supported": True,
            "manual_action_supported": True,
            "default_crawl_mode": "headed",
            "category_id_type": "string",
        },
    }


def build_runtime_capabilities() -> dict[str, Any]:
    retrieval = _sidecar_capability(
        settings.retrieval_api_url,
        configured_reason="retrieval_api_url_not_configured",
    )
    recommendations = _sidecar_capability(
        settings.recommendation_api_url,
        configured_reason="recommendation_api_url_not_configured",
    )
    operator = build_operator_health_summary()
    scheduler = get_scheduler_runtime_status()

    return {
        "search": {
            "lexical": {"available": True, "reason": None},
            "semantic": retrieval,
            "hybrid": dict(retrieval),
            "export": {
                "lexical": {"available": True, "reason": None},
                "semantic": dict(retrieval),
                "hybrid": dict(retrieval),
            },
        },
        "recommendations": {
            "similar_jobs": recommendations,
        },
        "ai": {
            "jobs": _runtime_status("jobs"),
            "companies": _runtime_status("companies"),
        },
        "scheduler": {
            "available": bool(scheduler.get("enabled", True)),
            **scheduler,
        },
        "operator_recovery": {
            "available": True,
            "health_status": operator.get("status", "unknown"),
        },
        "sources": _source_capabilities(),
        "operator": {
            "status": operator.get("status", "unknown"),
            "workers": operator.get("workers", {}),
            "queues": operator.get("queues", {}),
            "freshness": operator.get("freshness", {}),
        },
    }
```

- [x] **Step 4: Add API router and register it**

Create `backend/app/api/capabilities.py`:

```python
from fastapi import APIRouter

from app.services.runtime_capabilities_service import build_runtime_capabilities

router = APIRouter(tags=["capabilities"])


@router.get("/capabilities")
async def get_capabilities():
    return build_runtime_capabilities()
```

Modify `backend/app/api/__init__.py` so it imports and includes the router:

```python
from app.api import capabilities, companies, crawl_jobs, filters, health, jobs, recommendations, settings

router.include_router(capabilities.router, prefix="/api/v1")
```

- [x] **Step 5: Add scheduler runtime status helper if missing**

If `backend/app/services/scheduler_runtime.py` has no `get_scheduler_runtime_status`, add:

```python
def get_scheduler_runtime_status() -> dict:
    service = SchedulerService.get_instance()
    scheduler = getattr(service, "scheduler", None)
    return {
        "enabled": True,
        "owner": "backend-api",
        "running": bool(scheduler and getattr(scheduler, "running", False)),
    }
```

- [x] **Step 6: Run capability tests**

Run:

```bash
python -m pytest backend/tests/test_capabilities_api.py -q
```

Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add backend/app/services/runtime_capabilities_service.py backend/app/api/capabilities.py backend/app/api/__init__.py backend/app/services/scheduler_runtime.py backend/tests/test_capabilities_api.py
git commit -m "feat: expose runtime capability contract"
```

---

### Task 2: Operator Health Read-Only Metrics

**Files:**
- Modify: `backend/app/api/health.py`
- Test: `backend/tests/test_health_api.py`

- [x] **Step 1: Add failing health summary test**

Append to `backend/tests/test_health_api.py`:

```python
def test_operator_health_summary_includes_backlog_outbox_and_embedding_metrics(monkeypatch):
    class _Query:
        def __init__(self, value=None, rows=None, count_value=0):
            self.value = value
            self.rows = rows or []
            self.count_value = count_value

        def scalar(self):
            return self.value

        def count(self):
            return self.count_value

        def filter(self, *args, **kwargs):
            return self

        def group_by(self, *args, **kwargs):
            return self

        def all(self):
            return self.rows

    class _DB:
        def query(self, *entities):
            names = [getattr(entity, "__name__", str(entity)) for entity in entities]
            text = " ".join(names)
            if "CrawlJobListing.detail_status" in text:
                return _Query(rows=[("pending", 7), ("failed", 2)])
            if "EnrichmentRun.status" in text:
                return _Query(rows=[("queued", 3)])
            if "EventOutbox.status" in text:
                return _Query(rows=[("pending", 5), ("failed", 1)])
            if "JobEmbedding" in text:
                return _Query(count_value=4)
            if "Job" in text:
                return _Query(count_value=10)
            return _Query()

        def close(self):
            pass

    monkeypatch.setattr(health_module, "SessionLocal", lambda: _DB())
    monkeypatch.setattr(
        health_module,
        "RedisStreamBus",
        lambda: type(
            "Bus",
            (),
            {
                "redis": type(
                    "Redis",
                    (),
                    {
                        "xlen": lambda self, stream: 0,
                        "xinfo_groups": lambda self, stream: [],
                    },
                )()
            },
        )(),
    )

    payload = health_module.build_operator_health_summary()

    assert payload["freshness"]["crawl_job_listings"]["pending"] == 7
    assert payload["freshness"]["crawl_job_listings"]["failed"] == 2
    assert payload["freshness"]["outbox"]["pending"] == 5
    assert payload["freshness"]["outbox"]["failed"] == 1
    assert payload["freshness"]["embeddings"]["missing_current_embeddings"] == 6
```

- [x] **Step 2: Run failing test**

Run:

```bash
python -m pytest backend/tests/test_health_api.py -q
```

Expected: FAIL because `outbox` and `missing_current_embeddings` are absent.

- [x] **Step 3: Extend health query fields**

Modify `backend/app/api/health.py` imports:

```python
from app.models import CrawlJobListing, EnrichmentRun, EventOutbox, Job, JobEmbedding, JobSkillMention
```

Inside `build_operator_health_summary()`, after `enrichment_status_rows`, add:

```python
        outbox_status_rows = (
            db.query(EventOutbox.status, func.count(EventOutbox.id))
            .group_by(EventOutbox.status)
            .all()
        )
        total_embeddings = db.query(JobEmbedding).count()
```

After `enrichment_counts` is defined, add:

```python
        outbox_counts = {str(status): int(count) for status, count in outbox_status_rows}
        missing_current_embeddings = max(total_jobs - total_embeddings, 0)
        pending_outbox = int(outbox_counts.get("pending", 0))
        failed_outbox = int(outbox_counts.get("failed", 0))
        if pending_outbox:
            issues.append(f"event_outbox has {pending_outbox} pending rows")
        if failed_outbox:
            issues.append(f"event_outbox has {failed_outbox} failed rows")
        if missing_current_embeddings:
            issues.append(f"embeddings missing for {missing_current_embeddings} of {total_jobs} jobs")
```

In the `freshness` dictionary, change `embeddings` and add `outbox`:

```python
            "outbox": outbox_counts,
            "embeddings": {
                "newest_updated_at": _isoformat_or_none(newest_embedding_at),
                "current_embeddings": total_embeddings,
                "missing_current_embeddings": missing_current_embeddings,
            },
```

- [x] **Step 4: Run health tests**

Run:

```bash
python -m pytest backend/tests/test_health_api.py -q
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/api/health.py backend/tests/test_health_api.py
git commit -m "feat: expand operator health backlog metrics"
```

---

### Task 3: Shared Crawl Request Validation

**Files:**
- Create: `backend/app/services/crawl_request_validation.py`
- Modify: `backend/app/schemas/crawl_job.py`
- Modify: `backend/app/schemas/schedule.py`
- Test: `backend/tests/test_crawl_request_validation.py`
- Test: `backend/tests/test_crawl_jobs_api.py`
- Test: `backend/tests/test_scheduler_dispatcher.py`

- [x] **Step 1: Add focused validation tests**

Create `backend/tests/test_crawl_request_validation.py`:

```python
import sys
from pathlib import Path
from uuid import uuid4

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.crawl_request_validation import validate_crawl_request


def test_validate_listing_request_requires_categories():
    with pytest.raises(ValueError, match="listing runs require category_ids"):
        validate_crawl_request(
            source_site="jobsdb",
            crawl_phase="listing",
            crawl_mode=None,
            category_ids=None,
            source_listing_crawl_job_id=None,
        )


def test_validate_detail_request_accepts_source_listing_batch_without_categories():
    result = validate_crawl_request(
        source_site="jobsdb",
        crawl_phase="detail",
        crawl_mode=None,
        category_ids=None,
        source_listing_crawl_job_id=uuid4(),
    )

    assert result.source_site == "jobsdb"
    assert result.crawl_phase == "detail"
    assert result.crawl_mode == "headed"


def test_validate_ctgoodjobs_requires_string_categories():
    with pytest.raises(ValueError, match="CTGoodJobs category_ids must be strings"):
        validate_crawl_request(
            source_site="ctgoodjobs",
            crawl_phase="listing",
            crawl_mode=None,
            category_ids=[1200],
            source_listing_crawl_job_id=None,
        )
```

- [x] **Step 2: Run failing validation tests**

Run:

```bash
python -m pytest backend/tests/test_crawl_request_validation.py -q
```

Expected: FAIL with missing module.

- [x] **Step 3: Add validation service**

Create `backend/app/services/crawl_request_validation.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from app.crawl_modes import resolve_crawl_mode
from app.crawl_phases import resolve_crawl_phase

CategoryId = int | str


@dataclass(frozen=True)
class ValidatedCrawlRequest:
    source_site: str
    crawl_phase: str
    crawl_mode: str
    category_ids: list[CategoryId] | None
    source_listing_crawl_job_id: UUID | None


def validate_crawl_request(
    *,
    source_site: str | None,
    crawl_phase: str | None,
    crawl_mode: str | None,
    category_ids: Sequence[CategoryId] | None,
    source_listing_crawl_job_id: UUID | None,
) -> ValidatedCrawlRequest:
    normalized_source = normalize_source_site(source_site)
    resolved_phase = resolve_crawl_phase(crawl_phase)
    resolved_mode = resolve_crawl_mode(normalized_source, crawl_mode)
    normalized_categories = list(category_ids) if category_ids else None

    if resolved_phase == "listing":
        if not normalized_categories:
            raise ValueError("listing runs require category_ids")
        validate_category_ids_for_source_site(normalized_source, normalized_categories)
    else:
        if source_listing_crawl_job_id is None and not normalized_categories:
            raise ValueError("detail runs require source_listing_crawl_job_id or category_ids")
        if normalized_categories:
            validate_category_ids_for_source_site(normalized_source, normalized_categories)

    return ValidatedCrawlRequest(
        source_site=normalized_source,
        crawl_phase=resolved_phase,
        crawl_mode=resolved_mode,
        category_ids=normalized_categories,
        source_listing_crawl_job_id=source_listing_crawl_job_id,
    )


def normalize_source_site(source_site: str | None) -> str:
    return (source_site or "").strip().lower() or "jobsdb"


def validate_category_ids_for_source_site(
    source_site: str | None,
    category_ids: Sequence[CategoryId] | None,
) -> None:
    normalized_source_site = normalize_source_site(source_site)
    if normalized_source_site == "ctgoodjobs" and not category_ids:
        raise ValueError("CTGoodJobs category_ids must be provided")
    if not category_ids:
        return
    if normalized_source_site == "jobsdb":
        if any(not isinstance(category_id, int) for category_id in category_ids):
            raise ValueError("JobsDB category_ids must be integers")
    if normalized_source_site == "ctgoodjobs":
        if any(not isinstance(category_id, str) or not category_id.startswith("ctgoodjobs:") for category_id in category_ids):
            raise ValueError("CTGoodJobs category_ids must be strings with the ctgoodjobs: prefix")
```

- [x] **Step 4: Replace duplicated schema validation**

In `backend/app/schemas/schedule.py`, replace the local `CategoryId`, `normalize_source_site`, and `validate_category_ids_for_source_site` definitions with imports:

```python
from app.services.crawl_request_validation import CategoryId, normalize_source_site, validate_category_ids_for_source_site, validate_crawl_request
```

In `backend/app/schemas/crawl_job.py`, replace the schedule validation imports with:

```python
from app.services.crawl_request_validation import normalize_source_site, validate_category_ids_for_source_site, validate_crawl_request
```

Replace the body of `CrawlJobCreateRequest.validate_request_shape()` after `if self.schedule_id is not None` with:

```python
        validated = validate_crawl_request(
            source_site=self.source_site,
            crawl_phase=self.crawl_phase,
            crawl_mode=self.crawl_mode,
            category_ids=self.category_ids,
            source_listing_crawl_job_id=self.source_listing_crawl_job_id,
        )
        self.source_site = validated.source_site
        self.crawl_phase = validated.crawl_phase
        self.crawl_mode = validated.crawl_mode
        self.category_ids = validated.category_ids
        return self
```

In `backend/app/schemas/schedule.py`, import:

```python
from app.services.crawl_request_validation import validate_crawl_request
```

Replace `ScheduleCreateSchema.validate_category_ids()` body with:

```python
        validated = validate_crawl_request(
            source_site=self.source_site,
            crawl_phase=self.crawl_phase,
            crawl_mode=self.crawl_mode,
            category_ids=self.category_ids,
            source_listing_crawl_job_id=None,
        )
        self.source_site = validated.source_site
        self.crawl_phase = validated.crawl_phase
        self.crawl_mode = validated.crawl_mode
        self.category_ids = validated.category_ids
        return self
```

Replace `ImmediateScrapeRequest.validate_category_ids()` body with:

```python
        validated = validate_crawl_request(
            source_site=self.source_site,
            crawl_phase=self.crawl_phase,
            crawl_mode=self.crawl_mode,
            category_ids=self.category_ids,
            source_listing_crawl_job_id=self.source_listing_crawl_job_id,
        )
        self.source_site = validated.source_site
        self.crawl_phase = validated.crawl_phase
        self.crawl_mode = validated.crawl_mode
        self.category_ids = validated.category_ids
        return self
```

For `ScheduleUpdateSchema`, preserve partial-update semantics. Only call `validate_crawl_request()` when both `source_site` and `category_ids` are present, keeping existing behavior.

- [x] **Step 5: Run validation and existing API tests**

Run:

```bash
python -m pytest backend/tests/test_crawl_request_validation.py backend/tests/test_crawl_jobs_api.py backend/tests/test_scheduler_dispatcher.py -q
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add backend/app/services/crawl_request_validation.py backend/app/schemas/crawl_job.py backend/app/schemas/schedule.py backend/tests/test_crawl_request_validation.py backend/tests/test_crawl_jobs_api.py backend/tests/test_scheduler_dispatcher.py
git commit -m "refactor: share crawl request validation"
```

---

### Task 4: Listing Batch Backlog Filters

**Files:**
- Modify: `backend/app/repositories/crawl_job_listing_repository.py`
- Modify: `backend/app/api/crawl_jobs.py`
- Test: `backend/tests/test_crawl_job_listing_repository.py`
- Test: `backend/tests/test_crawl_jobs_api.py`

- [x] **Step 1: Add failing repository test for grouped backlog filters**

Append to `backend/tests/test_crawl_job_listing_repository.py`:

```python
def test_list_listing_batches_filters_by_category_and_detail_status():
    db = _build_sqlite_session()
    try:
        jobsdb_batch = _create_crawl_job(db, source_site="jobsdb")
        ctgoodjobs_batch = _create_crawl_job(db, source_site="ctgoodjobs")
        repository = CrawlJobListingRepository()

        first, _ = repository.upsert_listing(
            db,
            crawl_job_id=jobsdb_batch.id,
            source_site="jobsdb",
            source_job_id="123456",
            source_url="https://hk.jobsdb.com/job/123456",
            source_classification_id="6281",
            source_classification_name="ICT",
            listing_page=1,
            listing_rank=1,
            listing_payload={"title": "Pending"},
        )
        second, _ = repository.upsert_listing(
            db,
            crawl_job_id=ctgoodjobs_batch.id,
            source_site="ctgoodjobs",
            source_job_id="10090657",
            source_url="https://jobs.ctgoodjobs.hk/job/10090657",
            source_classification_id="ctgoodjobs:021",
            source_classification_name="Information Technology",
            listing_page=1,
            listing_rank=1,
            listing_payload={"title": "Failed"},
        )
        detail_crawl_job = _create_crawl_job(db, source_site="ctgoodjobs")
        repository.mark_detail_failed(
            db,
            listing_id=second.id,
            detail_crawl_job_id=detail_crawl_job.id,
            error_message="blocked",
        )

        jobsdb_pending = repository.list_listing_batches(
            db,
            source_site="jobsdb",
            category_id="6281",
            detail_status="pending",
        )
        ctgoodjobs_failed = repository.list_listing_batches(
            db,
            source_site="ctgoodjobs",
            category_id="ctgoodjobs:021",
            detail_status="failed",
        )

        assert [batch["crawl_job_id"] for batch in jobsdb_pending] == [str(jobsdb_batch.id)]
        assert jobsdb_pending[0]["detail_pending"] == 1
        assert [batch["crawl_job_id"] for batch in ctgoodjobs_failed] == [str(ctgoodjobs_batch.id)]
        assert ctgoodjobs_failed[0]["detail_failed"] == 1
    finally:
        db.close()
```

- [x] **Step 2: Run failing repository test**

Run:

```bash
python -m pytest backend/tests/test_crawl_job_listing_repository.py::test_list_listing_batches_filters_by_category_and_detail_status -q
```

Expected: FAIL because `list_listing_batches()` does not accept `category_id` or `detail_status`.

- [x] **Step 3: Add grouped query implementation**

Update `CrawlJobListingRepository.list_listing_batches()` signature:

```python
    def list_listing_batches(
        self,
        db: Session,
        *,
        source_site: str | None = None,
        category_id: str | None = None,
        detail_status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
```

Replace the recent crawl job loop with a grouped listing query:

```python
        query = db.query(CrawlJobListing.crawl_job_id).filter(CrawlJobListing.crawl_job_id.isnot(None))
        if source_site:
            query = query.filter(CrawlJobListing.source_site == str(source_site).strip().lower())
        if category_id:
            query = query.filter(CrawlJobListing.source_classification_id == str(category_id))
        if detail_status:
            query = query.filter(CrawlJobListing.detail_status == str(detail_status))

        crawl_job_ids = [
            row[0]
            for row in (
                query.group_by(CrawlJobListing.crawl_job_id)
                .order_by(func.max(CrawlJobListing.created_at).desc())
                .limit(int(limit or 20))
                .all()
            )
        ]
        if not crawl_job_ids:
            return []

        crawl_jobs = {
            row.id: row
            for row in db.query(CrawlJob).filter(CrawlJob.id.in_(crawl_job_ids)).all()
        }
        batches: list[dict[str, Any]] = []
        for crawl_job_id in crawl_job_ids:
            crawl_job = crawl_jobs.get(crawl_job_id)
            if crawl_job is None:
                continue
            status_query = db.query(CrawlJobListing.detail_status, func.count(CrawlJobListing.id)).filter(
                CrawlJobListing.crawl_job_id == crawl_job_id
            )
            if category_id:
                status_query = status_query.filter(CrawlJobListing.source_classification_id == str(category_id))
            status_counts = {
                str(status): int(count)
                for status, count in status_query.group_by(CrawlJobListing.detail_status).all()
            }
            listings_staged = sum(status_counts.values())
            request_payload = crawl_job.request_payload if isinstance(crawl_job.request_payload, dict) else {}
            batches.append(
                {
                    "crawl_job_id": str(crawl_job.id),
                    "source_site": crawl_job.source_site,
                    "status": crawl_job.status,
                    "category_ids": list(request_payload.get("category_ids") or []),
                    "queued_at": crawl_job.queued_at.isoformat() if crawl_job.queued_at else None,
                    "completed_at": crawl_job.completed_at.isoformat() if crawl_job.completed_at else None,
                    "listings_staged": listings_staged,
                    "detail_pending": status_counts.get("pending", 0),
                    "detail_running": status_counts.get("running", 0),
                    "detail_completed": status_counts.get("completed", 0),
                    "detail_failed": status_counts.get("failed", 0),
                    "detail_manual_action_required": status_counts.get("manual_action_required", 0),
                }
            )
        return batches
```

- [x] **Step 4: Expose filters in API**

Modify `backend/app/api/crawl_jobs.py` `list_listing_batches()` parameters:

```python
    category_id: str | None = None,
    detail_status: str | None = None,
```

Pass them into the repository:

```python
            category_id=category_id,
            detail_status=detail_status,
```

- [x] **Step 5: Run repository and API tests**

Run:

```bash
python -m pytest backend/tests/test_crawl_job_listing_repository.py backend/tests/test_crawl_jobs_api.py -q
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add backend/app/repositories/crawl_job_listing_repository.py backend/app/api/crawl_jobs.py backend/tests/test_crawl_job_listing_repository.py backend/tests/test_crawl_jobs_api.py
git commit -m "feat: query listing backlog by status and category"
```

---

### Task 5: Frontend API Client and Capability Gating

**Files:**
- Create: `frontend/src/api/client.js`
- Create: `frontend/src/api/capabilities.js`
- Modify: `frontend/src/components/JobBrowser.jsx`
- Modify: `frontend/src/components/JobDetailModal.jsx`
- Modify: `frontend/src/components/scraper/ScheduleManager.jsx`
- Test: `frontend/src/api/client.test.js`
- Test: `frontend/src/components/JobBrowser.test.jsx`
- Test: `frontend/src/components/JobDetailModal.test.jsx`
- Test: `frontend/src/components/scraper/ScheduleManager.test.jsx`

- [x] **Step 1: Add API client tests**

Create `frontend/src/api/client.test.js`:

```javascript
import { describe, expect, it, vi } from 'vitest';

import { apiFetchJson, formatApiErrorDetail } from './client';

describe('api client', () => {
  it('extracts backend detail messages from failed JSON responses', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: false,
        status: 503,
        json: async () => ({ detail: { message: 'retrieval-api unavailable' } }),
      }),
    );

    await expect(apiFetchJson('/api/v1/capabilities')).rejects.toThrow('retrieval-api unavailable');
  });

  it('formats array details into readable messages', () => {
    expect(formatApiErrorDetail([{ msg: 'field required' }, { message: 'bad source' }])).toBe(
      'field required; bad source',
    );
  });
});
```

- [x] **Step 2: Run failing frontend API client test**

Run:

```bash
npm --prefix frontend test -- --run src/api/client.test.js
```

Expected: FAIL with missing module.

- [x] **Step 3: Add shared API client**

Create `frontend/src/api/client.js`:

```javascript
export function formatApiErrorDetail(detail) {
  if (!detail) {
    return null;
  }
  if (typeof detail === 'string') {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => item?.message || item?.msg || String(item))
      .filter(Boolean)
      .join('; ');
  }
  if (typeof detail === 'object') {
    return detail.message || detail.error || detail.reason || JSON.stringify(detail);
  }
  return String(detail);
}

export async function apiFetchJson(url, options = {}) {
  const { timeoutMs = 15000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      ...fetchOptions,
      signal: fetchOptions.signal || controller.signal,
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(formatApiErrorDetail(data?.detail) || `Request failed with status ${response.status}`);
    }
    return data;
  } finally {
    clearTimeout(timeout);
  }
}
```

Create `frontend/src/api/capabilities.js`:

```javascript
import { API_BASE_URL } from './base';
import { apiFetchJson } from './client';

export function fetchCapabilities() {
  return apiFetchJson(`${API_BASE_URL}/api/v1/capabilities`, { timeoutMs: 8000 });
}
```

- [x] **Step 4: Gate JobBrowser retrieval modes**

In `frontend/src/components/JobBrowser.jsx`, import `fetchCapabilities`.

Add state:

```javascript
const [capabilities, setCapabilities] = useState(null);
```

Add an effect near other initial fetch effects:

```javascript
useEffect(() => {
  let cancelled = false;
  fetchCapabilities()
    .then((payload) => {
      if (!cancelled) {
        setCapabilities(payload);
      }
    })
    .catch(() => {
      if (!cancelled) {
        setCapabilities(null);
      }
    });
  return () => {
    cancelled = true;
  };
}, []);
```

Compute mode availability before render:

```javascript
const semanticAvailable = capabilities?.search?.semantic?.available !== false;
const hybridAvailable = capabilities?.search?.hybrid?.available !== false;
```

In the retrieval mode `<select>`, disable semantic/hybrid options:

```jsx
<option value="semantic" disabled={!semanticAvailable}>
  Semantic
</option>
<option value="hybrid" disabled={!hybridAvailable}>
  Hybrid
</option>
```

If the selected retrieval mode becomes unavailable, reset to lexical:

```javascript
useEffect(() => {
  if ((retrievalMode === 'semantic' && !semanticAvailable) || (retrievalMode === 'hybrid' && !hybridAvailable)) {
    setRetrievalMode('lexical');
  }
}, [hybridAvailable, retrievalMode, semanticAvailable]);
```

- [x] **Step 5: Gate related jobs in JobDetailModal**

In `frontend/src/components/JobDetailModal.jsx`, add an optional prop:

```javascript
function JobDetailModal({ job, onClose, capabilities = null }) {
```

Before fetching recommendations, check:

```javascript
const recommendationsAvailable = capabilities?.recommendations?.similar_jobs?.available !== false;
```

Only call recommendations endpoint when available. When unavailable, render a quiet status:

```jsx
{!recommendationsAvailable && (
  <p className="related-jobs-status">Related jobs are unavailable in the current runtime profile.</p>
)}
```

- [x] **Step 6: Pass capabilities from JobBrowser to JobDetailModal**

Where `JobDetailModal` is rendered in `JobBrowser.jsx`, pass:

```jsx
capabilities={capabilities}
```

- [x] **Step 7: Surface scheduler capabilities in ScheduleManager**

In `frontend/src/components/scraper/ScheduleManager.jsx`, import `fetchCapabilities` and add state:

```javascript
const [capabilities, setCapabilities] = useState(null);
```

Fetch capabilities on mount. In the existing operator health banner area, render a scheduler warning when:

```javascript
capabilities?.scheduler?.available === false
```

Use copy:

```jsx
Scheduler dispatch is unavailable in the current runtime profile.
```

- [x] **Step 8: Add frontend tests for gated modes**

In `frontend/src/components/JobBrowser.test.jsx`, update `beforeEach` fetch mock to handle `/api/v1/capabilities`:

```javascript
if (url.pathname === '/api/v1/capabilities') {
  return Promise.resolve({
    ok: true,
    json: async () => ({
      search: {
        lexical: { available: true },
        semantic: { available: false, reason: 'retrieval_api_url_not_configured' },
        hybrid: { available: false, reason: 'retrieval_api_url_not_configured' },
      },
      recommendations: { similar_jobs: { available: false } },
    }),
  });
}
```

Add test:

```javascript
it('disables semantic and hybrid retrieval modes when capabilities report retrieval unavailable', async () => {
  render(<JobBrowser />);

  const select = await screen.findByLabelText(/retrieval mode/i);
  expect(within(select).getByRole('option', { name: /semantic/i })).toBeDisabled();
  expect(within(select).getByRole('option', { name: /hybrid/i })).toBeDisabled();
});
```

- [x] **Step 9: Run focused frontend tests**

Run:

```bash
npm --prefix frontend test -- --run src/api/client.test.js src/components/JobBrowser.test.jsx src/components/JobDetailModal.test.jsx src/components/scraper/ScheduleManager.test.jsx
```

Expected: PASS.

- [x] **Step 10: Commit**

```bash
git add frontend/src/api/client.js frontend/src/api/capabilities.js frontend/src/api/client.test.js frontend/src/components/JobBrowser.jsx frontend/src/components/JobBrowser.test.jsx frontend/src/components/JobDetailModal.jsx frontend/src/components/JobDetailModal.test.jsx frontend/src/components/scraper/ScheduleManager.jsx frontend/src/components/scraper/ScheduleManager.test.jsx
git commit -m "feat: gate frontend controls by runtime capabilities"
```

---

### Task 6: Audit Documentation Validation Script

**Files:**
- Create: `backend/scripts/validate_audit_docs.py`
- Test: `backend/tests/test_validate_audit_docs.py`

- [x] **Step 1: Add failing validation tests**

Create `backend/tests/test_validate_audit_docs.py`:

```python
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.validate_audit_docs import validate_audit_docs


def test_validate_audit_docs_accepts_current_tree():
    errors = validate_audit_docs(Path("docs/audit"))

    assert errors == []


def test_validate_audit_docs_reports_missing_required_section(tmp_path):
    audit_root = tmp_path / "audit"
    leaf_dir = audit_root / "01-business-domains"
    leaf_dir.mkdir(parents=True)
    (audit_root / "README.md").write_text(
        "# Audit Map\n\n## Directions\n- [Broken](01-business-domains/broken.md)\n",
        encoding="utf-8",
    )
    (leaf_dir / "broken.md").write_text(
        "# Broken\n\n## Current Responsibilities\nText\n",
        encoding="utf-8",
    )

    errors = validate_audit_docs(audit_root)

    assert any("missing required section: Optimization Backlog" in error for error in errors)
```

- [x] **Step 2: Run failing validation tests**

Run:

```bash
python -m pytest backend/tests/test_validate_audit_docs.py -q
```

Expected: FAIL with missing script module.

- [x] **Step 3: Add validation script**

Create `backend/scripts/validate_audit_docs.py`:

```python
from __future__ import annotations

import re
from pathlib import Path

REQUIRED_SECTIONS = (
    "Current Responsibilities",
    "Current Implementation Map",
    "Data and Control Flow",
    "Tests and Coverage",
    "Known Gaps or Risks",
    "Optimization Backlog",
    "Follow-up Audit Questions",
)
PLACEHOLDER_PATTERN = re.compile(r"\b(TBD|TODO|FIXME|placeholder)\b", re.IGNORECASE)
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
BACKTICK_PATH_PATTERN = re.compile(r"`((?:backend|frontend|database|docs|scripts)/[^`]+)`")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_leaf(path: Path) -> bool:
    return path.name != "README.md"


def _headings(text: str) -> set[str]:
    return {
        line.lstrip("#").strip()
        for line in text.splitlines()
        if line.startswith("## ")
    }


def _local_doc_links(text: str) -> list[str]:
    return [
        target
        for target in MARKDOWN_LINK_PATTERN.findall(text)
        if not target.startswith(("http://", "https://", "#"))
    ]


def validate_audit_docs(audit_root: Path) -> list[str]:
    errors: list[str] = []
    repo_root = _repo_root()
    audit_root = audit_root.resolve()
    readme = audit_root / "README.md"
    if not readme.exists():
        return [f"{readme}: missing README.md"]

    readme_text = readme.read_text(encoding="utf-8")
    for link in _local_doc_links(readme_text):
        target = (audit_root / link).resolve()
        if not target.exists():
            errors.append(f"{readme}: broken README link: {link}")

    for path in sorted(audit_root.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        if PLACEHOLDER_PATTERN.search(text):
            errors.append(f"{path}: placeholder text found")
        if _is_leaf(path):
            headings = _headings(text)
            for section in REQUIRED_SECTIONS:
                if section not in headings:
                    errors.append(f"{path}: missing required section: {section}")
        for raw_path in BACKTICK_PATH_PATTERN.findall(text):
            cleaned = raw_path.rstrip(".,:;")
            if "*" in cleaned:
                continue
            if not (repo_root / cleaned).exists():
                errors.append(f"{path}: referenced path does not exist: {cleaned}")
    return errors


def main() -> int:
    errors = validate_audit_docs(_repo_root() / "docs" / "audit")
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 4: Run validation tests and script**

Run:

```bash
python -m pytest backend/tests/test_validate_audit_docs.py -q
python backend/scripts/validate_audit_docs.py
```

Expected: both PASS / exit 0. If the script reports stale audit references, fix the audit docs only when the reference is clearly stale; do not broaden the script to hide real drift.

- [x] **Step 5: Commit**

```bash
git add backend/scripts/validate_audit_docs.py backend/tests/test_validate_audit_docs.py docs/audit
git commit -m "test: validate audit documentation map"
```

---

## Final Verification

Run these commands after all tasks:

```bash
python -m pytest backend/tests/test_capabilities_api.py backend/tests/test_health_api.py backend/tests/test_crawl_request_validation.py backend/tests/test_crawl_job_listing_repository.py backend/tests/test_crawl_jobs_api.py backend/tests/test_scheduler_dispatcher.py backend/tests/test_validate_audit_docs.py -q
npm --prefix frontend test -- --run src/api/client.test.js src/components/JobBrowser.test.jsx src/components/JobDetailModal.test.jsx src/components/scraper/ScheduleManager.test.jsx
npm --prefix frontend run build
```

Expected:
- Backend tests pass.
- Frontend focused tests pass.
- Vite build passes.

## Plan Self-Review

- Spec coverage: covers Batch 1 capability contract, health metrics, shared validation, listing backlog filters, frontend capability states, and audit validation.
- Placeholder scan: no `TBD`, `TODO`, `FIXME`, or incomplete implementation instructions are intentionally present.
- Type consistency: `build_runtime_capabilities`, `validate_crawl_request`, `apiFetchJson`, and `validate_audit_docs` names are consistent across tasks and tests.

