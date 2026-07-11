# OfferToday `jobId`-Only Identity Compatibility Design

> Date: 2026-07-11
> Status: Option A approved by the user; written review pending
> Scope: Corrective amendment to Plan 2 Task 8 only

## Objective

Correct the OfferToday identity contract exposed by the bounded Plan 2 Task 8 smoke without weakening identity validation or falsifying upstream evidence.

The implementation must accept the observed OfferToday HK payload shape, where `jobId` is the only job identity field returned by listing and detail responses, while retaining strict support for a future or endpoint-specific explicit `encryptJobId`.

This design does not authorize another live request. It defines the offline correction that must pass deterministic review before a replacement Task 8 smoke can be proposed.

## Relationship to Existing Plan 2 Documents

This design amends the identity-specific requirements in:

- `docs/superpowers/specs/2026-07-10-offertoday-broad-it-coverage-reliability-research-design.md`;
- `docs/superpowers/specs/2026-07-11-offertoday-plan2-live-census-calibration-design.md`; and
- `docs/superpowers/plans/2026-07-11-offertoday-plan2-live-census-calibration.md`.

It supersedes only the assumption that every accepted listing row must contain two independently observed raw strings, `jobId` and `encryptJobId`. All other Task 8 request budgets, no-write guarantees, artifact requirements, review gates, and Task 9 sequencing remain unchanged.

## Triggering Evidence

### Bounded Research Smoke

The single authorized Task 8 smoke produced:

- run ID `fab9d8e1-4c12-4170-a539-c0a6cdbbca93`;
- category `118000`, endpoint `search`, `rcdType=7`, page 1;
- API code `0`, 10 rows, reported total `265`, and `hasMore=true`;
- 10 nonblank `jobId` values;
- zero observed `encryptJobId` values; and
- no detail requests because the current runner classified every row as `missing_encrypted_job_id`.

Artifact verification passed and the manifest hash is `1928423eed6cfd95e4cd2a3af3eb1d62c2ea6d460b122acb0ca0fefcfb4b548b`.

### Independent Browse Evidence

A separate product crawl, `5d1a13f3-fbc6-48f6-b7f4-6740962cfb80`, observed the same shape from endpoint `browse`:

- API code `0`, 10 rows, reported total `431`, and `hasMore=true`;
- 10 nonblank `jobId` values; and
- zero observed `encryptJobId` values.

The shared strict runner stopped that product crawl with `identity_issue`, proving the defect is not confined to the research CLI or the `search` endpoint.

### Historical Database Evidence

Read-only inspection of the current PostgreSQL database found:

- 15,697 OfferToday staging rows across 42 crawl jobs;
- an upstream-shaped `jobId` in all 15,697 rows;
- no upstream-shaped `encryptJobId` in any listing row;
- 6,055 completed detail payloads with `jobId`;
- no upstream-shaped `encryptJobId` in any completed detail payload; and
- successful historical details for all 10 IDs returned by the Task 8 smoke.

The same 24-character opaque token is used as `source_job_id`, the public `/hk/job/<token>` path component, and the identity returned by successful detail responses.

### Data-Flow Evidence

The browser runtime returns the decoded response dictionary without projecting listing fields. The parser preserves each raw listing row under `raw_data`, and the listing runner reads `raw_data.jobId` and `raw_data.encryptJobId` directly. Source hashes captured by the smoke match the current files.

Therefore the missing field is not caused by browser transport, response projection, parser loss, locale conversion, or artifact serialization.

## Decision

Adopt Option A: provenance-aware detail-route fallback.

1. `jobId` remains the canonical OfferToday business identity.
2. An explicit valid `encryptJobId` remains the preferred detail-route and public-URL identifier.
3. When no nonblank `encryptJobId` evidence exists, resolve the detail-route identifier to `jobId`.
4. Record whether the route identifier came from `encryptJobId` or `jobId_fallback`.
5. Never insert a fabricated `encryptJobId` into `raw_data` or claim that the upstream response supplied it.
6. Continue rejecting invalid identity values, conflicting aliases, response mismatches, and cross-row mapping conflicts.

## Terminology

### Canonical Job ID

The validated nonblank `jobId`. This remains the deduplication, staging, publication, and detail-response ownership key.

### Observed Encrypted Job ID

A nonblank string actually present as `encryptJobId` in upstream or preserved identity evidence. It may be absent.

### Resolved Detail-Route ID

The value sent through the existing `encryptJobId` query parameter and used in the public job URL:

```text
explicit encryptJobId, when valid
otherwise canonical jobId
```

The compatibility field name `encrypted_job_id` may continue to carry this resolved value internally, but every new observation and persisted JSON payload must also record its provenance.

### Resolution Source

Exactly one of:

