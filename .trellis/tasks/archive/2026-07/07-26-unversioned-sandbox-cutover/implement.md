# Implementation plan

1. Build export/import/manifest/verification/clear-runtime commands and fixtures.
2. Exercise RESTRICT cycles and Redis pending state on disposable PostgreSQL/
   Redis twice from clean starts.
3. Run final backend/frontend/architecture gates against target code.
4. Stop shared sandbox, export, clear, destroy, bootstrap, import, and verify.
5. Delete transient artifact, atomically start stack, run smoke checks, and prove
   zero old task/version commands.

Abort before destroying the shared DB if any retention identity is ambiguous.
