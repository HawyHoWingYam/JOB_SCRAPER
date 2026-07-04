#!/usr/bin/env python3
"""One-time OfferToday auth setup.

Opens a headed Chromium browser, waits for the user to manually complete
any WAF challenge and log in, then saves the full browser session
(cookies + localStorage + sessionStorage) to a JSON file.

That file can then be passed to offertoday_standalone_crawl.py via
--auth-state so each crawl run starts pre-authenticated.

Usage:
    python offertoday_auth_setup.py
    python offertoday_auth_setup.py --output path/to/auth_state.json
    python offertoday_auth_setup.py --timeout 600
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("offertoday-auth-setup")

_OFFERTODAY_SEARCH = "https://www.offertoday.com/hk/search"
_WAF_PATH = "/web/passport/cm/verify"
# OfferToday (BOSS Zhipin) stores the auth JWT in localStorage under this key.
_GEEK_TOKEN_KEY = "geek_token"
_DEFAULT_TIMEOUT_SECONDS = 300
_POLL_INTERVAL_SECONDS = 1.5


async def _wait_for_login(page, *, timeout_seconds: int) -> bool:
    """Poll until geek_token appears in localStorage. Returns True on success."""
    iterations = int(timeout_seconds / _POLL_INTERVAL_SECONDS)
    last_waf_logged = False

    for _ in range(iterations):
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)

        try:
            token = await page.evaluate(
                f"() => localStorage.getItem('{_GEEK_TOKEN_KEY}')"
            )
            current_url = page.url
        except Exception:
            # Page may be navigating; keep polling.
            continue

        if token:
            return True

        if _WAF_PATH in current_url and not last_waf_logged:
            logger.warning(
                "WAF challenge page detected — please click the verification button in the browser."
            )
            last_waf_logged = True
        elif _WAF_PATH not in current_url:
            last_waf_logged = False

    return False


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Save OfferToday browser session for use with offertoday_standalone_crawl.py.",
    )
    parser.add_argument(
        "--output",
        default="offertoday_auth_state.json",
        help="Path to write the Playwright storage_state JSON file. (default: offertoday_auth_state.json)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=_DEFAULT_TIMEOUT_SECONDS,
        help=f"Seconds to wait for login before giving up. (default: {_DEFAULT_TIMEOUT_SECONDS})",
    )
    args = parser.parse_args()
    output_path = Path(args.output).resolve()

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error(
            "Playwright is not installed. Run: pip install playwright && playwright install chromium"
        )
        return 1

    logger.info("Opening headed Chromium → %s", _OFFERTODAY_SEARCH)
    logger.info("Steps:")
    logger.info("  1. If a WAF slider appears, click the verification button.")
    logger.info("  2. Click '登入' and complete login (email/Google/Apple).")
    logger.info("  3. The script saves your session automatically once logged in.")
    logger.info("Waiting up to %d seconds…", args.timeout)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--start-maximized"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="zh-HK",
            viewport=None,  # use the window size set by --start-maximized
        )
        page = await context.new_page()

        await page.goto(_OFFERTODAY_SEARCH, wait_until="domcontentloaded", timeout=30_000)

        logged_in = await _wait_for_login(page, timeout_seconds=args.timeout)

        if logged_in:
            logger.info("Login detected. Saving session state…")
        else:
            logger.warning(
                "Timed out waiting for login (%ds). Saving current state anyway — "
                "it may still contain WAF cookies useful for the next crawl run.",
                args.timeout,
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(output_path))
        logger.info("Session saved to: %s", output_path)

        await browser.close()

    if logged_in:
        logger.info("Done. Pass --auth-state %s to offertoday_standalone_crawl.py.", output_path)
        return 0
    else:
        logger.warning(
            "Session saved without confirmed login. "
            "Re-run this script and complete the login flow for best results."
        )
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
