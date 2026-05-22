# Audit Map

This directory splits the project audit across six complementary views. The split is meant to make ownership, runtime behavior, and future refactors easier to discuss than a simple frontend/backend/database split.

## Directions

1. Business domains
   - [Scraper and Crawl](01-business-domains/scraper-crawl.md)
   - [Scheduler](01-business-domains/scheduler.md)
   - [Ingestion](01-business-domains/ingestion.md)
   - [AI Enrichment](01-business-domains/ai-enrichment.md)
   - [Search and Retrieval](01-business-domains/search-retrieval.md)
   - [Operator and Recovery](01-business-domains/operator-recovery.md)
2. Data lifecycle
   - [Source Discovery](02-data-lifecycle/source-discovery.md)
   - [Listing Staging](02-data-lifecycle/listing-staging.md)
   - [Detail Acquisition](02-data-lifecycle/detail-acquisition.md)
   - [Normalization](02-data-lifecycle/normalization.md)
   - [Persistence](02-data-lifecycle/persistence.md)
   - [Enrichment](02-data-lifecycle/enrichment.md)
   - [Serving](02-data-lifecycle/serving.md)
   - [Recovery](02-data-lifecycle/recovery.md)
3. Execution units
   - [Backend API](03-execution-units/backend-api.md)
   - [Crawler Workers](03-execution-units/crawler-workers.md)
   - [Ingest Workers](03-execution-units/ingest-workers.md)
   - [AI Workers](03-execution-units/ai-workers.md)
   - [Embedding and Retrieval Workers](03-execution-units/embedding-retrieval-workers.md)
   - [Frontend Console](03-execution-units/frontend-console.md)
   - [Operator Scripts](03-execution-units/operator-scripts.md)
4. Adapter boundaries
   - [JobsDB Adapter](04-adapters/jobsdb-adapter.md)
   - [CTgoodjobs Adapter](04-adapters/ctgoodjobs-adapter.md)
   - [LLM Provider Adapters](04-adapters/llm-provider-adapters.md)
   - [Search and Embedding Adapters](04-adapters/search-embedding-adapters.md)
   - [Browser Runtime Adapters](04-adapters/browser-runtime-adapters.md)
5. Operator perspectives
   - [User-facing Job Search](05-operator-perspectives/user-facing-job-search.md)
   - [Admin Operator Scheduler](05-operator-perspectives/admin-operator-scheduler.md)
   - [AI Configuration](05-operator-perspectives/ai-configuration.md)
   - [Monitoring and Health](05-operator-perspectives/monitoring-health.md)
   - [Recovery and Manual Intervention](05-operator-perspectives/recovery-manual-intervention.md)
   - [Audit Reporting](05-operator-perspectives/audit-reporting.md)
6. Database
   - [Schema Map](06-database/schema-map.md)
   - [Crawl and Staging Tables](06-database/crawl-and-staging-tables.md)
   - [Canonical Job Store](06-database/canonical-job-store.md)
   - [Taxonomy and Skills](06-database/taxonomy-and-skills.md)
   - [Enrichment and Runtime Settings](06-database/enrichment-and-runtime-settings.md)
   - [Embeddings and Retrieval](06-database/embeddings-and-retrieval.md)
   - [Scheduler and Operational State](06-database/scheduler-and-operational-state.md)
   - [Outbox and Event Delivery](06-database/outbox-and-event-delivery.md)
   - [Migrations, Bootstrap, and Integrity](06-database/migrations-bootstrap-and-integrity.md)

## Optimization Backlog

- Add a validation script that checks every audit leaf file has required sections, live local file references, and no stale placeholders.
- Keep this map generated or validated against the actual `docs/audit` tree when audit sections are added, renamed, or removed.
- Link future implementation tasks back to the relevant audit backlog item so documentation and refactor work stay connected.

## Reading Notes

- Paths are current as of the branch `codex/ctgoodjobs-headed-mode-20260513`.
- The audit files describe current implementation state, not a target architecture.
- Audit files include an `Optimization Backlog` section for concrete refactor or hardening candidates found during review.
- The deleted coarse files `backend.md`, `frontend.md`, and `database.md` are intentionally replaced by this hierarchy.
