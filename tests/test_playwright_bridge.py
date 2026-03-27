from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

import bootstrap
from leaflink.client.models import AuthSession, SessionCookie
from leaflink.client.playwright_bridge import (
    extract_project_from_socket_frame,
    extract_project_tree_from_browser_model,
    load_project_tree_from_browser,
)


class PlaywrightBridgeTests(unittest.TestCase):
    def test_extract_project_tree_from_browser_model(self) -> None:
        model = {
            "_id": "project-1",
            "name": "Paper",
            "rootFolder": [
                {
                    "_id": "root-folder",
                    "name": "rootFolder",
                    "folders": [
                        {
                            "_id": "figs-folder",
                            "name": "figs",
                            "folders": [],
                            "docs": [],
                            "fileRefs": [{"_id": "img-1", "name": "plot.pdf"}],
                        }
                    ],
                    "docs": [{"_id": "doc-1", "name": "main.tex"}],
                    "fileRefs": [{"_id": "bib-1", "name": "refs.bib"}],
                }
            ],
        }
        tree = extract_project_tree_from_browser_model(model)
        self.assertEqual(tree.project_id, "project-1")
        self.assertEqual(tree.root_folder_id, "root-folder")
        self.assertEqual(tree.entities["main.tex"].entity_type, "doc")
        self.assertEqual(tree.entities["refs.bib"].entity_type, "file")
        self.assertEqual(tree.entities["figs"].entity_type, "folder")
        self.assertEqual(tree.entities["figs/plot.pdf"].parent_folder_id, "figs-folder")

    def test_extract_project_from_socket_frame(self) -> None:
        frame = (
            '5:::{"name":"joinProjectResponse","args":[{"project":{"_id":"project-1","name":"Paper",'
            '"rootFolder":[{"_id":"root-folder","name":"rootFolder","folders":[],"docs":[],'
            '"fileRefs":[]}]}}]}'
        )
        project = extract_project_from_socket_frame(frame)
        self.assertIsNotNone(project)
        self.assertEqual(project["_id"], "project-1")
        self.assertEqual(project["rootFolder"][0]["_id"], "root-folder")

    def test_load_project_tree_uses_editor_route_and_accepts_non_project_response_urls(self) -> None:
        captured_url: dict[str, str] = {}
        project_payload = {
            "project": {
                "_id": "project-1",
                "name": "Paper",
                "rootFolder": [
                    {
                        "_id": "root-folder",
                        "name": "rootFolder",
                        "folders": [],
                        "docs": [{"_id": "doc-1", "name": "main.tex"}],
                        "fileRefs": [],
                    }
                ],
            }
        }

        class _FakeResponse:
            def __init__(self, url: str) -> None:
                self.url = url
                self.headers = {"content-type": "application/json"}

            def json(self):
                return project_payload

        class _FakePage:
            def __init__(self) -> None:
                self._response_handler = None
                self._websocket_handler = None

            def on(self, event: str, handler) -> None:
                if event == "response":
                    self._response_handler = handler
                elif event == "websocket":
                    self._websocket_handler = handler

            def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
                captured_url["value"] = url
                if self._response_handler is not None:
                    self._response_handler(_FakeResponse("https://cn.overleaf.com/socket.io/bootstrap"))
                if self._websocket_handler is not None:
                    class _FakeWebSocket:
                        def on(self, event: str, handler) -> None:
                            if event == "framereceived":
                                handler(
                                    '5:::{"name":"joinProjectResponse","args":[{"project":{"_id":"project-1",'
                                    '"name":"Paper","rootFolder":[{"_id":"root-folder","name":"rootFolder",'
                                    '"folders":[],"docs":[{"_id":"doc-1","name":"main.tex"}],"fileRefs":[]}]}}]}'
                                )

                    self._websocket_handler(_FakeWebSocket())

            def evaluate(self, script: str):
                return None

            def wait_for_timeout(self, timeout_ms: int) -> None:
                return None

        class _FakeContext:
            def add_cookies(self, cookies) -> None:
                return None

            def new_page(self) -> _FakePage:
                return _FakePage()

        class _FakeBrowser:
            def new_context(self) -> _FakeContext:
                return _FakeContext()

            def close(self) -> None:
                return None

        class _FakePlaywright:
            chromium = None

            def __init__(self) -> None:
                self.chromium = self

            def launch(self, headless: bool = True) -> _FakeBrowser:
                return _FakeBrowser()

        class _FakePlaywrightManager:
            def __enter__(self) -> _FakePlaywright:
                return _FakePlaywright()

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

        fake_module = type("FakePlaywrightModule", (), {"sync_playwright": lambda: _FakePlaywrightManager()})
        session = AuthSession(
            base_url="https://cn.overleaf.com",
            cookies=[SessionCookie(name="sharelatex.sid", value="x", domain="cn.overleaf.com")],
            created_at="now",
            updated_at="now",
        )

        with patch.dict(sys.modules, {"playwright.sync_api": fake_module}):
            tree = load_project_tree_from_browser("https://cn.overleaf.com", session, "project-1", timeout_seconds=1)

        self.assertEqual(captured_url["value"], "https://cn.overleaf.com/Project/project-1")
        self.assertEqual(tree.project_id, "project-1")
        self.assertIn("main.tex", tree.entities)
