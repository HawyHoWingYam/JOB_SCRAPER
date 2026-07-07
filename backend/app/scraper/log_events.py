from __future__ import annotations

from typing import Any


def build_scrape_log_event(event: str, **fields: Any) -> str:
    parts = [str(event).strip()]
    for key, value in fields.items():
        if value is None:
            continue
        rendered = str(value).replace("\n", "\\n")
        parts.append(f"{key}={rendered}")
    return " ".join(parts)
