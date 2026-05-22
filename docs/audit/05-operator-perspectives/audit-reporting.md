# Operator Perspective: Audit Reporting

## Current Responsibilities

This perspective covers documentation, health reports, governance reports, migration notes, and future audit trails for operator actions.

## Current Implementation Map

- Audit docs: `docs/audit/*`
- Health report: `backend/scripts/operator_health_report.py`
- Governance reports: `backend/scripts/govern_skill_history.py`, `govern_skill_review_candidates.py`, `govern_job_taxonomy.py`
- Runtime events: `backend/app/models/crawl_job.py`, `event_outbox.py`

## Data and Control Flow

Current reporting is a mix of Markdown documentation, CLI script output, database event rows, and Redis stream data. Crawl job events provide durable operational history for crawl-specific workflows.

## Tests and Coverage

- `backend/tests/test_operator_health_report.py`
- `backend/tests/test_skill_history_governance.py`
- `backend/tests/test_redis_stream_bus.py`
- `backend/tests/test_crawl_jobs_api.py`

## Known Gaps or Risks

- Audit reporting is not yet centralized.
- Docs can drift from code unless refreshed alongside changes.
- Operator script outputs are not all persisted as structured audit records.
- Crawl job events are the strongest current audit model, but comparable records do not yet exist for AI settings, recovery scripts, governance actions, or manual intervention decisions.
- Audit docs are hand-maintained and need validation against current file paths and route names.

## Optimization Backlog

- Introduce `operator_audit_events` for settings changes, script dry-runs/executions, recovery actions, governance decisions, and manual-action lifecycle updates.
- Add a lightweight doc validation script that checks referenced files/routes and required sections such as `Optimization Backlog`.
- Standardize operator scripts around dry-run, execute, JSON output, exit codes, and audit-event emission.
- Use crawl job events as the template for broader operational event models across enrichment, governance, and scheduler workflows.

## Follow-up Audit Questions

- Should mutating operator scripts write to a shared `operator_audit_events` table?
- Should audit docs be regenerated or validated by a script?
- Should crawl job events become the model for other operational event streams?
