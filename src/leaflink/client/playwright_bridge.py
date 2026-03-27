"""Browser-assisted helpers for extracting Overleaf project metadata."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

from leaflink.client.models import AuthSession, RemoteEntity, RemoteProjectTree
from leaflink.exceptions import ClientError

_PROJECT_SEARCH_SCRIPT = r"""
() => {
  const MAX_DEPTH = 6;
  const MAX_KEYS = 120;
  const seen = new WeakSet();

  const normalizeFolder = folder => ({
    _id: String(folder?._id ?? ''),
    name: String(folder?.name ?? ''),
    folders: Array.isArray(folder?.folders) ? folder.folders.map(normalizeFolder) : [],
    docs: Array.isArray(folder?.docs)
      ? folder.docs.map(doc => ({ _id: String(doc?._id ?? ''), name: String(doc?.name ?? '') }))
      : [],
    fileRefs: Array.isArray(folder?.fileRefs)
      ? folder.fileRefs.map(file => ({ _id: String(file?._id ?? ''), name: String(file?.name ?? '') }))
      : [],
  });

  const normalizeProject = project => ({
    _id: String(project?._id ?? project?.id ?? ''),
    name: String(project?.name ?? ''),
    rootFolder: Array.isArray(project?.rootFolder) ? project.rootFolder.map(normalizeFolder) : [],
  });

  const looksLikeProject = candidate =>
    !!candidate &&
    typeof candidate === 'object' &&
    (candidate._id || candidate.id) &&
    Array.isArray(candidate.rootFolder) &&
    candidate.rootFolder.length > 0;

  const visit = (value, depth) => {
    if (!value || typeof value !== 'object') return null;
    if (seen.has(value) || depth > MAX_DEPTH) return null;
    seen.add(value);

    if (looksLikeProject(value)) return normalizeProject(value);
    if (looksLikeProject(value.project)) return normalizeProject(value.project);

    let entries = [];
    try {
      entries = Object.entries(value).slice(0, MAX_KEYS);
    } catch (error) {
      return null;
    }
    for (const [, child] of entries) {
      const found = visit(child, depth + 1);
      if (found) return found;
    }
    return null;
  };

  const roots = [
    window.__INITIAL_STATE__,
    window.ol,
    window.overleaf,
    window.metaAttributesCache,
    window._ide,
    window,
  ];

  for (const root of roots) {
    const found = visit(root, 0);
    if (found) return found;
  }
  return null;
}
"""


def extract_project_from_payload(payload: Any) -> dict[str, Any] | None:
    """Recursively search for a project object that contains rootFolder data."""
    if isinstance(payload, dict):
        if _looks_like_project_dict(payload):
            return payload
        project = payload.get("project")
        if _looks_like_project_dict(project):
            return project
        for value in payload.values():
            found = extract_project_from_payload(value)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = extract_project_from_payload(item)
            if found is not None:
                return found
    return None


def extract_project_from_socket_frame(payload: str) -> dict[str, Any] | None:
    """Extract a project model from a Socket.IO joinProjectResponse frame."""
    frame = payload.strip()
    json_start = frame.find("{")
    if json_start < 0:
        return None
    try:
        message = json.loads(frame[json_start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(message, dict) or message.get("name") != "joinProjectResponse":
        return None
    args = message.get("args")
    if not isinstance(args, list) or not args:
        return None
    first_arg = args[0]
    if not isinstance(first_arg, dict):
        return None
    return extract_project_from_payload(first_arg)


def extract_project_tree_from_browser_model(
    model: dict[str, Any], project_id: str | None = None
) -> RemoteProjectTree:
    """Convert a browser project model into a flat path -> entity map."""
    normalized_project_id = str(model.get("_id") or project_id or "")
    root_folders = model.get("rootFolder") or []
    if not normalized_project_id or not root_folders:
        raise ClientError("Could not extract a project tree from the browser session.")

    root_folder = root_folders[0]
    root_folder_id = str(root_folder.get("_id") or "")
    if not root_folder_id:
        raise ClientError("The project tree is missing the root folder id.")

    entities: dict[str, RemoteEntity] = {}

    def walk_folder(folder: dict[str, Any], parent_path: PurePosixPath, parent_id: str | None, is_root: bool = False) -> None:
        folder_name = str(folder.get("name") or "")
        folder_path = parent_path if is_root or not folder_name else parent_path / folder_name
        folder_id = str(folder.get("_id") or "")
        if not is_root and folder_name and folder_id:
            entities[folder_path.as_posix()] = RemoteEntity(
                entity_id=folder_id,
                entity_type="folder",
                path=folder_path.as_posix(),
                name=folder_name,
                parent_folder_id=parent_id,
            )

        for doc in folder.get("docs") or []:
            name = str(doc.get("name") or "")
            entity_id = str(doc.get("_id") or "")
            if not name or not entity_id:
                continue
            path = (folder_path / name).as_posix()
            entities[path] = RemoteEntity(
                entity_id=entity_id,
                entity_type="doc",
                path=path,
                name=name,
                parent_folder_id=folder_id or parent_id,
            )

        for file_ref in folder.get("fileRefs") or []:
            name = str(file_ref.get("name") or "")
            entity_id = str(file_ref.get("_id") or "")
            if not name or not entity_id:
                continue
            path = (folder_path / name).as_posix()
            entities[path] = RemoteEntity(
                entity_id=entity_id,
                entity_type="file",
                path=path,
                name=name,
                parent_folder_id=folder_id or parent_id,
            )

        for child in folder.get("folders") or []:
            walk_folder(child, folder_path, folder_id or parent_id, is_root=False)

    walk_folder(root_folder, PurePosixPath(""), None, is_root=True)
    return RemoteProjectTree(
        project_id=normalized_project_id,
        root_folder_id=root_folder_id,
        entities=entities,
    )


def load_project_tree_from_browser(
    base_url: str,
    session: AuthSession,
    project_id: str,
    timeout_seconds: int = 25,
) -> RemoteProjectTree:
    """Use Playwright to load the editor and discover the project tree."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise ClientError(
            "Playwright is required for full remote write support. Install `leaflink[browser]`."
        ) from exc

    project_url = f"{base_url.rstrip('/')}/Project/{project_id}"
    captured: dict[str, Any] = {}

    def handle_response(response) -> None:  # pragma: no cover - browser-dependent
        try:
            if "json" not in response.headers.get("content-type", ""):
                return
            payload = response.json()
        except Exception:
            return
        candidate = extract_project_from_payload(payload)
        if candidate is not None:
            captured["project"] = candidate

    with sync_playwright() as playwright:  # pragma: no cover - browser-dependent
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies([cookie.to_dict() for cookie in session.cookies])
        page = context.new_page()
        page.on("response", handle_response)

        def handle_websocket(websocket) -> None:
            def on_frame(payload: str | bytes) -> None:
                text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
                candidate = extract_project_from_socket_frame(text)
                if candidate is not None:
                    captured["project"] = candidate

            websocket.on("framereceived", on_frame)

        page.on("websocket", handle_websocket)
        page.goto(project_url, wait_until="domcontentloaded")

        for _ in range(timeout_seconds):
            if "project" in captured:
                browser.close()
                return extract_project_tree_from_browser_model(captured["project"], project_id=project_id)
            candidate = page.evaluate(_PROJECT_SEARCH_SCRIPT)
            if candidate:
                browser.close()
                return extract_project_tree_from_browser_model(candidate, project_id=project_id)
            page.wait_for_timeout(1000)

        browser.close()
    raise ClientError(
        "Could not discover the remote project tree from the editor session. "
        "Please open the project once in a browser and try again."
    )


def _looks_like_project_dict(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and bool(payload.get("_id") or payload.get("id"))
        and isinstance(payload.get("rootFolder"), list)
        and len(payload.get("rootFolder") or []) > 0
    )
