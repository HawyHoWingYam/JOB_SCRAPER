# Technical design

Implement `ClassificationBatchRuntime` from the parent design with a small
preview/start/status/retry/stop interface. Domain adapters own selection and
one-item processing. The frontend shares interaction primitives but does not
share raw domain payload parsing. Skill threshold evaluation is transactionally
idempotent on normalized candidate identity.
