from __future__ import annotations

from typing import Any

from app.logging_config import redact_url


def _render_log_field(key: str, value: Any) -> str:
    rendered = str(value)
    if key == "url" or key.endswith("_url"):
        rendered = redact_url(rendered, redact_query=True)
    return rendered.replace("\n", "\\n")


def build_scrape_log_event(event: str, **fields: Any) -> str:
    parts = [str(event).strip()]
    for key, value in fields.items():
        if value is None:
            continue
        rendered = _render_log_field(key, value)
        parts.append(f"{key}={rendered}")
    return " ".join(parts)
