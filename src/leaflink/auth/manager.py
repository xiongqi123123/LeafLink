"""Persist and load authentication state."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from leaflink.auth.browser_login import BrowserLoginResult, login_with_browser
from leaflink.auth.cookie_import import import_cookies_from_file
from leaflink.client.models import AuthSession, SessionCookie
from leaflink.utils.paths import app_config_dir
from leaflink.utils.time import utc_now_iso


class AuthManager:
    """Store auth sessions in the user config directory."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or app_config_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.auth_path = self.root / "auth.json"

    def load_all(self) -> dict[str, AuthSession]:
        if not self.auth_path.exists():
            return {}
        raw = json.loads(self.auth_path.read_text(encoding="utf-8"))
        sessions: dict[str, AuthSession] = {}
        for base_url, item in raw.items():
            sessions[base_url] = AuthSession(
                base_url=base_url,
                cookies=[SessionCookie(**cookie) for cookie in item["cookies"]],
                created_at=item["created_at"],
                updated_at=item["updated_at"],
            )
        return sessions

    def load(self, base_url: str) -> AuthSession | None:
        return self.load_all().get(base_url.rstrip("/"))

    def save(self, session: AuthSession) -> None:
        sessions = self.load_all()
        sessions[session.base_url.rstrip("/")] = session
        payload = {
            base_url: {
                "cookies": [asdict(cookie) for cookie in saved.cookies],
                "created_at": saved.created_at,
                "updated_at": saved.updated_at,
            }
            for base_url, saved in sessions.items()
        }
        self.auth_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def login(self, base_url: str, cookie_file: Path | None = None) -> AuthSession:
        base_url = base_url.rstrip("/")
        if cookie_file is not None:
            cookies = import_cookies_from_file(cookie_file)
            resolved_base_url = base_url
        else:
            browser_result = login_with_browser(base_url)
            cookies = browser_result.cookies
            resolved_base_url = browser_result.base_url
        existing = self.load(base_url)
        now = utc_now_iso()
        session = AuthSession(
            base_url=resolved_base_url,
            cookies=cookies,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self.save(session)
        return session

    def logout(self, base_url: str | None = None) -> int:
        if not self.auth_path.exists():
            return 0
        if base_url is None:
            self.auth_path.unlink()
            return 1
        sessions = self.load_all()
        removed = 1 if sessions.pop(base_url.rstrip("/"), None) else 0
        if sessions:
            payload = {
                url: {
                    "cookies": [asdict(cookie) for cookie in session.cookies],
                    "created_at": session.created_at,
                    "updated_at": session.updated_at,
                }
                for url, session in sessions.items()
            }
            self.auth_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        elif self.auth_path.exists():
            self.auth_path.unlink()
        return removed
