# Company industry governance implementation plan

## Dependencies

- Requires `07-18-job-intelligence-foundation`.
- Consult official standards research and verify C&SD redistribution terms before committing seed assets.

## Ordered checklist

1. Load `trellis-before-dev`, parent artifacts, ADR-0009–0013, and backend/database specs.
2. Acquire/version official HSIC V2.0 source artifact with source metadata; add parser/manifest tests before checking in derived seed content.
3. Implement full hierarchy/cycle/code/bilingual/content-hash validation.
4. Add Alembic models, constraints, recursive-query indexes, mapping/review/assignment tables, and Primary partial unique index.
5. Implement revision publication and hierarchy/breadcrumb/filter Interface.
6. Remove Company Industry contamination writes from data mapper and ingest worker; route valid company evidence into Module.
7. Implement deterministic mapping/auto-assignment and review-item creation.
8. Implement local-operator review/mapping decisions through foundation UoW.
9. Add Company/read/filter/queue/audit response contracts and outbox invalidation.
10. Implement legacy pollution audit and dry-run rebuild report; do not execute live cutover.
11. Export backend fixtures and run full validation.

## Validation

```bash
cd backend && pytest -q tests/test_company_industry_governance.py tests/test_company_repository.py
cd backend && ruff check app tests scripts && black --check app tests scripts && mypy app
cd backend && pytest -q
python3 ./.trellis/scripts/task.py validate 07-18-company-industry-governance
```

## Risk and rollback points

- Block seed publication until official provenance/redistribution requirements are recorded.
- Never use job classification/category labels as an industry mapping shortcut.
- Keep legacy `Company.industry` and raw metadata through child 7 rollback window.
- Application rollback may resume legacy reads, but contamination writes must not be silently re-enabled without explicit rollback decision.
