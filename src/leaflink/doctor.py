"""Environment checks behind `leaflink doctor`."""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from importlib import metadata
from typing import Callable

from leaflink import __version__
from leaflink.exceptions import BrowserUnavailableError, LeafsyncError
from leaflink.utils.browser import check_headless_chromium


@dataclass(slots=True)
class DoctorCheck:
    level: str  # "ok", "warn" or "error"
    message: str
    browser_missing: bool = False


def check_runtime() -> DoctorCheck:
    return DoctorCheck("ok", f"leaflink {__version__} on Python {platform.python_version()} ({sys.platform})")


def check_package(name: str, purpose: str) -> DoctorCheck:
    try:
        return DoctorCheck("ok", f"{name} {metadata.version(name)}")
    except metadata.PackageNotFoundError:
        return DoctorCheck("error", f"{name} is missing ({purpose}). Reinstall with `pip install -U leaflink`.")


def check_chromium(probe: Callable[[], None] = check_headless_chromium) -> DoctorCheck:
    try:
        probe()
    except BrowserUnavailableError as exc:
        return DoctorCheck("error", str(exc), browser_missing=exc.missing)
    return DoctorCheck("ok", "Chromium starts (needed by push, sync and browser login)")


def check_display(env: dict[str, str] | None = None, platform_name: str = sys.platform) -> DoctorCheck | None:
    env = os.environ if env is None else env
    if not platform_name.startswith("linux") or env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"):
        return None
    return DoctorCheck(
        "warn",
        "No display detected: `leaflink login` cannot open a browser here. Use `leaflink auth import` instead.",
    )


def check_session(base_url: str, has_session: bool, count_projects: Callable[[], int]) -> DoctorCheck:
    if not has_session:
        return DoctorCheck("warn", f"Not logged in to {base_url}. Run `leaflink login` or `leaflink auth import`.")
    try:
        count = count_projects()
    except LeafsyncError as exc:
        return DoctorCheck("error", f"Saved session for {base_url} does not work: {exc}")
    return DoctorCheck("ok", f"Session for {base_url} works ({count} projects)")
