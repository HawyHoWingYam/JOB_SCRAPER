# Excluded AI Enrichment handoff reproduction

## Reproduction

On 2026-07-25, two direct read-only local API calls against the screenshot scope
were repeated:

- Source `jobsdb`
- Source Classification `jobsdb:6281`
- Posted dates `2000-07-01` through `2026-07-22`
- Pending limit `4000`
- Reason `source_catalog_provenance_missing`

Result:

```text
matching=3131
effective=0
excluded=3131
governance_total=0
governance_items=0
```

## Cause

- `frontend/src/components/ai/AIEnrichmentPage.jsx:46-66,1037-1044` correctly
  carries the bounded scope to Governance.
- `backend/app/services/enrichment_run_service.py:399-447` counts read-only
  preflight exclusions even when no review row exists.
- `backend/app/api/job_intelligence.py:544-608` resolves scoped Governance IDs
  only from active review rows and returns an explicit empty page otherwise.
- `frontend/src/components/jobIntelligence/ProvenanceRepairPanel.jsx:29-48`
  requires a selected review item's reasons before rendering repair controls.

The original UI fix would have promoted batch provenance repair above the empty
queue. The approved redesign instead removes Source Catalog provenance/version
as a concept and replaces the entire Governance queue with automation-first
batch processing.
