# Technical design

Implement the `SandboxCutover` interface in the parent design. The retained
artifact is a one-time transformation input with identity/hash manifests, not a
backup. Target schema creation must be deterministic on an empty database. There
is no rollback after successful verification and artifact deletion.
