from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import bootstrap
from test_sync_engine import FakeClient

from leaflink import cli, doctor
from leaflink.exceptions import BrowserUnavailableError, ClientError
from leaflink.project.metadata import ProjectConfig, ProjectMetadataStore
from leaflink.sync.engine import SyncEngine
from leaflink.utils.browser import launch_error, load_sync_playwright


class LaunchErrorTests(unittest.TestCase):
    def test_missing_executable_is_flagged(self) -> None:
        error = launch_error(RuntimeError("BrowserType.launch: Executable doesn't exist at /x/chrome-headless-shell"))
        self.assertTrue(error.missing)
        self.assertIn("playwright install chromium", str(error))

    def test_other_failures_keep_first_line(self) -> None:
        error = launch_error(RuntimeError("\nBrowserType.launch: Missing X server or $DISPLAY\nCall log: ..."))
        self.assertFalse(error.missing)
        self.assertEqual(str(error), "Could not start Chromium: BrowserType.launch: Missing X server or $DISPLAY")

    def test_missing_playwright_package(self) -> None:
        with patch.dict(sys.modules, {"playwright.sync_api": None}):
            with self.assertRaises(BrowserUnavailableError) as ctx:
                load_sync_playwright()
        self.assertIn("pip install -U leaflink", str(ctx.exception))


class _BrowserlessClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.writes: list[str] = []

    def prepare_remote_writes(self, project_id: str) -> None:
        raise BrowserUnavailableError("no chromium", missing=True)

    def upload_file(self, project_id: str, path: str, content: bytes) -> None:
        self.writes.append(f"upload {path}")

    def delete_file(self, project_id: str, path: str) -> None:
        self.writes.append(f"delete {path}")


class PushPreflightTests(unittest.TestCase):
    def _engine(self, root: Path, client: FakeClient) -> SyncEngine:
        ProjectMetadataStore(root).init(
            ProjectConfig(project_id="abc123", base_url="https://www.overleaf.com", project_name="Paper")
        )
        engine = SyncEngine(root, client)
        engine.clone_into(client.download_project_archive("abc123"), revision="r1")
        return engine

    def test_push_fails_before_any_remote_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = _BrowserlessClient()
            engine = self._engine(root, client)
            (root / "refs.bib").unlink()
            (root / "main.tex").write_text("local\n", encoding="utf-8")
            client.remote_files["main.tex"] = b"remote\n"

            with self.assertRaises(BrowserUnavailableError):
                engine.push(strategy="keep-local")
            self.assertEqual(client.writes, [])

    def test_push_without_changes_does_not_need_browser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _BrowserlessClient()
            report = self._engine(Path(tmp), client).push()
            self.assertEqual(report.pushed, [])

    def test_pull_with_conflicts_checks_browser_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = _BrowserlessClient()
            engine = self._engine(root, client)
            (root / "main.tex").write_text("local\n", encoding="utf-8")
            client.remote_files["main.tex"] = b"remote\n"

            with self.assertRaises(BrowserUnavailableError):
                engine.pull(strategy="keep-local")
            self.assertEqual((root / "main.tex").read_text(encoding="utf-8"), "local\n")
            self.assertEqual(client.writes, [])


class DoctorCheckTests(unittest.TestCase):
    def test_chromium_check_reports_missing_browser(self) -> None:
        def probe() -> None:
            raise BrowserUnavailableError("missing", missing=True)

        check = doctor.check_chromium(probe)
        self.assertEqual((check.level, check.browser_missing), ("error", True))
        self.assertEqual(doctor.check_chromium(lambda: None).level, "ok")

    def test_display_warning_only_on_headless_linux(self) -> None:
        self.assertIsNotNone(doctor.check_display(env={}, platform_name="linux"))
        self.assertIsNone(doctor.check_display(env={"DISPLAY": ":0"}, platform_name="linux"))
        self.assertIsNone(doctor.check_display(env={}, platform_name="darwin"))

    def test_session_check(self) -> None:
        url = "https://www.overleaf.com"
        self.assertEqual(doctor.check_session(url, False, lambda: 0).level, "warn")
        self.assertIn("3 projects", doctor.check_session(url, True, lambda: 3).message)

        def rejected() -> int:
            raise ClientError("HTTP 403")

        self.assertEqual(doctor.check_session(url, True, rejected).level, "error")


class CliBrowserErrorTests(unittest.TestCase):
    def test_missing_browser_is_reported_without_traceback(self) -> None:
        class Client(FakeClient):
            def list_projects(self):
                raise BrowserUnavailableError("Chromium for Playwright is not installed.", missing=True)

        stderr = StringIO()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LEAFLINK_CONFIG_DIR": tmp}):
            with patch.object(cli.sys, "stdin", StringIO()), redirect_stdout(StringIO()), redirect_stderr(stderr):
                code = cli.main(["list"], client_factory=lambda base_url: Client())
        self.assertEqual(code, 1)
        self.assertIn("Chromium for Playwright is not installed", stderr.getvalue())

    def test_offer_install_respects_answer_and_flag(self) -> None:
        with patch.object(cli, "install_chromium", return_value=True) as install, redirect_stdout(StringIO()):
            with patch.object(cli.sys, "stdin", StringIO()):
                self.assertFalse(cli._offer_chromium_install())
                self.assertTrue(cli._offer_chromium_install(assume_yes=True))
            tty = type("Tty", (StringIO,), {"isatty": lambda self: True})()
            with patch.object(cli.sys, "stdin", tty):
                self.assertFalse(cli._offer_chromium_install(read_line=lambda _: "n"))
                self.assertTrue(cli._offer_chromium_install(read_line=lambda _: ""))
        self.assertEqual(install.call_count, 2)


if __name__ == "__main__":
    unittest.main()
