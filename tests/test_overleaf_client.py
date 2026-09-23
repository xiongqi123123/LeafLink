from __future__ import annotations

import io
import unittest
import urllib.request
import zipfile
from unittest.mock import patch

import bootstrap
from leaflink.client.models import AuthSession, ProjectSummary, RemoteEntity, RemoteProjectTree, SessionCookie
from leaflink.client.overleaf_client import OverleafClient, _SameOriginRedirectHandler
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

    def test_redirect_handler_rejects_cross_origin_redirects(self) -> None:
        handler = _SameOriginRedirectHandler("https://overleaf.lan.x-lab.cc")
        request = urllib.request.Request("https://overleaf.lan.x-lab.cc/project/abc")

        with self.assertRaises(ClientError):
            handler.redirect_request(
                request,
                fp=None,
                code=302,
                msg="Found",
                headers={},
                newurl="https://www.overleaf.com/project/abc",
            )


class ClientPerformanceTests(unittest.TestCase):
    def test_sync_snapshot_uses_only_archive_and_preserves_content_fingerprints(self) -> None:
        client = _StubHistoryClient()
        enriched = client.get_project_snapshot("p1")
        with patch.object(client, "resolve_project", side_effect=AssertionError("project lookup")), \
             patch.object(client, "_get_project_history_metadata", side_effect=AssertionError("history lookup")):
            snapshot = client.get_sync_snapshot("p1")
        self.assertEqual(set(snapshot.files), set(enriched.files))
        for path, file in snapshot.files.items():
            self.assertEqual(file.content_hash, enriched.files[path].content_hash)
            self.assertEqual(file.size, enriched.files[path].size)
            self.assertIsNone(file.updated_at)
            self.assertIsNone(file.updated_by)

    def test_upload_batch_reuses_root_but_delete_refreshes_entity_ids(self) -> None:
        client = _StubListClient()
        old_tree = RemoteProjectTree("p1", "root", {
            "main.tex": RemoteEntity("old-id", "doc", "main.tex", "main.tex"),
        })
        new_tree = RemoteProjectTree("p1", "root", {
            "main.tex": RemoteEntity("new-id", "doc", "main.tex", "main.tex"),
        })
        with patch("leaflink.client.overleaf_client.load_project_tree_from_browser", side_effect=[old_tree, new_tree]) as load, \
             patch.object(client, "_get_csrf_token", return_value="csrf"), \
             patch.object(client, "_request", return_value=b'{"success":true}') as request:
            client.upload_file("p1", "main.tex", b"one")
            client.upload_file("p1", "refs.bib", b"two")
            self.assertEqual(load.call_count, 1)
            client.delete_file("p1", "main.tex")
            self.assertEqual(load.call_count, 2)
            self.assertEqual(request.call_args.args[:2], ("DELETE", "https://cn.overleaf.com/project/p1/doc/new-id"))

    def test_operation_reset_expires_root_and_tree_for_selected_project(self) -> None:
        client = _StubListClient()
        trees = [RemoteProjectTree("p1", "root-one", {}), RemoteProjectTree("p1", "root-two", {})]
        with patch("leaflink.client.overleaf_client.load_project_tree_from_browser", side_effect=trees) as load, \
             patch.object(client, "_get_csrf_token", return_value="csrf"), \
             patch.object(client, "_request", return_value=b'{"success":true}') as request:
            client.upload_file("p1", "main.tex", b"one")
            client.reset_remote_cache("p1")
            client.upload_file("p1", "main.tex", b"two")
            self.assertEqual(load.call_count, 2)
            self.assertIn("folder_id=root-two", request.call_args.args[1])
            client.reset_remote_cache()
            self.assertEqual(client._root_folder_ids, {})
            self.assertEqual(client._project_trees, {})
