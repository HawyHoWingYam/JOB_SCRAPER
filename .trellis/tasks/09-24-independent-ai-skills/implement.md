# Implementation plan

- [x] Add a failing service regression proving nonempty AI Skills are persisted
  and no Jev records are created.
- [x] Remove inline Jev orchestration from `AIEnrichmentService` and publish the
  AI projection directly.
- [x] Add durable baseline/correction applicability only where existing mention
  history cannot satisfy parent precedence requirements.
- [x] Add regressions for empty success, unchanged rerun, changed evidence,
  operator precedence, and manual Jev correction application.
- [x] Update backend contracts that currently describe inline or scheduled Jev.
- [x] Run targeted backend tests, lint, PostgreSQL integration, and parent E2E
  coverage before finishing this child.
