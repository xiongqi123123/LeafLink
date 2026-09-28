from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import bootstrap
from test_sync_engine import FakeClient

from leaflink import cli
from leaflink.project.metadata import ProjectConfig, ProjectMetadataStore
from leaflink.sync.engine import SyncEngine
from leaflink.sync.ignore import IgnoreMatcher, default_ignore_file_text


def _init(root: Path) -> None:
    ProjectMetadataStore(root).init(
        ProjectConfig(project_id="abc123", base_url="https://www.overleaf.com", project_name="Paper")
    )


class DefaultIgnoreFileTests(unittest.TestCase):
    def test_template_ignores_itself_and_latex_artifacts(self) -> None:
        matcher = IgnoreMatcher.from_text(default_ignore_file_text())
        self.assertTrue(matcher.matches(".leafignore"))
        self.assertTrue(matcher.matches("main.toc"))
        self.assertFalse(matcher.matches("sub/.leafignore"))
        self.assertFalse(matcher.matches("figures/plot.pdf"))
        self.assertFalse(matcher.matches("main.tex"))

    def test_clone_creates_local_only_ignore_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init(root)
            client = FakeClient()
            engine = SyncEngine(root, client)

            self.assertTrue(engine.clone_into(client.download_project_archive("abc123"), revision="r1"))
            self.assertIn("/.leafignore", (root / ".leafignore").read_text(encoding="utf-8"))

            (root / "main.toc").write_text("toc", encoding="utf-8")
            (root / "intro.tex").write_text("intro", encoding="utf-8")
            report = engine.push()
            self.assertEqual(report.pushed, ["intro.tex"])
            self.assertNotIn(".leafignore", client.remote_files)
            self.assertNotIn("main.toc", client.remote_files)

    def test_clone_keeps_remote_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init(root)
            client = FakeClient()
            client.remote_files[".leafignore"] = b"build/\n"
            created = SyncEngine(root, client).clone_into(client.download_project_archive("abc123"))
            self.assertFalse(created)
            self.assertEqual((root / ".leafignore").read_text(encoding="utf-8"), "build/\n")

    def test_existing_project_gets_file_but_deleted_tracked_policy_stays_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init(root)
            client = FakeClient()
            client.remote_files[".leafignore"] = b"build/\n"
            engine = SyncEngine(root, client)
            engine.clone_into(client.download_project_archive("abc123"))

            # The shared policy was synced before; deleting it locally is intentional.
            (root / ".leafignore").unlink()
            self.assertFalse(engine.ensure_ignore_file())
            self.assertFalse((root / ".leafignore").exists())

        with tempfile.TemporaryDirectory() as tmp:
            # An old clone that never had a policy gets the starter file.
            root = Path(tmp)
            _init(root)
            client = FakeClient()
            engine = SyncEngine(root, client)
            engine.clone_into(client.download_project_archive("abc123"))
            (root / ".leafignore").unlink()
            self.assertTrue(engine.ensure_ignore_file())
            self.assertTrue((root / ".leafignore").exists())

    def test_rule_edits_apply_on_next_push(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init(root)
            client = FakeClient()
            engine = SyncEngine(root, client)
            engine.clone_into(client.download_project_archive("abc123"))
            policy = root / ".leafignore"

            policy.write_text(policy.read_text(encoding="utf-8") + "notes.txt\n", encoding="utf-8")
            (root / "notes.txt").write_text("private", encoding="utf-8")
            self.assertEqual(engine.push().pushed, [])

            # Removing rules makes the files visible again, including the policy itself.
            policy.write_text("", encoding="utf-8")
            self.assertEqual(sorted(engine.push().pushed), [".leafignore", "notes.txt"])


class CliDefaultIgnoreTests(unittest.TestCase):
    def _run(self, root: Path, *args: str) -> str:
        buffer = StringIO()
        with patch.dict(os.environ, {"LEAFLINK_CONFIG_DIR": str(root / "config")}), redirect_stdout(buffer):
            code = cli.main([*args, "--project-dir", str(root / "paper")], client_factory=lambda _: self.client)
        self.assertEqual(code, 0)
        return buffer.getvalue()

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        paper = self.root / "paper"
        paper.mkdir()
        _init(paper)
        self.client = FakeClient()
        SyncEngine(paper, self.client).clone_into(self.client.download_project_archive("abc123"))
        (paper / ".leafignore").unlink()

    def test_dry_run_does_not_create_file(self) -> None:
        self._run(self.root, "push", "--dry-run")
        self.assertFalse((self.root / "paper" / ".leafignore").exists())

    def test_status_creates_file_and_says_so(self) -> None:
        output = self._run(self.root, "status")
        self.assertIn("Created .leafignore", output)
        self.assertTrue((self.root / "paper" / ".leafignore").exists())


if __name__ == "__main__":
    unittest.main()
