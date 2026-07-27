# Technical design

Collapse to one current protocol set. Preserve event identity/idempotency and DB
transactional safety, but no compatibility selector or optimistic revision.
Schema creation is an empty-database bootstrap, not a migration system. External
dependency/runtime/model release pins remain outside scope.
