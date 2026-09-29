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

Job Browser text expressions search Job Description only. After deploying the
Description-only embedding contract to an existing sandbox, run the idempotent
schema/index upgrades and manually rebuild embeddings with the ML image:

```bash
docker compose run --rm --no-deps backend-api \
  python -m scripts.upgrade_job_embedding_contract
docker compose run --rm --no-deps backend-api \
  python -m scripts.upgrade_job_search_indexes
docker compose --profile workers build embedding-worker retrieval-api
docker compose --profile workers run --rm --no-deps embedding-worker \
  python -m scripts.rebuild_job_description_embeddings --batch-size 500
docker compose --profile workers up -d --no-deps --force-recreate \
  embedding-worker retrieval-api
```

The rebuild commits each keyset page independently and can be rerun safely;
current rows are skipped. Semantic and hybrid search ignore legacy embedding
documents until they have been rebuilt. Rollback does not require deleting Job
data: stop using the new retrieval code, and optionally drop only
`ix_jobs_description_trgm` and the `job_embeddings.document_contract` column
after restoring compatible code.

## Runtime Notes

- Job Intelligence governance is a trusted-local, single-operator feature with
  no login, Bearer token, or RBAC. Never expose its decision routes to an
  untrusted network; `local-operator` audit attribution and CORS are not
  authentication. See [Job Intelligence foundation](backend/docs/job-intelligence-foundation.md).
- Docker API containers now default to stable non-reload startup. This avoids `watchfiles` crashes on bind-mounted `/app` volumes while keeping the app behavior unchanged.
- To opt into live reload for any API container, set `UVICORN_RELOAD=true`. If Docker-mounted file watching is still unstable, also set `UVICORN_RELOAD_FORCE_POLLING=true`.
- If `UVICORN_RELOAD` is unset, direct `python -m app.main`, `python -m app.retrieval_main`, and `python -m app.recommendation_main` runs still fall back to `DEBUG`.
- Crawl jobs now support explicit `crawl_mode` values: `headless` and `headed`.
- Recommended operational defaults are source-aware:
  - `JobsDB` defaults to `headless`
  - `CTGoodJobs` defaults to `headless`
- `CTGoodJobs` headless runs can be paired with the explicit `CTGOODJOBS_PROXY_*` settings in `.env` for per-request proxy rotation; global `HTTP_PROXY` / `HTTPS_PROXY` variables are not part of that runtime path.
- `POST /api/jobs/search` supports `lexical`, `semantic`, and `hybrid`, but the non-lexical modes require `retrieval-api`.
- `POST /api/jobs/search/export` mirrors the active retrieval mode. `semantic` and `hybrid` export require `retrieval-api`.
- `GET /api/jobs/{job_id}/similar` and `GET /api/recommendations/jobs` proxy to `recommendation-api`.
- Scrape progress is sourced from durable `crawl_jobs` and `crawl_job_events`; the legacy in-process category scrape endpoints are no longer part of the runtime path.

## Crawl Tasks

- Use the Sidebar `Crawl Tasks` page for running, failed, completed, cancelled, and manual-action crawl jobs.
- The `Scraping Progress` panel is now a live-status surface for stream health and quick recovery hints, not the durable task history.
- Live smoke commands and artifact expectations for the scheduler-driven crawl matrix are documented in `docs/runbooks/live-frontend-source-crawl-smoke.md`.

### Live Smoke Matrix

| Source | Listing smoke | Detail smoke | Expected operator outcome |
|--------|---------------|--------------|---------------------------|
| JobsDB | Yes | Yes | Detail can pause in `manual_action_required` when the headed automation profile is already open |
| CTGoodJobs | Yes | Yes | Listing/detail can pause in `manual_action_required` for headed profile reuse recovery |
| OfferToday | Yes | Yes | Healthy auth can finish with `success`; stale auth or anti-bot pressure should classify into session/WAF/IP/manual buckets |

## Headed Crawl Worker

`JobsDB` full detail capture is currently expected to run through the local host-side headed worker because direct HTTP and containerized headless browser fetches can be blocked by Cloudflare.

Typical local setup:

```bash
# Keep the normal Docker control plane and headless workers running.
docker compose up -d postgres-db redis-mq backend-api frontend-ui
docker compose --profile workers up -d crawl-worker ingest-worker enrichment-worker

# Then prepare the host environment and run the headed crawl worker on the host.
python3 backend/scripts/prepare_headed_crawl_worker_host.py

# Or launch it in a dedicated visible cmd window on Windows.
py -3 backend\scripts\prepare_headed_crawl_worker_host.py
```

Recommended profile setup:

- use a dedicated browser profile directory via `JOBSDB_HEADED_BROWSER_USER_DATA_DIR`
- container-owned headed automation now defaults to Playwright `chromium`
- the host-side manual/browser helper supports `chromium`, `msedge`, and `chrome` on
  macOS, Linux, and Windows; for Playwright Chromium install the browser once with
  `python3 -m playwright install chromium` in the host helper environment
- when Docker provides the database, the host helper automatically maps
  `postgres-db:5432` to the published `127.0.0.1:5433`; set
  `MANUAL_ACTION_HELPER_DATABASE_URL` only when using a different database host
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
python3 backend/scripts/backfill_jobsdb_details.py
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
- trigger a direct override crawl and confirm `/api/scrape/progress` reports the queued/running job

## Backend QA

Use these commands when validating backend-only changes or before moving on to deeper runtime work.

### Host path

Install backend development dependencies into your local Python environment first:

```bash
python3 -m pip install -r backend/requirements-dev.txt
```

Then, from the repo root, run:

```bash
python3 -m pytest --collect-only -q backend/tests
python3 -m pytest -q backend/tests
```

### Docker path

Use Docker when you want verification closest to the shared containerized runtime:

```bash
docker compose run --rm backend-api python -m pytest --collect-only -q tests
docker compose run --rm backend-api python -m pytest -q tests
```

## Empty-schema bootstrap

This sandbox has no migration or schema-version system. `docker compose up`
runs the one-shot `db-bootstrap` service before the API. Bootstrap creates the
`vector` extension and every current ORM table only when the database contains
no tables.

If any table already exists, bootstrap refuses to mutate the database. Stop the
stack, clear the sandbox PostgreSQL schema/volume, deploy the complete current
code set, and then start the stack again. Mixed-code deployment and in-place
schema upgrades are unsupported.

```bash
docker compose down
docker volume rm job_scraper_pg_data  # destructive sandbox reset
docker compose up -d
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/jobs/search` | Search jobs |
| `POST /api/jobs/search/export` | Export search results |
| `GET /api/jobs/{job_id}/similar` | Related job recommendations |
| `POST /api/ai/enrich` | AI enrichment |
| `GET /api/stats/skills` | Skill statistics |

## License

MIT
