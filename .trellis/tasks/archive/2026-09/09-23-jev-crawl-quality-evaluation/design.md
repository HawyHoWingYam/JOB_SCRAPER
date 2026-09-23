# Phase 3B crawl-content quality evaluation design

## Boundary

This task is an offline evaluator. It accepts immutable minimized content
snapshots, runs deterministic classifiers first, optionally sends uncertain
cases to the existing budgeted Jev adapter, and produces local artifacts and a
decision report. It imports no repair, dispatch, resume, reset, browser-helper,
or product mutation service.

```text
controlled/real snapshot
  -> deterministic disposition
  -> bounded uncertain candidate set
  -> typed Jev quality decision
  -> immutable receipt
  -> full-denominator metrics/report
```

## Controlled contract

Each case freezes case/group/split/source/language, page stage, transport/parser
state, a minimized excerpt, evidence hash, deterministic classification, the
expected usability disposition, expected problem kind, explicit label
provenance, and optional stability group. Exact schema rejects extra fields,
hash drift, duplicate IDs, and group leakage.

Challenge/login/error examples contain only synthetic marker text, never real
cookies, headers, account state, upstream response bodies, or credentials.

## Deterministic-first candidate seam

Existing high-confidence classifications remain authoritative routing evidence:

- WAF/IP-block/manual-action states are `deterministic_problem` and need no Jev.
- CT terminal-unavailable state and OfferToday terminal response are
  `deterministic_problem` and need no Jev.
- Explicit transport/parser failure is `technical_failure`, not content truth.
- Structurally successful detail content is eligible for cheap rules and Jev.
- Missing evidence is `insufficient` and never a valid negative.

The baseline uses normalized visible-text length, description-to-template ratio,
and known markers only. It must not read hidden auth material or infer Job truth
from generic body text where source contracts forbid it.

## Jev questions

The first choice is `usable_job_detail|quality_problem|insufficient`. A second
choice records the problem kind from a fixed enumeration. State labels source
content as untrusted evidence, freezes source/stage/status context, and avoids
including full raw pages. Every request reuses `JevRunService` reservations and
the OpenRouter-compatible `NativeSystemOneClient`.

## Real snapshot

The PostgreSQL exporter begins `SET TRANSACTION READ ONLY`, hard-caps rows, and
selects existing listing/detail snapshots without changing their state. It emits
only normalized source identity/status metadata, safe bounded excerpts, content
hashes, candidate/baseline disposition, language/source strata, and provenance.
Files are manifest-bound and exact-set verified. Raw payloads, headers, cookies,
contact details, URLs with query secrets, and challenge bodies are excluded.

## Scoring

Candidate recall is scored before Jev judging. Precision uses answered
`quality_problem` flags; recall retains missed candidates and non-answers in the
denominator. False-flag rate includes every valid detail. Problem-kind accuracy
is separate from binary usability. `insufficient`, unavailable, invalid, and
budget-skipped remain visible in coverage/error denominators.

Passing controlled gates without independent bilingual real references yields
`inconclusive`; a controlled miss yields `defer`; only all gates plus trusted
real references can yield `proceed_limited_review`.

## Compatibility and rollback

No schema/product/API/UI change is introduced. Rollback deletes local artifacts
and disables Jev. Existing crawl status machines, repair services, task-board
projections, and Job data are unchanged.
