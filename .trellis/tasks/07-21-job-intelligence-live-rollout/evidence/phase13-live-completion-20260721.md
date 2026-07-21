# Job Intelligence Phase 13 live completion evidence

## Decision and release identity

- Fresh writer-reopen approval: user replied `批准` immediately after the
  explicit Phase 13 approval prompt on 2026-07-21.
- Application commit: `0333c2912e61e5a0bcea93d07cfafe5766ef7d72`.
- Backend image digest:
  `sha256:1662a7cec29aba2244c62cc7d0febaee214c6d88791366e172a9edd400707372`.
- Effective Compose SHA-256:
  `91cfc39bed69a48ed0bcb2cf976eba0b477b86170aceb08b74276e7d4afae64a`.
- Manifest hash:
  `e7a3f38bac9c40d3d455e04a0c4560f8ac0affe48b107b67f5025d2576f0257d`.
- Checkpoint directory: `runtime/job-intelligence-cutover/20260721T120446Z`.

## Phase 13 result

`13-reopen_writers.json` completed at `2026-07-21T13:28:01.402941Z`
with output hash
`c6fc4be5efca2966911806fe152e7a3543ed9438ca5adfd5fddbe36a87f206fd`.

Persistent writer evidence was `running` for API, detail/listing, embedding,
enrichment, ingest, outbox publisher, scheduler, and Scrapyd. The intentionally
transient manual-action helper and Source Catalog admin remained `stopped`.
There were no missing or `unknown` writers.

## Post-reopen target-environment smoke

- `GET /health`: `healthy`, service `backend-api`.
- Governance summary: three areas, trusted-local warning present, 17,596 Jobs
  represented in coverage.
- Lexical Job search: HTTP success, total `4,972`, one requested result returned.
- Semantic Job search through `retrieval-api`: HTTP success, total `17,596`, one
  requested result returned.
- Job recommendations through `recommendation-api`: five results returned.
- Backend API, Scrapyd, retrieval API, and recommendation API all reported
  healthy; scheduler, ingest, enrichment, and embedding containers were running.
- Outbox progressed without deletion or manual status rewriting: the first
  post-reopen observation was `pending=63,042`, `published=11,410`; the final
  smoke observation was `pending=27,369`, `published=47,083`, and the closing
  monitoring observation reached `pending=0`, `published=74,452`. The total
  remained `74,452`, proving normal publisher progress without deletion.

## Runtime packaging correction

The first target-environment retrieval start exposed an eager-import defect:
`app.api.__init__` loaded production crawl routes inside the trimmed ML image.
The fix lazily exposes the production root router and keeps sidecar imports
isolated.

- Runtime hotfix commit: `366bf3b8 fix: isolate retrieval API imports`.
- OpenAPI regression correction: `9063508f test: accept versioned board OpenAPI union`.
- Retrieval image ID:
  `sha256:5498861d4ca09373a316aeb3b21ccc8d0598d2cd533f22a94ba0144534cfd23d`.
- Regression evidence: retrieval entrypoint container import passed; retrieval
  container health passed; focused Ruff and compileall passed; focused backend
  tests finished `17 passed`.

## Rollback retention and decision

- Verified backup ID: `ji-live-20260721T120446Z`.
- Backup SHA-256:
  `1fa678f3deb93e572015f0aee8c8c5338fb835cb1a6361a57ddc6e77d989ec70`.
- Verified restore database: `jobsdb_20260721t120446_cutover_restore`.
- Rollback plan: `runtime/job-intelligence-cutover/20260721T120446Z/rollback-plan.json`.
- Monitoring/rollback owner: `local-operator` for the retained rollback window.

Decision: **GO / completed**. Phase 1 through Phase 13, target-environment
API/search/worker smoke, outbox recovery, and rollback retention all have direct
evidence for the exact manifest chain.
