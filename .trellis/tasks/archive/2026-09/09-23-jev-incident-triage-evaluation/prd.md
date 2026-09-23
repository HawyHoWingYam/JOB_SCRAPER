# Jev phase 5: operational incident triage evaluation

## Goal

Evaluate read-only clustering and prioritization of repeated crawl incidents so
operators inspect clusters rather than duplicate events. A historical run with
143 identical ingest failures is the concrete bottleneck evidence.

## Requirements

- Cluster by source, phase, deterministic class/code/stage, and secret-safe
  normalized symptom; preserve every event reference and count.
- Typed advisory dispositions only: known manual recovery, transient/
  infrastructure, source/parser regression, investigate now, insufficient.
- Never call retry/resume/cancel/reset/dismiss, change status/severity, delete
  logs, or write CrawlJob/CrawlJobEvent state.
- Metrics: event compression, actionable-cluster recall, false-safe rate,
  stability, coverage, latency/cost. Frozen gates: actionable recall >= .95,
  false-safe <= .02, coverage >= .70, stability >= .95, compression >= 2x.
- Evidence selection, refresh, and provider routing remain deferred until their
  measurement prerequisites exist.
- No real Jev request while the HTTP 520 reservation remains ambiguous.

## Acceptance criteria

- [x] Strict controlled incidents, safe normalization, deterministic clustering
  and full-denominator metrics pass.
- [x] Deterministic fallback proves zero operational actions. Real/loopback model
  prioritization is deferred until operator outcome labels exist.
- [x] Result/spec/Issue and full quality evidence are recorded.
