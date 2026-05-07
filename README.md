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

# Start ML-backed retrieval services when you need semantic/hybrid search
# or the embedding worker runtime.
docker compose --profile workers up -d retrieval-api embedding-worker

# Access
# Frontend: http://localhost:5173
# Backend: http://localhost:8000
# API Docs: http://localhost:8000/docs
```

The default `backend-api` image only supports the lexical search baseline. Semantic and hybrid retrieval run behind the internal `retrieval-api` service, and embedding generation runs in `embedding-worker`, both built with `backend/requirements-ml.txt`.

## Backend Migrations

```bash
alembic -c backend/alembic.ini history
```

Alembic reads `DATABASE_URL` from the project `.env`. The local development default points at the PostgreSQL container on `localhost:5433`.

This repository does not have a full Alembic baseline yet. The current first revision only tracks the enrichment-run tables added in Task 2.

For a fresh local database, bootstrap the existing application schema first:

```bash
python backend/scripts/init_db.py
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
| `POST /api/v1/ai/enrich` | AI enrichment |
| `GET /api/v1/stats/skills` | Skill statistics |
| `GET /api/v1/stats/categories` | Category distribution |

## License

MIT
