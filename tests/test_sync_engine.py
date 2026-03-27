from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import bootstrap
from leaflink.client.models import DownloadedArchive, ProjectInfo, ProjectSummary, RemoteFile, RemoteProjectSnapshot
from leaflink.project.metadata import ProjectConfig, ProjectMetadataStore
from leaflink.sync.engine import SyncEngine
from leaflink.sync.state import StateStore, remote_snapshot_to_fingerprints, scan_local_files
from leaflink.sync.watcher import BatchedLocalChanges
from leaflink.utils.hashing import sha256_bytes


class FakeClient:
    def __init__(self) -> None:
        self.remote_files = {"main.tex": b"hello\n", "refs.bib": b"@book{a}\n"}
        self.project_id = "abc123"
        self.project_name = "Paper"

    def list_projects(self) -> list[ProjectSummary]:
        return [ProjectSummary(project_id=self.project_id, name=self.project_name)]

    def resolve_project(self, project_url_or_id: str) -> ProjectInfo:
        return ProjectInfo(project_id=self.project_id, name=self.project_name, base_url="https://www.overleaf.com")

    def get_project_snapshot(self, project_id: str) -> RemoteProjectSnapshot:
        return RemoteProjectSnapshot(
            project_id=project_id,
            project_name=self.project_name,
            revision="r1",
            files={
                path: RemoteFile(path=path, content_hash=sha256_bytes(content), size=len(content))
                for path, content in self.remote_files.items()
            },
        )

    def download_project_archive(self, project_id: str) -> DownloadedArchive:
        return DownloadedArchive(project_id=project_id, project_name=self.project_name, files=dict(self.remote_files))

    def upload_file(self, project_id: str, path: str, content: bytes) -> None:
        self.remote_files[path] = content

    def delete_file(self, project_id: str, path: str) -> None:
        self.remote_files.pop(path, None)

    def download_pdf(self, project_id: str) -> bytes:
        return b"%PDF-1.7 mock"


class SyncEngineTests(unittest.TestCase):
    def test_pull_and_push_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata = ProjectMetadataStore(root)
            metadata.init(ProjectConfig(project_id="abc123", base_url="https://www.overleaf.com", project_name="Paper"))
            client = FakeClient()
            engine = SyncEngine(root, client)

            engine.clone_into(client.download_project_archive("abc123"), revision="r1")
            self.assertEqual((root / "main.tex").read_text(encoding="utf-8"), "hello\n")

            (root / "main.tex").write_text("local edit\n", encoding="utf-8")
            push_report = engine.push()
            self.assertIn("main.tex", push_report.pushed)
            self.assertEqual(client.remote_files["main.tex"], b"local edit\n")

    def test_pull_duplicate_both_on_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata = ProjectMetadataStore(root)
            metadata.init(ProjectConfig(project_id="abc123", base_url="https://www.overleaf.com", project_name="Paper"))
            client = FakeClient()
            engine = SyncEngine(root, client)
            engine.clone_into(client.download_project_archive("abc123"), revision="r1")

            (root / "main.tex").write_text("local edit\n", encoding="utf-8")
            client.remote_files["main.tex"] = b"remote edit\n"
            report = engine.pull(strategy="duplicate-both")

            conflict_copy = root / "main.remote.conflict.tex"
            self.assertIn("main.remote.conflict.tex", report.pulled)
            self.assertEqual(conflict_copy.read_text(encoding="utf-8"), "remote edit\n")
            self.assertEqual((root / "main.tex").read_text(encoding="utf-8"), "local edit\n")

    def test_pull_auto_merges_non_overlapping_text_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata = ProjectMetadataStore(root)
            metadata.init(ProjectConfig(project_id="abc123", base_url="https://www.overleaf.com", project_name="Paper"))
            client = FakeClient()
            client.remote_files["main.tex"] = b"title: old\nbody: old\nfooter: old\n"
            engine = SyncEngine(root, client)
            engine.clone_into(client.download_project_archive("abc123"), revision="r1")

            (root / "main.tex").write_text("title: local\nbody: old\nfooter: old\n", encoding="utf-8")
            client.remote_files["main.tex"] = b"title: old\nbody: old\nfooter: remote\n"

            report = engine.pull()

            self.assertIn("main.tex", report.merged)
            self.assertEqual(
                (root / "main.tex").read_text(encoding="utf-8"),
                "title: local\nbody: old\nfooter: remote\n",
            )
            self.assertEqual(
                client.remote_files["main.tex"],
                b"title: local\nbody: old\nfooter: remote\n",
            )

    def test_debounce_batching(self) -> None:
        batch = BatchedLocalChanges()
        batch.record("main.tex", timestamp=10.0)
        batch.record("refs.bib", timestamp=10.5)
        self.assertFalse(batch.ready(1.0, now=11.0))
        self.assertTrue(batch.ready(1.0, now=11.6))
        self.assertEqual(batch.pop(), ["main.tex", "refs.bib"])

    def test_status_reports_persistent_divergence_as_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata = ProjectMetadataStore(root)
            metadata.init(ProjectConfig(project_id="abc123", base_url="https://www.overleaf.com", project_name="Paper"))
            client = FakeClient()
            engine = SyncEngine(root, client)
            engine.clone_into(client.download_project_archive("abc123"), revision="r1")

            (root / "main.tex").write_text("local edit\n", encoding="utf-8")
            client.remote_files["main.tex"] = b"remote edit\n"
            state = engine.state_store.load()
            state.local_files = scan_local_files(root, engine.ignore)
            state.remote_files = remote_snapshot_to_fingerprints(client.get_project_snapshot("abc123"))
            engine.state_store.save(state)

            report = engine.status()
            self.assertIn("main.tex", report.conflicts)
