# Jev Phase 1B evaluation report

Date: 2026-09-23

Decision: **inconclusive — do not start the Phase 2 recommendation rollout**

## What was evaluated

- 17 versioned controlled cases: 8 development and 9 held-out.
- Separate Skill evidence-support and Candidate recommendation questions.
- English, Traditional Chinese, and mixed-language controlled construction.
- Required, preferred, negated, incidental, absent/insufficient, missing
  Candidate, generic/reject, and option-reordering cases.
- A read-only 100-row real-corpus snapshot from the current PostgreSQL data.
- The existing exact/alias/curation + local string-similarity Candidate
  baseline.
- Six real Jev development smoke attempts across the integration work,
  followed by no further retry after the invalid credential was confirmed.

No user labeling was requested. No Job, Skill, Mention, Candidate, taxonomy, or
production Jev run row was written.

## Artifact integrity and leakage checks

- Controlled JSONL passed exact-schema, stable-ID, canonical hash, unique case,
  and group-disjoint development/held-out validation.
- Option-order stability has one held-out pair with the same semantic options.
- Real-corpus extraction used `SET TRANSACTION READ ONLY`, a 100-row hard cap,
  HTML/contact minimization, canonical description/taxonomy hashes, connected
  company/duplicate grouping, temporal group splitting, and fail-closed
  manifest verification.
- Raw Job payloads and raw descriptions were not stored in the exported model
  artifact. The artifact remains local under `/tmp`, outside the repository.

## Controlled local baseline

| Decision | Eligible | Answered | Correct | Answered correctness | Coverage | Technical failure |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Skill evidence support | 4 | 0 | 0 | not evaluable | 0.000 | 0.000 |
| Candidate recommendation | 5 | 5 | 4 | 0.800 | 1.000 | 0.000 |

Option-reordering stability was `1/1` (`1.000`). The local Candidate baseline
misses the frozen `0.85` correctness gate and has no trustworthy deterministic
evidence-support decision. Its similarity score is a string heuristic, not a
confidence or accuracy estimate.

## Real-corpus availability

| Stratum | Count |
| --- | ---: |
| Total rows | 100 |
| ctgoodjobs | 100 |
| English | 96 |
| Mixed | 4 |
| Traditional Chinese only | 0 |
| Existing Skill match | 81 |
| Unresolved Candidate | 16 |
| Generic | 2 |
| Rejected | 1 |
| Independently reviewed reference | 0 |
| Existing-AI weak reference | 100 |

The refreshed artifact contains 8 connected groups: 54 rows in development and
46 rows in held-out. The uneven row ratio is intentional: connected groups are
never split merely to hit a target percentage. No visible HTML markers remained
after normalization.

The snapshot supports both evidence and Candidate shadow work, but does not
contain the required independently reviewed English and Traditional-Chinese
reference slices. Existing AI projections are correlated weak references and
cannot establish semantic accuracy.

## Real Jev smoke

- Endpoint/model: both the locally documented `rsiai.net` endpoint and the
  current official `api.typesafe.ai/v1/systemone` endpoint; `jev-latest`,
  `jev-1.13.0`, and `jev-preview` were checked.
- Selected cases: one development evidence case.
- Result: `unavailable`, safe error code `http_401`.
- Validated token usage: input `0`, output `0`.
- Confirmed spend: USD `0.00`.
- Conservative uncertain reservations: six real attempts × USD `0.05` = USD
  `0.30`; remaining evaluation allowance USD `9.70`.
- Retry: none after the persistent ledger confirmed the unavailable result.

Two requests happened before the CLI persistent-state correction was complete.
Both were backfilled as uncertain reservations. Later requests verified that
the file-backed ledger survives process restart and cumulatively retains all
six reservations. The official-endpoint and alternate-model controls also
returned `http_401`, so neither endpoint-only nor model-name mismatch is a
sufficient explanation. The token was never persisted in artifacts or source.

## Frozen gates

| Gate | Required | Observed | Result |
| --- | ---: | ---: | --- |
| Controlled evidence answered correctness | >= 0.90 | no Jev answers | not evaluable |
| Controlled recommendation top-1 correctness | >= 0.85 | no Jev answers | not evaluable |
| Technical failure rate | <= 0.05 | 1/1 smoke unavailable | fail/incomplete |
| Actionable coverage | >= 0.60 | 0/1 smoke | fail/incomplete |
| Option-order stability | >= 0.95 | Jev not run | not evaluable |
| Independent bilingual real references | English + zh-Hant | none | missing |

## Decision and next action

This is **inconclusive**, not a quality failure and not permission to roll out.
Phase 2 remains blocked. To resume:

1. replace/activate the invalid API token in `docs/jev.md` or Settings;
2. keep the persistent ledger with USD `0.30` uncertain already reserved;
3. obtain automated independent reviewer references for bounded English and
   Traditional-Chinese real slices without asking the user to label examples;
4. run one successful development smoke, then the bounded controlled/real
   evaluation without changing the frozen gates;
5. proceed to operator-confirmed review UI only if every release gate passes.

## Limitations

- Real-case agreement is not human-validated accuracy.
- No production operator-time measurement exists yet.
- Current real data is source- and language-skewed.
- Provider billing truth is not available; the local allowance ledger is a
  conservative safety mechanism.
