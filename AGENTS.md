# JobsDB Scraper — Project Memory

> Production-grade job scraping application with AI enrichment for JobsDB Hong Kong and CTGoodJobs.
> **Last Updated**: 2026-02-04

---

## Project

| Aspect | Details |
|--------|---------|
| **Backend** | Python 3.11, FastAPI 0.135, SQLAlchemy 2.0, PostgreSQL 15, Redis 7 |
| **Frontend** | React 19, Vite 5, Recharts, Lucide React |
| **Infra** | Docker Compose, Playwright (browser automation) |
| **AI** | Multi-provider LLM (Gemini, Anthropic, Zhipu, custom) |

**Entry points:**
- Backend API: `backend/app/main.py` → FastAPI app served via uvicorn
- Backend retrieval: `backend/app/retrieval_main.py`
- Backend recommendations: `backend/app/recommendation_main.py`
- Frontend: `frontend/src/main.jsx` → React root

---

## Commands

### Backend (Python)

```bash
# Run API server (host)
python -m app.main

# Run tests
python -m pytest -q backend/tests
python -m pytest --collect-only -q backend/tests

# Install deps
python -m pip install -r backend/requirements-dev.txt

# Run migrations
alembic -c backend/alembic.ini history
alembic -c backend/alembic.ini upgrade head

# Format & lint
black backend/
ruff check backend/
isort backend/
mypy backend/
```

### Backend (Docker)

```bash
# Run tests in container
docker compose run --rm backend-api python -m pytest -q tests

# Start all services
docker compose up -d

# Start with live-reload dev overrides
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Start worker profiles
docker compose --profile workers up -d crawl-worker ingest-worker enrichment-worker

# Start ML services (semantic search, embeddings, recommendations)
docker compose --profile workers up -d retrieval-api embedding-worker recommendation-api
```

### Frontend

```bash
cd frontend

npm run dev        # Vite dev server (hot reload)
npm run build      # Production build
npm test           # Vitest runner
npm run lint       # ESLint
npm run format     # Prettier formatting
```

---

## Architecture

### Services (Docker Compose)

| Service | Image / Role |
|---------|-------------|
| `postgres-db` | PostgreSQL 15 + pgvector |
| `redis-mq` | Redis 7 message queue (streams) |
| `db-bootstrap` | One-shot schema bootstrapper |
| `backend-api` | FastAPI app (port 8000) |
| `frontend-ui` | Vite dev server (port 5173) |
| `crawl-worker` | Consumes crawl jobs from Redis |
| `ingest-worker` | Processes raw scrape data into DB |
| `enrichment-worker` | LLM enrichment of job descriptions |
| `embedding-worker` | Generates vector embeddings |
| `retrieval-api` | Semantic/hybrid search service |
| `recommendation-api` | Related-job recommendation service |

### Backend Layout (`backend/app/`)

| Module | Role |
|--------|------|
| `api/` | FastAPI route handlers (jobs, companies, stats, schedules, progress, ai, settings, filters) |
| `models/` | SQLAlchemy ORM models (Job, Company, Schedule, Skill, etc.) |
| `schemas/` | Pydantic request/response schemas |
| `repositories/` | Data access layer (JobRepository, CrawlJobRepository, etc.) |
| `services/` | Business logic (AI enrichment, scheduling, crawl dispatch, retrieval, taxonomy) |
| `workers/` | Long-running worker processes (crawl, ingest, enrichment, embedding, scheduler) |
| `scraper/` | Web scraping engines (Playwright-based) |
| `sources/` | Source-specific adapters (jobsdb, ctgoodjobs) |
| `utils/` | Helpers (normalizers, taxonomy policy, source identity) |
| `config.py` | Pydantic-settings configuration (from `.env`) |
| `database.py` | SQLAlchemy engine + session factory |
| `main.py` | FastAPI app assembly + lifespan |

### Data Flow (Scrape → Enrich → Search)

```
User triggers crawl → Redis stream → crawl-worker (Playwright) → raw HTML
  → ingest-worker parses & stores to PostgreSQL
  → enrichment-worker calls LLM for classification + skill extraction
  → embedding-worker generates vector embeddings (optional ML path)
Search: lexical (PostgreSQL full-text) or semantic (retrieval-api via pgvector)
```

---

## Conventions

### Backend

