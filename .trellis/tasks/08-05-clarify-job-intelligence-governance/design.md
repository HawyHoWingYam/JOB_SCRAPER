# Technical design: Skill governance and Company Industry removal

## Boundaries

The in-scope product boundary is Job Skill normalization and review. Company Industry is removed end-to-end. Shared classification code may remain only when it serves Skill review or other active domains; no shared abstraction may retain a Company Industry route merely for symmetry.

## Data flow

```text
bundled skill_taxonomy.json
        ↓ idempotent synchronize
current taxonomy nodes + aliases
        ↓ readiness gate
AI Skill extraction → Skill Mention
        ├─ exact name/alias → canonical assignment
        ├─ explicit generic/reject rule → governed disposition + evidence
        └─ unknown repeated term → Skill Candidate
                                  ↓ threshold from Settings (current 10)
                           Skill review queue
                                  ↓ operator decision
                      assignment / generic / rejected / pending
```

`CurrentSkillEnrichment` remains responsible for extraction-result normalization and evidence persistence. A new synchronization/reprojection seam should call existing taxonomy store operations and preserve active mention provenance. Candidate decisions must be transactional: the operator decision, mention resolution, Candidate state, and Job assignment projection either commit together or not at all.

## Taxonomy initialization and reprojection

- Transform the bundled manifest through the existing taxonomy transform and synchronize it through `CurrentTaxonomyStore.synchronize`.
- Make synchronization available as an explicit bootstrap/upgrade operation and invoke readiness checks before Skill enrichment and review selection. Avoid silently treating an empty table as a valid taxonomy.
- Reproject active Skill Mentions in bounded, repeatable work. Exact names and aliases become assignments; generic/rejected dispositions remain evidence; unresolved terms remain Candidates.
- Never overwrite an operator-confirmed assignment merely because a later manifest sync omits or relabels a node. The implementation must define a safe precedence rule and record conflicts.

## Skill review workflow

- Replace the operator-facing classification batch controls with a list endpoint for unresolved Candidates whose `distinct_job_count` meets the persisted threshold.
- Show Candidate label, occurrence/job counts, raw variants, suggested existing Category → Technology path, and representative evidence.
- Decisions are explicit: match an existing Skill, create a new Skill under an existing parent path, mark generic, reject, or leave pending.
- LLM output is advisory. The API must reject a create decision without an authenticated/explicit operator action and must validate active parent/technology identity before writing.
- After commit, reproject all related active mentions and jobs idempotently. A Candidate that no longer qualifies or has already been resolved disappears from the ready list.
- Keep low-frequency Candidates queryable but out of the primary ready queue.

## Job Detail and search contracts

- Product read models expose governed Skill assignments as `skills` and unresolved evidence separately as candidate mentions with explicit pending status.
- Job filters and facets use assignments only. Candidate, generic, and rejected evidence must never enter canonical Skill filtering.
- Job Detail renders pending evidence collapsed and labels it as unreviewed; taxonomy-unavailable state is distinct from “no technical skills extracted.”

## Company Industry deletion

- Remove Company Industry routes, serializers, adapters, UI tabs/components, search filter/facet wiring, product-read-model fields, and domain-specific tests/spec entries.
- This repository has no in-place migration runtime. Remove Company Industry tables and data through the documented destructive sandbox cutover: stop services, export only retained evidence, clear the confirmed sandbox, deploy the complete new code/schema, bootstrap, import, and verify.
- The retained export must omit Company Industry assignments, mappings, taxonomy, aliases, candidates/review records, and related references. Verify no active route, query, or frontend contract references the deleted domain before cutover.
- Do not delete Skill taxonomy tables, Skill Mention/Candidate tables, or generic classification utilities still used by Skills.

## Compatibility and rollback

- Keep the persisted threshold field/API key for compatibility; change its current/default value and UI label only after tests cover the migration.
- The destructive sandbox cutover is the rollback boundary: restore the documented database backup/export to recover deleted data. Code rollback alone cannot restore rows.
- Taxonomy synchronization and reprojection must be restartable and safe to rerun. Record progress or use bounded queries so interruption does not leave partially resolved mentions without a repeatable recovery path.

## Trade-offs

- Operator confirmation for new Skills reduces taxonomy drift and duplicate concepts at the cost of a small review queue.
- Removing Company Industry simplifies the current product and permanently gives up its existing search/filter capability unless restored from backup and reimplemented later.
- Retaining the threshold setting and shared Skill primitives avoids a broad configuration migration while changing the operator mental model.
