# Batch 3 Operator Health Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated operator health page and one authoritative backend operator health contract that surfaces scheduler, queue, backlog, headed runtime, outbox, and dead-letter status in one place.

**Architecture:** Refactor the existing `/health` aggregation into a dedicated backend operator health service, expose that service through both root `/health` and a new `/api/v1/operator/health` route, then add a new frontend operator view inside the current `activeView` shell. Keep this batch read-only: the page explains what is broken and why, but does not add remediation actions yet.

**Tech Stack:** FastAPI, SQLAlchemy, Redis stream metadata, React 19, Vite, Vitest, Testing Library

---

### Task 1: Build the Backend Operator Health Read Model

**Files:**
- Create: `backend/app/services/operator_health_service.py`
- Modify: `backend/app/repositories/crawl_job_listing_repository.py`
- Test: `backend/tests/test_operator_health_api.py`

- [ ] **Step 1: Write the failing backend service tests**

```python
from datetime import datetime, timezone

from app.services.operator_health_service import build_operator_health_summary


def test_build_operator_health_summary_includes_dead_letters_manual_action_and_headed_runtime(monkeypatch):
    summary = build_operator_health_summary(
        redis_client=_FakeRedis(),
        session_factory=_fake_session_factory(
            detail_counts={"pending": 7, "failed": 2, "manual_action_required": 3},
            outbox_counts={"pending": 5, "failed": 1},
            embedding_counts={"total": 12, "current": 4},
        ),
        scheduler_status_getter=lambda: {
            "owner": "scheduler-worker",
            "worker_name": "scheduler-worker",
            "available": False,
            "manual_run_available": True,
            "heartbeat_status": "stale",
            "last_heartbeat_at": "2026-05-22T01:00:00+00:00",
            "last_reconcile_at": "2026-05-22T00:59:30+00:00",
            "active_schedule_count": 4,
            "registered_job_count": 4,
            "reason": "scheduler_worker_stale",
        },
        settings_obj=_FakeSettings(
            jobsdb_headed_browser_channel="msedge",
            jobsdb_headed_browser_user_data_dir="C:/profiles/msedge",
            jobsdb_headed_worker_lock_port=47651,
        ),
        now=lambda: datetime(2026, 5, 22, 1, 5, tzinfo=timezone.utc),
    )

    assert summary["status"] == "degraded"
    assert summary["scheduler"]["heartbeat_status"] == "stale"
    assert summary["backlogs"]["manual_action_detail_rows"] == 3
    assert summary["backlogs"]["dead_letter_count"] == 9
    assert summary["headed_runtime"]["browser_channel"] == "msedge"
    assert summary["generated_at"] == "2026-05-22T01:05:00+00:00"
```

- [ ] **Step 2: Run the new backend service test and verify it fails**

Run: `python -m pytest backend/tests/test_operator_health_api.py -q`
Expected: FAIL because `operator_health_service.py` and the new contract do not exist yet.

- [ ] **Step 3: Add a grouped backlog query helper for listing detail status counts**

```python
# backend/app/repositories/crawl_job_listing_repository.py
from sqlalchemy import func

class CrawlJobListingRepository:
    def summarize_detail_status_counts(
        self,
        db: Session,
        *,
        source_site: str | None = None,
    ) -> dict[str, int]:
        query = db.query(
            CrawlJobListing.detail_status,
            func.count(CrawlJobListing.id),
        )
        if source_site:
            query = query.filter(CrawlJobListing.source_site == str(source_site).strip().lower())

        rows = query.group_by(CrawlJobListing.detail_status).all()
        return {str(status): int(count) for status, count in rows}
```

- [ ] **Step 4: Implement the headed runtime summary helper and the operator health service**

