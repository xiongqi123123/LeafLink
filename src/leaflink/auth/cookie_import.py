"""Load cookies from a JSON file."""

from __future__ import annotations

import json
from pathlib import Path

from leaflink.client.models import SessionCookie


def import_cookies_from_file(path: Path) -> list[SessionCookie]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cookies: list[SessionCookie] = []
    items = raw["cookies"] if isinstance(raw, dict) and "cookies" in raw else raw
    for item in items:
        cookies.append(
            SessionCookie(
                name=item["name"],
                value=item["value"],
                domain=item["domain"],
                path=item.get("path", "/"),
                secure=bool(item.get("secure", True)),
                http_only=bool(item.get("httpOnly", item.get("http_only", True))),
            )
        )
    return cookies
