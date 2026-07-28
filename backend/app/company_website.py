from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def normalize_company_website(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("website must be a valid HTTP or HTTPS URL")
    host = parsed.hostname.lower()
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            host,
            parsed.path.rstrip("/"),
            parsed.query,
            "",
        )
    )


__all__ = ["normalize_company_website"]
