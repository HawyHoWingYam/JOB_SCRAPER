# Unified Job AI Enrichment Contracts

## 1. Scope / Trigger

Use this contract when changing Job-enrichment selection, execution, Skills,
Related Jobs ranking, monitoring, retry, stop, or `/api/ai` endpoints. Company
enrichment is separate.

## 2. Signatures

```python
AIEnrichmentService.enrich_job(job, db) -> dict
JobInsightExtractor.extract(
    title,
    description,
    skill_taxonomy_candidates,
    related_jobs_candidates,
) -> dict
RelatedJobsService.replace_snapshot(...) -> None
RelatedJobsService.recommend_for_job(job_id, limit=5) -> dict
```

```text
GET  /ai/pending/filter-options
POST /ai/pending/preview
POST /ai/runs
POST /ai/runs/{id}/stop
POST /ai/runs/{id}/retry-failed
GET  /api/jobs/{id}/similar
```

Persistence adds one current snapshot per source Job in
`job_related_jobs_snapshots` and zero to five ordered rows in
`job_related_jobs_snapshot_items`. It does not add a second run type.

## 3. Contracts

- One ordinary provider request returns four required sections: non-empty
  `summary`, `experience`, `skills[]`, and `related_jobs[]`.
- Before that request, the recommendation service freezes at most ten real
  candidate Jobs. The result may select zero to five of those exact IDs with
  unique IDs and concise reasons.
- Skill dispositions are `match_existing`, `unresolved`, `generic`, and
  `rejected`. A match must reference an active assignable supplied Skill code.
  Unresolved evidence remains internal and non-searchable; enrichment never
  creates taxonomy nodes.
- The complete response is validated before ORM mutation. The service validates
  again at the transaction seam so an injected extractor cannot bypass the
  contract.
- Job summary, experience, governed Skill projection, internal evidence,
  Related Jobs snapshot, and Manual Job freshness are written in one session
  with one final commit. Any failure rolls back all new outputs.
- Operator-authored Job facts and operator-authored Skill decisions are
  protected from later enrichment.
- Related Jobs reads prefer a usable saved snapshot. Missing, empty, or
  unusable snapshots fall back to deterministic similarity; reads never call
  an LLM.
- Ordinary run states, preview, Start, Stop, failed-only retry, monitoring,
  history, reservation, and evidence eligibility remain the run authority.
- Historical successful Jobs are not automatically reset or queued when this
  contract changes.

## 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Any required response section missing or malformed | Fail item; roll back every new output |
| `match_existing` uses unknown/inactive code | Fail item before mutation |
| Related ID is invented or duplicated | Fail item before mutation |
| More than five Related Jobs or malformed reason | Fail item before mutation |
| Frozen candidate list is empty and result is empty | Successful enrichment with an empty snapshot |
| Saved snapshot has no live target rows | Return deterministic similarity results |
| Manual Job has no description | Exclude as `needs_job_description` before provider call |
| Empty explicit filters without acknowledgement | `422` |
| A run already owns the active slot | `409`, `detail.code=active_run_exists` |

## 5. Good / Base / Bad Cases

- Good: one response maps Python, records an unresolved framework term, writes
  experience, and ranks three supplied candidates in one commit.
- Base: there are no deterministic candidates; enrichment succeeds with an
  empty snapshot and the read side may return no similar Jobs.
- Bad: update `job.ai_summary` before discovering that a Related Job ID was
  invented.
- Bad: issue a second provider request to correct Skills or rank Related Jobs.

## 6. Tests Required

- Assert exactly one `generate_json()` call and at most ten frozen candidates.
- Assert all four Skill dispositions, unknown-code rejection, complete
  experience validation, Related Jobs bounds, duplicate/invented IDs, and zero
  candidate success.
- Assert validation failure leaves the previous summary, experience, Skill
  projection, snapshot, and Manual evidence hash unchanged.
- Assert operator-authored Skills survive replacement.
- Assert snapshot ordering, replacement, deleted targets, empty snapshot
  fallback, and no provider call on reads.
- Assert ordinary preview/create/retry/stop/evidence eligibility behavior and
  public route inventory.

## 7. Wrong vs Correct

### Wrong

```python
job.ai_summary = response.get("summary")
skills = response.get("skills", [])
db.commit()
```

### Correct

```python
validator.validate_result(response, skill_candidates, related_candidates)
job.ai_summary = response["summary"]
skill_writer.replace_job_skills(...)
related_writer.replace_snapshot(...)
db.commit()
```

Required sections never receive permissive defaults before validation.
