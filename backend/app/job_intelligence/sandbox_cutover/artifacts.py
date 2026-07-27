from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def content_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class RetentionArtifactIntegrityError(ValueError):
    pass


class RetentionArtifactStore:
    """Atomic one-time artifact storage with content verification."""

    def write(self, output: Path, payload: dict[str, Any]) -> str:
        payload_hash = content_hash(payload)
        envelope = {"payload": payload, "payload_hash": payload_hash}
        self._write_atomic(output, canonical_json_bytes(envelope) + b"\n")
        return payload_hash

    def read(self, path: Path) -> dict[str, Any]:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(envelope, dict) or set(envelope) != {
            "payload",
            "payload_hash",
        }:
            raise RetentionArtifactIntegrityError(
                "Sandbox retention artifact envelope is invalid"
            )
        payload = envelope["payload"]
        expected_hash = envelope["payload_hash"]
        if not isinstance(payload, dict) or not isinstance(expected_hash, str):
            raise RetentionArtifactIntegrityError(
                "Sandbox retention artifact envelope is invalid"
            )
        if content_hash(payload) != expected_hash:
            raise RetentionArtifactIntegrityError(
                "Sandbox retention artifact content hash mismatch"
            )
        return payload

    @staticmethod
    def _write_atomic(output: Path, payload: bytes) -> None:
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if output.is_symlink():
            raise ValueError("Sandbox retention artifact cannot be a symbolic link")
        temporary = output.with_name(f".{output.name}.{uuid4().hex}.tmp")
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
