from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
import bootstrap
from test_sync_engine import FakeClient
from leaflink.project.metadata import ProjectConfig, ProjectMetadataStore
from leaflink.sync.engine import SyncEngine
from leaflink.sync.ignore import IgnoreMatcher

class IgnoreSyncTests(unittest.TestCase):
    def setup_project(self, root, rules=""):
        ProjectMetadataStore(root).init(ProjectConfig(project_id="abc123", base_url="https://www.overleaf.com", project_name="Test"))
        client = FakeClient()
        client.remote_files[".leafignore"] = rules.encode()
        (root / ".leafignore").write_text(rules)
        return client, SyncEngine(root, client)

    def test_clone_and_pull_do_not_write_ignored_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            c, e = self.setup_project(root, "secret.txt\n")
            c.remote_files["secret.txt"] = b"remote"
            e.clone_into(c.download_project_archive("abc123"))
            self.assertFalse((root / "secret.txt").exists())
            (root / "secret.txt").write_bytes(b"local")
            c.remote_files["secret.txt"] = b"changed"
            self.assertNotIn("secret.txt", e.status().remote_changes.all_paths())
            e.pull()
            self.assertEqual((root / "secret.txt").read_bytes(), b"local")
            del c.remote_files["secret.txt"]
            e.pull()
            self.assertEqual((root / "secret.txt").read_bytes(), b"local")

    def test_new_ignore_does_not_delete_tracked_remote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            c, e = self.setup_project(root)
            c.remote_files["secret.txt"] = b"original"
            e.clone_into(c.download_project_archive("abc123"))
            (root / ".leafignore").write_text("secret.txt\n")
            self.assertNotIn("secret.txt", e.status().local_changes.deleted)
            (root / "secret.txt").write_bytes(b"local edit")
            e.push()
            self.assertEqual(c.remote_files["secret.txt"], b"original")

    def test_remote_ignore_rules_apply_during_clone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            c, e = self.setup_project(root)
            (root / ".leafignore").unlink()
            c.remote_files.update({".leafignore": b"build/\n", "build/out.pdf": b"pdf"})
            e.clone_into(c.download_project_archive("abc123"))
            self.assertFalse((root / "build/out.pdf").exists())

    def test_ignored_new_file_not_uploaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            c, e = self.setup_project(root, "secret.txt\n")
            e.clone_into(c.download_project_archive("abc123"))
            (root / "secret.txt").write_bytes(b"private")
            e.push()
            self.assertNotIn("secret.txt", c.remote_files)

    def test_unignore_preserves_conflict_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            c, e = self.setup_project(root)
            c.remote_files["secret.txt"] = b"base\n"
            e.clone_into(c.download_project_archive("abc123"))
            (root / ".leafignore").write_text("secret.txt\n")
            (root / "secret.txt").write_bytes(b"local\n")
            c.remote_files["secret.txt"] = b"remote\n"
            e.push()
            (root / ".leafignore").write_text("")
            self.assertIn("secret.txt", e.status().conflicts)

    def test_globs_and_negation(self):
        m = IgnoreMatcher(["*.pdf", "!figures/keep.pdf", "/root.txt", "build/", "figures/*.tmp"])
        self.assertFalse(m.matches("figures/keep.pdf"))
        self.assertTrue(m.matches("figures/other.pdf"))
        self.assertTrue(m.matches("root.txt"))
        self.assertFalse(m.matches("nested/root.txt"))
        self.assertFalse(m.matches("build"))
        self.assertTrue(m.matches("nested/build/output"))
        self.assertFalse(m.matches("figures/deep/file.tmp"))
        self.assertTrue(IgnoreMatcher(["**/*.tmp"]).matches("file.tmp"))
        self.assertTrue(IgnoreMatcher(["**/*.tmp"]).matches("a/b/file.tmp"))
        self.assertTrue(IgnoreMatcher(["!.leaflink/**"]).matches(".leaflink/state.json"))

    def test_new_rules_protect_tracked_files_in_fresh_engine(self):
        for operation in ("pull", "push"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                c, e = self.setup_project(root)
                c.remote_files["secret.txt"] = b"original"
                e.clone_into(c.download_project_archive("abc123"))
                (root / ".leafignore").write_text("secret.txt\n")
                if operation == "pull":
                    del c.remote_files["secret.txt"]
                else:
                    (root / "secret.txt").unlink()
                e = SyncEngine(root, c)
                getattr(e, operation)()
                if operation == "pull":
                    self.assertEqual((root / "secret.txt").read_bytes(), b"original")
                else:
                    self.assertEqual(c.remote_files["secret.txt"], b"original")

    def test_custom_ignore_and_metadata_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            c, _ = self.setup_project(root)
            (root / "custom.ignore").write_text("secret.txt\n!**\nsecret.txt\n")
            c.remote_files.update({"secret.txt": b"private", ".git/config": b"bad", ".leaflink/state.json": b"bad"})
            e = SyncEngine(root, c, ignore_file="custom.ignore")
            e.clone_into(c.download_project_archive("abc123"))
            self.assertFalse((root / "secret.txt").exists())
            self.assertFalse((root / ".git/config").exists())
            self.assertNotEqual((root / ".leaflink/state.json").read_bytes(), b"bad")

    def test_dry_run_does_not_modify_ignored_or_visible_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            c, e = self.setup_project(root, "secret.txt\n")
            e.clone_into(c.download_project_archive("abc123"))
            (root / "secret.txt").write_bytes(b"private")
            (root / "main.tex").write_bytes(b"change")
            before = dict(c.remote_files)
            e.push(dry_run=True)
            self.assertEqual(c.remote_files, before)
            self.assertEqual((root / "secret.txt").read_bytes(), b"private")

    def test_remote_rule_update_filters_same_pull(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            c, e = self.setup_project(root)
            e.clone_into(c.download_project_archive("abc123"))
            c.remote_files.update({".leafignore": b"secret.txt\n", "secret.txt": b"remote"})
            e.pull(dry_run=True)
            self.assertEqual((root / ".leafignore").read_text(), "")
            self.assertFalse((root / "secret.txt").exists())
            e.pull()
            self.assertEqual((root / ".leafignore").read_text(), "secret.txt\n")
            self.assertFalse((root / "secret.txt").exists())

    def test_remote_rule_update_protects_same_pull_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            c, e = self.setup_project(root)
            c.remote_files["secret.txt"] = b"local copy"
            e.clone_into(c.download_project_archive("abc123"))
            c.remote_files[".leafignore"] = b"secret.txt\n"
            del c.remote_files["secret.txt"]
            e.pull()
            self.assertEqual((root / "secret.txt").read_bytes(), b"local copy")
