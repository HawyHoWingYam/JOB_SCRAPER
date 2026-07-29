# Technical Design: Remove Canonical Job Taxonomy

## 1. Summary

Remove the Job domain from the ordinary current-taxonomy system while retaining the
Company Industry and Skill domains. Source Classification Paths become the only Job
classification evidence exposed by the product, but remain source-qualified rather
than being combined into a replacement global hierarchy.

This is one atomic cross-layer contract removal rather than separate backend/frontend
features: mixed deployments are unsupported by the database contract, and the sandbox
cutover deploys one complete code set.

## 2. Target Boundaries

### Source classification

`SourceJobAttributes` remains authoritative for source-native classification paths and
employment labels. Its models, ingest events, source-qualified identifiers, read APIs,
and source-context filtering remain unchanged.

### Current taxonomy infrastructure

The generic node/alias/store/reader infrastructure remains only where it supports:

- Company Industry nodes, mappings, and assignments;
- Skill nodes, assignments, Candidates, Mentions, and curation.

The following Job-specific seams are removed:

- `CurrentJobTaxonomyAssignment` and `current_job_taxonomy_assignments`;
- Job seed/transform and Job assignment/read contracts;
- Job rows and allowed `job` discriminator values in shared taxonomy tables;
- Job Source-to-Canonical mapping resolution;
- Job Taxonomy tree/state HTTP routes and schemas.

Shared modules are narrowed rather than deleted wholesale. In particular,
`current_taxonomy_nodes`, `current_taxonomy_aliases`, and
`current_source_taxonomy_mappings` continue serving retained domains.

### AI enrichment and automated classification

AI enrichment no longer builds a Canonical Job Taxonomy candidate slice, asks the
extractor for a Job taxonomy classification, stores an assignment, or emits
`job.canonical_taxonomy_changed`.

The shared automated-classification runtime removes `job_taxonomy` from its supported
domain and persistence constraint. Company Industry and Skill adapters and batches
remain available. Skill Candidate automatic processing is unchanged.

### Product reads and search

Remove `canonical_taxonomy`, Job taxonomy availability, Job taxonomy breadcrumbs, and
canonical filter identifiers from backend schemas and frontend state. Remove Job
taxonomy facets and bulk reads rather than returning a permanent `unassigned` or
`unavailable` compatibility object.

Source Classification Paths remain in Job detail and source-context filtering. The
Dashboard Category chart and its navigation are removed; source paths are not folded
into a cross-source aggregate.

### Recommendations

Candidate retrieval remains pgvector cosine-distance retrieval over non-deleted Jobs.
Final scoring becomes:

```text
combined = semantic_similarity * 0.80
         + governed_skill_overlap * 0.15
         + freshness * 0.05
```

Remove taxonomy score helpers, bulk taxonomy reads, taxonomy response payloads, and UI
taxonomy labels. Company and location remain display-only; title deduplication and the
existing limit behavior remain unchanged.

### Embeddings

`CurrentEmbeddingDocumentBuilder` composes documents from ordinary Job content and
Governed Skill names only. Remove the taxonomy reader and taxonomy-change event.

Existing vectors are not retained because their input contained Canonical Job Taxonomy
text. The cutover imports no `job_embeddings`; the existing embedding workflow then
regenerates vectors for the retained Job corpus before Related Jobs is considered fully
ready.

## 3. Contract and File Impact

### Backend application

- Narrow models and exports in `backend/app/models/current_taxonomy.py` and
  `backend/app/models/__init__.py`.
- Narrow shared current-taxonomy contracts, transforms, store, enrichment, reader, and
  package exports under `backend/app/job_intelligence/current_taxonomies/`.
- Remove Job taxonomy routes/schemas and product projections in
  `backend/app/api/current_taxonomies.py`, `backend/app/schemas/`, and
  `backend/app/job_intelligence/product_read_model.py`.
- Remove canonical filter/facet/stats/export behavior in `backend/app/api/jobs.py`,
  `backend/app/api/stats.py`, and `backend/app/services/job_search_facets.py`.
- Remove the Job classification adapter/domain/readiness path while retaining Company
  Industry and Skill behavior in `backend/app/services/` and `backend/app/api/ai.py`.
- Apply the approved recommendation and embedding changes in
  `job_recommendation_service.py` and `current_embedding_document_builder.py`.

### Frontend

- Remove Job taxonomy display from `JobDetailModal` and `JobBrowser`.
- Remove canonical query keys, filter selectors, chips, summaries, and route hydration
  from `FilterPanel`, `JobBrowser`, `jobBrowserQueryUtils`, `jobBrowserLayerSummary`,
  and `appRoute`.
- Remove the Dashboard Category chart and Job Taxonomy classification entry points.
- Keep Company Industry and Skill API calls, tabs, components, and fixtures.
- Remove Related Jobs taxonomy labels from the modal.

### Data, fixtures, and documentation

- Delete the Job taxonomy seed while retaining `hsic_v2.json` and
  `skill_taxonomy.json`.
- Update backend-owned and frontend mirror fixtures together.
- Rewrite current-taxonomy, product-read, classification, dashboard, search, enrichment,
  and sandbox-cutover specs to describe the two retained governed domains plus source
  Job attributes.
- Remove Canonical Job Taxonomy vocabulary from `CONTEXT.md` without deleting Source
  Classification, Company Industry, or Skill terms.

## 4. Sandbox Cutover

The repository intentionally has no Alembic or in-place schema migration path. Use the
existing order:

1. Pass all code and disposable rehearsal checks.
2. Stop persistent services.
3. Export a transient retained artifact that excludes Job Taxonomy and Job embeddings
   but includes Jobs, Companies, source attributes, Company Industry, and complete Skill
   governance state.
4. Validate the artifact, clear PostgreSQL/Redis, and deploy the complete code set.
5. Bootstrap the empty schema from narrowed ORM metadata.
6. Import and exactly verify the retained artifact.
7. Start services and regenerate Job embeddings.
8. Smoke-test Job detail, source classifications, Skills, Company Industry, search,
   enrichment, Dashboard, and Related Jobs.
9. Finalize the transient artifact only after verification.

The supported rollback boundary is before database clearing: abort and continue using
the old complete stack. After clearing, services stay stopped while the new cutover is
repaired forward; there is no mixed-schema deployment or application restore command.

## 5. Compatibility and Failure Handling

- API removal is intentional; frontend and backend deploy atomically.
- Old canonical route/query parameters are ignored or removed rather than silently
  remapped to Source Classification Paths.
- If embedding regeneration is incomplete, Related Jobs may be unavailable/empty for
  affected Jobs; it must not reuse stale vectors.
- Missing Source Classification evidence remains a valid state and does not trigger a
  Canonical fallback.
- Company Industry and Skill regression failures block cutover.

## 6. Verification Strategy

- Architecture searches prove no runtime Job Taxonomy symbols, routes, payload fields,
  domain discriminator, seed, or change event remains.
- Focused backend tests cover source attributes, retained taxonomy domains, enrichment,
  classification batches, search/facets, stats, embeddings, recommendations, product
  serialization, and sandbox cutover.
- Focused frontend tests cover Job detail, Job Browser/filter routes, Dashboard,
  classification console, and Related Jobs.
- Full backend tests, frontend lint/tests/build, fixture equality, empty-schema bootstrap,
  and two disposable cutover rehearsals pass before shared-state operations.
