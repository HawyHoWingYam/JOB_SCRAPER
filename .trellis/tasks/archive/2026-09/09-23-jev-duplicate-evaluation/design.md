# Phase 3A duplicate evaluation design

## Boundary

This task owns an offline evaluation module. It reads frozen Job evidence and
embeddings, generates bounded candidate pairs, optionally obtains typed Jev
decisions, and writes local versioned artifacts. It imports no product mutation
service and exposes no HTTP product route. Production Jobs and Related Jobs are
unchanged.

The deep interface is:

```text
export real corpus -> verify manifest
build candidates(snapshot, policy) -> ordered candidate pairs
build System One request(pair, rubric) -> typed request
record observation(receipt) -> immutable JSONL
score(cases, candidates, observations, gates) -> decision report
```

Candidate generation and pair judgment remain distinct so a good judge cannot
hide missed candidates and a high-recall blocker cannot hide false associations.

## Artifact contracts

### Controlled cases

Tracked JSONL rows contain stable case/group IDs, split, language, scenario
tags, two source-preserving Job snapshots, expected pair disposition, label
provenance, evidence hashes, and optional stability group. Exact validation
rejects extra/missing fields, duplicated IDs, group leakage, hash drift, invalid
outcomes, or missing required strata.

### Real corpus

The exporter begins `SET TRANSACTION READ ONLY`, applies an explicit row/pair
cap, and freezes:

- Job UUID and `(source_site, source_job_id)` for both sides;
- company name/identity, title, location, posted/updated timestamps;
- minimized visible description, raw-description hash, normalized fingerprint;
- embedding document hash/dimensions and snapshot time;
- candidate method/rank/scores, source/language strata;
- reference status and provenance.

Artifacts contain exactly a manifest, jobs JSONL, candidate-pairs JSONL, and
policy JSON. Every child file is SHA-256 bound in the manifest. `raw_data`, API
credentials, full headers, and upstream error bodies are forbidden.

## Candidate generation

Use frozen rows, never live mutable ORM objects during scoring.

1. Normalize title/company/location using versioned NFKC/whitespace/case rules.
2. Produce a deterministic lexical baseline from exact/near title, normalized
   company, location, and date proximity.
3. Produce embedding neighbors with a bounded per-Job top-K. Union forward and
   reverse directed neighbors into one canonical `(min_uuid, max_uuid)` pair.
4. Exclude self-pairs, exact same source identity, deleted Jobs, malformed or
   missing evidence. Same-source reposts with distinct source IDs remain
   eligible.
5. Sort by cheap score descending and stable source-qualified IDs; cap before
   any model call.

The existing Related Jobs service is evidence for the pgvector seam, not a
callable duplicate API: its freshness boost and case-insensitive title removal
would erase hard negatives and bias evaluation. Shared low-level cosine/token
helpers may be extracted only if this reduces duplication without changing the
product contract.

## Jev decision

Each pair becomes one `choice` question:

```text
same_vacancy       evidence supports the same concrete opening/repost
different_vacancy  evidence supports distinct roles/openings
insufficient       available evidence cannot safely decide
```

State includes both labeled records in stable left/right order and explicitly
says source text is evidence, not instructions. Options use stable codes and a
held-out stability pair reverses presentation order without changing semantics.
The existing `NativeSystemOneClient`, `JevRunService`, persistent reservations,
and typed receipt statuses are reused. OpenRouter receipt ID/provider and its
USD `usage.cost` are retained; provider cost is rounded up to integer
microdollars and may not exceed the pre-dispatch reservation. No clustering
follows the response.

## Scoring and decision

- Candidate recall@K is computed before judging from all controlled positive
  pairs, including positives omitted by the blocker.
- Pair precision uses answered `same_vacancy` decisions. Pair recall uses all
  eligible controlled positive pairs; missed candidates and non-answers count
  against it.
- False-association rate uses every eligible controlled negative pair.
- Coverage uses every eligible candidate pair. Technical failures and option
  stability retain their full denominators.
- Real output reports agreement only within each reference-provenance/source/
  language stratum. Existing projections or another model are weak references.

`proceed_limited_review` requires all frozen controlled gates, artifact
integrity, budget compliance, and independent English plus Traditional-Chinese
real references. A controlled miss yields `defer`; invalid credentials,
insufficient references, or unevaluable denominators yield `inconclusive`.

## Credential and budget gate

The CLI stores SHA-256 fingerprints of rejected credentials, never the secret.
A paid command compares the supplied key fingerprint before creating a run; a
known rejected fingerprint fails locally with zero reservations and zero HTTP
calls. A new fingerprint still requires explicit paid confirmation, a one-case
development smoke, and a maximum reservation that fits the same persistent
ledger. Seven earlier attempts retain USD 0.35 uncertain; no code path resets
the allowance on restart.

## Compatibility, rollback, and security

The evaluation adds no schema or product API. Rollback deletes local artifacts
and disables Jev; product behavior never changes. Description minimization must
strip HTML/script/style and contact details while hashes preserve change
detection. Reports contain IDs/hashes and aggregate excerpts only, never the
credential or raw provider body.
