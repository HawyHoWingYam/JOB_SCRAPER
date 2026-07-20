from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from app.job_intelligence.cutover.contracts import (
    CutoverManifest,
    CutoverManifestEnvelope,
)


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        _normalize_json_value(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _normalize_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("Cutover artifacts cannot contain non-finite floats")
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Enum):
        return _normalize_json_value(value.value)
    if isinstance(value, bytes):
        return {"sha256": hashlib.sha256(value).hexdigest(), "length": len(value)}
    if isinstance(value, dict):
        return {
            str(key): _normalize_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_normalize_json_value(item) for item in value]
        return sorted(normalized, key=lambda item: canonical_json_bytes(item))
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return _normalize_json_value(tolist())
    raise TypeError(f"Unsupported cutover artifact value: {type(value).__name__}")


def content_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class ManifestIntegrityError(ValueError):
    pass


class VerifiedArtifactStore:
    def write(self, output: Path, payload: dict[str, Any]) -> str:
        payload_hash = content_hash(payload)
        envelope = {
            "payload": payload,
            "payload_hash": payload_hash,
        }
        self._write_atomic(output, canonical_json_bytes(envelope) + b"\n")
        return payload_hash

    def write_bytes(self, output: Path, payload: bytes) -> str:
        payload_hash = hashlib.sha256(payload).hexdigest()
        self._write_atomic(output, payload)
        return payload_hash

    def read(self, path: Path) -> dict[str, Any]:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(envelope, dict) or set(envelope) != {
            "payload",
            "payload_hash",
        }:
            raise ManifestIntegrityError("Cutover artifact envelope is invalid")
        payload = envelope["payload"]
        expected_hash = envelope["payload_hash"]
        if not isinstance(payload, dict) or not isinstance(expected_hash, str):
            raise ManifestIntegrityError("Cutover artifact envelope is invalid")
        if content_hash(payload) != expected_hash:
            raise ManifestIntegrityError("Cutover artifact content hash mismatch")
        return payload

    @staticmethod
    def _write_atomic(output: Path, payload: bytes) -> None:
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if output.is_symlink():
            raise ValueError("Cutover artifact path cannot be a symbolic link")
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


class CutoverManifestStore:
    def write(self, output: Path, manifest: CutoverManifest) -> str:
        manifest_payload = manifest.model_dump(mode="json", by_alias=True)
        manifest_hash = content_hash(manifest_payload)
        envelope = CutoverManifestEnvelope(
            manifest=manifest,
            manifest_hash=manifest_hash,
        )
        serialized = (
            canonical_json_bytes(envelope.model_dump(mode="json", by_alias=True))
            + b"\n"
        )
        VerifiedArtifactStore._write_atomic(output, serialized)
        return manifest_hash

    def read(self, path: Path) -> CutoverManifestEnvelope:
        raw = json.loads(path.read_text(encoding="utf-8"))
        envelope = CutoverManifestEnvelope.model_validate(raw)
        payload = envelope.manifest.model_dump(mode="json", by_alias=True)
        actual_hash = content_hash(payload)
        if actual_hash != envelope.manifest_hash:
            raise ManifestIntegrityError("Cutover manifest content hash mismatch")
        return envelope
