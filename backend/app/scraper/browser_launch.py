from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MISSING_BRANDED_BROWSER_MARKERS = (
    "Chromium distribution",
    "is not found at",
)
FALLBACK_BRANDED_CHANNELS = {"msedge", "chrome"}


@dataclass(frozen=True)
class BrowserLaunchResult:
    context: Any
    requested_channel: str | None
    resolved_channel: str | None
    attempted_fallback: bool


def _prepare_launch_kwargs(
    *,
    browser_channel: str | None,
    executable_path: str | None,
    headless: bool,
    extra_launch_kwargs: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str | None]:
    launch_kwargs = {"headless": headless, **dict(extra_launch_kwargs or {})}
    if executable_path:
        launch_kwargs["executable_path"] = executable_path
        return launch_kwargs, None

    requested_channel = str(browser_channel or "").strip() or None
    if requested_channel:
        launch_kwargs["channel"] = requested_channel
    return launch_kwargs, requested_channel


def _should_fallback(requested_channel: str | None, exc: Exception) -> bool:
    if requested_channel not in FALLBACK_BRANDED_CHANNELS:
        return False
    message = str(exc)
    return all(marker in message for marker in MISSING_BRANDED_BROWSER_MARKERS)


def _raise_launch_error(
    *,
    requested_channel: str | None,
    attempted_fallback: bool,
    message: str,
    cause: Exception,
) -> None:
    if attempted_fallback and requested_channel:
        raise RuntimeError(
            f"Unable to launch headed browser with requested channel '{requested_channel}' "
            f"or fallback 'chromium': {message}"
        ) from cause
    if requested_channel:
        raise RuntimeError(
            f"Unable to launch headed browser with channel '{requested_channel}': {message}"
        ) from cause
    raise RuntimeError(f"Unable to launch headed browser: {message}") from cause


def launch_persistent_context_with_fallback(
    chromium,
    *,
    user_data_dir: str,
    browser_channel: str | None,
    executable_path: str | None,
    headless: bool,
    extra_launch_kwargs: dict[str, Any] | None = None,
) -> BrowserLaunchResult:
    launch_kwargs, requested_channel = _prepare_launch_kwargs(
        browser_channel=browser_channel,
        executable_path=executable_path,
        headless=headless,
        extra_launch_kwargs=extra_launch_kwargs,
    )
    try:
        context = chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            **launch_kwargs,
        )
        return BrowserLaunchResult(
            context=context,
            requested_channel=requested_channel,
            resolved_channel=requested_channel,
            attempted_fallback=False,
        )
    except Exception as exc:
        if not _should_fallback(requested_channel, exc):
            _raise_launch_error(
                requested_channel=requested_channel,
                attempted_fallback=False,
                message=str(exc),
                cause=exc,
            )

    fallback_kwargs = {**launch_kwargs, "channel": "chromium"}
    try:
        context = chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            **fallback_kwargs,
        )
    except Exception as exc:
        _raise_launch_error(
            requested_channel=requested_channel,
            attempted_fallback=True,
            message=str(exc),
            cause=exc,
        )

    return BrowserLaunchResult(
        context=context,
        requested_channel=requested_channel,
        resolved_channel="chromium",
        attempted_fallback=True,
    )


async def launch_persistent_context_with_fallback_async(
    chromium,
    *,
    user_data_dir: str,
    browser_channel: str | None,
    executable_path: str | None,
    headless: bool,
    extra_launch_kwargs: dict[str, Any] | None = None,
) -> BrowserLaunchResult:
    launch_kwargs, requested_channel = _prepare_launch_kwargs(
        browser_channel=browser_channel,
        executable_path=executable_path,
        headless=headless,
        extra_launch_kwargs=extra_launch_kwargs,
    )
    try:
        context = await chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            **launch_kwargs,
        )
        return BrowserLaunchResult(
            context=context,
            requested_channel=requested_channel,
            resolved_channel=requested_channel,
            attempted_fallback=False,
        )
    except Exception as exc:
        if not _should_fallback(requested_channel, exc):
            _raise_launch_error(
                requested_channel=requested_channel,
                attempted_fallback=False,
                message=str(exc),
                cause=exc,
            )

    fallback_kwargs = {**launch_kwargs, "channel": "chromium"}
    try:
        context = await chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            **fallback_kwargs,
        )
    except Exception as exc:
        _raise_launch_error(
            requested_channel=requested_channel,
            attempted_fallback=True,
            message=str(exc),
            cause=exc,
        )

    return BrowserLaunchResult(
        context=context,
        requested_channel=requested_channel,
        resolved_channel="chromium",
        attempted_fallback=True,
    )