```python
# backend/app/services/operator_health_service.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func

from app.database import SessionLocal
from app.messaging.redis_stream_bus import RedisStreamBus
from app.messaging.topics import (
    STREAM_CRAWL_COMMANDS_HEADED,
    STREAM_JOB_INGEST,
    STREAM_JOB_INGEST_DEAD_LETTER,
    STREAM_JOB_LIFECYCLE,
)
from app.models import CrawlJobListing, EnrichmentRun, EventOutbox, Job, JobEmbedding, JobSkillMention
from app.repositories.crawl_job_listing_repository import CrawlJobListingRepository
from app.services.scheduler_runtime import get_scheduler_runtime_status
from app.utils.time import utc_now


@dataclass(frozen=True)
class OperatorHealthDependencies:
    session_factory: Any = SessionLocal
    redis_client: Any | None = None
    scheduler_status_getter: Any = get_scheduler_runtime_status
    settings_obj: Any | None = None
    now: Any = utc_now


def build_operator_health_summary(**overrides) -> dict[str, Any]:
    deps = OperatorHealthDependencies(**overrides)
    redis_client = deps.redis_client or RedisStreamBus().redis
    settings_obj = deps.settings_obj
    now = deps.now()

    workers: dict[str, dict[str, Any]] = {}
    queues: dict[str, dict[str, Any]] = {}
    issues: list[str] = []

    for stream_name, group_name, worker_name in [
        (STREAM_JOB_INGEST, "ingest-workers", "ingest-worker"),
        (STREAM_JOB_LIFECYCLE, "enrichment-workers", "enrichment-worker"),
        (STREAM_JOB_LIFECYCLE, "embedding-workers", "embedding-worker"),
        (STREAM_CRAWL_COMMANDS_HEADED, "crawl-headed-workers", "crawl-headed-worker"),
    ]:
        queues[worker_name] = _read_stream_group_summary(redis_client, stream_name, group_name)
        workers[worker_name] = {
            "status": "degraded"
            if queues[worker_name]["lag"] or queues[worker_name]["pending"]
            else "healthy",
            "stream": stream_name,
            "group": group_name,
            **queues[worker_name],
        }
        if queues[worker_name]["lag"]:
            issues.append(f"{stream_name} group {group_name} lag is {queues[worker_name]['lag']}")
        if queues[worker_name]["pending"]:
            issues.append(f"{stream_name} group {group_name} has {queues[worker_name]['pending']} pending messages")

    db = deps.session_factory()
    try:
        listing_counts = CrawlJobListingRepository().summarize_detail_status_counts(db)
        outbox_counts = dict(
            db.query(EventOutbox.status, func.count(EventOutbox.id))
            .group_by(EventOutbox.status)
            .all()
        )
        total_jobs = db.query(Job).filter(Job.is_deleted == False).count()
        current_embeddings = db.query(JobEmbedding).join(Job, JobEmbedding.job_id == Job.id).filter(Job.is_deleted == False).count()
        total_embeddings = db.query(JobEmbedding).count()
        newest_job_updated_at = db.query(func.max(Job.updated_at)).scalar()
        newest_embedding_at = db.query(func.max(JobEmbedding.updated_at)).scalar()
        newest_skill_mention_at = db.query(func.max(JobSkillMention.created_at)).scalar()
        enrichment_counts = dict(
            db.query(EnrichmentRun.status, func.count(EnrichmentRun.id))
            .group_by(EnrichmentRun.status)
            .all()
        )
    finally:
        db.close()

    scheduler = deps.scheduler_status_getter()
    headed_runtime = build_headed_runtime_summary(settings_obj, workers.get("crawl-headed-worker"))
    dead_letter_length = int(redis_client.xlen(STREAM_JOB_INGEST_DEAD_LETTER))

    backlogs = {
        "pending_detail_rows": int(listing_counts.get("pending", 0)),
        "failed_detail_rows": int(listing_counts.get("failed", 0)),
        "manual_action_detail_rows": int(listing_counts.get("manual_action_required", 0)),
        "outbox_pending": int(outbox_counts.get("pending", 0)),
        "outbox_failed": int(outbox_counts.get("failed", 0)),
        "dead_letter_count": dead_letter_length,
        "missing_current_embeddings": max(total_jobs - current_embeddings, 0),
        "ai_backlog_jobs": int(enrichment_counts.get("queued", 0)),
    }

    if backlogs["dead_letter_count"] > 0:
        issues.append(f"dead-letter stream contains {backlogs['dead_letter_count']} messages")
    if backlogs["manual_action_detail_rows"] > 0:
        issues.append(f"manual action backlog contains {backlogs['manual_action_detail_rows']} detail rows")
    if backlogs["outbox_failed"] > 0:
        issues.append(f"event_outbox has {backlogs['outbox_failed']} failed rows")
    if backlogs["missing_current_embeddings"] > 0:
        issues.append(f"embeddings missing for {backlogs['missing_current_embeddings']} jobs")
    if headed_runtime["configured"] and not headed_runtime["browser_user_data_dir_exists"]:
        issues.append("headed runtime browser profile path is missing")

    if any("lag is" in issue or "pending messages" in issue for issue in issues):
        status = "critical"
    elif issues:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "generated_at": now.isoformat(),
        "issues": issues,
        "workers": workers,
        "queues": queues,
        "scheduler": scheduler,
        "headed_runtime": headed_runtime,
        "backlogs": backlogs,
        "freshness": {
            "jobs": {"total": total_jobs, "newest_updated_at": _isoformat_or_none(newest_job_updated_at)},
            "embeddings": {
                "total_embeddings": total_embeddings,
                "current_embeddings": current_embeddings,
                "newest_updated_at": _isoformat_or_none(newest_embedding_at),
            },
            "skills": {"newest_mention_at": _isoformat_or_none(newest_skill_mention_at)},
            "scheduler_last_reconcile_at": scheduler.get("last_reconcile_at"),
            "scheduler_last_heartbeat_at": scheduler.get("last_heartbeat_at"),
        },
    }
```

