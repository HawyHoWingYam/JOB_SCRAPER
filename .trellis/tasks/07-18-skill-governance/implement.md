# Skill governance implementation plan

## Dependencies

- Requires `07-18-job-intelligence-foundation`.

## Ordered checklist

1. Load `trellis-before-dev`, parent artifacts, ADR-0006, and backend/search specs.
2. Add deterministic validator tests for every known static-data inconsistency and alias collision class.
3. Curate seed/rules/backfill targets explicitly; generate stable codes and revision manifest.
4. Add Alembic schema with constrained statuses/resolutions/FKs/indexes and retirement-safe delete semantics.
5. Implement governed seed publication and Skill read/search repository.
6. Refactor normalization into exact deterministic extraction Interface plus advisory recommendation Interface.
7. Implement concurrency-safe Candidate/mention registration and governed Job-Skill projection.
8. Implement all four local-operator decisions through foundation UoW with atomic affected-mention fan-out.
9. Replace Job serialization/stats/search/recommendation/embedding inputs with governed projections and secondary Unreviewed Skill Mentions.
10. Implement dry-run/rebuild report without live destructive execution.
11. Export real backend response fixtures and run full validation.

## Validation

```bash
cd backend && pytest -q tests/test_skill_normalizer.py tests/test_skill_governance.py tests/test_job_skill_serialization.py
cd backend && ruff check app tests scripts && black --check app tests scripts && mypy app
cd backend && pytest -q
python3 ./.trellis/scripts/task.py validate 07-18-skill-governance
```

## Risk and rollback points

- Do not let import/decision code auto-create missing curation targets; fail validation instead.
- Do not delete old mention/candidate state until child 7 snapshots it.
- If a high-fan-out Candidate decision fails, the entire transaction rolls back; never resume midway by hand.
- Preserve old tables/columns through rollback window even after new read contracts switch.
