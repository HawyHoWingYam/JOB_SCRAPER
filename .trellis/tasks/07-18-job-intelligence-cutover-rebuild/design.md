# Job intelligence cutover and rebuild design

## Orchestrator Interface

Provide one CLI Module, not a collection of undocumented SQL snippets:

```text
job_intelligence_cutover inventory --output <manifest>
job_intelligence_cutover dry-run --manifest <manifest> --checkpoint-dir <dir>
job_intelligence_cutover execute --manifest <manifest> --backup-id <id> --checkpoint-dir <dir>
job_intelligence_cutover verify --manifest <manifest> --checkpoint-dir <dir>
job_intelligence_cutover rollback-plan --manifest <manifest>
```

`execute` is impossible without a previously successful dry-run manifest, matching schema/taxonomy hashes, explicit backup ID, and verified quiescence.

## Cutover manifest

Immutable JSON/Markdown summary contains:

- application commit/image IDs and configuration fingerprint;
- Alembic current/target revisions;
- active Canonical/Skill/Company Industry revision hashes;
- Job/Company/raw evidence counts and stable aggregate hashes;
- legacy projection counts and reset boundary;
- writer inventory and expected stopped state;
- rebuild command versions/configuration/model versions;
- backup ID, checkpoint directory, start/operator (`local-operator`) metadata.

Secrets and raw descriptions are excluded.

## Writer quiescence

Inventory includes ingest/enrichment/embedding/scheduler workers, manual action helpers, crawl publication, API/manual writes, and any outbox consumer that mutates affected projections. Quiescence check uses runtime heartbeats/process/container state plus a database write-sentinel observation window. Uncertain state aborts; “probably stopped” is not accepted.

Read-only product access may remain available only if it cannot enqueue or mutate affected data. Simplest release option is a maintenance/read-only window for the whole application.

## Backup and legacy audit snapshot

- Create PostgreSQL consistent backup and test restore into a disposable database before execute.
- Export replaced legacy fields/projections with IDs, provenance/raw references, counts, and hashes to an immutable artifact location.
- Record backup/artifact checksums in manifest.
- The audit export is evidence, not the rollback mechanism; rollback restores the database backup and previous image.

## Phase/checkpoint sequence

1. `inventory_and_quiesce`
2. `backup_and_restore_test`
3. `legacy_audit_snapshot`
4. `schema_expand_and_seed_revisions`
5. `rebuild_source_classification_paths`
6. `rebuild_employment_types`
7. `rebuild_canonical_job_taxonomy`
8. `rebuild_company_industries`
9. `rebuild_skill_state`
10. `switch_authoritative_reads`
11. `rebuild_embeddings`
12. `cross_layer_verify`
13. `reopen_writers`

Each phase writes a checkpoint with input hashes, output counts/hashes, status, timing, and error. A completed checkpoint replays only when inputs and code version match; mismatches require a new manifest.

## Preserve/reset enforcement

Before and after every destructive phase, assert preserved Job/Company IDs, source identities, raw payload/metadata, descriptions, URLs, dates, salaries, and unrelated enrichment counts/hashes. The orchestrator has no command to delete Jobs or Companies.

Reset targets are explicit allowlists. A table/column outside the allowlist cannot be truncated/updated by the orchestrator.

## Rebuild behavior

- Domain child rebuild Interfaces are invoked with pinned revisions/rule/model versions.
- Unsupported evidence becomes typed Unknown/Unassigned/review reason.
- Batch processing uses stable ID ordering and transaction-sized checkpoints.
- Assignment/mention/review/outbox uniqueness makes restart safe.
- Embeddings begin only after taxonomy/Skill projections pass; document builder uses new governed contracts.

## Verification gates

### Database

- preserved identity/evidence hashes;
- FK/check/unique/Primary constraints;
- no orphan paths/nodes/mentions/assignments;
- revision/provenance/audit coverage;
- no authoritative legacy scalar reads;
- unresolved/review reason totals reconcile to input population.

### Runtime/API

- representative assigned/unassigned/unknown/multi-value response serialization;
- filter semantics and descendant expansion;
- governance queue counts/deep links;
- decision idempotency/conflict/audit/outbox;
- search/recommendation/stats use governed projections.

### Frontend

- governance three-area smoke;
- Job Browser/Detail/Company/Dashboard terminology and states;
- no retired labels or raw-value filter options.

### Embeddings

- eligible Job coverage target recorded in manifest;
- failed Jobs/reasons explicit;
- sample document includes accepted Canonical Job Taxonomy and governed Skills only.

## Rollback

Rollback is available until legacy cleanup and writer reopening acceptance expire:

1. Stop all services again.
2. Restore recorded database backup into verified target.
3. Deploy recorded previous application images/config.
4. Validate legacy health/counts.
5. Reopen old writers.

If failure occurs before authoritative read switch, prefer fixing and idempotently resuming. After read switch or widespread writes, restore rather than attempting reverse translation.

Legacy column drop is explicitly a later cleanup migration outside the immediate cutover transaction and only after rollback window approval.

## Testing

- Generate a representative legacy fixture from anonymized/aggregate-safe structure.
- Test dry-run has zero mutations.
- Inject failure after each checkpoint and prove safe resume.
- Inject active writer and prove abort.
- Restore backup fixture and prove rollback.
- Run full integration matrix on restored copy before production/local live cutover.