- `encryptJobId`: the route ID was explicitly observed; or
- `jobId_fallback`: no explicit encrypted ID was observed, so `jobId` was used.

## Architecture

### Shared Identity Resolver

`backend/app/sources/offertoday/detail_identity.py` will own one shared listing-identity resolver used by parsing, listing analysis, historical staging resolution, detail targeting, and repair.

The resolver returns a typed immutable value containing:

- `job_id`;
- resolved `encrypted_job_id`; and
- `encrypted_job_id_source`.

Resolution rules:

1. Read and validate all supported `jobId` aliases, including preserved `raw_data.jobId`.
2. Reject missing, non-string, or conflicting `jobId` evidence.
3. Read all supported `encryptJobId` aliases, including preserved `raw_data.encryptJobId`.
4. Reject non-null non-string or conflicting nonblank encrypted-ID evidence.
5. Use the one explicit encrypted value when present.
6. Otherwise use the canonical `jobId` and mark the source `jobId_fallback`.
7. When `source_job_id` is supplied, require it to equal canonical `jobId`.

Blank or null encrypted-ID aliases count as unobserved and use the fallback. They never overwrite a conflicting nonblank value.

### Parser Boundary

`backend/app/sources/offertoday/parsers.py` will:

- preserve the decoded upstream row value-for-value in `raw_data` without adding identity aliases;
- set normalized `job_id` to canonical `jobId`;
- set normalized `encrypted_job_id` to the resolved detail-route ID; and
- add normalized `encrypted_job_id_source`.

The parser must use the shared resolver so production, audit, replay, and research cannot apply different fallback rules.

### Listing Runner and Evidence

`backend/app/sources/offertoday/listing_runner.py` will distinguish raw observation from usable resolved identity.

For a `jobId`-only row:

- the row is accepted;
- its resolved pair is `(jobId, jobId)`;
- its source is `jobId_fallback`;
- the raw-missing encrypted-ID counter increments; and
- no `ListingIdentityIssue` is emitted solely because `encryptJobId` was absent.

Per-row evidence, accepted identity pairs, frozen detail targets, and serialized research events must carry the resolution source. Aggregate page evidence must separately report how many rows used `jobId_fallback`.

Mapping checks become provenance-aware:

- zero explicit encrypted IDs for a canonical `jobId` means its `jobId_fallback` route remains authoritative;
- exactly one explicit encrypted ID for a canonical `jobId` takes precedence over any older fallback for that same job;
- multiple distinct explicit encrypted IDs for one canonical `jobId` remain a forward conflict; and
- one authoritative resolved route ID cannot map to multiple canonical `jobId` values.

Promotion from fallback to one explicit value is recorded as a provenance upgrade, not an identity conflict. It changes future targeting without rewriting historical raw payloads.

### Staging and Historical Rows

New staging JSON records will contain normalized:

- `job_id`;
- resolved `encrypted_job_id`; and
- `encrypted_job_id_source`.

No relational column or migration is required.

Historical rows resolve as follows:

- explicit consistent encrypted-ID evidence uses source `encryptJobId`;
- rows containing only `jobId` use source `jobId_fallback`;
- preexisting normalized aliases equal to `jobId` remain usable but do not prove upstream observation when `raw_data.encryptJobId` is absent;
- one consistent explicit mapping takes precedence over fallback-only duplicates for the same canonical job; and
- genuine explicit alias or mapping conflicts remain fatal or deferred according to the existing caller contract.

### Detail Requests and Validation

The browser runtime keeps the current endpoint shape:

```text
/wapi/geek/recommend/jobDetail?id=<job_id>&encryptJobId=<resolved_route_id>
```

For observed HK `jobId`-only rows, both parameters contain the same token.

A successful detail response must still contain a `jobId` matching the requested canonical ID. If the response explicitly contains `encryptJobId`, it must match the requested resolved route ID. Absence of response `encryptJobId` is valid and does not weaken the `jobId` ownership check.

Repair and offline parsing must preserve the resolved route ID and its provenance through canonical result ownership. No mismatch may mutate staging, Job, or Company state.

## Baseline and Artifact Semantics

The current baseline conflates normalized encrypted-ID aliases with upstream observation. The correction will make these concepts explicit.

The baseline must report:

- observed explicit encrypted-ID rows;
- `jobId_fallback` rows;
- unusable identity rows; and
- genuine alias or mapping conflicts.

`missing_encrypted_job_id_rows` remains an observation metric for rows without explicit upstream evidence; it no longer implies that those rows are unusable. `identity_error_classifications` must not contain `missing_encrypted_job_id` when fallback resolution succeeded.

Snapshot and product hashes may change because their serialized identity metadata changes. Before any replacement smoke, two fresh quiescent baselines must be captured and must match each other. Old hashes remain historical provenance and must not be rewritten.

