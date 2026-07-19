# Company industry governance design

## Module Interfaces

```text
CompanyIndustry.publish_hsic(manifest) -> RevisionRef
CompanyIndustry.ingest_evidence(company_id, evidence) -> IndustryOutcome
CompanyIndustry.get_company_state(company_id) -> CompanyIndustryView
CompanyIndustry.list_review_items(query) -> Page[ReviewItem]
CompanyIndustry.decide(DecisionCommand) -> DecisionResult
CompanyIndustry.filter_descendants(node_ids) -> set[node_id]
CompanyIndustry.rebuild(company_ids, dry_run=true) -> RebuildReport
```

The Module owns HSIC hierarchy, mappings, assignments, review policy, and ancestor semantics. Ingest callers cannot write `Company.industry` or assignment rows directly. `decide` is a trusted local-operator Interface and is never injected into ingest or recommendation workers.

## HSIC revision import

- Import official HSIC V2.0 Section/Division/Group/Class/Sub-class codes, English/Chinese labels, official source URL/release, and explanatory metadata permitted by source terms.
- Normalize into a manifest and validate level/code format, one parent except root, no cycles, bilingual labels, uniqueness, full reachability, and deterministic content hash.
- Publish append-only through foundation. Identical content is idempotent; changed official content requires a new release/revision.
- Never silently overwrite labels/codes in a published revision.

## Persistence

- `company_industry_taxonomy_nodes`: revision FK, code, parent FK, level enum, labels, validity/source metadata; unique revision/code.
- `company_industry_crosswalk_edges`: explicit from/to standard+release+code, cardinality/method/provenance/confidence; no inferred Rev.4→Rev.5 edge.
- `source_industry_mappings`: Source, raw code/normalized label key, target node/revision, status/version, operator audit reference. Unique active Source/key.
- `company_industry_assignments`: Company/node unique pair, provenance, is_primary, primary_basis enum (`authoritative_source`, `operator`), version/timestamps. Partial unique active Primary per Company.
- `company_industry_review_items`: Company, raw evidence/provenance, reason/status/version, advisory recommendations, decision reference. De-duplicate active equivalent evidence.

Published nodes and historical mappings are retired/superseded, not cascade-deleted. Company deletion may cascade current assignments/items while audit retains subject snapshots.

## Evidence and auto-assignment policy

Accepted company-owned evidence includes an explicit company industry code/label from Source metadata, preserved manual input, or company-level AI evidence. Job Source Classification is rejected before this Module.

Automatic assignment occurs only when:

1. evidence contains a valid HSIC code in the active revision; or
2. Source code/label matches an active operator-approved deterministic mapping.

All other evidence creates/updates a review item. AI recommendations never write mapping/assignment/Primary.

## Most-specific and Primary semantics

- Assignment targets the most specific node supported by evidence; Module validates evidence path/claim.
- Ancestors are derived by recursive hierarchy queries and are not assignment rows.
- Multiple non-redundant assignments are allowed. If one assignment is ancestor of another with the same evidence, retain only the descendant; conflicting evidence remains separately visible.
- Primary requires explicit authoritative-source primary evidence or an operator action. First/order/AI never sets it.

## Operator decisions

Review actions:

- assign existing HSIC node;
- approve reusable Source Industry mapping and assign;
- mark insufficient/not-company-industry evidence.

Mapping and assignment changes use foundation confirmation/version/idempotency/audit/outbox protocol. No decision creates HSIC nodes.

## API and filtering

- Revision/tree endpoint supports lazy child loading, bilingual labels, breadcrumb, code, level, and revision.
- Company view returns all assignments, Primary metadata, provenance summary, and review refs.
- Ancestor filter expands descendants within one pinned revision and matches any assignment.
- Review queue filters by Source, raw label/code, age, reason, recommendation, company, and status.
- Mapping registry and audit endpoints expose operator-approved mappings and supersession history.

## Legacy evidence and rebuild

- Stop every Source Classification → Company Industry mapper write.
- Extract true OfferToday company evidence from preserved raw data.
- Treat JobsDB/CTgoodjobs legacy `industry` equal to Job Source Classification as polluted, not mapping evidence.
- Manual/free-text and uncertain metadata create review items.
- Dry-run reports auto-mappable, review, polluted, conflicting, Primary evidence, and no-evidence Companies.

## Testing

- Validate complete HSIC manifest and representative five-level breadcrumbs.
- PostgreSQL tests cover recursion, multiple assignments, ancestor de-duplication, partial unique Primary, mapping uniqueness, version/idempotency, and audit/outbox atomicity.
- Contract tests prove no job classification reaches the Module as company evidence.
