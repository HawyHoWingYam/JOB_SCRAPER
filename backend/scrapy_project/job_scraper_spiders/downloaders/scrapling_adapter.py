"""Scrapling adapter — wraps Scrapling as a measured antidote for hard anti-bot routes.

Scrapling (https://github.com/D4Vinci/Scrapling) provides stealth browser
sessions with TLS fingerprint customization, useful for sites that challenge
standard httpx or Playwright traffic.

This module keeps Scrapling behind an optional feature flag. It is imported
only when explicitly enabled (SCRAPLING_ENABLED=true).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Lazy import to avoid dependency conflicts at app startup
_SCRAPLING_AVAILABLE: bool | None = None


def is_scrapling_available() -> bool:
    """Check if Scrapling can be imported without forcing the import."""
    global _SCRAPLING_AVAILABLE
    if _SCRAPLING_AVAILABLE is None:
        try:
            import scrapling as _  # noqa: F401

            _SCRAPLING_AVAILABLE = True
        except ImportError:
            _SCRAPLING_AVAILABLE = False
    return _SCRAPLING_AVAILABLE


async def create_scrapling_session(**kwargs: Any) -> Any:
    """Create a Scrapling AsyncFetcher session (lazy import)."""
    if not is_scrapling_available():
        raise RuntimeError("Scrapling not installed. Install with: pip install scrapling")

    from scrapling import AsyncFetcher

    session = await AsyncFetcher(
        save_response_body=True,
        headless=kwargs.get("headless", True),
        stealth=kwargs.get("stealth", True),
    ).astart()
    return session


async def scrapling_fetch(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: str | None = None,
    **kwargs: Any,
) -> str:
    """Fetch a URL using a Scrapling session.

    Creates a temporary session for the request.
    For repeated requests, create a session with create_scrapling_session()
    and use its .get() / .post() methods directly.
    """
    session = await create_scrapling_session(**kwargs)
    try:
        if method.upper() == "GET":
            text = await session.get(url, headers=headers or {})
        elif method.upper() == "POST":
            if data:
                headers = {**(headers or {}), "content-type": "application/json;charset=UTF-8"}
                text = await session.post(url, headers=headers or {}, data=data)
            else:
                text = await session.post(url, headers=headers or {})
        else:
            raise ValueError(f"Unsupported method: {method}")
        return str(text) if text else ""
    finally:
        await session.close()
