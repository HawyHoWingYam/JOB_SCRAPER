# Skill governance

## Goal

Establish a governed Skill Taxonomy and explicit Skill Mention/Skill Candidate lifecycle in which unresolved evidence remains secondary, only governed Skills drive product intelligence, and every Candidate decision is performed by the local human Taxonomy Operator.

## Background

- The live database currently has no Skill Categories, Technologies, Skills, or Job-Skill links, but has more than 22k review-candidate mentions and more than 5k pending candidates.
- Static taxonomy and curation files contain invalid/missing targets.
- Parent decisions and ADR-0006 prohibit AI-executed Candidate decisions.

## Requirements

- Reconcile and deterministically validate Skill taxonomy, aliases, curation rules, and backfill targets before publishing an immutable governed revision.
- Preserve distinct contracts for Skill, Skill Mention, Skill Candidate, Unreviewed Skill Mention, generic tag, and rejection.
- Restrict mention resolutions and Candidate statuses with database/application invariants.
- Keep deterministic reviewed aliases/rules before Candidate creation; fuzzy/AI recommendation is advisory and cannot decide a Candidate.
- Support operator actions: merge to existing Skill, create governed Skill in a valid Category/Technology, classify generic, or reject.
- Apply each decision transactionally to all affected active mentions, Job-Skill links, Candidate state/counts, metrics, audit, and outbox.
- Expose governed Skills and secondary Unreviewed Skill Mentions separately; ordinary search/recommendation/analytics use governed Skills only.
- Provide candidate queue/recommendation/audit contracts and real response-model tests for Job Detail.
- Remove stale/nondeterministic cache behavior and define deterministic tie/order rules.

## Acceptance Criteria

- [ ] Static Skill seed/aliases/curations have no orphan targets, collisions, or invalid paths.
- [ ] Database contains a governed revision and constrained statuses/resolutions; no free-string transition bypass exists.
- [ ] Deterministic known alias resolves without Candidate; unknown technical evidence creates/updates one Candidate and unreviewed mentions.
- [ ] AI/fuzzy recommendations never execute Candidate actions.
- [ ] Merge/create/generic/reject actions update every affected mention and projection atomically with audit/outbox/idempotency/version checks.
- [ ] Governed Skills alone appear in ordinary search/recommendation/analytics; Job Detail labels secondary evidence `Unreviewed Skill Mentions`.
- [ ] Deleting/retiring Skills cannot leave a silent `match_existing` mention with null Skill.
- [ ] Backend serialization and frontend contract fixtures cover mixed governed/unreviewed/generic/rejected cases.

## Dependencies and scope

- Depends on `07-18-job-intelligence-foundation`.
- Product governance UI and live destructive rebuild are children 6 and 7.
- Generic job taxonomy and company industry rules are out of scope.

## Notes

- Complex child: requires `design.md` and `implement.md` review before start.
