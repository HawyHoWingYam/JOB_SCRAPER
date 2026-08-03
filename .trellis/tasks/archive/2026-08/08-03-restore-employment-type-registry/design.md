# Design: Restore Employment Type registry

## Boundary

Introduce one Employment Type registry seeding boundary owned near the Source Job Attributes domain. It consumes `EMPLOYMENT_TYPE_SEEDS` and is reused by two explicit entry points:

1. empty-database bootstrap, where schema plus seeds are one transaction;
2. a one-time non-empty-database repair command, where only registry rows may change.

Bootstrap remains schema initialization. Repair remains data repair. Sharing the seed boundary must not merge those operational contracts.

## Seed Contract

The seed operation accepts the caller's SQLAlchemy `Connection` or `Session` and does not commit independently. The caller owns transaction scope.

For every canonical tuple, it must distinguish:

- absent row: insert it;
- exact existing row: leave it unchanged;
- existing canonical code with a conflicting label/order: update it to the canonical values.

After mutation it verifies that the governed registry contains the canonical codes, labels, and display ordering. Unexpected extra codes are reported for operator review and preserved; they are not silently treated as governed values or automatically deleted.

## Empty Bootstrap Flow

```text
begin transaction
  acquire PostgreSQL advisory lock
  refuse if any table exists
  create required extension
  create all ORM tables
  verify exact table parity
  seed Employment Type registry
  verify exact canonical registry
commit
```

Any failure rolls back table creation and seed changes together on PostgreSQL.

## Existing Database Repair Flow

```text
operator invokes explicit repair command
  begin transaction
  verify required registry table exists
  lock/inspect canonical registry rows
  insert missing rows
  correct labels/order for existing canonical codes
  report and preserve unknown extra codes
  verify canonical registry
commit and print a concise result
```

The command must refuse to act if the expected table/schema boundary is unavailable. It does not invoke `metadata.create_all`, and it does not bypass bootstrap's non-empty refusal.

## Diagnostics

The detail pipeline should retain the stable failure category used by control-plane code while adding a sanitized cause for operators. Prefer structured logging plus a bounded stored message derived from SQLAlchemy/driver constraint metadata. Do not persist raw payloads or unrestricted exception representations.

At minimum, the missing-parent-row case should expose the violated constraint and referenced Employment Type code (or an equivalent safe explanation), so the next occurrence can be diagnosed from task data without reading PostgreSQL container logs.

## Compatibility and Rollout

- Existing databases are not modified merely by deploying the code.
- Run the explicit registry repair once against the current retained-data database, verify the seven rows, and only then retry detail targets.
- Fresh rebuilds receive the rows automatically through bootstrap.
- The retained-data cutover sequence remains stop → export → clear → deploy → bootstrap → import → verify → start. Import/verification must not remove or invalidate the canonical registry.

## Rollback

- Code rollback is safe because no schema shape changes are introduced.
- Before running repair, report existing rows and retain the normal operational backup/export because canonicalization can change governed labels/order.
- Do not delete canonical parent rows after jobs reference them.

## Chosen Trade-off

Canonical labels/order are system-owned rather than user-authored, so repair automatically restores them from `EMPLOYMENT_TYPE_SEEDS`. Unknown codes may represent data outside the current authority; repair reports and preserves them instead of deleting them.
