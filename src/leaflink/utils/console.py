"""Console styling helpers for terminal output."""

from __future__ import annotations

import os
import sys
from typing import TextIO

ANSI_RESET = "\033[0m"
ANSI_STYLES = {
    "dim": "\033[2m",
    "bold": "\033[1m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
}
LABEL_STYLES = {
    "sync": "cyan",
    "local": "magenta",
    "remote": "blue",
    "pull": "green",
    "push": "green",
    "merge": "cyan",
    "conflict": "red",
    "ok": "green",
    "warn": "yellow",
    "error": "red",
    "info": "cyan",
    "auth": "cyan",
}


def use_color(stream: TextIO | None = None) -> bool:
    handle = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    return hasattr(handle, "isatty") and handle.isatty()


def style_text(text: str, style: str, stream: TextIO | None = None) -> str:
    if not use_color(stream):
        return text
    prefix = ANSI_STYLES.get(style)
    if not prefix:
        return text
    return f"{prefix}{text}{ANSI_RESET}"


def format_label(label: str, text: str | None = None, stream: TextIO | None = None) -> str:
    style = LABEL_STYLES.get(label, "cyan")
    return style_text(text or f"[{label}]", style, stream=stream)


def print_console(label: str, message: str, stream: TextIO | None = None) -> None:
    handle = stream or sys.stdout
    print(f"{format_label(label, stream=handle)} {message}", file=handle)
