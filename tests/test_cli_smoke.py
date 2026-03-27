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
from leaflink.cli import (
    _display_width,
    _format_conflict_preview,
    _format_change_suffix,
    _looks_like_project_reference,
    _pad_display,
    _print_project_list,
    _print_sync_event,
    _resolve_clone_inputs,
    _style_text,
    _truncate_display,
)
from leaflink.client.models import ProjectSummary
from leaflink.sync.diff import ChangeSet
from leaflink.sync.engine import ChangeDetails, LocalChangeEvent, SyncLifecycleEvent, SyncReport


class CliSmokeTests(unittest.TestCase):
    def _run(self, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, "-m", "leaflink", *args]
        return subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            text=True,
            capture_output=True,
        )

    def test_help_and_cookie_import_logout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cookie_file = root / "cookies.json"
            cookie_file.write_text(
                json.dumps(
                    [
                        {
                            "name": "sharelatex.sid",
                            "value": "secret",
                            "domain": "www.overleaf.com",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path.cwd() / "src")
            env["LEAFLINK_CONFIG_DIR"] = str(root / "config")

            help_result = self._run("--help", env=env)
            self.assertEqual(help_result.returncode, 0)
            self.assertIn("Sync local folders", help_result.stdout)

            import_result = self._run("auth", "import", "--cookie-file", str(cookie_file), env=env)
            self.assertEqual(import_result.returncode, 0, import_result.stderr)
            self.assertIn("Imported cookies", import_result.stdout)

            logout_result = self._run("logout", env=env)
            self.assertEqual(logout_result.returncode, 0, logout_result.stderr)
            self.assertIn("Removed saved auth session", logout_result.stdout)

    def test_print_project_list_formats_columns(self) -> None:
        buffer = StringIO()
        projects = [
            ProjectSummary(project_id="abc123", name="Paper", updated_at="2026-03-27T00:00:00Z"),
            ProjectSummary(project_id="def456", name="中文项目", updated_at=None),
        ]
        with redirect_stdout(buffer):
            _print_project_list(projects)
        output = buffer.getvalue()
        self.assertIn("Name", output)
        self.assertIn("Project ID", output)
        self.assertIn("中文项目", output)
        self.assertIn("abc123", output)

    def test_display_padding_uses_terminal_width(self) -> None:
        self.assertEqual(_display_width("abc"), 3)
        self.assertEqual(_display_width("中文"), 4)
        self.assertEqual(_pad_display("中文", 6), "中文  ")

    def test_truncate_display_uses_ellipsis(self) -> None:
        self.assertEqual(_truncate_display("中文简历模板（Chinese Resume Template）", 20), "中文简历模板（Chine…")

    def test_format_change_suffix_and_sync_event_output(self) -> None:
        self.assertIn("saved ", _format_change_suffix(ChangeDetails(path="main.tex", changed_at="2026-03-27T02:00:00+00:00")))
        self.assertIn("by Alice", _format_change_suffix(ChangeDetails(path="main.tex", changed_by="Alice")))

        report = SyncReport(
            local_changes=ChangeSet(),
            remote_changes=ChangeSet(modified=["main.tex"]),
            conflicts=[],
            pulled=["main.tex"],
            remote_details={"main.tex": ChangeDetails(path="main.tex", changed_at="2026-03-27T02:00:00+00:00", changed_by="Alice")},
        )
        buffer = StringIO()
        with redirect_stdout(buffer):
            _print_sync_event(SyncLifecycleEvent(stage="startup", message="Starting local watcher.", occurred_at="2026-03-27T02:00:01+00:00"))
            _print_sync_event(LocalChangeEvent(path="main.tex", changed_at="2026-03-27T02:00:02+00:00"))
            _print_sync_event(report)
        output = buffer.getvalue()
        self.assertIn("[sync] Starting local watcher.", output)
        self.assertIn("[local] modified: main.tex", output)
        self.assertIn("[remote] changed: main.tex", output)
        self.assertIn("by Alice", output)

    def test_conflict_preview_is_condensed_to_relevant_hunk(self) -> None:
        preview = "\n".join(
            [
                "line 1",
                "line 2",
                "line 3",
                "<<<<<<< local/resume.tex",
                "local line",
                "||||||| base/resume.tex",
                "base line",
                "=======",
                "remote line",
                ">>>>>>> remote/resume.tex",
                "line 4",
                "line 5",
                "line 6",
            ]
        )

        formatted = _format_conflict_preview(preview, context_lines=1)

        self.assertIn("line 3", formatted)
        self.assertIn("line 4", formatted)
        self.assertNotIn("line 1", formatted)
        self.assertNotIn("line 6", formatted)
        self.assertIn("<<<<<<< local/resume.tex", formatted)

    def test_style_text_is_plain_when_not_in_tty(self) -> None:
        self.assertEqual(_style_text("hello", "red"), "hello")

    def test_resolve_clone_inputs_supports_project_names_with_spaces(self) -> None:
        project_ref, target_dir = _resolve_clone_inputs(["ACM", "MM", "2026", "xiongqi"], None)
        self.assertEqual(project_ref, "ACM MM 2026 xiongqi")
        self.assertIsNone(target_dir)

        project_ref, target_dir = _resolve_clone_inputs(["69c0a83c665d307225ca1e2a", "paper-dir"], None)
        self.assertEqual(project_ref, "69c0a83c665d307225ca1e2a")
        self.assertEqual(str(target_dir), "paper-dir")
        self.assertTrue(_looks_like_project_reference("69c0a83c665d307225ca1e2a"))
        self.assertFalse(_looks_like_project_reference("ACM"))
