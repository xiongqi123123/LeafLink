from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import bootstrap
from leaflink.auth.cookie_import import (
    cookies_from_pairs,
    default_cookie_domain,
    import_cookies_from_file,
    parse_cookie_pairs,
)
from leaflink.auth.manager import AuthManager
from leaflink.cli import _prompt_cookie_pairs
from leaflink.exceptions import AuthenticationError


class CookieParsingTests(unittest.TestCase):
    def test_default_domain_covers_official_hosts_and_self_hosted(self) -> None:
        self.assertEqual(default_cookie_domain("https://www.overleaf.com"), ".overleaf.com")
        self.assertEqual(default_cookie_domain("https://cn.overleaf.com"), ".overleaf.com")
        self.assertEqual(default_cookie_domain("http://overleaf.lan:8080"), "overleaf.lan")

    def test_parse_cookie_pairs_accepts_single_pair_and_header(self) -> None:
        self.assertEqual(parse_cookie_pairs("sharelatex.sid=s%3Aabc=="), [("sharelatex.sid", "s%3Aabc==")])
        self.assertEqual(parse_cookie_pairs("a=1; b=2;"), [("a", "1"), ("b", "2")])
        with self.assertRaises(AuthenticationError):
            parse_cookie_pairs("novalue")

    def test_cookies_from_pairs_use_base_url_domain(self) -> None:
        cookies = cookies_from_pairs([("sharelatex.sid", "x")], base_url="https://overleaf.lan")
        self.assertEqual([(c.name, c.value, c.domain) for c in cookies], [("sharelatex.sid", "x", "overleaf.lan")])
        self.assertTrue(cookies[0].secure)
        self.assertFalse(cookies_from_pairs([("sharelatex.sid", "x")], base_url="http://overleaf.lan:8080")[0].secure)


class CookieFileTests(unittest.TestCase):
    def _write(self, payload: object) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "cookies.json"
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
        return path

    def test_domain_defaults_to_base_url(self) -> None:
        path = self._write([{"name": "overleaf_session2", "value": "x"}])
        cookies = import_cookies_from_file(path, base_url="https://www.overleaf.com")
        self.assertEqual(cookies[0].domain, ".overleaf.com")

    def test_plain_name_value_object_is_accepted(self) -> None:
        path = self._write({"sharelatex.sid": "x", "_csrf": "y"})
        cookies = import_cookies_from_file(path, base_url="https://overleaf.lan")
        self.assertEqual([(c.name, c.value) for c in cookies], [("sharelatex.sid", "x"), ("_csrf", "y")])

    def test_invalid_file_explains_expected_format(self) -> None:
        for payload in ("not json", [{"value": "x"}], {"cookies": "nope"}):
            with self.subTest(payload=payload):
                with self.assertRaises(AuthenticationError) as ctx:
                    import_cookies_from_file(self._write(payload), base_url="https://www.overleaf.com")
                self.assertIn('"name": "overleaf_session2"', str(ctx.exception))


class CookiePromptTests(unittest.TestCase):
    def test_prompt_collects_pairs_and_header(self) -> None:
        names = iter(["sharelatex.sid", "a=1; b=2", ""])
        with redirect_stdout(StringIO()):
            pairs = _prompt_cookie_pairs(
                "https://overleaf.lan",
                read_line=lambda _: next(names),
                read_secret=lambda _: "secret",
            )
        self.assertEqual(pairs, [("sharelatex.sid", "secret"), ("a", "1"), ("b", "2")])

    def test_prompt_requires_at_least_one_cookie(self) -> None:
        with redirect_stdout(StringIO()), self.assertRaises(AuthenticationError):
            _prompt_cookie_pairs("https://overleaf.lan", read_line=lambda _: "", read_secret=lambda _: "")


class AuthManagerPairsTests(unittest.TestCase):
    def test_login_with_pairs_saves_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = AuthManager(Path(tmp))
            session = manager.login("https://overleaf.lan", cookie_pairs=[("sharelatex.sid", "x")])
            self.assertEqual([(c.name, c.domain) for c in session.cookies], [("sharelatex.sid", "overleaf.lan")])
            self.assertEqual(manager.load("https://overleaf.lan").cookies[0].value, "x")


class CookieCliTests(unittest.TestCase):
    def _run(self, *args: str, config_dir: Path) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(bootstrap.SRC)
        env["LEAFLINK_CONFIG_DIR"] = str(config_dir)
        return subprocess.run(
            [sys.executable, "-m", "leaflink", *args],
            env=env,
            text=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
        )

    def test_auth_import_with_cookie_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            result = self._run(
                "auth", "import", "--base-url", "https://overleaf.lan", "--cookie", "sharelatex.sid=abc",
                config_dir=config_dir,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads((config_dir / "auth.json").read_text(encoding="utf-8"))
            cookie = payload["https://overleaf.lan"]["cookies"][0]
            self.assertEqual((cookie["name"], cookie["value"], cookie["domain"]), ("sharelatex.sid", "abc", "overleaf.lan"))

    def test_auth_import_without_source_or_tty_fails_with_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run("auth", "import", config_dir=Path(tmp))
            self.assertEqual(result.returncode, 1)
            self.assertIn("--cookie NAME=VALUE", result.stderr)

    def test_help_shows_cookie_file_example(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run("auth", "import", "--help", config_dir=Path(tmp))
            self.assertEqual(result.returncode, 0)
            self.assertIn('"name": "overleaf_session2"', result.stdout)
            self.assertIn("sharelatex.sid", result.stdout)


if __name__ == "__main__":
    unittest.main()
