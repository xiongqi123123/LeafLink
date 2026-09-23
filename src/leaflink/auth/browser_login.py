"""Browser-assisted login using Playwright when available."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse

from leaflink.client.models import SessionCookie
from leaflink.config import normalize_base_url
from leaflink.exceptions import AuthenticationError
from leaflink.utils.console import print_console

SUPPORTED_HOSTS = {"www.overleaf.com", "cn.overleaf.com"}
SUPPORTED_COOKIE_DOMAINS = {"overleaf.com", *SUPPORTED_HOSTS}
IMPORTANT_COOKIE_NAMES = {
    "sharelatex.sid",
    "overleaf_session2",
    "connect.sid",
    "_csrf",
    "XSRF-TOKEN",
}
COOKIE_NAME_BLACKLIST_PREFIXES = (
    "_ga",
    "_gid",
    "_gat",
    "ajs_",
    "amplitude_",
    "mp_",
)


@dataclass(slots=True)
class BrowserLoginResult:
    base_url: str
    cookies: list[SessionCookie]


def select_relevant_cookies(cookies: Iterable[dict[str, object]], base_url: str | None = None) -> list[SessionCookie]:
    selected: list[SessionCookie] = []
    fallback: list[SessionCookie] = []
    seen: set[tuple[str, str, str]] = set()
    for item in cookies:
        name = str(item.get("name", ""))
        domain = str(item.get("domain", "")).lstrip(".").lower()
        if not is_supported_cookie_domain(domain, base_url=base_url):
            continue
        cookie = SessionCookie(
            name=name,
            value=str(item.get("value", "")),
            domain=str(item.get("domain", "")),
            path=str(item.get("path", "/")),
            secure=bool(item.get("secure", True)),
            http_only=bool(item.get("httpOnly", True)),
        )
        key = (cookie.domain, cookie.path, cookie.name)
        if key in seen:
            continue
        seen.add(key)
        if name in IMPORTANT_COOKIE_NAMES or name.endswith(".sid"):
            selected.append(cookie)
            continue
        if not any(name.startswith(prefix) for prefix in COOKIE_NAME_BLACKLIST_PREFIXES):
            fallback.append(cookie)
    return selected or fallback


def select_supported_cookies(cookies: Iterable[dict[str, object]], base_url: str | None = None) -> list[SessionCookie]:
    supported: list[SessionCookie] = []
    for item in cookies:
        domain = str(item.get("domain", "")).lstrip(".").lower()
        if not is_supported_cookie_domain(domain, base_url=base_url):
            continue
        supported.append(
            SessionCookie(
                name=str(item.get("name", "")),
                value=str(item.get("value", "")),
                domain=str(item.get("domain", "")),
                path=str(item.get("path", "/")),
                secure=bool(item.get("secure", True)),
                http_only=bool(item.get("httpOnly", True)),
            )
        )
    return supported


def has_supported_cookies(cookies: Iterable[dict[str, object]], base_url: str | None = None) -> bool:
    for item in cookies:
        domain = str(item.get("domain", "")).lstrip(".").lower()
        if is_supported_cookie_domain(domain, base_url=base_url):
            return True
    return False


def is_supported_cookie_domain(domain: str, base_url: str | None = None) -> bool:
    normalized = domain.lstrip(".").lower()
    if base_url is not None:
        allowed_hosts = _allowed_cookie_hosts(base_url)
        return any(host == normalized or host.endswith(f".{normalized}") for host in allowed_hosts)
    if normalized in SUPPORTED_COOKIE_DOMAINS:
        return True
    return any(host.endswith(f".{normalized}") for host in SUPPORTED_HOSTS)


def is_project_dashboard(urls: Iterable[str], base_url: str | None = None) -> bool:
    allowed_origins = _allowed_url_origins(base_url) if base_url is not None else {("https", host) for host in SUPPORTED_HOSTS}
    for url in urls:
        parsed = urlparse(url)
        if (parsed.scheme.lower(), parsed.netloc.lower()) in allowed_origins and parsed.path.startswith("/project"):
            return True
    return False


def detect_base_url(urls: Iterable[str], fallback: str) -> str:
    detected = fallback.rstrip("/")
    allowed_origins = _allowed_url_origins(fallback)
    for url in urls:
        parsed = urlparse(url)
        origin = (parsed.scheme.lower(), parsed.netloc.lower())
        if origin in allowed_origins:
            detected = f"{origin[0]}://{origin[1]}"
    return detected


def _allowed_url_origins(base_url: str) -> set[tuple[str, str]]:
    normalized = normalize_base_url(base_url)
    parsed = urlparse(normalized)
    if parsed.netloc in SUPPORTED_HOSTS:
        return {("https", host) for host in SUPPORTED_HOSTS}
    return {(parsed.scheme, parsed.netloc)}


def _allowed_cookie_hosts(base_url: str) -> set[str]:
    normalized = normalize_base_url(base_url)
    parsed = urlparse(normalized)
    if parsed.hostname in SUPPORTED_HOSTS:
        return set(SUPPORTED_HOSTS)
    return {parsed.hostname.lower()} if parsed.hostname else set()


def login_with_browser(base_url: str, timeout_seconds: int = 300) -> BrowserLoginResult:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise AuthenticationError(
            "Playwright is not installed. Install `leaflink[browser]` or use `--cookie-file`."
        ) from exc

    login_url = f"{base_url.rstrip('/')}/login"
    with sync_playwright() as playwright:  # pragma: no cover
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(login_url, wait_until="domcontentloaded")
        print_console(
            "auth",
            "Complete login in the browser window. leaflink will detect the session automatically and close the browser.",
        )
        deadline = time.monotonic() + timeout_seconds
        last_urls = [page.url]
        while time.monotonic() < deadline:
            try:
                context.pages
                urls = [current.url for current in context.pages]
                last_urls = urls or last_urls
                browser_cookies = context.cookies()
                cookies = select_relevant_cookies(browser_cookies, base_url=base_url)
            except PlaywrightError as exc:
                raise AuthenticationError(
                    "The browser window was closed before leaflink captured a reusable session. "
                    "Please run `leaflink login` again and leave the browser open until leaflink confirms success."
                ) from exc

            if is_project_dashboard(last_urls, base_url=base_url) and has_supported_cookies(browser_cookies, base_url=base_url):
                if not cookies:
                    cookies = select_supported_cookies(browser_cookies, base_url=base_url)
                resolved_base_url = detect_base_url(last_urls, fallback=base_url)
                browser.close()
                return BrowserLoginResult(base_url=resolved_base_url, cookies=cookies)
            page.wait_for_timeout(1000)

        browser.close()
    raise AuthenticationError(
        "Timed out waiting for a successful Overleaf session. "
        "Please make sure the project dashboard opens in the browser before closing it."
    )