- [ ] **Step 5: Run the backend service tests and make them pass**

Run: `python -m pytest backend/tests/test_operator_health_api.py -q`
Expected: PASS

- [ ] **Step 6: Commit the backend operator health service layer**

```bash
git add backend/app/services/operator_health_service.py backend/app/repositories/crawl_job_listing_repository.py backend/tests/test_operator_health_api.py
git commit -m "feat: add operator health service summary"
```

### Task 2: Expose the Operator Health Contract Through FastAPI

**Files:**
- Create: `backend/app/api/operator.py`
- Modify: `backend/app/api/__init__.py`
- Modify: `backend/app/api/health.py`
- Test: `backend/tests/test_operator_health_api.py`
- Test: `backend/tests/test_health_api.py`

- [ ] **Step 1: Add failing route coverage for the dedicated operator API and root health passthrough**

```python
import httpx
from fastapi import FastAPI

from app.api import router as api_router
import app.api.health as health_module
import app.api.operator as operator_module


async def test_operator_health_route_returns_unified_contract(monkeypatch):
    payload = {
        "status": "degraded",
        "generated_at": "2026-05-22T02:00:00+00:00",
        "issues": ["manual action backlog contains 3 detail rows"],
        "scheduler": {"owner": "scheduler-worker", "heartbeat_status": "fresh"},
        "headed_runtime": {"configured": True, "browser_channel": "msedge"},
        "backlogs": {"manual_action_detail_rows": 3, "dead_letter_count": 2},
        "workers": {},
        "queues": {},
        "freshness": {},
    }
    monkeypatch.setattr(operator_module, "build_operator_health_summary", lambda: payload)

    app = FastAPI()
    app.include_router(api_router)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/operator/health")

    assert response.status_code == 200
    assert response.json() == payload


async def test_root_health_embeds_operator_summary_from_service(monkeypatch):
    monkeypatch.setattr(health_module, "refresh_llm_status", lambda *args: {"is_degraded": False, "degradation_reason": None})
    monkeypatch.setattr(
        health_module,
        "build_operator_health_summary",
        lambda: {
            "status": "degraded",
            "generated_at": "2026-05-22T02:00:00+00:00",
            "issues": ["dead-letter stream contains 2 messages"],
            "workers": {},
            "queues": {},
            "scheduler": {"heartbeat_status": "fresh"},
            "headed_runtime": {"configured": False},
            "backlogs": {"dead_letter_count": 2},
            "freshness": {},
        },
    )

    payload = await health_module.health_check()

    assert payload["status"] == "degraded"
    assert payload["operator"]["backlogs"]["dead_letter_count"] == 2
```

