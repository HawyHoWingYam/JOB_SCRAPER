# Authoritative Source Catalog Runtime Contracts

## Scenario: Published source-native classifications constrain every crawl request

### 1. Scope / Trigger

Use this contract when changing category discovery, category APIs, crawl request
validation, source listing request builders, Source Catalog persistence, catalog
validation, or catalog publication/rollback for JobsDB, CTgoodjobs, or
OfferToday.

The Source Catalog controls pre-dispatch source scope. Post-collection Canonical
Job Taxonomy mapping and enrichment remain separate downstream concerns.

### 2. Signatures

The executable service boundary is:

```python
SourceCatalogService.get_published(source_site) -> PublishedSourceCatalog
SourceCatalogService.validate_classifications(source_site, ids) -> tuple[...]
SourceCatalogService.compile_classifications(source_site, ids) -> tuple[SourceQueryTarget, ...]
SourceCatalogService.resolve_scope(source_site, *, mode, classification_ids=()) -> tuple[...]
```

Runtime code resolves a revision before issuing any source request:

```python
load_published_query_plan(source_site, classification_ids) -> PublishedSourceQueryPlan
load_published_scope_query_plan(
    source_site,
    *,
    mode: Literal["all", "exact", "subtree"],
    classification_ids=(),
) -> PublishedSourceQueryPlan
```

The adapter seam has exactly three production implementations:

```python
class SourceCatalogAdapter(Protocol):
    source_site: str
    def discover(self) -> DiscoveredCatalog: ...
    def compile(self, node: CatalogNodeSnapshot) -> tuple[SourceQueryTarget, ...]: ...
    async def smoke(self, target: SourceQueryTarget) -> dict[str, JsonScalar]: ...
```

Persistence is owned by these tables, introduced at Alembic revision
`20260718_180000`:

```text
source_catalog_candidates
source_catalog_validation_runs
source_catalog_revisions
source_catalog_active_revisions
source_catalog_change_reviews
source_catalog_publications
```

Governance routes live below `/api/v1/source-catalogs`. The legacy
`GET /api/v1/categories` route is only a projection of the active revision.
The explicit operator CLI is `backend/scripts/source_catalog_admin.py`.

### 3. Contracts

#### Authority and immutability

- `source_catalog_active_revisions` is the sole executable authority and has one
  row at most per source.
- A candidate, inactive revision, bundled registry, or live discovery result
  must never be read by request validation or runtime dispatch.
- Candidate source/base/fingerprint/payload/provenance/diff fields are immutable.
  Validation state and bounded evidence may evolve.
- Published revisions are immutable. PostgreSQL triggers reject revision
  update/delete and candidate payload mutation, including writes that bypass
  the ORM.
- Publication copies a validated candidate, switches the active pointer, writes
  an append-only publication event, consumes the review, and commits once.
  Any failure rolls the entire transaction back.

#### Normalized identity and scope

- A selectable node has exactly one Source Classification identity in the form
  `<source>:<opaque-token>`. The token is non-empty and contains only letters,
  digits, `.`, `_`, or `-`; whitespace and additional `:` characters are
  rejected.
- The opaque classification token and source-native ID are separate fields. Do
  not silently derive a changed stable identity from display labels.
- Alias nodes remain visible but have no classification ID and no exact,
  subtree, or query capability.
- `all`, `exact`, and `subtree` expansion traverses the active revision in
  revision order and includes each queryable node exactly once.
- Catalog capabilities declare `supports_all_scope`, explicit all-scope roots,
  and an optional UI recommendation. A recommendation is never executable
  authority or a hidden default.
- OfferToday same-code children are aliases. `offertoday:118000` remains the UI
  recommendation, while explicit all-source scope is still supported.

#### Final outbound constraints

| Source | Query Target and final request contract |
|---|---|
| JobsDB | `jobsdb.classification`; both standalone and Scrapy call the shared JobsDB request builder and send `classification=<native_id>`. |
| CTgoodjobs | `ctgoodjobs.category`; use only the published, validated `url_path`; unknown IDs fail before navigation; catalog smoke and production crawling remain headed. |
| OfferToday | `offertoday.category`; send one bounded browse request with `jobFunctionCodes=[category_code]`, empty keyword, and explicit strategy metadata. |

OfferToday classification-only execution always uses `default_to_it=False` and
must not add categoryless keyword conditions. Explicit keyword requests retain
their legacy behavior only after every supplied classification has been
validated against the active revision.

CTgoodjobs bundled data may seed or recover candidate discovery with provenance.
It is never an executable fallback. Runtime code must not call `discover()`.

#### Validation and publication

- Every candidate gets one deterministic full-catalog offline validation run.
  Added or query-semantics-changed targets get one durable live-smoke run per
  target fingerprint.
- Smoke is bounded to one target/page, plus OfferToday warmup. It performs no
  detail crawl, staging write, or catalog publication.
- Persist only allowlisted scalar evidence. Never persist or log bodies,
  cookies, auth/session data, browser state, or unbounded ID lists.
- A stale worker cannot overwrite a reclaimed validation result. Failed and
  manual-action-required runs are retryable without moving the active pointer.
