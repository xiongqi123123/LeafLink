from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import bootstrap
from leaflink.project.metadata import ProjectConfig, ProjectMetadataStore
from leaflink.sync.ignore import IgnoreMatcher
from leaflink.sync.state import FileFingerprint, StateStore, SyncState, scan_local_files


class StateTests(unittest.TestCase):
    def test_scan_local_files_and_state_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text("hello", encoding="utf-8")
            (root / "build").mkdir()
            (root / "build" / "ignored.log").write_text("ignored", encoding="utf-8")
            matcher = IgnoreMatcher(patterns=["build/", "*.log"])
            files = scan_local_files(root, matcher)
            self.assertEqual(list(files), ["main.tex"])

            metadata = ProjectMetadataStore(root)
            metadata.init(ProjectConfig(project_id="p1", base_url="https://www.overleaf.com", project_name="Paper"))
            store = StateStore(metadata)
            state = SyncState(local_files=files, remote_files={"main.tex": FileFingerprint("main.tex", 5, 0.0, "abc")})
            store.save(state)
            loaded = store.load()
            self.assertEqual(set(loaded.local_files), {"main.tex"})
            self.assertEqual(loaded.remote_files["main.tex"].sha256, "abc")