- [ ] **Step 2: Run the route-focused backend tests and confirm they fail**

Run: `python -m pytest backend/tests/test_operator_health_api.py backend/tests/test_health_api.py -q`
Expected: FAIL because `/api/v1/operator/health` does not exist and `/health` does not yet delegate to the new service.

- [ ] **Step 3: Implement the dedicated operator router**

```python
# backend/app/api/operator.py
from fastapi import APIRouter

from app.services.operator_health_service import build_operator_health_summary

router = APIRouter(prefix="/api/v1/operator", tags=["operator"])


@router.get("/health")
async def operator_health():
    return build_operator_health_summary()
```

- [ ] **Step 4: Refactor root health to delegate to the new service**

```python
# backend/app/api/health.py
from app.services.operator_health_service import build_operator_health_summary


@router.get("/health")
async def health_check():
    job_llm_status = refresh_llm_status()
    company_llm_status = refresh_llm_status("companies")
    operator_status = build_operator_health_summary()
    degraded_issues = []

    if job_llm_status["is_degraded"]:
        degraded_issues.append(f"Job LLM: {job_llm_status['degradation_reason']}")
    if company_llm_status["is_degraded"]:
        degraded_issues.append(f"Company LLM: {company_llm_status['degradation_reason']}")
    if operator_status["status"] != "healthy":
        degraded_issues.extend(operator_status["issues"])

    if degraded_issues:
        return {
            "status": "degraded",
            "service": "backend-api",
            "issues": degraded_issues,
            "operator": operator_status,
        }

    return {
        "status": "healthy",
        "service": "backend-api",
        "operator": operator_status,
    }
```

- [ ] **Step 5: Wire the new router into the API entrypoint**

```python
# backend/app/api/__init__.py
from app.api import (
    capabilities,
    companies,
    crawl_jobs,
    filters,
    health,
    jobs,
    operator,
    recommendations,
    settings,
)

router.include_router(operator.router)
```

- [ ] **Step 6: Run the backend route tests and make them pass**

Run: `python -m pytest backend/tests/test_operator_health_api.py backend/tests/test_health_api.py -q`
Expected: PASS

- [ ] **Step 7: Commit the backend route integration**

```bash
git add backend/app/api/operator.py backend/app/api/__init__.py backend/app/api/health.py backend/tests/test_operator_health_api.py backend/tests/test_health_api.py
git commit -m "feat: expose operator health API"
```

### Task 3: Add Frontend Navigation and Operator API Client

**Files:**
- Create: `frontend/src/api/operatorHealth.js`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/App.test.jsx`
- Modify: `frontend/src/components/Sidebar.jsx`
- Modify: `frontend/src/components/Sidebar.test.jsx`

- [ ] **Step 1: Write the failing frontend navigation tests**

```jsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import App from './App';
import Sidebar from './components/Sidebar';


