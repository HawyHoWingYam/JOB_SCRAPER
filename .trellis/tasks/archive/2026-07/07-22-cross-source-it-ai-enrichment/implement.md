# Implementation plan: IT Enrichment scoped governance

This is an inline implementation plan. Do not start Phase 2 until the user
approves the PRD, design, and this checklist.

## Phase 1 — contract and backend seam

- [ ] Add a public `PendingSelectionReport` interface to the existing
      `EnrichmentRunService` (or extract one deep selection module if the
      current implementation cannot expose it cleanly). Make preview delegate
      to it and cover selected/effective/excluded IDs and grouped reasons.
- [ ] Add request/response schemas for scoped provenance inspection and apply.
- [ ] Add trusted-local Job Intelligence routes that resolve the current active
      Source Catalog revision, inspect only the current bounded pending slice,
      and revalidate the report before apply.
- [ ] Keep `SourceCatalogProvenanceRepair` as the only write implementation;
      preserve fingerprint, active-pointer, coverage, NULL-only, batch, and
      outbox fences.
- [ ] Add optional page-mode parameters to the three governance queue query
      modules/routes while preserving opaque cursor compatibility.

## Phase 2 — route scope and AI Enrichment handoff

- [ ] Extend governance hash parsing/serialization with source-qualified
      classifications, dates, pending limit, reason, and page.
- [ ] Update AI exclusion details to preserve the scope context and use a
      reason-specific link label; keep current preview counts truthful.
- [ ] Add source-parent descendant summary text without changing the existing
      source-qualified filter semantics.
- [ ] Ensure scoped governance queue requests carry the exact scope and that
      clearing scope returns to the unfiltered queue.

## Phase 3 — queue and detail redesign

- [ ] Change the shared queue default from 50 to 10 and add compact rows,
      previous/next controls, numeric page input, page bounds, loading state,
      and empty scoped state.
- [ ] Keep the selected item detail column aligned and visible on desktop;
      implement narrow-width queue/detail stacking and explicit back behavior.
- [ ] Add a scoped context banner and a first-use explanation of Job
      Intelligence Governance.
- [ ] Refactor evidence rendering so technical evidence and audit details are
      collapsed by default.
- [ ] Add reason-specific `ProvenanceRepairPanel`; hide generic canonical
      decisions for source provenance/path-missing reasons while retaining them
      for canonical classifier reasons.
- [ ] Implement inspect → confirm → apply → partial-result → return-to-AI flow.

## Phase 4 — tests and frontend verification

- [ ] Update backend tests for selection/review query page mode, scoped repair
      inspect/apply, drift/blocker responses, partial repair, and idempotency.
- [ ] Update frontend API, route, queue, AI Enrichment, and governance page
      tests for scope, page input, reason-specific detail, and partial results.
- [ ] Run focused frontend tests and lint/build.
- [ ] Start the frontend against the local app/API and perform browser-level
      verification at desktop and narrow widths. Verify the exact path:
      choose one source IT parent → preview exclusion → scoped governance link
      → page jump → select item → inspect → confirm or blocked report → return
      to AI → refreshed preview.
- [ ] Capture any visual/layout regression and fix before the quality gate.

## Risk points and rollback

- Risk: page-mode offsets can shift when decisions resolve items. Keep item
  details independently loadable, show live counts, preserve cursor mode, and
  treat page mode as an operator convenience rather than an audit cursor.
- Risk: a stale AI preview scope can change before repair. Re-resolve the scope
  and re-inspect inside the apply route; reject drift rather than widening the
  write set.
- Risk: the frontend accidentally offers canonical assignment for a provenance
  blocker. Add a reason-specific action test and keep the adapter decision
  policy centralized.
- Risk: long technical evidence reintroduces horizontal overflow. Test long
  hashes/IDs and use bounded, scrollable evidence blocks.
- Rollback: frontend scope/detail changes can be reverted independently from
  additive backend routes; no data write is performed unless the explicit apply
  flow is confirmed.

## Validation commands

From `frontend/`:

```bash
npm test
npm run lint
npm run build
```

From the repository root, run the focused backend tests using the project's
normal backend test environment, plus the relevant API/service tests for
enrichment selection, canonical governance, and source attribute provenance
repair. The final session must also include a browser-level frontend check,
not only unit tests.
