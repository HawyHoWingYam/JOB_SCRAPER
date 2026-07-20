# Job Intelligence cutover go/no-go checklist

Do not mark GO from memory. Every checked item needs an artifact path, command
output, or named operator witness. Any blank/unknown item is NO-GO.

## Release identity

- [ ] Separate live execution approval recorded: ____________________
- [ ] Operator is `local-operator`: ____________________
- [ ] Application commit matches manifest: ____________________
- [ ] Application image matches manifest: ____________________
- [ ] Configuration SHA-256 matches manifest: ____________________
- [ ] Current/target Alembic revisions reviewed: ____________________
- [ ] Canonical, mapping, HSIC, Skill, and embedding pins reviewed: __________
- [ ] Manifest envelope/hash verified: ____________________
- [ ] New empty checkpoint directory is mode 0700: ____________________

## Dry run and corpus boundary

- [ ] Dry run reports `mutation_detected=false`: ____________________
- [ ] Job/Company/raw evidence preserved fingerprints reviewed: _____________
- [ ] Reset allowlist exactly matches ADR-0014: ____________________
- [ ] Anonymized legacy fixture passes: ____________________
- [ ] Legacy audit artifact/checksum exists: ____________________
- [ ] No raw descriptions, cookies, sessions, or credentials in artifacts: ___

## Quiescence

- [ ] Pre-cutover outbox drained: ____________________
- [ ] Crawl/enrichment/scheduler active-run counts are zero: _________________
- [ ] Every known writer has explicit stopped evidence: ____________________
- [ ] No writer state is unknown: ____________________
- [ ] Database sentinel unchanged for at least 30 seconds: __________________

## Backup and rollback

- [ ] `pg_dump`/`pg_restore` versions recorded: ____________________
- [ ] Backup ID and SHA-256 recorded: ____________________
- [ ] Restore target is distinct and ends `_cutover_restore`: ________________
- [ ] Restored preserved fingerprints exactly match: ____________________
- [ ] Previous image/configuration remains deployable: ____________________
- [ ] Rollback plan artifact reviewed: ____________________
- [ ] Rollback decision owner and window recorded: ____________________

## Rebuild reconciliation

- [ ] Source paths/labels/Employment Types reconcile: ____________________
- [ ] Unsupported Source evidence has explicit reason: ____________________
- [ ] Every Job has Canonical assignment or active review: _________________
- [ ] Company-owned evidence only; legacy Industry produced review only: ____
- [ ] Skill matches/candidates/generic/rejected totals reconcile: ___________
- [ ] No duplicate active assignment/review/mention/outbox rows: ____________
- [ ] Eligible embedding coverage is 100% for exact model/version/384 dims: __
- [ ] Preserved fingerprints still pass after rebuild: ____________________

## Runtime smoke

- [ ] Backend governed API/read smoke passed: ____________________
- [ ] Governance queues/reads/decision idempotency smoke passed: ____________
- [ ] Search/filter/recommendation smoke passed: ____________________
- [ ] Embedding document/retrieval smoke passed: ____________________
- [ ] Frontend tests/build and governed terminology smoke passed: ___________
- [ ] Runtime evidence timestamp is after Phase 11: ____________________
- [ ] `verify-report.json` status is verified: ____________________

## Writer reopening

- [ ] Fresh separate approval to reopen writers: ____________________
- [ ] `--confirm-reopen-writers` value independently checked: _______________
- [ ] Persistent services restarted successfully: ____________________
- [ ] All writer evidence is running/stopped as expected, none unknown: ______
- [ ] Post-reopen API/search/worker health smoke passed: ____________________
- [ ] Rollback window monitoring owner assigned: ____________________

## Decision

- [ ] GO
- [ ] NO-GO

Decision timestamp (UTC): ____________________

Operator signature: ____________________

Reviewer signature: ____________________

Reason / conditions: _______________________________________________________
