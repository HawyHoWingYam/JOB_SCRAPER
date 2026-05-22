# Execution Unit: Frontend Console

## Current Responsibilities

The frontend console is the React/Vite interface for dashboard, job search/export, job details, company enrichment, AI enrichment, runtime settings, scheduling, crawl progress, manual crawl actions, and operator health.

## Current Implementation Map

- App shell: `frontend/src/App.jsx`, `frontend/src/components/Sidebar.jsx`
- API base: `frontend/src/api/base.js`
- Main views: `frontend/src/components/Dashboard.jsx`, `JobBrowser.jsx`, `companies/CompaniesPage.jsx`, `ai/AIEnrichmentPage.jsx`, `operator/OperatorHealthPage.jsx`, `settings/AISettingsPage.jsx`, `scraper/ScheduleManager.jsx`
- Operator API client: `frontend/src/api/operatorHealth.js`
- Crawl progress: `frontend/src/components/scraper/ScrapeProgressPanel.jsx`
- Styling: `frontend/src/App.css`, component CSS files under `frontend/src/components/**`
- Docker service: `frontend-ui`

## Data and Control Flow

The app uses internal React state for navigation rather than URL routing. `frontend/src/api/base.js` returns an empty API base in development, so `/api` calls use the Vite proxy and production calls use `VITE_API_URL` when configured.

Navigation stays inside the `activeView` app shell in `frontend/src/App.jsx`. The sidebar exposes an `operator` view, and `frontend/src/components/operator/OperatorHealthPage.jsx` fetches `GET /api/v1/operator/health` through `frontend/src/api/operatorHealth.js` to render a read-only triage page with scheduler, headed runtime, backlog, and issue summaries. `ScheduleManager` still calls root `/health` for its pipeline attention banner while crawl progress uses server-sent events through `ScrapeProgressPanel` and supports manual resume/cancel actions.

Several large views still call `fetch` directly and mix request state, transformation logic, polling/SSE behavior, and presentation. Job search supports lexical, semantic, and hybrid modes through the backend, but UI state is not yet capability-aware.

## Tests and Coverage

- `frontend/src/App.test.jsx`
- `frontend/src/components/Sidebar.test.jsx`
- `frontend/src/components/JobBrowser.test.jsx`
- `frontend/src/components/JobDetailModal.test.jsx`
- `frontend/src/components/companies/CompaniesPage.test.jsx`
- `frontend/src/components/ai/AIEnrichmentPage.test.jsx`
- `frontend/src/components/operator/OperatorHealthPage.test.jsx`
- `frontend/src/components/settings/AISettingsPage.test.jsx`
- `frontend/src/components/scraper/ScheduleManager.test.jsx`
- `frontend/src/components/scraper/ScheduleForm.test.jsx`
- `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`

## Known Gaps or Risks

- No React Router means refresh and deep-link behavior is limited for jobs, AI runs, companies, and schedules.
- The operator page is read-only and intentionally omits remediation controls, so operators must switch to other views or scripts to act.
- `ScheduleManager` still depends on root `/health`, which sits outside the Vite `/api` proxy convention.
- Large views mix API calls, state machines, polling/SSE, and presentation, increasing regression risk.
- Semantic/recommendation UI modes can be selected before backend sidecar capability is known.
- Request error handling and backend `detail` extraction are implemented ad hoc across views.

## Optimization Backlog

- Centralize API clients and shared response/error handling, including alignment between root `/health` and `/api/v1/operator/health`.
- Add capability-aware UI states for semantic search, recommendations, AI runtime readiness, scheduler state, and sidecar availability.
- Move to React Router for deep links to selected jobs, AI runs, company pages, schedules, and crawl progress.
- Split large views into hooks/services for data fetching and smaller presentational components.
- Add shared SSE/polling utilities with reconnect, cancellation, and stale-state handling.

## Follow-up Audit Questions

- Which console routes must be linkable for operators first: jobs, AI runs, crawl jobs, or schedules?
- Should `ScheduleManager` continue reading embedded operator status from `/health`, or should it consume the dedicated operator endpoint too?
- Should the UI hide unavailable capabilities or show disabled controls with backend status context?