| Rule | Standard |
|------|----------|
| **Formatting** | `black` (default config) + `isort` + `ruff` |
| **Imports** | Standard library → third-party → local (`app.*`) |
| **API routes** | FastAPI with `APIRouter`, prefix `/api/v1` |
| **DB access** | Repository pattern via `repositories/`; never raw SQL in routes |
| **Schemas** | Pydantic v2 `BaseModel` for request/response |
| **Tests** | `pytest` + `pytest-asyncio` in `backend/tests/` |
| **DB sessions** | FastAPI dependency `get_db()` yields `SessionLocal` |
| **Config** | `app.config.Settings` via `pydantic-settings`, values from `.env` |
| **Error handling** | `HTTPException` in routes, domain-specific exceptions in services |

### Frontend

| Rule | Standard |
|------|----------|
| **Components** | PascalCase, functional with Hooks |
| **CSS classes** | kebab-case, BEM-inspired (e.g. `glass-panel`, `search-input`) |
| **Event handlers** | `handle` prefix + camelCase (`handleSubmit`, `handleCrawl`) |
| **Styling** | Plain CSS (no preprocessor), CSS custom properties |
| **State** | `useState` / `useEffect` / custom hooks |
| **API calls** | `src/api/client.js` (custom fetch wrapper) |
| **Tests** | Vitest + jsdom + Testing Library in `frontend/src/` |
| **Lazy loading** | `React.lazy` + `Suspense` for page-level components |
| **Routing** | Hash-based (`window.location.hash`), no React Router |

### Project-wide

| Rule | Standard |
|------|----------|
| **Docker** | `docker compose` (v2); profiles for optional services |
| **Python path** | `backend/` is the source root; imports are `app.*` not `backend.*` |
| **Env vars** | Defined in `.env` file at project root; `pydantic-settings` loads it |
| **Crawl modes** | `headless` (Docker) and `headed` (host-side browser, Cloudflare bypass) |
| **LLM providers** | `gemini`, `anthropic`, `zhipu`, `custom`, `mock` — set via `LLM_PROVIDER` env |

---

## Design System

> Guide for integrating Figma designs using Model Context Protocol.

### Color Palette (Dark Theme)

```css
:root {
  --color-bg-primary: #101114;
  --color-bg-secondary: #17191d;
  --color-bg-tertiary: #20242a;
  --color-bg-elevated: #242932;
  --color-bg-glass: #17191d;
  --color-bg-glass-hover: #20242a;

  --color-text-primary: #f4f6f8;
  --color-text-secondary: #a7afbc;
  --color-text-muted: #7d8795;

  --color-primary: #6aa5ff;
  --color-primary-hover: #8ab8ff;
  --color-primary-glow: rgba(106, 165, 255, 0.22);
  --color-primary-light: rgba(106, 165, 255, 0.12);

  --color-accent: #d8a657;
  --color-accent-hover: #efc06a;
  --color-accent-glow: rgba(216, 166, 87, 0.18);

  --color-success: #4fbf8b;
  --color-success-hover: #70d5a5;
  --color-success-glow: rgba(79, 191, 139, 0.18);

  --color-error: #f16f6f;
  --color-error-hover: #ff8c8c;
  --color-error-glow: rgba(241, 111, 111, 0.18);

  --color-warning: #e9b949;
  --color-warning-bg: rgba(233, 185, 73, 0.1);

  --color-border: rgba(255, 255, 255, 0.1);
  --color-border-hover: rgba(255, 255, 255, 0.18);
  --color-border-strong: rgba(255, 255, 255, 0.24);
}
```

### Typography

```css
:root {
  --font-sans: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --font-display: var(--font-sans);

  --text-xs: 0.75rem;
  --text-sm: 0.875rem;
  --text-base: 1rem;
  --text-lg: 1.125rem;
  --text-xl: 1.25rem;
  --text-2xl: 1.5rem;
  --text-3xl: 1.875rem;
  --text-4xl: 2.25rem;
}
```

### Spacing

```css
:root {
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-5: 1.25rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
  --space-10: 2.5rem;
  --space-12: 3rem;

  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.35);
  --shadow-md: 0 12px 28px rgba(0, 0, 0, 0.28);
  --shadow-lg: 0 20px 45px rgba(0, 0, 0, 0.38);
  --shadow-glow: 0 0 0 1px rgba(106, 165, 255, 0.08);

  --radius-sm: 0.25rem;
  --radius-md: 0.5rem;
  --radius-lg: 0.5rem;
  --radius-xl: 0.5rem;
  --radius-full: 9999px;
}
```

