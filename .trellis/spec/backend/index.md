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
| [Database Guidelines](./database-guidelines.md) | Governance transactions, immutable history, migrations | Active |
| [Error Handling](./error-handling.md) | IP/manual-action recovery plus acknowledged manual crawl cancellation | Active |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | To fill |
| [Logging Guidelines](./logging-guidelines.md) | Cross-source crawl cadence, correlation, bounded fields, and secret-safe URLs | Active |
| [Crawl Task Detail Metrics](./crawl-task-detail-metrics.md) | Cross-source detail denominators, outcomes, remaining work, and UI projection | Active |
| [Manual Job Detail Pacing](./scraper-detail-pacing.md) | Source settings, immutable task snapshots, dispatch exclusion, and per-attempt pacing | Active |
| [AI Enrichment Run Operations](./ai-enrichment-runs.md) | Filter candidates, single-active scheduling, waiting promotion, monitor, retry, and cooperative Stop | Active |
| [CTGoodJobs Transport Research](./ctgoodjobs-transport-research.md) | Bounded HTTP/headless/headed comparison, sanitized evidence, viability replay, and WAF hard stops | Active |
| [OfferToday Production Crawl](./offertoday-production-crawl.md) | Cursor listing, partial caps, bound detail scope, distinct progress, and hard-stop contracts | Active |
| [OfferToday Research Artifacts](./offertoday-research-artifacts.md) | Historical artifact parent, verification, replay, and exit-code contracts | Preserved |
| [Authoritative Source Catalog Runtime](./source-catalog-runtime.md) | Published revision authority, source-native Query Targets, validation, and guarded publication | Active |
| [Source Job Attributes](./source-job-attributes.md) | Source-owned classification paths, governed Employment Types, atomic projection, APIs, and rebuild evidence | Active |
| [Canonical Job Taxonomy Governance](./canonical-job-taxonomy.md) | Stable governed releases, reviewed Source mappings, assignments/reviews, canonical reads, and dry-run rebuild | Active |
| [Company Industry Governance](./company-industry.md) | Immutable HSIC V2.0 releases, company-owned evidence, reviewed mappings, assignments/reviews, reads, and dry-run rebuild | Active |

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
