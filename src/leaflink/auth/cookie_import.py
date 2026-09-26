"""Build session cookies from JSON files or name/value pairs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from leaflink.client.models import SessionCookie
from leaflink.config import normalize_base_url
from leaflink.exceptions import AuthenticationError

OFFICIAL_HOSTS = {"www.overleaf.com", "cn.overleaf.com"}

COOKIE_FILE_EXAMPLE = """\
[
  {"name": "overleaf_session2", "value": "s%3A...", "domain": ".overleaf.com"}
]"""


def default_cookie_domain(base_url: str) -> str:
    """Return the domain to attach to cookies entered without one."""
    host = urlparse(normalize_base_url(base_url)).hostname or ""
    if host in OFFICIAL_HOSTS:
        return ".overleaf.com"
    return host


def parse_cookie_pairs(text: str) -> list[tuple[str, str]]:
    """Parse `NAME=VALUE` or a `Cookie` header such as `a=1; b=2`."""
    pairs: list[tuple[str, str]] = []
    for part in text.split(";"):
        part = part.strip()
        if not part:
            continue
        name, sep, value = part.partition("=")
        name = name.strip()
        if not sep or not name:
            raise AuthenticationError(f"Expected NAME=VALUE, got {part!r}.")
        pairs.append((name, value.strip()))
    return pairs


def cookies_from_pairs(pairs: Iterable[tuple[str, str]], base_url: str) -> list[SessionCookie]:
    domain = default_cookie_domain(base_url)
    secure = _default_secure(base_url)
    return [SessionCookie(name=name, value=value, domain=domain, secure=secure) for name, value in pairs]


def import_cookies_from_file(path: Path, base_url: str | None = None) -> list[SessionCookie]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AuthenticationError(f"Cannot read cookie file {path}: {exc.strerror or exc}.") from exc
    except json.JSONDecodeError as exc:
        raise AuthenticationError(_format_error(f"{path} is not valid JSON ({exc.msg}, line {exc.lineno}).")) from exc

    if isinstance(raw, dict) and "cookies" in raw:
        items = raw["cookies"]
    elif isinstance(raw, dict) and all(isinstance(value, str) for value in raw.values()):
        items = [{"name": name, "value": value} for name, value in raw.items()]
    else:
        items = raw
    if not isinstance(items, list):
        raise AuthenticationError(_format_error(f"{path} must contain a list of cookies."))

    cookies: list[SessionCookie] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict) or "name" not in item or "value" not in item:
            raise AuthenticationError(_format_error(f"Cookie #{index + 1} in {path} needs \"name\" and \"value\"."))
        domain = item.get("domain")
        if not domain:
            if base_url is None:
                raise AuthenticationError(_format_error(f"Cookie #{index + 1} in {path} needs a \"domain\"."))
            domain = default_cookie_domain(base_url)
        cookies.append(
            SessionCookie(
                name=str(item["name"]),
                value=str(item["value"]),
                domain=str(domain),
                path=item.get("path", "/"),
                secure=bool(item.get("secure", True if base_url is None else _default_secure(base_url))),
                http_only=bool(item.get("httpOnly", item.get("http_only", True))),
            )
        )
    return cookies


def _default_secure(base_url: str) -> bool:
    return urlparse(normalize_base_url(base_url)).scheme == "https"


def _format_error(message: str) -> str:
    return f"{message}\nExpected a cookie file like:\n{COOKIE_FILE_EXAMPLE}"
