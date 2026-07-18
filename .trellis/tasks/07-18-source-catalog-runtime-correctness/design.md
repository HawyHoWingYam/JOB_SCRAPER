# Source Catalog runtime correctness design

## Module boundary

`SourceCatalogService` is the only executable catalog interface for API validation, future Crawl Scope resolution, and runtime dispatch. It hides candidate/revision persistence, diffing, validation selection, active-pointer changes, and three source adapters.

`SourceCategoryRegistry` becomes a legacy read adapter over `SourceCatalogService.get_published(...)`; it no longer fetches CTgoodjobs or owns authority.

## Data contracts

### Normalized catalog node

```python
@dataclass(frozen=True)
class CatalogNodeSnapshot:
    node_key: str
    source_site: SourceSite
    classification_id: str | None
    native_id: int | str
    native_label: str
    parent_node_key: str | None
    native_path: tuple[str, ...]
    depth: int
    selectable: bool
    supports_exact: bool
    supports_subtree: bool
    queryable: bool
    alias_of_node_key: str | None
    query_semantics_hash: str | None
    source_metadata: Mapping[str, JsonValue]
```

`node_key` uniquely identifies a node inside a revision, including non-selectable aliases. `classification_id` is the stable scope reference and is present only when the node can represent independent source classification intent. It is always source-qualified:

```text
jobsdb:6281
ctgoodjobs:021
offertoday:118000
```

The OfferToday same-code child is retained as an alias node pointing to its root and has no independent scope action. Catalog fingerprint includes source-native and normalized execution fields but excludes optional Canonical Job Taxonomy annotations.

Each revision also carries catalog-level capabilities:

```python
@dataclass(frozen=True)
class CatalogScopeCapabilities:
    supports_all_scope: bool
    all_scope_root_node_keys: tuple[str, ...]
    recommended_scope: Mapping[str, JsonValue] | None
```

JobsDB and CTgoodjobs resolve all mode over every flat queryable classification. OfferToday resolves all mode as the deduplicated union of every root subtree; its recommended scope remains Subtree Scope on `offertoday:118000`. Recommendation is UI assistance only and never an empty/default payload.

### Query Target

Query Targets are page-independent and contain no session/browser/auth data.

```json
{"version":1,"adapter":"jobsdb.classification","classification_id":"jobsdb:6281","native_id":6281}
```

```json
{"version":1,"adapter":"ctgoodjobs.category","classification_id":"ctgoodjobs:021","native_id":"021","url_path":"/jobs/jobs-in-information-technology"}
```

```json
{"version":1,"adapter":"offertoday.category","classification_id":"offertoday:118000","category_code":118000,"endpoint":"browse","keyword":"","rcd_type":7}
```

Pagination is execution state controlled by Page Depth/Run Page Cap, not part of Query Target identity.

### Candidate and revision states

```text
Candidate: discovered -> validating -> validated | validation_failed | manual_action_required
Candidate: validated -> published
Candidate: any non-published -> superseded

Revision: immutable inactive history
Active pointer: exactly one revision per Source
```

Candidate payload/fingerprint are immutable. Validation summary/state and validation-run rows evolve. Publication copies the validated immutable payload into a revision and atomically changes the Source pointer.

## Persistence

- `source_catalog_candidates`
  - UUID, source, base revision, fingerprint, normalized payload JSON, source payload JSON, diff JSON, state, timestamps.
  - Unique source/fingerprint while non-superseded to make repeated discovery idempotent.
- `source_catalog_validation_runs`
  - candidate, validation kind, optional node/classification, expected target hash, status, attempt, bounded evidence/error/manual-action JSON, timestamps.
- `source_catalog_revisions`
  - UUID, source, sequence, fingerprint, normalized/source payload JSON, provenance JSON, predecessor, publication metadata.
  - Immutable after insert.
- `source_catalog_active_revisions`
  - source primary key, revision FK, updated timestamp/actor.
- `source_catalog_change_reviews`
  - one-time review ID/token hash, operation (`publish|rollback`), candidate/target revision, candidate fingerprint, base active revision, Automation-impact digest, actor, expiry, consumed timestamp.
- Publication audit may use append-only `source_catalog_publications` if pointer history cannot be reconstructed cleanly.

All new models must be imported through `app.models`, included in `Base.metadata.create_all`, represented in existing-DB migration/convergence, and tested on fresh bootstrap.

## Adapter interface

```python
class SourceCatalogAdapter(Protocol):
    source_site: SourceSite

    def discover(self) -> DiscoveredCatalog: ...
    def compile(self, node: CatalogNodeSnapshot) -> tuple[SourceQueryTarget, ...]: ...
    def smoke(self, target: SourceQueryTarget) -> SmokeEvidence: ...
```

The shared module validates:

- exact schema/version and deterministic serialization;
- unique node keys and source-qualified classification IDs;
- parent existence, cycle freedom, path/depth consistency;
- alias target validity and non-selectability;
- declared exact/subtree/query capabilities;
- successful compilation of every queryable node;
- unique/deduplicated Query Target identities;
- changed-target selection via `query_semantics_hash`.

All/Subtree expansion is not an adapter fallback. `CrawlScopeService` traverses the normalized revision from the declared all roots or selected subtree, chooses each queryable classification exactly once, and only then asks the adapter to compile those nodes. The resolved plan stores the ordered classification set, expansion hash, Query Target count, and compiled target fingerprint. OfferToday classification-scoped compilation always calls legacy helpers with `default_to_it=False` and never adds keyword targets.

