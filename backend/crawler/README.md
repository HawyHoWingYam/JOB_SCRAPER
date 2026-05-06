# `backend/crawler`

This directory is reserved for the eventized crawler worker implementation.

Planned worker responsibilities:

- Run Scrapy-based jobs for JobsDB crawling.
- Use `scrapy-playwright` when a browser-backed fetch is required.
- Keep crawler-specific code isolated from the FastAPI application entrypoints.

The worker container is built from `backend/Dockerfile.worker` and shares the
backend Python dependencies needed for Scrapy, Playwright, and downstream
pipeline integration.
