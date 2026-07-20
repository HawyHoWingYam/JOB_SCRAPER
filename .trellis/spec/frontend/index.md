# Frontend Development Guidelines

> Best practices for frontend development in this project.

---

## Overview

This directory contains guidelines for frontend development. Fill in each file with your project's specific conventions.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | To fill |
| [Component Guidelines](./component-guidelines.md) | Component patterns, props, composition | To fill |
| [Hook Guidelines](./hook-guidelines.md) | Custom hooks, data fetching patterns | To fill |
| [State Management](./state-management.md) | Local state, global state, server state | To fill |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | To fill |
| [Type Safety](./type-safety.md) | Type patterns, validation | To fill |
| [Scraper Pacing Settings UI](./scraper-pacing-settings-ui.md) | Settings cards, API round trips, Direct Override summary, and active-task warning | Active |
| [Crawl Task Pacing Snapshot UI](./crawl-task-pacing-snapshot-ui.md) | Detail-task startup snapshot rendering and cancellation lifecycle controls | Active |
| [Source Catalog Governance UI](./source-catalog-governance-ui.md) | Read-only catalog loading, strict decoders, durable validation, impact-gated publish/rollback, and structured errors | Active |
| [Task Control Wizard UI](./task-control-wizard-ui.md) | History-visible authoring, recoverable drafts, server review/plan authority, cancellation, and focus | Active |
| [AI Enrichment Operations Console](./ai-enrichment-console.md) | Monitoring-first two-slot UI, filtered preview, persistence, retry, and cooperative Stop | Active |
| [Source Job Attribute Contracts](../backend/source-job-attributes.md) | Cross-layer filter options, compatibility seam, and code-authoritative Source Job Attribute reads | Active |
| [Job Intelligence Product Reads](../backend/job-intelligence-product-surfaces.md) | Governance queues, stable deep links, active governed read contracts, availability, accessibility, and fixture parity | Active |

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
