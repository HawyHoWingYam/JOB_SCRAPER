# Design: Add Company Industry Source Mapping setup path

## Current-state manifest

Add one governed JSON manifest for Company Industry Source Mapping dispositions. It has no revision or release identity. Each Source section is the complete current state for that Source, and each normalized Source Industry Label appears exactly once.

Each entry contains the Source label/key and exactly one disposition:

- `mapped`: one or more active assignable Company Industry target codes;
- `non_mapping`: no targets and a required stable reason.

The initial OfferToday section dispositions all 54 currently observed runtime labels: 47 structured `industry.name` labels and 7 retained compatibility-only labels used only when structured evidence is absent. Concrete HSIC targets require Taxonomy Operator review; broad labels such as `其他` must use non-mapping rather than guessed specificity.

## Synchronization boundary

Add an explicit deployment management command. It loads the entire manifest, normalizes and rejects duplicate identities, checks observed-label coverage, validates every positive target against the active assignable Company Industry Taxonomy, and computes deterministic per-Source created/updated/removed/unchanged counts before mutation.

After full validation, each Source is synchronized in one transaction: delete/replace only that Source's positive `company_industry` rows in `current_source_taxonomy_mappings`. A Source failure preserves its prior rows and makes the command exit unsuccessfully. Reapplying identical data is a no-op.

Explicit non-mapping dispositions remain in the manifest and never create fake mapping targets. Runtime compares positive manifest targets with current database rows; drift or invalid targets fail closed as configuration errors. This avoids a schema migration while keeping the manifest authoritative.

## Candidate selection and readiness

Introduce a shared Company mapping disposition resolver used by Preview and Start selection:

- `mapped`: eligible Batch item;
- `non_mapping`: governed exclusion, counted in Preview, no Batch item, no Retry;
- missing disposition, manifest/DB drift, inactive target, or malformed evidence: actionable unsupported/error item.

The limit applies to the initially selected unassigned Company population before exclusions; the system does not pull replacements from outside the bounded selection.

Extend the classification Preview projection with Company readiness counts: selected, mapped/effective, unmapped/error, and excluded-non-mapping. Start is permitted only when mapped/effective is greater than zero. The backend enforces the same guard for direct API callers. In a partially ready batch, mapped items run and unsupported items retain existing per-item failure isolation.

## Frontend

Render mapped/selected/unmapped/excluded counts and actionable readiness text on the Company Industry tab. Disable Start when mapped is zero. Job Taxonomy and Skill retain their existing Preview presentation.

## Compatibility and rollout

- Do not add mapping versions, releases, startup synchronization, CRUD APIs, or taxonomy fallback nodes.
- Do not change optional Source-to-Canonical Job Mapping behavior.
- No database schema change is required; empty-schema bootstrap and retained-data cutover stay untouched.
- Validate the 54-label manifest and tests before running the management command against the shared sandbox.
- Rollback restores the previous manifest and reruns the same synchronization command.

## Validation

Test manifest shape and full observed coverage, positive/non-mapping exclusivity, target validity, atomic rollback, stale-row removal, idempotence, per-Source isolation, drift detection, readiness counts, direct-Start guard, selection-time exclusion, partial-batch isolation, UI rendering, and one real mapped Company success path.
