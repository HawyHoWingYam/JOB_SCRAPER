# Block publication of non-executable source classification catalogs

## Goal

Prevent ordinary Source-classification synchronization from making a newly
discovered catalog active when any queryable classification cannot be compiled
into a bounded source-native query target. Preserve the last executable current
registry for that Source and return one actionable report covering every invalid
node.

## Background

- Ordinary classifications are current rows with no candidate, revision, or
  publication lifecycle. In this task, “publication” means the direct-sync
  boundary at which observations would become active current rows.
- `SourceClassificationRegistry.synchronize_catalog(...)` currently projects a
  discovered catalog into observations and writes them without first compiling
  every queryable node (`backend/app/services/source_classification_registry.py`).
- CTgoodjobs compilation requires a non-empty native ID and an exact relative
  path matching `/jobs/jobs-in-<slug>`; it intentionally rejects guessed paths,
  absolute URLs, query strings, and fragments
  (`backend/app/source_classifications/adapters/ctgoodjobs.py`).
- The reported One-Off review error exposed an already-active CTgoodjobs row
  whose `query_metadata.url_path` was absent or invalid. Repairing that current
  run or existing data is not part of this task.

## Requirements

1. Add a source-neutral pre-write executability gate to catalog synchronization.
   The registry must ask the owning Source adapter to validate/compile the
   discovered nodes before it mutates or flushes classification rows.
2. Keep Source-specific rules inside Source adapters. CTgoodjobs is the first
   required complete case: every queryable synchronized top-level classification
   must have a validated native `url_path`; no label-to-slug or other URL
   inference is allowed.
3. Treat the Source catalog as one atomic unit. If any required node is invalid,
   create, update, reactivate, and inactivate counts must all remain unapplied so
   the Source’s previous current rows stay unchanged. A failed Source must not
   block independent synchronization of other Sources.
4. Validate the complete candidate set and report all invalid nodes in one
   failure. Each diagnostic must identify the Source, `classification_id`,
   `native_id`, label, invalid field/value, and stable reason/code. Diagnostics
   must remain bounded and safe for logs.
5. Preserve the ordinary unversioned registry model. Do not add candidate,
   revision, publication, rollback, or provenance-repair tables or APIs.

## Acceptance Criteria

- [x] Given a CTgoodjobs discovered catalog containing multiple missing or
      malformed native paths, synchronization returns one deterministic error
      containing every offending node and performs no database writes.
- [x] Given an existing valid CTgoodjobs registry, a later invalid complete sync
      leaves its rows, active flags, labels, parents, timestamps, and query
      metadata unchanged.
- [x] Given a valid CTgoodjobs catalog, synchronization still creates/updates
      the ordinary registry and its compiled targets retain the exact discovered
      native paths.
- [x] Startup refresh records the invalid CTgoodjobs Source as failed while
      valid JobsDB and OfferToday refreshes still succeed independently.
- [x] Regression tests prove validation happens before the first database flush
      or mutation and that diagnostics are aggregate, stable, and bounded.
- [x] Existing ordinary-classification adapter, registry, scope, and API tests
      remain green.

## Out of Scope

- Repairing or retrying the One-Off run shown in the original report.
- Backfilling or otherwise modifying existing CTgoodjobs classification rows.
- Guessing native URLs from labels, IDs, or slugs.
- Retrofitting new Source-specific executability rules beyond the contracts
  already owned by JobsDB and OfferToday adapters.
- Reintroducing a versioned Source Catalog publication workflow.
