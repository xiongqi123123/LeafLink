"""Load Playwright and launch or install the Chromium build it drives."""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Callable

from leaflink.exceptions import BrowserUnavailableError

INSTALL_COMMAND = "playwright install chromium"
MISSING_BROWSER_MESSAGE = (
    f"Chromium for Playwright is not installed. Run `{INSTALL_COMMAND}` or `leaflink doctor`. "
    "This is needed again after Playwright upgrades."
)


def load_sync_playwright() -> Callable[[], Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserUnavailableError(
            "Playwright is missing from this environment. Reinstall with `pip install -U leaflink`."
        ) from exc
    return sync_playwright


def launch_chromium(playwright: Any, headless: bool) -> Any:
    from playwright.sync_api import Error as PlaywrightError

    try:
        return playwright.chromium.launch(headless=headless)
    except PlaywrightError as exc:
        raise launch_error(exc) from exc


def launch_error(exc: Exception) -> BrowserUnavailableError:
    message = str(exc)
    if "Executable doesn't exist" in message or "playwright install" in message:
        return BrowserUnavailableError(MISSING_BROWSER_MESSAGE, missing=True)
    first_line = next((line.strip() for line in message.splitlines() if line.strip()), type(exc).__name__)
    return BrowserUnavailableError(f"Could not start Chromium: {first_line}")


def check_headless_chromium() -> None:
    """Start and close headless Chromium, raising BrowserUnavailableError on failure."""
    sync_playwright = load_sync_playwright()
    with sync_playwright() as playwright:
        launch_chromium(playwright, headless=True).close()


def install_chromium() -> bool:
    result = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
    return result.returncode == 0