The adapter owns only source variation.

### JobsDB adapter

- Discovery wraps `get_all_categories()` as flat exact/queryable classifications.
- Compile returns native integer `classification`.
- Shared request builder produces the JobsDB search params currently implemented by `CategoryListScraper.fetch_page`.
- The retained Scrapy path must use that same builder rather than a fixed URL plus metadata.
- Smoke performs one page-1 GET and verifies the final request contains the selected `classification`, expected content type/shape, and no detail/staging work.

### CTgoodjobs adapter

- Discovery parses live source data into a candidate; static registry is seed/fallback input for discovery only, never an executable fallback after publication.
- Compile resolves published native ID/slug/path; unknown ID is an error before request.
- Runtime standalone and Scrapy code use the compiled published path. Remove `slug=raw_id` guessing.
- Smoke uses the supported headed mode, one category/page, and records passed/failed/manual-action evidence. It never advertises headless.

### OfferToday adapter

- Discovery preserves roots, unique leaves, and same-code aliases.
- Root Exact compiles one root category target. Root Subtree is expanded by Crawl Scope traversal into root plus unique queryable descendants; the alias does not duplicate the root.
- Compile uses category/browse semantics and `jobFunctionCodes`.
- Classification-only compilation never invokes the legacy default IT categoryless keyword pack. Explicit keyword-only/hybrid intent remains outside v1.
- Smoke performs required warmup plus one category page request, without detail or staging, and verifies `jobFunctionCodes`.

## Validation orchestration

`CatalogValidationCoordinator.start(candidate_id)` persists one generic offline run and one live-smoke run for each added/query-changed target. It returns immediately with a validation-run projection; governance clients poll.

Workers claim durable validation rows with compare-and-set/row locking. Crash leaves a retryable stale run, not a published candidate. Source smoke may invoke source executors, but validation has a separate command/result and cannot write Crawl Jobs, listings, or published jobs.

Manual action persists only bounded operator context. CTgoodjobs remains headed; resume/retry reuses the same candidate/target hash. If the candidate fingerprint changes, existing validation evidence is invalid.

## Publication and impact seam

`review_publication(candidate_id)` verifies validation and asks a typed `CatalogImpactEvaluator` for impact. Child 2 provides the production evaluator backed by versioned Authored Crawl Scope.

Initial revision activation is allowed only through an explicit operator command and an impact result that states no versioned Automations exist (or that legacy control data is awaiting the approved reset). There is no permissive no-op evaluator. Production rollout may defer initial activation until child 2 is deployed.

`review_publication(...)` persists a short-lived, single-use change-review record bound to candidate/target fingerprint, base active revision, impact digest, actor, and expiry. `publish(..., review_token)` locks candidate, review, and active pointer; verifies every binding; conditionally switches only when the active pointer still equals the reviewed base; inserts immutable revision/publication audit; consumes the review; and commits. Concurrent publish/rollback returns `CATALOG_IMPACT_STALE`. Rollback uses the same review record and creates a new publication event pointing at an old immutable revision; it never edits that revision.

## API

- `GET /api/v1/source-catalogs`: summary only, no discovery.
- `GET /api/v1/source-catalogs/{source}/published`: tree/capabilities.
- `POST /api/v1/source-catalogs/{source}/candidates`: discover/idempotently reuse.
- `GET /api/v1/source-catalogs/{source}/candidates/{id}`.
- `POST .../{id}/validation-runs`; `GET .../validation-runs`.
- `POST .../{id}/publication-reviews`; `POST .../{id}/publish`.
- `GET .../{source}/revisions`.
- `POST .../{revision}/rollback-reviews`; `POST .../{revision}/rollback`.

The legacy `GET /categories?source_site=...` flattens selectable nodes from the published revision with the old keys. If no revision exists it returns a structured `CATALOG_NOT_PUBLISHED`, not live/fallback data.

## Runtime integration

- `crawl_request_validation` resolves primitive compatibility IDs only against the published revision.
- New runtime code accepts compiled Query Targets; the later Crawl Scope child owns target snapshots.
- Standalone and Scrapy implementations call shared source request builders so tests prove the selected target changes URL/params/body.
- Tests capture the final outbound HTTP/Scrapy request URL, query params, or JSON body; testing only a compiler object or callback metadata is insufficient.
- Query target metadata carried into staged records is descriptive; correctness is proved at the outbound request seam.
- Runtime never calls adapter discovery.

## Errors and observability

Stable errors:

- `CATALOG_NOT_PUBLISHED`
- `CATALOG_CANDIDATE_STALE`
- `CATALOG_VALIDATION_REQUIRED`
- `CATALOG_VALIDATION_FAILED`
- `CATALOG_MANUAL_ACTION_REQUIRED`
- `CATALOG_IMPACT_STALE`
- `SOURCE_CLASSIFICATION_UNKNOWN`
- `SOURCE_CLASSIFICATION_NOT_EXECUTABLE`

Use `build_scrape_log_event`; log source, candidate/revision, bounded node count, target hash prefix, status, elapsed time, and error classification. Never log source payload bodies, cookies, auth, browser state, or lists of target IDs.

## Compatibility and rollback

- Existing category response shape remains available as a projection, but live CTgoodjobs behavior is removed.
- The source capability catalog remains separate and may reference active revision health.
- Do not auto-create/publish revisions during bootstrap.
- Before switching runtime consumers, deterministic tests and an explicit initial published revision are required for every Source.
- Rollback reactivates the prior revision through the service; code rollback must not mutate revision payloads.
