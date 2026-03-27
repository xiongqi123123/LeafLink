from __future__ import annotations

import io
import unittest
import zipfile

import bootstrap
from leaflink.client.models import AuthSession, ProjectSummary, SessionCookie
from leaflink.client.overleaf_client import OverleafClient
from leaflink.exceptions import ClientError


class _StubListClient(OverleafClient):
    def __init__(self) -> None:
        session = AuthSession(
            base_url="https://cn.overleaf.com",
            cookies=[SessionCookie(name="sharelatex.sid", value="x", domain=".overleaf.com")],
            created_at="now",
            updated_at="now",
        )
        super().__init__("https://cn.overleaf.com", session)

    def _get_dashboard_csrf_token(self) -> str:
        return "csrf-token"

    def _request_json(self, method: str, url: str, payload=None, headers=None):
        if url.endswith("/api/project"):
            return {
                "totalSize": 2,
                "projects": [
                    {"id": "p1", "name": "Paper A", "lastUpdated": "2026-03-27T00:00:00.000Z"},
                    {"id": "p2", "name": "Paper B", "lastUpdated": "2026-03-26T00:00:00.000Z"},
                ],
            }
        raise AssertionError(f"unexpected request: {method} {url}")

    def _request(self, method: str, url: str, data=None, headers=None):
        if "/project/" in url:
            return b"<html><title>Paper A - Overleaf</title></html>"
        raise AssertionError(f"unexpected request: {method} {url}")


class _StubResolveClient(_StubListClient):
    def __init__(self, projects: list[ProjectSummary]) -> None:
        super().__init__()
        self._projects = projects

    def list_projects(self) -> list[ProjectSummary]:
        return self._projects

    def _request(self, method: str, url: str, data=None, headers=None):
        project_id = url.rsplit("/", 1)[-1]
        return f"<html><title>{project_id} - Overleaf</title></html>".encode()


class _StubHistoryClient(_StubListClient):
    def list_projects(self) -> list[ProjectSummary]:
        return [ProjectSummary(project_id="p1", name="Paper A")]

    def download_project_archive(self, project_id: str):
        from leaflink.client.models import DownloadedArchive

        return DownloadedArchive(
            project_id=project_id,
            project_name="Paper A",
            files={"main.tex": b"hello", "refs.bib": b"@book{a}"},
        )

    def _request_json(self, method: str, url: str, payload=None, headers=None):
        response = self._request_json_value(method, url, payload=payload, headers=headers)
        if isinstance(response, dict):
            return response
        return {}

    def _request_json_value(self, method: str, url: str, payload=None, headers=None):
        if url.endswith("/latest/history"):
            return {
                "chunk": {
                    "history": {
                        "changes": [
                            {
                                "timestamp": "2026-03-27T01:23:45.000Z",
                                "v2Authors": ["user-1"],
                                "operations": [{"pathname": "main.tex"}],
                            }
                        ]
                    }
                }
            }
        if url.endswith("/changes/users"):
            return [{"user_id": "user-1", "first_name": "Alice", "last_name": "Zhang"}]
        return {}


class OverleafClientTests(unittest.TestCase):
    def test_list_projects_uses_api_payload(self) -> None:
        client = _StubListClient()
        projects = client.list_projects()
        self.assertEqual([(item.project_id, item.name) for item in projects], [("p1", "Paper A"), ("p2", "Paper B")])
        self.assertEqual(projects[0].updated_at, "2026-03-27T00:00:00.000Z")

    def test_resolve_project_by_exact_name_uses_list_lookup(self) -> None:
        client = _StubResolveClient(
            [
                ProjectSummary(project_id="id-1", name="梁承伟简历"),
                ProjectSummary(project_id="id-2", name="Paper B"),
            ]
        )
        info = client.resolve_project("梁承伟简历")
        self.assertEqual(info.project_id, "id-1")
        self.assertEqual(info.name, "梁承伟简历")

    def test_resolve_project_by_duplicate_name_raises_clear_error(self) -> None:
        client = _StubResolveClient(
            [
                ProjectSummary(project_id="id-1", name="Same"),
                ProjectSummary(project_id="id-2", name="Same"),
            ]
        )
        with self.assertRaises(ClientError):
            client.resolve_project("Same")

    def test_get_project_snapshot_enriches_remote_file_metadata(self) -> None:
        client = _StubHistoryClient()
        snapshot = client.get_project_snapshot("p1")
        self.assertEqual(snapshot.files["main.tex"].updated_at, "2026-03-27T01:23:45.000Z")
        self.assertEqual(snapshot.files["main.tex"].updated_by, "Alice Zhang")

    def test_read_archive_preserves_root_relative_paths_without_dropping_first_folder(self) -> None:
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("resume.tex", "root")
            archive.writestr("fonts/Main/Fontin-SmallCaps.otf", b"font")
            archive.writestr("images/you.png", b"image")

        files = OverleafClient._read_archive(payload.getvalue())
        self.assertIn("resume.tex", files)
        self.assertIn("fonts/Main/Fontin-SmallCaps.otf", files)
        self.assertIn("images/you.png", files)

    def test_read_archive_strips_single_common_wrapper_folder(self) -> None:
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("project-name/resume.tex", "root")
            archive.writestr("project-name/fonts/Main/Fontin-SmallCaps.otf", b"font")

        files = OverleafClient._read_archive(payload.getvalue())
        self.assertIn("resume.tex", files)
        self.assertIn("fonts/Main/Fontin-SmallCaps.otf", files)
