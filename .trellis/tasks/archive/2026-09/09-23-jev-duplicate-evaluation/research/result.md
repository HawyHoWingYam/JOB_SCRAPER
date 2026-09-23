# Phase 3A Jev duplicate evaluation result

Decision: **inconclusive**.

All frozen controlled gates passed, but independent human-reviewed English and
Traditional-Chinese real-corpus references are unavailable. Per the predeclared
rule, controlled correctness cannot authorize product associations by itself.

## Controlled result

- 16/16 requests returned typed `answered` receipts.
- Candidate recall@10: 8/8 unique positive pairs (`1.0`).
- Pair precision: `1.0`.
- Positive judgment recall: 9/9 (`1.0`); this includes both presentation orders
  of the stability pair, while candidate recall counts that pair once.
- False-association rate: 0/5 (`0.0`).
- Actionable coverage: 14/16 (`0.875`); two explicit `insufficient` outcomes
  correctly remain non-actions.
- Technical failure rate: 0/16 (`0.0`).
- Option-order stability: 1/1 (`1.0`).

## Execution and cost

- 8,889 input tokens and 800 output tokens.
- p50/p95 latency: 392/739 ms.
- Confirmed controlled-run cost: 382 microdollars (USD 0.000382).
- A preceding OpenRouter contract smoke cost 20 microdollars.
- Persistent ledger after the run: 402 spent, 350,000 uncertain reserved, and
  9,649,598 remaining from the USD 10 allowance.

## Real-corpus replay

Two independent PostgreSQL read-only exports each selected 100 Jobs and capped
the union at 500 candidate pairs. `jobs.jsonl`, `candidate-pairs.jsonl`, and
`policy.json` were byte-for-byte deterministic across both exports and passed
manifest verification. The current pure-Python all-pairs implementation took
roughly 40 seconds per 100-Job export in the backend container and should be
optimized or replaced with database-side nearest-neighbor retrieval before a
large production snapshot.

No product Job, Company, embedding, taxonomy, recommendation, or duplicate
association record was written or changed.