Research artifacts must make the distinction auditable:

- raw missing counts show what OfferToday actually returned;
- fallback counts show how many route IDs were derived;
- every accepted pair and detail target shows its resolution source; and
- strict replay reproduces the same resolution and hashes without network access.

## Error Handling

The following remain hard identity failures:

- missing or blank canonical `jobId`;
- non-null non-string `jobId` or `encryptJobId` evidence;
- conflicting nonblank aliases for either identity;
- canonical `source_job_id` mismatch;
- multiple explicit route IDs for one canonical job or one authoritative route ID for multiple canonical jobs; and
- detail-response `jobId` or explicit `encryptJobId` mismatch.

The following are not failures by themselves:

- absent, null, or blank `encryptJobId` with a valid canonical `jobId`; and
- equal resolved `job_id` and `encrypted_job_id` when provenance is `jobId_fallback`.

Auth expiry, WAF, IP block, transport, invalid payload, terminal code `2520`, pacing, and batch-stop behavior are unchanged.

## Deterministic Test Design

Implementation follows red-green-refactor. Tests must first fail against the current strict behavior.

### Required Real-Schema Regressions

1. A saved `search` row with only `jobId` resolves to a fallback pair and is accepted.
2. A saved `browse` row with only `jobId` resolves identically.
3. Raw evidence remains unchanged and does not gain `encryptJobId`.
4. The page reports raw missing and fallback counts without an identity issue.
5. The row is eligible for staging and detail-cohort freezing.
6. The detail request sends the canonical token in both query parameters.
7. A successful detail response containing only matching `jobId` validates.
8. Historical staging rows with only `jobId` resolve without mutation.

### Required Strictness Regressions

1. Distinct valid explicit `jobId` and `encryptJobId` values remain distinct.
2. Non-string explicit encrypted evidence is rejected.
3. Conflicting encrypted aliases are rejected.
4. A single explicit mapping promotes and replaces fallback authority for the same canonical job.
5. Multiple explicit forward mappings and authoritative reverse collisions are deferred.
6. Detail `jobId` mismatch is rejected before parse or persistence.
7. Explicit detail `encryptJobId` mismatch is rejected.
8. Offline repair preserves the resolved route ID and provenance.

### Artifact and Baseline Regressions

1. Event and manifest serialization includes resolution source and fallback counts.
2. Strict replay reproduces fallback decisions exactly.
3. Baselines separate observed-missing rows from unusable identity rows.
4. Conservation and no-write checks remain unchanged.
5. Existing explicit two-ID fixtures continue to pass.

## Verification Scope

Before requesting another live smoke, run and preserve evidence for:

- focused identity, parser, listing-runner, detail-pipeline, baseline, artifact, smoke, and live-service tests;
- the complete Plan 2 smoke-focused selector;
- the complete Plan 1 regression selector;
- Python compilation for all changed modules;
- Ruff on changed Python files;
- artifact strict-replay verification using offline fixtures; and
- a committed-range check proving no migration, ORM model, Compose, or environment-file changes.

Any deterministic failure must be resolved before asking for live authorization.

## Replacement Smoke Gate

The correction does not reuse or erase the failed smoke. Run `fab9d8e1-4c12-4170-a539-c0a6cdbbca93` remains immutable evidence of the invalid strict assumption.

After implementation, deterministic verification, and review:

1. report the exact code and document commits;
2. report all test and static-check evidence;
3. request explicit permission for exactly one replacement Task 8 smoke;
4. capture two new matching baselines immediately before that smoke; and
5. do not begin Task 9 unless the replacement smoke report is accepted.

## Out of Scope

- Database migrations or relational schema changes.
- Rewriting historical staging payloads.
- Deleting or replacing the failed Task 8 artifact.
- Changing production endpoint, `rcdType`, search families, pacing, or unique-ID targets.
- Starting calibration, pilot, census, or Tasks 9-15.
- Automatically performing a replacement live request.

## Acceptance Criteria

The corrective implementation is ready for replacement-smoke review only when:

1. real `jobId`-only search and browse fixtures are accepted with `jobId_fallback` provenance;
2. raw payloads remain unchanged;
3. explicit two-ID inputs and genuine conflicts retain strict behavior;
4. historical `jobId`-only staging rows resolve without a migration or rewrite;
5. detail ownership remains enforced by canonical `jobId` and any explicit encrypted evidence;
6. baseline and artifact outputs distinguish observation from resolution;
7. all focused, Plan 2, and Plan 1 deterministic verification passes;
8. no product data changes during offline work;
9. unrelated dirty-worktree changes remain untouched; and
10. no live OfferToday request or Task 9 work occurs without its separate gate.
