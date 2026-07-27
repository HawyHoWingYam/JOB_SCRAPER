# Design: pre-write catalog executability gate

## Boundary

`SourceClassificationRegistry.synchronize_catalog(...)` remains the single
catalog-to-current-registry boundary. It receives the owning adapter (or an
equivalent compile callback/protocol) and validates the complete discovered
catalog before projecting observations into mutable ORM rows.

The registry owns atomic orchestration and aggregate diagnostics. Adapters own
source-native executability rules through their existing `compile(node)`
contract. The design must not duplicate CTgoodjobs URL syntax in the registry.

## Data Flow

1. An adapter discovers a `DiscoveredCatalog`.
2. The registry selects every classified node that is required to be executable
   by the ordinary authoring contract.
3. It calls the same adapter compilation contract used by runtime resolution.
4. It collects every `CatalogValidationError` rather than stopping at the first.
5. If failures exist, it raises one aggregate domain validation error before
   reading or mutating current ORM rows.
6. If all nodes compile, the existing observation projection and direct
   synchronize/upsert path runs unchanged.

Startup continues wrapping each Source in its own nested transaction. A failed
Source produces a failure result while the loop proceeds to the next adapter.

## Diagnostic Contract

The aggregate error has a stable top-level code and ordered node diagnostics.
Ordering is deterministic (classification identity/node key), and every item is
bounded to Source, classification ID, native ID, label, field/value, and the
adapter’s stable failure code/reason. Raw pages, exception traces, credentials,
or unbounded metadata are excluded.

If the current `CatalogValidationError` shape cannot carry structured aggregate
details, extend the domain error with a backward-compatible optional details
field or introduce a focused aggregate subtype. Existing callers that rely on
`code`, message, and `node_key` must continue to work.

## Compatibility

- No database migration is expected.
- Ordinary current-row APIs and authoring payloads do not change.
- Adapter compilation remains the source of truth for runnable targets.
- Direct `synchronize(...)` calls used for incremental captured paths retain
  their structural validation; the new full-catalog executability gate applies
  to `synchronize_catalog(...)`.

## Atomicity and Rollback

The strongest guarantee comes from ordering: finish all compile checks before
the first ORM mutation or flush. Transaction rollback remains a secondary
safety net. Tests must compare persisted rows before and after an invalid sync,
including timestamps and metadata, rather than checking only row counts.

## Trade-offs

Aggregating all errors performs a full validation pass even after the first
failure, but catalog sizes are bounded and the reduced operator repair cycle is
worth the cost. Reusing `compile` avoids a second validation language and
prevents runtime and synchronization rules from drifting.
