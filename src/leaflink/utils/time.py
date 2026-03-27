"""Time helpers."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def local_time_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().replace(microsecond=0).isoformat()


def format_display_time(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value
