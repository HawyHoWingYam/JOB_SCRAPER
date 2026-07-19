# Company industry governance

## Goal

Replace polluted free-text Company Industry with immutable HSIC V2.0-based governed revisions, provenance-bearing zero-to-many Company Industry Assignments, reviewed Source Industry mappings, and human-resolved review items.

## Background

- Current Company industry is nullable free text; exact-string filters expose 69 raw values and at least 1,687 Companies match a Job Source Classification.
- OfferToday has true company-level evidence, while JobsDB/CTgoodjobs paths currently substitute role classifications.
- Parent decisions are ADR-0009 through ADR-0013 and the official standards research.

## Requirements

- Import/validate the complete official five-level HSIC V2.0 hierarchy with bilingual labels, codes, release/source metadata, and immutable content hash.
- Support append-only Company Industry Taxonomy Revisions and explicit revisioned/provenance-bearing ISIC crosswalk edges only.
- Model zero-to-many Company Industry Assignments at the most specific evidence-supported node; derive ancestors and enforce at most one explicit Primary.
- Auto-assign only from a valid authoritative HSIC code or Taxonomy Operator-approved deterministic Source Industry mapping.
- Convert unmapped source labels, manual free text, and AI inference into Company Industry Review Items; AI recommendations never execute.
- Expose Company Industry decision Interfaces only through trusted local governance routes with fixed `actor=local-operator`; ingest and recommendation workers cannot receive those Interfaces.
- Provide operator mapping/review decisions with confirmation, idempotency, optimistic concurrency, audit, and outbox.
- Provide ancestor/subtree filtering by stable IDs, breadcrumbs, complete read contracts, and product-surface APIs.
- Remove all Source Classification → Company Industry writes and define non-destructive capture of legacy/raw evidence.
- Provide polluted-data detection, dry-run mapping/rebuild reports, HSIC seed/reference tests, and PostgreSQL contract tests.

## Acceptance Criteria

- [ ] HSIC revision has all five levels, valid parentage/codes, bilingual labels, official provenance, and deterministic content hash.
- [ ] Re-importing identical release is deterministic; changed content requires a new revision.
- [ ] Assignment targets the most-specific supported node; ancestors are not duplicated and ancestor filters include descendants.
- [ ] At most one active Primary exists per Company, and Primary always has authoritative/operator basis.
- [ ] Only valid code/reviewed mapping auto-assigns; manual/AI/unmapped evidence creates review item without assignment.
- [ ] Review/mapping decisions are versioned, idempotent, audited, and cannot create HSIC nodes.
- [ ] Every Company Industry decision records `local-operator`, and ingest/recommendation worker dependencies cannot reach decision Interfaces.
- [ ] No ingest path writes a Job Source Classification into Company Industry.
- [ ] Legacy audit/dry-run identifies polluted, recoverable, unknown, and conflicting Companies without guessing.

## Dependencies and scope

- Depends on `07-18-job-intelligence-foundation`.
- Official HSIC source terms/redistribution requirements must be satisfied before seeding.
- Product UI and destructive live cutover are children 6 and 7.

## Notes

- Complex child: requires `design.md` and `implement.md` review before start.
