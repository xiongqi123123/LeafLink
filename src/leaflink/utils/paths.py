"""Filesystem path helpers."""

from __future__ import annotations

import os
from pathlib import Path


def _fallback_config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "leaflink"
    return Path.home() / ".config" / "leaflink"


def app_config_dir() -> Path:
    override = os.environ.get("LEAFLINK_CONFIG_DIR")
    if override:
        return Path(override).expanduser().resolve()

    try:
        from platformdirs import user_config_dir

        return Path(user_config_dir("leaflink", appauthor=False))
    except Exception:
        return _fallback_config_dir()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
