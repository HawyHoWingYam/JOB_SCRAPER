# Ordinary Source Classification Contracts

## Scenario: current top-level classifications drive every source crawl

### 1. Scope / Trigger

Use this contract when changing classification discovery, classification APIs,
crawl authoring, dispatch, or listing request builders for JobsDB, CTgoodjobs,
or OfferToday. Source classifications are ordinary current rows. There is no
candidate, revision, publication, rollback, or provenance-repair lifecycle.

### 2. Signatures

```python
SourceClassificationRegistry(db).synchronize(
    source_site,
    observed_classifications,
    complete=True,
) -> SourceClassificationSyncResult
SourceClassificationRegistry(db).list_top_level(
    source_site,
    active_only=True,
) -> tuple[SourceClassification, ...]

load_source_query_plan(source_site, classification_ids) -> OrdinarySourceQueryPlan
load_source_scope_query_plan(
    source_site,
    *,
    mode: Literal["all", "selected"],
    classification_ids=(),
) -> OrdinarySourceQueryPlan
```

```text
GET /api/source-classifications/{source_site}?active_only=true
GET /api/categories?source_site={source_site}
```

The database authority is `source_classifications`. The six former
`source_catalog_*` governance tables were intentionally dropped by the
sandbox-only `20260726_180000` cutover.

### 3. Contracts

- A classification ID is `<source>:<opaque-token>` and never comes from its
  mutable display label.
- Synchronization creates newly observed classifications immediately, updates
  labels/query metadata, reactivates returning rows, and marks missing
  top-level rows inactive only when the observation is complete.
- Crawl authoring uses only active top-level rows. Child classifications may be
  preserved as source evidence, but are not crawl-authoring choices.
- `mode="all"` resolves every active top-level row; `mode="selected"` resolves
  only the supplied active top-level IDs. No revision is captured or resolved.
- The three `SourceClassificationAdapter` implementations discover source
  categories and compile bounded source-native `SourceQueryTarget` values.
- Startup may refresh ordinary classifications independently per source. A
  failure for one source must not inactivate or block the other sources.
- Existing Jobs, Companies, source-attribute projections, enrichment results,
  and classification paths survive classification synchronization and the
  destructive governance-table cutover.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Unsupported source | Reject before database or transport work |
| Unknown, inactive, or child ID selected for crawling | `SOURCE_CLASSIFICATION_UNKNOWN` or validation error; issue no source request |
| Selected scope is empty | Reject; issue no source request |
| Adapter cannot compile one bounded source query | `SOURCE_CLASSIFICATION_NOT_EXECUTABLE` |
| One source discovery fails during startup refresh | Record that source failure; keep other source sync results |
| Complete sync omits an old top-level row | Mark it inactive; do not delete historical Job evidence |
| Incremental path observation omits other rows | Keep other rows active |

### 5. Good / Base / Bad Cases

- **Good:** a new JobsDB top-level category appears, synchronization inserts
  it, and it is immediately available to author a later crawl.
- **Good:** `mode="all"` for OfferToday compiles one bounded query for every
  active large category; child categories are irrelevant to authoring.
- **Base:** a label changes while the source-native ID stays stable. Update the
  label on the same classification row.
- **Bad:** requiring an operator to publish a revision before the new category
  can be crawled.
- **Bad:** deleting collected Jobs or Companies when a classification becomes
  inactive.

### 6. Tests Required

- `test_source_classification_registry.py`: create/update/reactivate/inactivate,
  source isolation, qualified IDs, and top-level reads.
- `test_source_classification_adapters.py`: discovery and bounded query
  compilation for all three sources without network-dependent CI.
- `test_crawl_scope_service.py` and `test_crawl_control_api.py`: all/selected
  scope, unknown/inactive/child rejection, and absence of catalog revision
  fields.
- `test_source_catalog_migration.py`: the destructive sandbox migration drops
  only former governance tables/columns and preserves collected-data tables.
- Standalone and Scrapy runtime tests assert both paths consume the ordinary
  query plan and emit the same source-native constraint.

### 7. Wrong vs Correct

#### Wrong

```python
revision = source_catalog_service.get_published(source_site)
plan = revision.compile(classification_ids)
```

This recreates publication and revision authority that no longer exists.

#### Correct

```python
rows = SourceClassificationRegistry(db).list_top_level(source_site)
plan = load_source_query_plan(
    source_site,
    [row.classification_id for row in rows],
)
```

Current active large classifications are the only crawl-authoring authority.
