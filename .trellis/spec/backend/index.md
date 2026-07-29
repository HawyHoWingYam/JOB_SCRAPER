# Backend Development Guidelines

> Best practices for backend development in this project.

---

## Overview

This directory contains guidelines for backend development. Fill in each file with your project's specific conventions.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | To fill |
| [Database Guidelines](./database-guidelines.md) | Empty-schema bootstrap, destructive sandbox safety, and PostgreSQL test isolation | Active |
| [Error Handling](./error-handling.md) | IP/manual-action recovery plus acknowledged manual crawl cancellation | Active |
| [Trellis GitHub Issue Lifecycle](./github-issue-task-lifecycle.md) | Trellis task hooks, GitHub issue binding, and explicit manual QA closure | Active |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | To fill |
| [Logging Guidelines](./logging-guidelines.md) | Cross-source crawl cadence, correlation, bounded fields, and secret-safe URLs | Active |
| [Crawl Task Detail Metrics](./crawl-task-detail-metrics.md) | Cross-source detail denominators, outcomes, remaining work, and UI projection | Active |
| [Manual Job Detail Pacing](./scraper-detail-pacing.md) | Source settings, immutable task snapshots, dispatch exclusion, and per-attempt pacing | Active |
| [AI Enrichment Run Operations](./ai-enrichment-runs.md) | Filter candidates, single-active scheduling, waiting promotion, monitor, retry, and cooperative Stop | Active |
| [Company Enrichment Runs](./company-enrichment-runs.md) | Krill Chat/Responses routing, explicit Company-only Web Search, capability probes, persistence, and safe diagnostics | Active |
| [CTGoodJobs Transport Research](./ctgoodjobs-transport-research.md) | Bounded HTTP/headless/headed comparison, sanitized evidence, viability replay, and WAF hard stops | Active |
| [OfferToday Production Crawl](./offertoday-production-crawl.md) | Cursor listing, partial caps, finite detail scope, normalized progress, and hard-stop contracts | Active |
| [OfferToday Research Artifacts](./offertoday-research-artifacts.md) | Historical artifact parent, verification, replay, and exit-code contracts | Preserved |
| [Ordinary Source Classifications](./ordinary-source-classifications.md) | Current top-level classifications, direct synchronization, and unversioned crawl scope | Active |
| [Crawl Control Automation Review](./crawl-control-automation-review.md) | Read-only scheduled-run review, fingerprint fencing, and non-frozen detail preview | Active |
| [Task Control Board Projections](./task-control-board-projections.md) | Current Board, per-Source authority, normalized Task Details, and safe action contracts | Active |
| [Source Job Attributes](./source-job-attributes.md) | Source-owned classification paths, governed Employment Types, atomic projection, APIs, and rebuild evidence | Active |
| [Ordinary Current Taxonomies](./ordinary-current-taxonomies.md) | Stable current Company Industry and Skill assignment/evidence contracts without releases or review queues | Active |
| [Automated Classification Batches](./automated-classification-batches.md) | Company Industry and Skill preview/run/stop/retry lifecycle plus repeated-Skill auto-creation | Active |
| [Job Intelligence Product Reads](./job-intelligence-product-surfaces.md) | Ordinary current composition, safe Job Detail serialization, bulk recommendations, and fixture contracts | Active |
| [Dashboard Operational Statistics](./dashboard-operational-stats.md) | Retained-corpus enrichment, Skill, and Candidate denominators with refresh isolation and accessibility | Active |
| [Job Browser Search](./job-browser-search.md) | Layered scope, contextual facets, selectors, pagination, and same-tab restoration | Active |
| [Unversioned Sandbox Cutover](./job-intelligence-cutover.md) | Transient retention export, destructive rebuild, exact verification, and history removal | Active |

---

## How to Fill These Guidelines

For each guideline file:

1. Document your project's **actual conventions** (not ideals)
2. Include **code examples** from your codebase
3. List **forbidden patterns** and why
4. Add **common mistakes** your team has made

The goal is to help AI assistants and new team members understand how YOUR project works.

---

**Language**: All documentation should be written in **English**.
