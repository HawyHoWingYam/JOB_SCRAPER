# Job intelligence product surfaces design

## Surface architecture

Add one route-level `JobIntelligenceGovernancePage` with three peer routes/tabs:

```text
/job-intelligence/job-taxonomy
/job-intelligence/skill-candidates
/job-intelligence/company-industries
```

Each area composes the same deep UI Modules:

- `GovernanceQueue`: pagination/filter/selection/conflict refresh.
- `EvidencePanel`: domain-provided typed evidence renderer.
- `RecommendationPanel`: advisory choices only.
- `DecisionDialog`: action/target/affected count/consequences/confirmation.
- `AuditTimeline`: append-only history.

The shared Interface contains queue mechanics, not domain action rules. Domain adapters provide typed actions/labels and call the reviewed backend endpoints.

## Data access seam

Create a small `jobIntelligenceApi` adapter with explicit methods for summary, three queues, detail/audit reads, tree/options, and decisions. It returns normalized response objects but does not infer taxonomy, mapping, Primary, or transition validity.

Decision requests always send `expected_version`, generated idempotency key, `confirmed=true`, and optional note/target. No token/login state exists. Route placement is a UX boundary rather than authorization; the UI displays the trusted-local warning, and deployment guidance prohibits exposing the unprotected decision endpoints to an untrusted network. A 409 stale-version response closes/disables the stale confirmation, refreshes the item, and explains what changed.

Backend-generated contract fixtures are imported into frontend tests. UI-local minimal objects may be used only for presentation helpers, not route/response contract tests.

## Governance page layout

- Header: purpose, local-operator/trusted-local notice, total pending/oldest age, refresh state.
- Primary navigation: three areas with pending badges.
- Desktop: queue list/table left, selected evidence/decision workspace right.
- Narrow width: queue then detail stack with explicit back navigation; no horizontal data loss.
- URL contains area, item ID, and filters needed for stable deep links.
- Empty/error/partial states are scoped per area so one failed queue does not blank all governance.

### Job Taxonomy Review

Show Job/source evidence, all Source Classification Paths, current Unassigned reason, allowed-slice/recommendations, model/mapping provenance, and actions to assign an existing Job Subcategory or mark insufficient evidence. Taxonomy tree selection uses stable IDs and breadcrumbs.

### Skill Candidates

Show normalized/raw variants, occurrence/affected Job counts, representative evidence, Source/Canonical Job Taxonomy context, recommendations, and actions merge/create/generic/reject. Candidate terms never use governed Skill styling before decision.

### Company Industries

Provide HSIC revision/tree browser, Source Industry mapping registry, Company Industry Review queue, affected Company/Job counts, evidence/provenance, recommendations, assignment/Primary action, and audit. Ancestor selection explains subtree behavior.

## Read-only surface changes

### Job Browser

- Rename Job Type → Employment Type and make it multi-select.
- Canonical Job Taxonomy uses hierarchical stable-ID multi-select.
- Company Industry uses HSIC hierarchy and descendant semantics.
- Source filters use source-qualified path identities rather than names.
- Cards display accepted canonical breadcrumb and Employment Types; no fallback appears as accepted.

### Job Detail

- Role evidence: all Source Classification Paths and Employment Types.
- Canonical section: accepted assignment with provenance summary or explicit Unassigned/review link.
- Company: Primary + N Company Industries with breadcrumbs and read-only governance link.
- Skills: governed tags; separate secondary `Unreviewed Skill Mentions` with review link.

### Add Job / Companies / AI Enrichment / Dashboard

- Manual free text becomes evidence/review or a governed selector per backend contract.
- Companies display governed Industry assignments only.
- AI Enrichment Source filters key by qualified identity and show review/exclusion links, no decision controls.
- Dashboard separates governed coverage, Unassigned/review backlog, and Unknown counts; retired labels disappear.

## Interaction and accessibility

- All controls have visible labels; status never relies on color alone.
- Queue selection/focus is preserved on refresh where item remains.
- Dialog focus trap, Escape/cancel, destructive wording, affected-count announcement, and post-decision focus return are required.
- Live regions announce loading, conflict, decision success/failure, and count changes without excessive chatter.
- Keyboard navigation covers tabs, queue rows, tree, filters, and dialogs.

## Visual direction

Reuse the product's dark theme but use calmer governance styling: strong information hierarchy, dense evidence only where needed, limited glow, and color reserved for status/risk/action. Do not copy the control-board wizard visual implementation into this separate product area.

## Testing

- Contract tests render every backend fixture and reject missing required fields.
- Component tests cover loading/empty/error/Unknown/stale conflict and each decision confirmation.
- Integration tests prove decisions exist only in governance routes and read-only deep links elsewhere.
- Manual browser QA covers desktop/narrow widths, keyboard/focus, long bilingual HSIC labels, many paths/industries, and large affected counts.
