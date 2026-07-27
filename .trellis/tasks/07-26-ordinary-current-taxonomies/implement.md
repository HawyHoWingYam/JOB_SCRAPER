# Implementation plan

1. Add active-release-to-ordinary fixture transforms and preservation manifests.
   - [x] Pure Job, Company Industry, and Skill fixture transforms use stable
     codes and emit no release/revision/version fields.
   - [x] Preservation manifests validate legacy identity remaps against the
     complete current code set.
   - [x] Load active persisted assignment/projection/evidence rows into a
     validated revision-free preservation snapshot before cutover.
2. Add target stable schemas and current taxonomy store interfaces.
   - [x] Add ordinary current node/alias tables with direct hierarchy FKs.
   - [x] Add a flush-only `CurrentTaxonomyStore` with stable-code upsert,
     inactive handling, exact replay, and alias replacement.
   - [x] Add current Job/Company/Skill assignment and optional Source mapping
     tables before switching consumers.
3. Move reads, filters, assignments, embedding documents, and optional mappings.
   - [x] Current mapping reads constrain assignable codes when present and
     return the complete active assignable taxonomy when absent.
   - [x] Preserve active useful Job and Company Source mappings as ordinary
     optional mapping rows; drop excluded/unmapped coverage dispositions.
   - [x] Add one ordinary current Reader for Job, Company Industry, and Skill
     trees/projections, including ancestor-to-assignable-code expansion.
   - [x] Generate current Job Taxonomy embedding text without revision or
     version identity.
   - [x] Add a flush-only exact cutover writer for retained Job, Company,
     Skill, Candidate, and Mention rows.
   - [x] Add last-write-wins runtime writers for Job assignment, Company
     assignment sets, and Job Skill projections with no expected version.
   - [x] Switch domain reads, filters, assignment writers, and embedding
     documents to the current Store.
     - Runtime writer contracts are complete and tested.
     - Unversioned backend response schemas/routes and frontend read clients are
       complete but intentionally not mounted into the legacy-schema runtime.
     - A current-only Embedding composer is complete; the worker entrypoint
       now uses it as part of the stopped-stack atomic switch.
     - The root router now mounts only the ordinary current taxonomy API for
       these domains; legacy Governance routers are unmounted.
     - The atomic consumer set is mapped across product reads, filters,
       embeddings, stats/search, and API schemas; do not hot-switch the mounted
       legacy-schema stack one file at a time.
     - Job/Company/Skill hierarchical filter endpoints, lexical Skill matching,
       Job Browser taxonomy predicates, Skill autocomplete, and Dashboard
       taxonomy statistics now read ordinary current tables and stable codes.
     - Current Reader bulk-loads Job, Company, and Skill states for the pending
       product-read switch without per-item revision lookups.
     - Product response composition now reads ordinary current Job, Company,
       Skill, and Skill Candidate Mention state without revision or review
       fields. Job Detail and committed frontend/backend fixtures expose
       `candidate_mentions` plus top-level `skill_candidate_mentions`; legacy
       `provisional_skills` and `unreviewed_skill_mentions` compatibility has
       been removed.
     - AI enrichment writes ordinary current Job assignments, Skill
       projections, and unresolved Candidate/Mention evidence. A present
       Source mapping constrains the Job classifier; a missing mapping falls
       back to the complete assignable taxonomy and does not exclude the Job.
     - OfferToday ingest, detail repair, and ingest-worker Company Industry
       projection now write ordinary current assignments. Missing mappings
       preserve raw evidence and leave the Company unassigned without a review
       queue.
4. Remap accepted projections/audits and Skill Candidate/Mention evidence.
   - [x] Add unversioned Skill Candidate evidence and Mention tables without
     review recommendations, revision IDs, or lock versions.
   - [x] Load and remap active Job, Company, Skill projections plus Candidate
     and Mention evidence into flush-only target rows.
   - [x] Preserve taxonomy governance audit identity/cursors while removing
     revision and lock-version payload keys and replacing known legacy node IDs
     with stable codes.
5. Delete release/active/publisher/coverage/review vertical slices.
   - [x] Delete backend review/recommendation/decision routes and the complete
     frontend Job Intelligence Governance page in the same atomic switch.
     - [x] Delete the complete frontend Governance page, queue/recovery/decision
       components, API methods, deep links, Dashboard panel, and orphan styles;
       Job Browser tree reads use the ordinary current endpoints.
     - [x] Delete mounted and orphan backend Job Taxonomy, Company Industry,
       and Skill Governance routes/schemas plus historical Canonical recovery
       endpoints and worker branch.
     - [x] Delete the retired Governance summary, Governance HTTP/audit, and
       inactive Company review-reference product tests instead of retaining
       them as skips.
     - [x] Migrate disposable-PostgreSQL product-contract seed helpers and
       assertions from legacy revision tables to current tables; the suite
       passes without creating any legacy taxonomy/Governance table.
     - [x] Compose Job Detail and manual snapshots through one current read
       service so raw ORM validation cannot query retired governed Skill
       relationships; CSV export bulk-loads current Skill names.
     - [x] Delete the orphaned legacy `batch_enrich_jobs.py` manual
       provisional/review workflow and remove `Job.skills` /
       `Job.provisional_skills` legacy convenience properties.
     - [x] Delete the orphaned fail-closed `JobTaxonomyRegistry` and
       `JobCategoryNormalizer` compatibility modules and their obsolete
       Canonical preflight/registry test suite.
   - [x] Delete legacy ORM/modules from every runtime consumer after stats,
     search, enrichment, ingest, and embeddings use current tables.
     - Legacy release ORM/readers remain reachable only from the explicit
       preservation and one-time cutover bridge. The parent plan's final
       sandbox-cutover child deletes that bridge and its source tables after
       retained assignment/evidence import is verified.
6. Run domain, API, filter, embedding-document, frontend fixture, and static
   architecture tests.
   - [x] Target current-taxonomy module/API/embedding tests, Ruff, Mypy,
     compileall, frontend API test, full frontend lint, and production build
     pass before runtime mounting.
   - [x] Current Job Detail Skill Candidate response, committed fixture parity,
     targeted backend tests, and targeted frontend product tests pass without
     legacy Skill response fallbacks.
   - [x] Disposable PostgreSQL product response suite passes 21 tests using
     only ordinary current taxonomy tables; the disposable database is removed
     after verification.
   - [x] Run the final full-scope suites after legacy runtime consumers are
     deleted.
     - Backend focused scope: 69 passed, 14 skipped without PostgreSQL.
     - Disposable PostgreSQL product scope: 21 passed; database deleted.
     - Frontend taxonomy/product scope: 46 passed; full lint and build pass.
     - Full frontend run: 184 passed and six pre-existing CompaniesPage polling
       timing tests failed outside this task's changed files.

Do not mutate the shared sandbox; only disposable fixtures are transformed here.
