#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.manual_actions.live_browser_registry import get_live_browser_registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("offertoday-auth-setup")

_OFFERTODAY_SEARCH = "https://www.offertoday.com/hk/search"
_WAF_PATH = "/web/passport/cm/verify"
_GEEK_TOKEN_KEY = "geek_token"
_DEFAULT_TIMEOUT_SECONDS = 300
_POLL_INTERVAL_SECONDS = 1.5


async def _wait_for_login(page, *, timeout_seconds: int) -> bool:
    iterations = int(timeout_seconds / _POLL_INTERVAL_SECONDS)
    last_waf_logged = False

    for _ in range(iterations):
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)

        try:
            token = await page.evaluate(f"() => localStorage.getItem('{_GEEK_TOKEN_KEY}')")
            current_url = page.url
        except Exception:
            continue

        if token:
            return True

        if _WAF_PATH in str(current_url or "") and not last_waf_logged:
            logger.warning("WAF challenge detected. Complete the verification in the browser window.")
            last_waf_logged = True
        elif _WAF_PATH not in str(current_url or ""):
            last_waf_logged = False

    return False


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare an OfferToday browser profile and optional storage_state for later crawl runs.",
    )
    parser.add_argument(
        "--output",
        default="offertoday_auth_state.json",
        help="Optional path to save Playwright storage_state JSON.",
    )
    parser.add_argument(
        "--browser-profile",
        default=settings.offertoday_headed_browser_user_data_dir or "",
        help="Browser profile directory for the dedicated OfferToday automation browser.",
    )
    parser.add_argument(
        "--cdp-port",
        type=int,
        default=9222,
        help="Remote debugging port for the OfferToday automation browser.",
    )
    parser.add_argument(
        "--register-live-session",
        action="store_true",
        default=False,
        help="Register the launched browser in the shared live-browser registry.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=_DEFAULT_TIMEOUT_SECONDS,
        help=f"Seconds to wait for login before giving up. Default: {_DEFAULT_TIMEOUT_SECONDS}.",
    )
    args = parser.parse_args()

    output_path = Path(args.output).resolve() if args.output else None
    profile_path = (
        Path(args.browser_profile).resolve()
        if args.browser_profile
        else (Path(settings.offertoday_headed_browser_user_data_dir).resolve() if settings.offertoday_headed_browser_user_data_dir else None)
    )

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Playwright is not installed. Run: pip install playwright && playwright install chromium")
        return 1

    if profile_path is None:
        logger.error("No OfferToday browser profile path is configured.")
        return 1

    launch_kwargs: dict[str, object] = {"headless": False}
    if settings.offertoday_headed_browser_executable_path:
        launch_kwargs["executable_path"] = settings.offertoday_headed_browser_executable_path
    else:
        launch_kwargs["channel"] = settings.offertoday_headed_browser_channel

    logger.info("Opening OfferToday browser with profile: %s", profile_path)
    logger.info("Remote debugging port: %s", args.cdp_port)
    logger.info("Waiting up to %d seconds for login or WAF verification.", args.timeout)

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            args=[
                "--start-maximized",
                f"--remote-debugging-port={args.cdp_port}",
            ],
            **launch_kwargs,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(_OFFERTODAY_SEARCH, wait_until="domcontentloaded", timeout=30_000)

        logged_in = await _wait_for_login(page, timeout_seconds=args.timeout)
        if logged_in:
            logger.info("Login detected.")
        else:
            logger.warning("Timed out waiting for login confirmation; saving current state anyway.")

        if args.register_live_session:
            get_live_browser_registry().register(
                browser_channel=settings.offertoday_headed_browser_channel,
                browser_profile_path=str(profile_path),
                blocked_url=_OFFERTODAY_SEARCH,
                debug_port=int(args.cdp_port),
                status="live",
            )
            logger.info("Registered OfferToday live browser session for profile: %s", profile_path)

        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            await context.storage_state(path=str(output_path))
            logger.info("Saved OfferToday storage_state to: %s", output_path)

        await context.close()

    return 0 if logged_in else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
