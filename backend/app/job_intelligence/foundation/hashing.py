from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
import hashlib
import json
from typing import Any
from uuid import UUID


def _normalized_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("Governance payload mapping keys must be strings")
        return {key: _normalized_json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_normalized_json_value(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise TypeError("Governance datetimes must include a timezone")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(
        f"Governance payload contains non-JSON value {type(value).__name__}"
    )


def canonical_json(value: Any) -> str:
    """Return one deterministic UTF-8 JSON representation for governance hashes."""

    return json.dumps(
        _normalized_json_value(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def json_payload(value: Any) -> Any:
    """Return a detached JSON-compatible governance payload."""

    return _normalized_json_value(value)


def normalized_content_hash(value: Any) -> str:
    """Hash governed content after deterministic JSON normalization."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
