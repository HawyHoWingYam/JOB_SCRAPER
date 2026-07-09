# JobsDB Hong Kong Scraper

A production-grade job scraping application with AI enrichment.

## Features

- **Job Scraping**: REST API scraper for JobsDB Hong Kong
- **Category-Based Scraping**: Scrape all 24 job categories
- **Scheduled Scraping**: Cron-based automation
- **AI Enrichment**: LLM-powered job classification and skill extraction
- **Dashboard**: Charts and statistics with Recharts

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 19, Vite, Recharts |
| Backend | Python 3.11, FastAPI |
| Database | PostgreSQL 15 |
| Queue | Redis 7 |
| AI | Google Gemini, Zhipu |

## Quick Start

```bash
# Start all services
docker-compose up -d

# Rebuild the backend image after Python dependency changes.
docker compose up -d --build backend-api

# Start default worker-profile services (headless crawling + ingest + enrichment + retrieval/recommendations).
docker compose --profile workers up -d crawl-worker ingest-worker enrichment-worker retrieval-api embedding-worker recommendation-api

# Start ML-backed services when you need semantic/hybrid search,
# non-lexical export, embedding generation, or related-job recommendations.
docker compose --profile workers up -d retrieval-api embedding-worker recommendation-api

# Access
# Frontend (Docker): http://localhost:3000
# Frontend (host `cd frontend && npm run dev`): http://localhost:5173
# Backend: http://localhost:8000
# API Docs: http://localhost:8000/docs
```

The default `backend-api` image only supports the lexical search baseline. Semantic and hybrid retrieval, plus non-lexical export, run behind the internal `retrieval-api` service. Embedding generation runs in `embedding-worker`, and related-job recommendations run behind `recommendation-api`.

## Runtime Notes

- Docker API containers now default to stable non-reload startup. This avoids `watchfiles` crashes on bind-mounted `/app` volumes while keeping the app behavior unchanged.
- To opt into live reload for any API container, set `UVICORN_RELOAD=true`. If Docker-mounted file watching is still unstable, also set `UVICORN_RELOAD_FORCE_POLLING=true`.
- If `UVICORN_RELOAD` is unset, direct `python -m app.main`, `python -m app.retrieval_main`, and `python -m app.recommendation_main` runs still fall back to `DEBUG`.
- Crawl jobs now support explicit `crawl_mode` values: `headless` and `headed`.
- Recommended operational defaults are source-aware:
  - `JobsDB` defaults to `headed`
  - `CTGoodJobs` defaults to `headless`
- `CTGoodJobs` headless runs can be paired with the explicit `CTGOODJOBS_PROXY_*` settings in `.env` for per-request proxy rotation; global `HTTP_PROXY` / `HTTPS_PROXY` variables are not part of that runtime path.
- `POST /api/v1/jobs/search` supports `lexical`, `semantic`, and `hybrid`, but the non-lexical modes require `retrieval-api`.
- `POST /api/v1/jobs/search/export` mirrors the active retrieval mode. `semantic` and `hybrid` export require `retrieval-api`.
- `GET /api/v1/jobs/{job_id}/similar` and `GET /api/v1/recommendations/jobs` proxy to `recommendation-api`.
- Scrape progress is sourced from durable `crawl_jobs` and `crawl_job_events`; the legacy in-process category scrape endpoints are no longer part of the runtime path.

## Crawl Tasks

- Use the Sidebar `Crawl Tasks` page for running, failed, completed, cancelled, and manual-action crawl jobs.
- The `Scraping Progress` panel is now a live-status surface for stream health and quick recovery hints, not the durable task history.

## Headed Crawl Worker

`JobsDB` full detail capture is currently expected to run through the local host-side headed worker because direct HTTP and containerized headless browser fetches can be blocked by Cloudflare.

Typical local setup:

```bash
# Keep the normal Docker control plane and headless workers running.
docker compose up -d postgres-db redis-mq backend-api frontend-ui
docker compose --profile workers up -d crawl-worker ingest-worker enrichment-worker

# Then run the headed crawl worker on the Windows host.
python backend\scripts\prepare_headed_crawl_worker_host.py

# Or launch it in a dedicated visible cmd window.
python backend\scripts\prepare_headed_crawl_worker_host.py
```