describe('Operator navigation', () => {
  it('renders operator health in the sidebar navigation', async () => {
    const setActiveView = vi.fn();
    render(<Sidebar activeView="dashboard" setActiveView={setActiveView} />);

    await userEvent.click(screen.getByRole('button', { name: /operator health/i }));

    expect(setActiveView).toHaveBeenCalledWith('operator');
  });

  it('loads the operator health page when navigated from the sidebar', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);
      if (url === '/api/v1/operator/health') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'degraded',
            generated_at: '2026-05-22T02:00:00+00:00',
            issues: ['dead-letter stream contains 2 messages'],
            workers: {},
            queues: {},
            scheduler: { owner: 'scheduler-worker', heartbeat_status: 'fresh' },
            headed_runtime: { configured: false },
            backlogs: { dead_letter_count: 2 },
            freshness: {},
          }),
        });
      }
      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<App />);
    await userEvent.click(screen.getByRole('button', { name: /operator health/i }));

    expect(await screen.findByRole('heading', { name: /operator health/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the navigation-focused frontend tests and verify they fail**

Run: `npm --prefix frontend test -- --run src/App.test.jsx src/components/Sidebar.test.jsx`
Expected: FAIL because there is no `operator` view or operator navigation item yet.

- [ ] **Step 3: Add the operator health API helper**

```javascript
// frontend/src/api/operatorHealth.js
import { apiFetchJson } from './client';

export function fetchOperatorHealth(options = {}) {
  return apiFetchJson('/api/v1/operator/health', {
    timeoutMs: 15000,
    ...options,
  });
}
```

- [ ] **Step 4: Add the operator navigation item and app shell wiring**

```jsx
// frontend/src/components/Sidebar.jsx
import { LayoutDashboard, Briefcase, CalendarClock, Settings, Activity, BrainCircuit, Building2, ShieldAlert } from 'lucide-react';

const navItems = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'jobs', label: 'Job Browser', icon: Briefcase },
  { id: 'companies', label: 'Companies', icon: Building2 },
  { id: 'ai', label: 'AI Enrichment', icon: BrainCircuit },
  { id: 'scheduler', label: 'Scheduler', icon: CalendarClock },
  { id: 'operator', label: 'Operator Health', icon: ShieldAlert },
];
```

```jsx
// frontend/src/App.jsx
const OperatorHealthPage = lazy(() => import('./components/operator/OperatorHealthPage'));

{activeView === 'operator' && <OperatorHealthPage />}
```

- [ ] **Step 5: Run the navigation tests and make them pass**

Run: `npm --prefix frontend test -- --run src/App.test.jsx src/components/Sidebar.test.jsx`
Expected: PASS

- [ ] **Step 6: Commit the frontend navigation layer**

```bash
git add frontend/src/api/operatorHealth.js frontend/src/App.jsx frontend/src/App.test.jsx frontend/src/components/Sidebar.jsx frontend/src/components/Sidebar.test.jsx
git commit -m "feat: add operator health navigation shell"
```

### Task 4: Implement the Operator Health Page UI

**Files:**
- Create: `frontend/src/components/operator/OperatorHealthPage.jsx`
- Create: `frontend/src/components/operator/OperatorHealthPage.css`
- Test: `frontend/src/components/operator/OperatorHealthPage.test.jsx`

- [ ] **Step 1: Write the failing component tests for healthy/degraded rendering and manual refresh**

```jsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import OperatorHealthPage from './OperatorHealthPage';


describe('OperatorHealthPage', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: async () => ({
          status: 'degraded',
          generated_at: '2026-05-22T02:00:00+00:00',
          issues: ['manual action backlog contains 3 detail rows'],
          workers: {
            'ingest-worker': { status: 'healthy', lag: 0, pending: 0 },
            'scheduler-worker': { status: 'stale', lag: 0, pending: 0 },
          },
          queues: {
            'stream.job.ingest': { lag: 0, pending: 0, consumers: 1, length: 10 },
            'stream.job.ingest.dead_letter': { lag: 0, pending: 0, consumers: 0, length: 2 },
          },
          scheduler: { owner: 'scheduler-worker', heartbeat_status: 'stale', manual_run_available: true },
          headed_runtime: { configured: true, browser_channel: 'msedge', browser_user_data_dir_exists: false },
          backlogs: { pending_detail_rows: 7, manual_action_detail_rows: 3, dead_letter_count: 2, outbox_failed: 1 },
          freshness: { scheduler_last_heartbeat_at: '2026-05-22T01:58:00+00:00' },
        }),
      }),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders grouped runtime sections from the operator health payload', async () => {
    render(<OperatorHealthPage />);

    expect(await screen.findByRole('heading', { name: /operator health/i })).toBeInTheDocument();
    expect(screen.getByText(/manual action backlog contains 3 detail rows/i)).toBeInTheDocument();
    expect(screen.getByText(/scheduler-worker/i)).toBeInTheDocument();
    expect(screen.getByText(/dead-letter count/i)).toBeInTheDocument();
    expect(screen.getByText(/^2$/)).toBeInTheDocument();
    expect(screen.getByText(/msedge/i)).toBeInTheDocument();
  });

  it('re-fetches the payload when refresh is pressed', async () => {
    render(<OperatorHealthPage />);

    await screen.findByRole('heading', { name: /operator health/i });
    await userEvent.click(screen.getByRole('button', { name: /refresh/i }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    });
  });
});
```

- [ ] **Step 2: Run the new operator page tests and verify they fail**

Run: `npm --prefix frontend test -- --run src/components/operator/OperatorHealthPage.test.jsx`
Expected: FAIL because the page component and stylesheet do not exist yet.

- [ ] **Step 3: Implement the page component**

```jsx
// frontend/src/components/operator/OperatorHealthPage.jsx
import React, { useEffect, useState } from 'react';
import { AlertTriangle, RefreshCw, ShieldAlert } from 'lucide-react';
import { fetchOperatorHealth } from '../../api/operatorHealth';
import './OperatorHealthPage.css';

function formatTimestamp(value) {
  if (!value) return 'Unavailable';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? `${value}` : parsed.toLocaleString('en-US');
}

export default function OperatorHealthPage() {
  const [payload, setPayload] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadHealth = async () => {
    setIsLoading(true);
    setError(null);
    try {
      setPayload(await fetchOperatorHealth());
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadHealth();
  }, []);

  return (
    <section className="operator-health-page dashboard-container">
      <header className="dashboard-header operator-health-header">
        <div>
          <h2><ShieldAlert className="title-icon" /> Operator Health</h2>
          <p className="subtitle">Unified runtime posture for queues, workers, scheduler, and backlog.</p>
        </div>
        <button className="cyber-btn primary-glow" type="button" onClick={loadHealth} disabled={isLoading}>
          <RefreshCw size={18} /> {isLoading ? 'Refreshing...' : 'Refresh'}
        </button>
      </header>

      {error && (
        <div className="error-banner glass-panel">
          <AlertTriangle size={20} />
          <span>{error}</span>
        </div>
      )}

      {payload && (
        <>
          <section className="operator-status-overview glass-panel">
            <strong>Status: {payload.status}</strong>
            <span>Last updated: {formatTimestamp(payload.generated_at)}</span>
          </section>

          <section className="operator-section glass-panel">
            <h3>Issues</h3>
            {(payload.issues || []).length === 0 ? (
              <p>Unavailable issues: none. Runtime currently reports no operator issues.</p>
            ) : (
              <ul>
                {payload.issues.map((issue) => <li key={issue}>{issue}</li>)}
              </ul>
            )}
          </section>

          <section className="operator-grid">
            <article className="glass-panel operator-card">
              <h3>Scheduler</h3>
              <div>Owner: {payload.scheduler?.owner || 'Unavailable'}</div>
              <div>Heartbeat: {payload.scheduler?.heartbeat_status || 'Unavailable'}</div>
              <div>Manual runs: {payload.scheduler?.manual_run_available === false ? 'Disabled' : 'Available'}</div>
            </article>

            <article className="glass-panel operator-card">
              <h3>Headed Runtime</h3>
              <div>Configured: {payload.headed_runtime?.configured ? 'Yes' : 'No'}</div>
              <div>Browser Channel: {payload.headed_runtime?.browser_channel || 'Unavailable'}</div>
              <div>Profile Path Ready: {payload.headed_runtime?.browser_user_data_dir_exists ? 'Yes' : 'No'}</div>
            </article>
          </section>

          <section className="operator-section glass-panel">
            <h3>Backlogs</h3>
            <div className="operator-metric-grid">
              <div><span>Pending Detail Rows</span><strong>{payload.backlogs?.pending_detail_rows ?? 'Unavailable'}</strong></div>
              <div><span>Manual Action Rows</span><strong>{payload.backlogs?.manual_action_detail_rows ?? 'Unavailable'}</strong></div>
              <div><span>Dead-Letter Count</span><strong>{payload.backlogs?.dead_letter_count ?? 'Unavailable'}</strong></div>
              <div><span>Outbox Failed</span><strong>{payload.backlogs?.outbox_failed ?? 'Unavailable'}</strong></div>
            </div>
          </section>
        </>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Implement the page stylesheet**

```css
/* frontend/src/components/operator/OperatorHealthPage.css */
.operator-health-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.operator-health-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
}

.operator-status-overview {
  display: flex;
  justify-content: space-between;
  gap: var(--space-4);
  align-items: center;
  padding: var(--space-4);
}

.operator-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--space-4);
}