### Component Library

```
frontend/src/components/
├── Dashboard.jsx              # Stats overview + charts
├── FilterPanel.jsx            # Advanced job filters
├── JobBrowser.jsx             # Main job listing view
├── JobDetailModal.jsx         # Job detail modal
├── Pagination.jsx             # Simple pagination
├── PaginationControl.jsx      # Pagination with controls
├── ResultsList.jsx            # List display component
├── SearchBar.jsx              # Search input
├── Sidebar.jsx                # Navigation sidebar
├── SkillTags.jsx              # Skill tag display
├── ai/
│   └── AIEnrichmentPage.jsx  # AI enrichment controls + progress
├── charts/
│   ├── CategoryChart.jsx     # Category distribution
│   └── SkillChart.jsx        # Skill statistics
├── companies/
│   ├── CompaniesPage.jsx     # Company list + search
│   ├── CompanyDetailModal.jsx
│   ├── CompanySummaryCard.jsx
│   └── useCompanyEnrichmentRun.js  # Custom hook
├── scraper/
│   ├── ScheduleManager.jsx   # Scheduler UI (root)
│   ├── ScheduleForm.jsx      # Create/edit schedules
│   ├── ScheduleList.jsx      # List schedules
│   ├── ScheduleHistory.jsx   # Schedule run history
│   ├── ScrapeProgressPanel.jsx  # Scrape job progress
│   ├── crawlMode.js          # Crawl mode constants
│   ├── crawlPhase.js         # Crawl phase constants
│   └── listingBatchLabel.js  # Batch label helpers
├── settings/
│   └── AISettingsPage.jsx    # LLM provider settings
├── jobBrowserQueryUtils.js   # Job search query helpers
├── jobBrowserScopeUtils.js   # Search scope helpers
├── locationFilterUtils.js    # Location filter helpers
└── api/
    ├── base.js               # API base URL config
    ├── capabilities.js       # Runtime capabilities
    ├── client.js             # Shared fetch wrapper
    └── client.test.js
```

### Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Components | PascalCase | `ScheduleManager`, `JobBrowser`, `FilterPanel` |
| CSS Classes | kebab-case | `glass-panel`, `search-input`, `premium-select` |
| Event Handlers | camelCase with `handle` prefix | `handleSubmit`, `handleCrawl`, `handleFilterChange` |
| State Variables | camelCase | `isLoading`, `results`, `activeView` |
| Custom hooks | camelCase with `use` prefix | `useCompanyEnrichmentRun` |

### Styling Approach

Plain CSS with CSS custom properties. Theme is `dark` by default (`color-scheme: dark` on `<html>`). No preprocessor, no CSS-in-JS. Component styles are co-located as `.css` files imported into the corresponding `.jsx` component (e.g., `Dashboard.css` imported by `Dashboard.jsx`). Shared utility classes (`glass-panel`, `filter-label`, `premium-select`) live in `index.css`.

### Button Styles

```css
/* Default button (defined in index.css) */
button {
  min-height: 40px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-4);
  background: var(--color-bg-tertiary);
  color: var(--color-text-primary);
  cursor: pointer;
  font-size: var(--text-sm);
  font-weight: 600;
}

button:hover {
  border-color: var(--color-border-hover);
  background: var(--color-bg-elevated);
}
```

### Form Elements

```css
.premium-select,
.premium-input,
.search-input {
  width: 100%;
  min-height: 42px;
  padding: 0 var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: #111317;
  color: var(--color-text-primary);
  font-size: var(--text-sm);
}
```

### Card Components

```css
.glass-panel {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-secondary);
  box-shadow: var(--shadow-sm);
}

.glass-panel:hover {
  border-color: var(--color-border-hover);
}
```

### Figma Integration Guidelines

1. **Extract tokens first**: Map Figma colors/spacing to CSS custom properties (see color/typography/spacing tables above).
2. **Use existing patterns**: Match to established component patterns (glass-panel, premium-select, etc.).
3. **Maintain consistency**: Follow naming conventions.

| Figma Token | CSS Variable |
|-------------|--------------|
| Primary/Blue | `--color-primary` |
| Error/Red | `--color-error` |
| Background/Dark | `--color-bg-primary` |
| Text/Primary | `--color-text-primary` |
| Border | `--color-border` |

---

## Notes

<!-- Quick-add section for ephemeral observations or references. -->