Recommended profile setup:

- use a dedicated browser profile directory via `JOBSDB_HEADED_BROWSER_USER_DATA_DIR`
- container-owned headed automation now defaults to Playwright `chromium`
- host-side manual/browser-helper flows can still target `JOBSDB_HEADED_BROWSER_CHANNEL=msedge` or `chrome`
- open a JobsDB or CTGoodJobs page once in that automation profile and complete any anti-bot challenge before relying on automated headed runs
- keep the script running while you want headed JobsDB jobs to keep progressing
- if you want a separate persistent window without blocking your current shell, run `prepare_headed_crawl_worker_host.py` in a new terminal
- only run one headed worker at a time; the host worker now holds a localhost lock port (default `47651`) and exits early if another instance is already running

Behavior notes:

- `headed` crawl jobs are published onto a separate Redis stream and consumed by the host-side headed worker
- `headless` crawl jobs continue to be consumed by the Docker `crawl-worker`
- `CTGoodJobs` can still run in either mode from the control plane, but the current default is `headless`; the headed worker remains useful for debug, manual verification, and fallback investigation when anti-bot interstitials persist

## JobsDB Detail Repair

To repair previously ingested short `JobsDB` descriptions after the headed worker path is available:

```bash
python backend/scripts/backfill_jobsdb_details.py
```

This script targets degraded `JobsDB` rows and rewrites detail-related fields only when richer detail payloads are recovered.

## Worker-Profile QA

Bring up the ML/runtime profile before validating semantic search, non-lexical export, or related jobs:

```bash
docker compose --profile workers up -d retrieval-api embedding-worker recommendation-api
```

Recommended manual checks:

- search in `semantic` mode and confirm results return successfully
- search in `hybrid` mode and export the same scope
- open a job detail modal and confirm related jobs load
- trigger a direct override crawl and confirm `/api/v1/scrape/progress` reports the queued/running job

## Backend QA

Use these commands when validating backend-only changes or before moving on to deeper runtime work.

### Host path

Install backend development dependencies into your local Python environment first:

```bash
python -m pip install -r backend/requirements-dev.txt
```

Then, from the repo root, run:

```bash
python -m pytest --collect-only -q backend/tests
python -m pytest -q backend/tests
```

### Docker path

Use Docker when you want verification closest to the shared containerized runtime:

```bash
docker compose run --rm backend-api python -m pytest --collect-only -q tests
docker compose run --rm backend-api python -m pytest -q tests
```

## Backend Migrations

```bash
alembic -c backend/alembic.ini history
```

Alembic reads `DATABASE_URL` from the project `.env`. The local development default points at the PostgreSQL container on `localhost:5433`.

This repository does not have a full Alembic baseline yet. The current first revision only tracks the enrichment-run tables added in Task 2.

`docker compose up` now runs a one-shot `db-bootstrap` service that ensures the `vector` extension exists and creates the current ORM tables before the API and worker services start. If your `pg_data` volume predates this change and the stack is already unhealthy, run:

```bash
docker compose up db-bootstrap
```

For a fresh local database, use db-bootstrap via Docker:

```bash
docker compose run --rm db-bootstrap
alembic -c backend/alembic.ini stamp 20260415_103800
```

For an existing database that was created before Alembic, use the existing schema bootstrap/convergence path first so the current tables exist, then register the current revision:

```bash
alembic -c backend/alembic.ini stamp 20260415_103800
```

Use `cd backend && alembic upgrade head` only for databases that already have the pre-Alembic base schema but do not yet have the new `enrichment_runs` tables.

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/jobs/search` | Search jobs |
| `POST /api/v1/jobs/search/export` | Export search results |
| `GET /api/v1/jobs/{job_id}/similar` | Related job recommendations |
| `POST /api/v1/ai/enrich` | AI enrichment |
| `GET /api/v1/stats/skills` | Skill statistics |
| `GET /api/v1/stats/categories` | Category distribution |

## License

MIT
