from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import bootstrap
from test_sync_engine import FakeClient

from leaflink.project.metadata import ProjectConfig, ProjectMetadataStore
from leaflink.sync.conflict import analyze_conflict
from leaflink.sync.engine import SyncEngine


class _RecordingClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.uploads: list[str] = []

    def upload_file(self, project_id: str, path: str, content: bytes) -> None:
        self.uploads.append(path)
        super().upload_file(project_id, path, content)


class DeletedOnBothSidesTests(unittest.TestCase):
    def _engine(self, root: Path, client: FakeClient) -> SyncEngine:
        ProjectMetadataStore(root).init(
            ProjectConfig(project_id="abc123", base_url="https://www.overleaf.com", project_name="Paper")
        )
        engine = SyncEngine(root, client)
        engine.clone_into(client.download_project_archive("abc123"), revision="r1")
        return engine

    def test_analysis_never_invents_content(self) -> None:
        analysis = analyze_conflict("a.tex", b"base", None, None)
        self.assertTrue(analysis.can_auto_merge)
        self.assertIsNone(analysis.merged_content)

    def test_push_does_not_resurrect_file_deleted_on_both_sides(self) -> None:
        for strategy in (None, "keep-local", "keep-remote", "duplicate-both"):
            with self.subTest(strategy=strategy), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                client = _RecordingClient()
                engine = self._engine(root, client)
                (root / "refs.bib").unlink()
                del client.remote_files["refs.bib"]

                report = engine.push(strategy=strategy)

                self.assertEqual(report.pushed, [])
                self.assertFalse((root / "refs.bib").exists())
                self.assertNotIn("refs.bib", client.remote_files)
                self.assertEqual(client.uploads, [])
                self.assertEqual(engine.status().conflicts, [])

    def test_pull_does_not_resurrect_file_deleted_on_both_sides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = _RecordingClient()
            engine = self._engine(root, client)
            (root / "refs.bib").unlink()
            del client.remote_files["refs.bib"]

            engine.pull(strategy="keep-local")

            self.assertFalse((root / "refs.bib").exists())
            self.assertEqual(client.uploads, [])


if __name__ == "__main__":
    unittest.main()