.operator-card,
.operator-section {
  padding: var(--space-5);
}

.operator-metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-3);
}

.operator-metric-grid div {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
```

- [ ] **Step 5: Run the operator page tests and make them pass**

Run: `npm --prefix frontend test -- --run src/components/operator/OperatorHealthPage.test.jsx`
Expected: PASS

- [ ] **Step 6: Commit the operator page UI**

```bash
git add frontend/src/components/operator/OperatorHealthPage.jsx frontend/src/components/operator/OperatorHealthPage.css frontend/src/components/operator/OperatorHealthPage.test.jsx
git commit -m "feat: add operator health page"
```

### Task 5: Sync Docs and Run End-to-End Verification

**Files:**
- Modify: `docs/audit/01-business-domains/operator-recovery.md`
- Modify: `docs/audit/03-execution-units/frontend-console.md`
- Modify: `docs/audit/05-operator-perspectives/monitoring-health.md`
- Modify: `docs/audit/03-execution-units/backend-api.md`

- [ ] **Step 1: Update the audit docs to reflect the new operator page and contract**

```md
## Current Implementation Map

- API: `backend/app/api/operator.py`, `backend/app/api/health.py`
- Service: `backend/app/services/operator_health_service.py`
- Frontend: `frontend/src/components/operator/OperatorHealthPage.jsx`

## Data and Control Flow

The operator page reads `/api/v1/operator/health`, which is built from queue posture, scheduler heartbeats,
listing backlog counts, outbox state, dead-letter stream length, and headed runtime configuration checks.
```

- [ ] **Step 2: Run the backend verification set**

Run: `python -m pytest backend/tests/test_operator_health_api.py backend/tests/test_health_api.py backend/tests/test_capabilities_api.py backend/tests/test_operator_health_report.py backend/tests/test_validate_audit_docs.py -q`
Expected: PASS

- [ ] **Step 3: Run the frontend verification set**

Run: `npm --prefix frontend test -- --run src/App.test.jsx src/components/Sidebar.test.jsx src/components/operator/OperatorHealthPage.test.jsx src/components/scraper/ScheduleManager.test.jsx`
Expected: PASS

- [ ] **Step 4: Run the frontend production build**

Run: `npm --prefix frontend run build`
Expected: Vite build completes with exit code 0.

- [ ] **Step 5: Commit the docs and final integration**

```bash
git add docs/audit/01-business-domains/operator-recovery.md docs/audit/03-execution-units/frontend-console.md docs/audit/05-operator-perspectives/monitoring-health.md docs/audit/03-execution-units/backend-api.md
git commit -m "docs: update operator health audit surfaces"
```