- Publish and rollback reviews are expiring, actor-bound, fingerprint-bound,
  active-base-bound, and single-use. Re-evaluate Automation impact inside the
  mutation transaction and compare its digest with the review.
- Production intentionally has no permissive `CatalogImpactEvaluator`. Until
  versioned Crawl Scope provides a real evaluator, initial publication remains
  blocked.
- Application startup and migrations must never discover, seed, validate, or
  publish a Source Catalog. Initial activation is an explicit operator action.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| No active revision for a source | `CATALOG_NOT_PUBLISHED`; issue no source request |
| Candidate-only, inactive, malformed, or unknown classification | `SOURCE_CLASSIFICATION_UNKNOWN`; do not call the source transport |
| Alias or non-queryable node selected | `SOURCE_CLASSIFICATION_NOT_EXECUTABLE` |
| Candidate changed or no longer publishable | `CATALOG_CANDIDATE_STALE` |
| Validation incomplete | `CATALOG_VALIDATION_REQUIRED` |
| Latest validation failed | `CATALOG_VALIDATION_FAILED` |
| Latest validation needs operator action | `CATALOG_MANUAL_ACTION_REQUIRED` |
| Review expired/reused, active pointer changed, or impact digest changed | `CATALOG_IMPACT_STALE`; roll back all mutation writes |
| CTgoodjobs path has scheme, host, query, fragment, or invalid category shape | Reject compilation before navigation |
| OfferToday classification compilation produces zero/multiple/keyword targets | Reject as non-executable |
| Smoke result contains body, cookies, nested objects, or unknown fields | Drop them before persistence; keep only allowlisted bounded scalars |

### 5. Good / Base / Bad Cases

- **Good:** `jobsdb:6281` resolves from one active revision and both retained
  JobsDB runtimes emit a final request containing `classification=6281`.
- **Good:** a new CTgoodjobs candidate contains an upstream category absent from
  the active revision. Governance can inspect it, but dispatch rejects the ID
  and sends no browser request until an explicit validated publication.
- **Base:** a label-only candidate change receives offline validation but no
  unchanged-target live smoke. The current active revision continues running.
- **Good:** an OfferToday IT subtree includes the root and each unique child
  once, keeps same-code aliases visible in the catalog, and emits no
  categoryless condition.
- **Bad:** `/categories` fetches CTgoodjobs live when no revision exists. This
  makes UI validation and headed execution disagree.
- **Bad:** startup publishes a bundled snapshot or publication proceeds with a
  no-op impact evaluator. Both bypass operator review and Automation impact.

### 6. Tests Required

- `test_source_catalog_domain.py`: deterministic fingerprint/diff; malformed
  identities; hierarchy, alias, all/exact/subtree, and expansion deduplication.
- `test_source_catalog_adapters.py`: compile every queryable node; capture final
  JobsDB/Scrapy request constraints; CTgoodjobs published paths and
  unknown-before-request behavior; OfferToday exact/subtree/all aliases and
  `jobFunctionCodes` with no categoryless supplement.
- `test_source_catalog_models.py` and `test_source_catalog_migration.py`:
  candidate/revision immutability, active pointer, table registration, trigger
  presence, and absence of migration-time publication.
- `test_source_catalog_validation.py`: offline plus changed-target selection,
  retry/manual action, stale-worker fencing, and failed/manual evidence
  allowlisting.
- `test_source_catalog_service.py`: missing evaluator, expiring/single-use
  reviews, mutation-time impact change, candidate-only rejection, publish and
  rollback, immutable history, and transaction rollback after an injected
  publication-audit failure.
- `test_source_catalog_api.py`: published tree/legacy/capability fingerprint
  agreement, no discovery, stable structured errors, and request-ID summary
  monitoring.
- Keep normal tests network-free. Live smoke is opt-in and must never be a
  deterministic CI requirement.

### 7. Wrong vs Correct

#### Wrong

```python
category = live_registry.get(raw_id) or static_registry.get(raw_id)
url = category.url if category else f"/jobs/jobs-in-{raw_id}"
await browser.goto(url)
```

This lets unpublished discovery/static guesses become executable authority and
can navigate before an unknown classification is rejected.

#### Correct

```python
plan = load_published_query_plan("ctgoodjobs", classification_ids)
for entry in plan.entries:
    assert entry.target.payload["crawl_mode"] == "headed"
    await browser.goto(f"https://jobs.ctgoodjobs.hk{entry.target.payload['url_path']}")
```

The active immutable revision resolves identity and URL before transport.

#### Wrong

```python
service = SourceCatalogService(db, impact_evaluator=lambda **_: {"allowed": True})
service.publish(candidate_id, review_token=token, actor=actor)
```

#### Correct

```python
service = SourceCatalogService(db, impact_evaluator=versioned_scope_impact_evaluator)
# Review and publish independently re-evaluate the same bound impact digest.
grant = service.review_publication(candidate_id, actor=actor)
service.publish(candidate_id, review_token=grant.review_token, actor=actor)
```

Without the real versioned-scope evaluator, leave publication blocked.
