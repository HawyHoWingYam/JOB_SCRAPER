# Project Overview
- Name: gangweipachong / JobsDB Hong Kong Scraper.
- Purpose: production-grade JobsDB Hong Kong scraping application with AI enrichment, searchable job browser, dashboard charts, and scheduling.
- Stack: React 19 + Vite frontend, Python 3.11 + FastAPI backend, PostgreSQL 15, Redis 7, optional Java orchestrator service.
- Repo layout: `frontend/` for React UI, `backend/` for FastAPI app/tests/scraper logic, `orchestrator-service/` for Java service, `ref/` and `docs/plans/` for plans/reference material.
- Current relevant UI area: `frontend/src/components/JobBrowser.jsx`, `FilterPanel.jsx`, and `JobBrowser.css`.
- Current relevant backend area: `backend/app/api/jobs.py` and utilities under `backend/app/utils/`.
