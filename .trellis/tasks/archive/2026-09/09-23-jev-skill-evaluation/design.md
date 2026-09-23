# Jev Phase 1B evaluation design

## Scope and authority

Phase 1B is an offline, read-only evaluation of two separate decisions:

1. **Skill evidence support** — whether a frozen source passage says a Skill is
   required, preferred, contradicted, incidental, absent, or insufficient.
2. **Candidate recommendation** — whether a frozen unresolved Candidate should
   map to one of a bounded set of existing governed Skills, remain unresolved,
   or be treated as generic/rejected.

The evaluation never writes Jobs, Skill assignments, Mentions, Candidates, or
taxonomy records. It does not invoke production enrichment or decision routes.
It emits versioned local artifacts and a deterministic report. Existing
projection labels and model agreement are weak references, not human truth.

## Artifact contracts

Tracked controlled fixtures use JSONL with one exact schema per line:

```text
case_id, group_id, split, decision_kind, language, source,
scenario_tags, state, questions, expected, label_provenance,
evidence_refs, evidence_sha256, taxonomy_snapshot_sha256
```

`split` is declared (`development` or `held_out`) and validation fails if a
group occurs in both. Evidence/candidate variants from one underlying Job,
company, duplicate description, or source identity share a `group_id`.
Controlled labels are `explicit_construction_v1`; bilingual cases are written
so their expected answer follows directly from the text rather than another
model's judgment.

Real-corpus export uses a read-only PostgreSQL transaction and writes a local
manifest plus JSONL. It includes stable Job/source identity, capture/update
times, language/source/ambiguity strata, a versioned raw-description hash,
minimal normalized evidence, current mention/assignment provenance, frozen
taxonomy snapshot hash, group/split, and reference provenance/status. Raw
`jobs.raw_data` is excluded. Existing AI projections are `weak_reference`; a
missing independent judgment is `unresolved`.

Evaluation observations bind `run_id`, manifest hash, case ID, rubric version,
model identity, status, typed answer, usage, latency, reservation/cost, and
error code. Reports verify parent hashes before scoring.

## Baselines and Jev questions

- Evidence baseline: current Job insight extraction output when available,
  evaluated only as a weak model reference; absence is unresolved. It is not
  rerun through the mutating enrichment service.
- Recommendation baseline A: exact active Skill label/alias and local curation
  resolution, implemented as a pure snapshot adapter.
- Recommendation baseline B: current local similarity ranking, moved/reused as
  a pure function and labelled heuristic, not confidence.
- Jev evidence question is a bounded `choice` over
  `required|preferred|contradicted|incidental|absent|insufficient`.
- Jev recommendation is a bounded `choice` whose options are stable taxonomy
  codes plus `keep_candidate|generic|reject|insufficient`. Option order is
  deterministically permuted for stability cases and preserved in receipts.

No response mutates product data. Unsupported or ambiguous answers are
`abstained`; transport/HTTP failure is `unavailable`; schema/option mismatch is
`invalid`.

## Frozen scoring policy and gates

These numeric gates are frozen before any held-out Jev scoring:

| Measure | Gate |
| --- | ---: |
| Controlled evidence answered correctness | >= 0.90 |
| Controlled recommendation top-1 correctness | >= 0.85 |
| Technical failure rate | <= 0.05 |
| Actionable coverage over every eligible case | >= 0.60 |
| Option-reordering stability | >= 0.95 |

Correctness denominators include answered wrong decisions. Coverage denominator
includes every eligible controlled case; abstained, unavailable, invalid, and
unresolved are never dropped. A gate is `not_evaluable` rather than pass when
its denominator is zero. Development data may explain errors but cannot change
these held-out gates in this task.

Real-corpus output reports agreement by reference provenance and language/source
stratum, actionable coverage, unresolved/error denominators, latency, tokens,
reserved/spent allowance, and correlated-reviewer limitations. It never calls
agreement accuracy. Operator time remains unmeasured until Phase 2 use.

## Execution and budget

The CLI has explicit `validate`, `export-real`, `plan`, `run`, and `report`
commands. `validate/plan/report` are offline and free. `export-real` requires a
PostgreSQL URL whose transaction is forced read-only. `run` requires an
explicit confirmation flag, valid Jev settings, a conservative per-request
maximum, and the Phase 1A cumulative allowance. A run cannot silently refill
USD 10. Each retry is a new reservation and observation.

The first live smoke is one development case. Only a successful, typed smoke
permits a larger bounded run. Invalid credentials, unavailable pricing, budget
exhaustion, or an uncertain charge stops dispatch and yields an inconclusive
report. The local bearer credential is read only at execution and never written
to artifacts.

## Proceed / defer decision

`proceed_limited_review` requires every controlled held-out gate to pass, no
integrity violation, real-corpus results to contain at least one independently
reviewed case per declared language slice, and spend within allowance.
Otherwise the result is `defer`; missing/invalid credentials or insufficient
independent real references yields `inconclusive`, not defer-as-failure.

Even a proceed result authorizes only Phase 2's operator-confirmed suggestion
surface. It never authorizes automatic Skill/fact writes.

## Rollback

Delete evaluation artifacts and disable Jev. No production facts require
rollback because this phase is read-only. Existing deterministic resolution and
review UI remain the baseline.
